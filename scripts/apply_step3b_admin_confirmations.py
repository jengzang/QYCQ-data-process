#!/usr/bin/env python3
import csv
import json
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = WORKDIR / 'outputs'
ARTIFACTS_DIR = WORKDIR / 'artifacts'
MANUAL_CONFIRM_PATH = OUTPUTS_DIR / 'manual_confirmed_mappings.csv'


def load_csv(path: Path):
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_step3b_manual_key_set(manual_rows):
    keys = set()
    for row in manual_rows:
        if row.get('level') != 'admin':
            continue
        if (row.get('action') or '').strip() == 'reject':
            continue
        if 'step3b_' in (row.get('source_suggestions') or ''):
            keys.add((row.get('parent_scope', '').strip(), row.get('source_value', '').strip()))
    return keys


def append_if_absent(existing_rows, level, parent_scope, source_value, confirmed_value, reason):
    key = (level, parent_scope, source_value)
    existing_keys = {
        (
            row.get('level', '').strip(),
            row.get('parent_scope', '').strip(),
            row.get('source_value', '').strip(),
        )
        for row in existing_rows
    }
    if key in existing_keys:
        return False
    existing_rows.append({
        'level': level,
        'parent_scope': parent_scope,
        'source_value': source_value,
        'confirmed_value': confirmed_value,
        'action': 'confirm',
        'source_suggestions': reason,
    })
    return True


def apply_auto_accept_name_close(manual_rows):
    path = ARTIFACTS_DIR / 'step3b_auto_accept_town_distance_le_20km_name_close.csv'
    rows = load_csv(path)
    added = 0
    for row in rows:
        if (row.get('auto_accept') or '').strip() != 'yes':
            continue
        parent_scope = row['parent_scope'].strip()
        source_admin = row['source_admin'].strip()
        candidate_admin = row['candidate_admin'].strip()
        dist = row.get('town_distance_km', '').strip()
        score = row.get('natural_score', '').strip()
        cover = row.get('coverage_ratio', '').strip()
        reason = f"step3b_auto_accept_20km_name_close:{candidate_admin}@{row.get('candidate_town','').strip()} dist={dist} score={score} cover={cover}"
        if append_if_absent(manual_rows, 'admin', parent_scope, source_admin, candidate_admin, reason):
            added += 1
    return added


def apply_relaxed_single_candidate(manual_rows):
    path = ARTIFACTS_DIR / 'step3b_relaxed_candidates_26.csv'
    rows = load_csv(path)
    added = 0
    for row in rows:
        if (row.get('group') or '').strip() != 'single_candidate':
            continue
        parent_scope = row['parent_scope'].strip()
        source_admin = row['source_admin'].strip()
        candidate_admin = row['candidate_admin'].strip()
        dist = row.get('town_distance_km', '').strip()
        score = row.get('natural_score', '').strip()
        matched = row.get('matched_natural_count', '').strip()
        cover = row.get('coverage_ratio', '').strip()
        reason = f"step3b_relaxed_single_candidate:{candidate_admin}@{row.get('candidate_town','').strip()} dist={dist} score={score} matched={matched} cover={cover}"
        if append_if_absent(manual_rows, 'admin', parent_scope, source_admin, candidate_admin, reason):
            added += 1
    return added


def export_remaining_review_pack(manual_rows):
    confirmed_step3b_keys = build_step3b_manual_key_set(manual_rows)
    remaining_rows = []

    relaxed_rows = load_csv(ARTIFACTS_DIR / 'step3b_relaxed_candidates_26.csv')
    for row in relaxed_rows:
        key = (row['parent_scope'].strip(), row['source_admin'].strip())
        if key in confirmed_step3b_keys:
            continue
        remaining_rows.append({
            'source_bucket': 'step3b_relaxed_candidates_26',
            'parent_scope': row['parent_scope'].strip(),
            'source_admin': row['source_admin'].strip(),
            'candidate_admin': row['candidate_admin'].strip(),
            'candidate_town': row.get('candidate_town', '').strip(),
            'town_distance_km': row.get('town_distance_km', '').strip(),
            'natural_score': row.get('natural_score', '').strip(),
            'matched_natural_count': row.get('matched_natural_count', '').strip(),
            'coverage_ratio': row.get('coverage_ratio', '').strip(),
            'candidate_count_within_scope': row.get('candidate_count_within_20km', '').strip(),
            'confidence_or_group': row.get('group', '').strip(),
            'top_candidates': row.get('top5_candidates', '').strip(),
        })

    review10_rows = load_csv(ARTIFACTS_DIR / 'step3b_review_town_distance_le_10km.csv')
    for row in review10_rows:
        key = (row['parent_scope'].strip(), row['source_admin'].strip())
        if key in confirmed_step3b_keys:
            continue
        confidence = (row.get('step3b_confidence') or '').strip()
        if confidence not in ('high', 'medium'):
            continue
        remaining_rows.append({
            'source_bucket': 'step3b_review_town_distance_le_10km',
            'parent_scope': row['parent_scope'].strip(),
            'source_admin': row['source_admin'].strip(),
            'candidate_admin': row.get('step3b_top_candidate_admin', '').strip(),
            'candidate_town': row.get('step3b_top_candidate_town', '').strip(),
            'town_distance_km': row.get('step3b_town_distance_km', '').strip(),
            'natural_score': row.get('step3b_top_score', '').strip(),
            'matched_natural_count': row.get('step3b_top_matched_natural_count', '').strip(),
            'coverage_ratio': row.get('step3b_top_coverage_ratio', '').strip(),
            'candidate_count_within_scope': row.get('step3b_candidate_count_within_10km', '').strip(),
            'confidence_or_group': confidence,
            'top_candidates': row.get('step3b_top5_candidates', '').strip(),
        })

    remaining_rows.sort(key=lambda row: (row['parent_scope'], row['source_admin'], row['source_bucket']))
    out_path = OUTPUTS_DIR / 'step3b_remaining_review_candidates.csv'
    fieldnames = [
        'source_bucket', 'parent_scope', 'source_admin', 'candidate_admin', 'candidate_town',
        'town_distance_km', 'natural_score', 'matched_natural_count', 'coverage_ratio',
        'candidate_count_within_scope', 'confidence_or_group', 'top_candidates'
    ]
    write_csv(out_path, remaining_rows, fieldnames)
    return out_path, remaining_rows


def main():
    manual_rows = load_csv(MANUAL_CONFIRM_PATH) if MANUAL_CONFIRM_PATH.exists() else []
    before_count = len(manual_rows)
    added_auto = apply_auto_accept_name_close(manual_rows)
    added_relaxed = apply_relaxed_single_candidate(manual_rows)

    fieldnames = ['level', 'parent_scope', 'source_value', 'confirmed_value', 'action', 'source_suggestions']
    write_csv(MANUAL_CONFIRM_PATH, manual_rows, fieldnames)

    review_path, remaining_rows = export_remaining_review_pack(manual_rows)

    summary = {
        'manual_confirm_path': str(MANUAL_CONFIRM_PATH),
        'before_count': before_count,
        'after_count': len(manual_rows),
        'added_auto_accept_name_close': added_auto,
        'added_relaxed_single_candidate': added_relaxed,
        'remaining_review_path': str(review_path),
        'remaining_review_count': len(remaining_rows),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
