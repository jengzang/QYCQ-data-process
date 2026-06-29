#!/usr/bin/env python3
import csv
import json
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = WORKDIR / 'outputs'
MANUAL_CONFIRM_PATH = OUTPUTS_DIR / 'manual_confirmed_mappings.csv'
UNRESOLVED_PATH = OUTPUTS_DIR / 'natural_village_unresolved.csv'
REVIEW_PATH = OUTPUTS_DIR / 'natural_second_pass_drop_trailing_village_review.csv'


def load_csv(path: Path):
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def make_parent_scope(row):
    return f"{row['xlsx_city'].strip()} / {row['xlsx_town'].strip()} / {row['xlsx_admin_village'].strip()}"


def build_existing_key_set(rows):
    return {
        (
            row.get('level', '').strip(),
            row.get('parent_scope', '').strip(),
            row.get('source_value', '').strip(),
        )
        for row in rows
        if (row.get('action') or '').strip() != 'reject'
    }


def append_if_absent(existing_rows, existing_keys, level, parent_scope, source_value, confirmed_value, source_suggestions):
    key = (level, parent_scope, source_value)
    if key in existing_keys:
        return False
    existing_rows.append({
        'level': level,
        'parent_scope': parent_scope,
        'source_value': source_value,
        'confirmed_value': confirmed_value,
        'action': 'confirm',
        'source_suggestions': source_suggestions,
    })
    existing_keys.add(key)
    return True


def qualifies(row):
    if row.get('candidate_count', '').strip() != '1':
        return False
    if row.get('match_status', '').strip() not in ('ambiguous_row_scope', 'ambiguous_normalized'):
        return False
    source = (row.get('xlsx_natural_village') or '').strip()
    candidate = (row.get('candidates') or '').strip()
    if not source or not candidate:
        return False
    if not source.endswith('村'):
        return False
    if source[:-1] != candidate:
        return False
    return True


def build_source_suggestions(row, candidate):
    return (
        'natural_second_pass_drop_trailing_village:'
        f" source={row.get('xlsx_natural_village','').strip()}"
        f" -> candidate={candidate};"
        f" status={row.get('match_status','').strip()};"
        f" candidate_count={row.get('candidate_count','').strip()}"
    )


def main():
    manual_rows = load_csv(MANUAL_CONFIRM_PATH) if MANUAL_CONFIRM_PATH.exists() else []
    unresolved_rows = load_csv(UNRESOLVED_PATH)
    existing_keys = build_existing_key_set(manual_rows)

    before_count = len(manual_rows)
    before_natural_count = sum(1 for row in manual_rows if row.get('level') == 'natural')

    review_rows = []
    added = 0
    for row in unresolved_rows:
        if not qualifies(row):
            continue
        parent_scope = make_parent_scope(row)
        source_value = row['xlsx_natural_village'].strip()
        confirmed_value = row['candidates'].strip()
        review_rows.append({
            'parent_scope': parent_scope,
            'source_value': source_value,
            'confirmed_value': confirmed_value,
            'matched_db_city': row.get('matched_db_city', '').strip(),
            'matched_db_town': row.get('matched_db_town', '').strip(),
            'matched_db_admin_village': row.get('matched_db_admin_village', '').strip(),
            'match_status': row.get('match_status', '').strip(),
            'candidate_count': row.get('candidate_count', '').strip(),
            'reason': 'candidate_count_1_and_drop_trailing_village',
        })
        if append_if_absent(
            manual_rows,
            existing_keys,
            'natural',
            parent_scope,
            source_value,
            confirmed_value,
            build_source_suggestions(row, confirmed_value),
        ):
            added += 1

    write_csv(
        MANUAL_CONFIRM_PATH,
        manual_rows,
        ['level', 'parent_scope', 'source_value', 'confirmed_value', 'action', 'source_suggestions'],
    )
    write_csv(
        REVIEW_PATH,
        review_rows,
        [
            'parent_scope', 'source_value', 'confirmed_value', 'matched_db_city', 'matched_db_town',
            'matched_db_admin_village', 'match_status', 'candidate_count', 'reason'
        ],
    )

    after_count = len(manual_rows)
    after_natural_count = sum(1 for row in manual_rows if row.get('level') == 'natural')

    print(json.dumps({
        'manual_confirm_path': str(MANUAL_CONFIRM_PATH),
        'review_path': str(REVIEW_PATH),
        'before_count': before_count,
        'after_count': after_count,
        'before_natural_confirm_count': before_natural_count,
        'after_natural_confirm_count': after_natural_count,
        'review_row_count': len(review_rows),
        'added_count': added,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
