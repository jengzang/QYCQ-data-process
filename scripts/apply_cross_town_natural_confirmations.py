#!/usr/bin/env python3
import csv
import json
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = WORKDIR / 'outputs'
MANUAL_CONFIRM_PATH = OUTPUTS_DIR / 'manual_confirmed_mappings.csv'
DIRECT_ACCEPT_PATH = OUTPUTS_DIR / 'cross_town_admin_natural_direct_accept_suggestions.csv'
SECOND_BATCH_SAFE_PATH = OUTPUTS_DIR / 'cross_town_admin_natural_second_batch_safe_accept.csv'
REMAINING_REVIEW_PATH = OUTPUTS_DIR / 'cross_town_admin_natural_still_review_needed.csv'
UNRESOLVED_PATH = OUTPUTS_DIR / 'natural_village_unresolved.csv'
OUTPUT_REMAINING_PATH = OUTPUTS_DIR / 'natural_cross_town_remaining_review_candidates.csv'


def load_csv(path: Path):
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def natural_parent_scope(row):
    return f"{row['xlsx_city'].strip()} / {row['xlsx_town'].strip()} / {row['xlsx_admin_village'].strip()}"


def existing_key_set(rows):
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


def apply_direct_accept(existing_rows, existing_keys):
    rows = load_csv(DIRECT_ACCEPT_PATH)
    added = 0
    for row in rows:
        parent_scope = natural_parent_scope(row)
        source_value = row['xlsx_natural_village'].strip()
        confirmed_value = row['top_candidate'].strip()
        evidence = row.get('decision_reason', '').strip() or row.get('reason', '').strip()
        source_suggestions = (
            f"auto_accept_cross_town_natural:{confirmed_value}; "
            f"resolved_towns={row.get('resolved_towns','').strip()}; "
            f"score={row.get('top_score','').strip()}; evidence={evidence}"
        )
        if append_if_absent(existing_rows, existing_keys, 'natural', parent_scope, source_value, confirmed_value, source_suggestions):
            added += 1
    return added


def apply_second_batch_safe(existing_rows, existing_keys):
    rows = load_csv(SECOND_BATCH_SAFE_PATH)
    added = 0
    for row in rows:
        if (row.get('verdict') or '').strip() != 'safe_accept':
            continue
        parent_scope = natural_parent_scope(row)
        source_value = row['xlsx_natural_village'].strip()
        confirmed_value = row['top_candidate'].strip()
        source_suggestions = (
            f"auto_accept_cross_town_natural_second_batch:{confirmed_value}; "
            f"score={row.get('top_score','').strip()}; "
            f"second={row.get('second_candidate','').strip()}({row.get('second_score','').strip()}); "
            f"reason={row.get('verdict_reason','').strip()}"
        )
        if append_if_absent(existing_rows, existing_keys, 'natural', parent_scope, source_value, confirmed_value, source_suggestions):
            added += 1
    return added


def export_remaining_review(existing_keys):
    unresolved_rows = load_csv(UNRESOLVED_PATH)
    unresolved_index = {
        (
            row.get('xlsx_city', '').strip(),
            row.get('xlsx_town', '').strip(),
            row.get('xlsx_admin_village', '').strip(),
            row.get('xlsx_natural_village', '').strip(),
        ): row
        for row in unresolved_rows
    }

    remaining_rows = []
    for row in load_csv(REMAINING_REVIEW_PATH):
        key = ('natural', natural_parent_scope(row), row['xlsx_natural_village'].strip())
        if key in existing_keys:
            continue
        unresolved = unresolved_index.get((
            row.get('xlsx_city', '').strip(),
            row.get('xlsx_town', '').strip(),
            row.get('xlsx_admin_village', '').strip(),
            row.get('xlsx_natural_village', '').strip(),
        ), {})
        remaining_rows.append({
            'parent_scope': natural_parent_scope(row),
            'source_natural': row.get('xlsx_natural_village', '').strip(),
            'matched_db_city': row.get('matched_db_city', '').strip(),
            'matched_db_town': row.get('matched_db_town', '').strip(),
            'matched_db_admin_village': row.get('matched_db_admin_village', '').strip(),
            'reason': row.get('reason', '').strip(),
            'pattern_class': row.get('pattern_class', '').strip(),
            'top_candidate': row.get('top_candidate', '').strip(),
            'top_score': row.get('top_score', '').strip(),
            'second_score': row.get('second_score', '').strip(),
            'decision_reason': row.get('decision_reason', '').strip(),
            'suggested_candidates': row.get('suggested_candidates', '').strip(),
            'unresolved_match_status': unresolved.get('match_status', '').strip(),
            'candidate_count': unresolved.get('candidate_count', '').strip(),
        })
    remaining_rows.sort(key=lambda r: (r['parent_scope'], r['source_natural']))
    fieldnames = [
        'parent_scope', 'source_natural', 'matched_db_city', 'matched_db_town', 'matched_db_admin_village',
        'reason', 'pattern_class', 'top_candidate', 'top_score', 'second_score', 'decision_reason',
        'suggested_candidates', 'unresolved_match_status', 'candidate_count'
    ]
    write_csv(OUTPUT_REMAINING_PATH, remaining_rows, fieldnames)
    return remaining_rows


def main():
    manual_rows = load_csv(MANUAL_CONFIRM_PATH) if MANUAL_CONFIRM_PATH.exists() else []
    before_count = len(manual_rows)
    keys = existing_key_set(manual_rows)
    before_natural_keys = len({k for k in keys if k[0] == 'natural'})

    added_direct = apply_direct_accept(manual_rows, keys)
    added_second_batch = apply_second_batch_safe(manual_rows, keys)

    fieldnames = ['level', 'parent_scope', 'source_value', 'confirmed_value', 'action', 'source_suggestions']
    write_csv(MANUAL_CONFIRM_PATH, manual_rows, fieldnames)

    remaining_rows = export_remaining_review(keys)
    after_natural_keys = len({k for k in keys if k[0] == 'natural'})

    summary = {
        'manual_confirm_path': str(MANUAL_CONFIRM_PATH),
        'before_count': before_count,
        'after_count': len(manual_rows),
        'before_natural_confirm_count': before_natural_keys,
        'after_natural_confirm_count': after_natural_keys,
        'added_direct_accept': added_direct,
        'added_second_batch_safe': added_second_batch,
        'remaining_review_path': str(OUTPUT_REMAINING_PATH),
        'remaining_review_count': len(remaining_rows),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
