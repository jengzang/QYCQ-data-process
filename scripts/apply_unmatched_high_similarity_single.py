#!/usr/bin/env python3
import csv
import json
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = WORKDIR / 'outputs'
MANUAL_CONFIRM_PATH = OUTPUTS_DIR / 'manual_confirmed_mappings.csv'
CANDIDATES_PATH = OUTPUTS_DIR / 'unmatched_high_similarity_single_candidates.csv'
REVIEW_PATH = OUTPUTS_DIR / 'unmatched_high_similarity_single_review.csv'
MIN_SCORE = 0.92
MIN_GAP = 0.05
MAX_CANDIDATE_COUNT_IN_SCOPE = 80


def load_csv(path: Path):
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


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
    try:
        top1_score = float(row.get('top1_score') or 0)
        score_gap = float(row.get('score_gap') or 0)
        candidate_count = int(row.get('candidate_count_in_scope') or 0)
    except ValueError:
        return False
    if top1_score < MIN_SCORE:
        return False
    if score_gap < MIN_GAP:
        return False
    if candidate_count <= 0 or candidate_count > MAX_CANDIDATE_COUNT_IN_SCOPE:
        return False
    return True


def build_source_suggestions(row):
    return (
        'unmatched_high_similarity_single:'
        f" source={row.get('source_value','').strip()}"
        f" -> candidate={row.get('candidate','').strip()};"
        f" top1={row.get('top1_score','').strip()};"
        f" top2={row.get('top2_score','').strip()};"
        f" gap={row.get('score_gap','').strip()};"
        f" search_hit_count={row.get('search_hit_count','').strip()}"
    )


def main():
    manual_rows = load_csv(MANUAL_CONFIRM_PATH) if MANUAL_CONFIRM_PATH.exists() else []
    candidate_rows = load_csv(CANDIDATES_PATH)
    existing_keys = build_existing_key_set(manual_rows)

    before_count = len(manual_rows)
    before_natural_count = sum(1 for row in manual_rows if row.get('level') == 'natural')

    review_rows = []
    added = 0
    for row in candidate_rows:
        if not qualifies(row):
            continue
        parent_scope = row['parent_scope'].strip()
        source_value = row['source_value'].strip()
        confirmed_value = row['candidate'].strip()
        review_rows.append({
            'parent_scope': parent_scope,
            'source_value': source_value,
            'confirmed_value': confirmed_value,
            'top1_score': row.get('top1_score', '').strip(),
            'top2_score': row.get('top2_score', '').strip(),
            'score_gap': row.get('score_gap', '').strip(),
            'candidate_count_in_scope': row.get('candidate_count_in_scope', '').strip(),
            'matched_db_city': row.get('matched_db_city', '').strip(),
            'matched_db_town': row.get('matched_db_town', '').strip(),
            'matched_db_admin_candidates': row.get('matched_db_admin_candidates', '').strip(),
            'search_hit_count': row.get('search_hit_count', '').strip(),
            'reason': f'high_similarity_single_in_scope score>={MIN_SCORE} gap>={MIN_GAP}',
        })
        if append_if_absent(
            manual_rows,
            existing_keys,
            'natural',
            parent_scope,
            source_value,
            confirmed_value,
            build_source_suggestions(row),
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
        ['parent_scope', 'source_value', 'confirmed_value', 'top1_score', 'top2_score', 'score_gap', 'candidate_count_in_scope', 'matched_db_city', 'matched_db_town', 'matched_db_admin_candidates', 'search_hit_count', 'reason'],
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
        'min_score': MIN_SCORE,
        'min_gap': MIN_GAP,
        'max_candidate_count_in_scope': MAX_CANDIDATE_COUNT_IN_SCOPE,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
