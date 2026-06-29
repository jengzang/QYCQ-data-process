#!/usr/bin/env python3
import csv
import json
import re
import unicodedata
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = WORKDIR / 'outputs'
MANUAL_CONFIRM_PATH = OUTPUTS_DIR / 'manual_confirmed_mappings.csv'
UNRESOLVED_PATH = OUTPUTS_DIR / 'natural_village_unresolved.csv'
REVIEW_PATH = OUTPUTS_DIR / 'unmatched_natural_suffix_equivalent_review.csv'
AUTO_CANDIDATES_PATH = OUTPUTS_DIR / 'unmatched_natural_auto_candidates.csv'

SUFFIXES = ['自然村', '村委会', '居民小组', '村民小组', '经济社', '村', '寨', '屯', '垌', '洞', '塝', '坪', '片', '队']


def load_csv(path: Path):
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def norm(value):
    if value is None:
        return ''
    text = unicodedata.normalize('NFKC', str(value)).strip()
    text = re.sub(r'\s+', '', text)
    return text


def strip_suffix(value):
    text = norm(value)
    changed = True
    while changed and text:
        changed = False
        for suffix in sorted(SUFFIXES, key=len, reverse=True):
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[:-len(suffix)]
                changed = True
                break
    return text


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


def build_source_suggestions(source_value, confirmed_value, matched_db_city, matched_db_town, matched_db_admin_candidates):
    return (
        'unmatched_suffix_equivalent_single_in_scope:'
        f' source={source_value}'
        f' -> candidate={confirmed_value};'
        f' db_scope={matched_db_city}/{matched_db_town}/{matched_db_admin_candidates}'
    )


def main():
    manual_rows = load_csv(MANUAL_CONFIRM_PATH) if MANUAL_CONFIRM_PATH.exists() else []
    unresolved_rows = load_csv(UNRESOLVED_PATH)
    auto_rows = load_csv(AUTO_CANDIDATES_PATH)
    existing_keys = build_existing_key_set(manual_rows)

    suffix_equivalent = [row for row in auto_rows if row.get('strategy', '').strip() == 'suffix_equivalent_single_in_scope']
    suffix_map = {
        (row.get('parent_scope', '').strip(), row.get('source_value', '').strip()): row
        for row in suffix_equivalent
    }

    before_count = len(manual_rows)
    before_natural_count = sum(1 for row in manual_rows if row.get('level') == 'natural')

    review_rows = []
    added = 0
    for row in unresolved_rows:
        if row.get('match_status', '').strip() != 'unmatched':
            continue
        parent_scope = make_parent_scope(row)
        source_value = row.get('xlsx_natural_village', '').strip()
        key = (parent_scope, source_value)
        auto = suffix_map.get(key)
        if not auto:
            continue
        confirmed_value = auto['confirmed_value'].strip()
        matched_db_city = auto.get('matched_db_city', '').strip()
        matched_db_town = auto.get('matched_db_town', '').strip()
        matched_db_admin_candidates = auto.get('matched_db_admin_candidates', '').strip()
        if strip_suffix(source_value) != strip_suffix(confirmed_value):
            continue
        review_rows.append({
            'parent_scope': parent_scope,
            'source_value': source_value,
            'confirmed_value': confirmed_value,
            'matched_db_city': matched_db_city,
            'matched_db_town': matched_db_town,
            'matched_db_admin_candidates': matched_db_admin_candidates,
            'reason': 'unmatched_suffix_equivalent_single_in_scope',
        })
        if append_if_absent(
            manual_rows,
            existing_keys,
            'natural',
            parent_scope,
            source_value,
            confirmed_value,
            build_source_suggestions(source_value, confirmed_value, matched_db_city, matched_db_town, matched_db_admin_candidates),
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
        ['parent_scope', 'source_value', 'confirmed_value', 'matched_db_city', 'matched_db_town', 'matched_db_admin_candidates', 'reason'],
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
