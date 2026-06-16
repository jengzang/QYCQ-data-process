#!/usr/bin/env python3
import csv
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
STAGING_DB = WORKDIR / 'villages_fromJNU.db'
TARGET_DB = WORKDIR / 'villages.db'
TARGET_TABLE = '广东省自然村'
TARGET_COLUMN = '方言分布'
ARTIFACT_DIR = WORKDIR / 'artifacts' / 'dialect_review'

FAMILY_ORDER = {
    '粤': 0,
    '客家': 1,
    '闽': 2,
    '土话': 3,
    '官话': 4,
    '湘语': 5,
    '少数民族': 6,
}

FAMILY_NAMES = set(FAMILY_ORDER.keys())


def component_sort_key(component: str):
    family = component.split('·', 1)[0] if component else ''
    is_bare = '·' not in component
    return (FAMILY_ORDER.get(family, 99), 1 if is_bare else 0, component)


def family_of(component: str):
    return component.split('·', 1)[0] if component else ''


def normalize_component(component: str):
    return (component or '').strip()


def render_single_value(row: sqlite3.Row):
    primary_family = row['primary_family']
    primary_subgroup = row['primary_subgroup']
    mixed_family_text = row['mixed_family_text'] or ''
    mixed_subgroup_text = row['mixed_subgroup_text'] or ''

    if primary_family and primary_family != '混合':
        if primary_subgroup:
            return f'{primary_family}·{primary_subgroup}'
        return primary_family

    if mixed_family_text:
        families = [x.strip() for x in mixed_family_text.split('、') if x.strip()]
        subgroups = [x.strip() for x in mixed_subgroup_text.split('、') if x.strip()]
        subgroup_components = []
        subgroup_families = set()
        for subgroup in subgroups:
            matched_family = None
            for family in families:
                if family in subgroup:
                    matched_family = family
                    break
            if matched_family:
                subgroup_components.append(subgroup)
                subgroup_families.add(matched_family)
        bare_families = [family for family in families if family not in subgroup_families]
        components = subgroup_components + bare_families
        components = sorted(dict.fromkeys(components), key=component_sort_key)
        return '、'.join(components)

    if primary_subgroup:
        return primary_subgroup
    return None


def reduce_components(components):
    components = [normalize_component(c) for c in components if normalize_component(c)]
    unique = []
    for comp in components:
        if comp not in unique:
            unique.append(comp)

    detailed_by_family = defaultdict(list)
    bare_by_family = defaultdict(list)
    for comp in unique:
        fam = family_of(comp)
        if '·' in comp:
            detailed_by_family[fam].append(comp)
        else:
            bare_by_family[fam].append(comp)

    reduced = []
    for fam in sorted(set(list(detailed_by_family.keys()) + list(bare_by_family.keys())), key=lambda x: FAMILY_ORDER.get(x, 99)):
        details = sorted(dict.fromkeys(detailed_by_family.get(fam, [])), key=component_sort_key)
        bares = sorted(dict.fromkeys(bare_by_family.get(fam, [])), key=component_sort_key)
        if details:
            reduced.extend(details)
        else:
            reduced.extend(bares)

    return sorted(dict.fromkeys(reduced), key=component_sort_key)


def standardize_final_value(value: str):
    components = [normalize_component(x) for x in (value or '').split('、') if normalize_component(x)]
    if not components:
        return None

    details_by_family = defaultdict(list)
    bare_by_family = defaultdict(list)
    other_components = []

    for comp in components:
        fam = family_of(comp)
        if fam in FAMILY_NAMES:
            if '·' in comp:
                if comp not in details_by_family[fam]:
                    details_by_family[fam].append(comp)
            else:
                if comp not in bare_by_family[fam]:
                    bare_by_family[fam].append(comp)
        else:
            if comp not in other_components:
                other_components.append(comp)

    final_components = []
    all_families = sorted(set(list(details_by_family.keys()) + list(bare_by_family.keys())), key=lambda x: FAMILY_ORDER.get(x, 99))
    for fam in all_families:
        if details_by_family.get(fam):
            final_components.extend(sorted(details_by_family[fam], key=component_sort_key))
        elif bare_by_family.get(fam):
            final_components.append(fam)

    final_components.extend(sorted(other_components, key=component_sort_key))
    final_components = sorted(dict.fromkeys(final_components), key=component_sort_key)
    return '、'.join(final_components) if final_components else None


def build_rowid_values():
    conn = sqlite3.connect(STAGING_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rowid_group = defaultdict(list)
    for row in cur.execute(
        'select matched_db_rowid, primary_family, primary_subgroup, mixed_family_text, mixed_subgroup_text from jnu_dialect_clean where matched_db_rowid is not null'
    ):
        single = render_single_value(row)
        if single:
            rowid_group[row['matched_db_rowid']].append(single)
    conn.close()

    rowid_values = {}
    standardized = {}
    for matched_db_rowid, singles in rowid_group.items():
        reduced = reduce_components(singles)
        old_value = '、'.join(reduced) if reduced else None
        new_value = standardize_final_value(old_value)
        rowid_values[matched_db_rowid] = old_value
        standardized[matched_db_rowid] = new_value
    return rowid_values, standardized


def export_rowid_diff(old_map, new_map):
    path = ARTIFACT_DIR / 'final_value_standardization_rowid_diff.csv'
    rows = []
    for rowid in sorted(set(old_map) | set(new_map)):
        old_value = old_map.get(rowid)
        new_value = new_map.get(rowid)
        if (old_value or '') == (new_value or ''):
            continue
        rows.append({
            'matched_db_rowid': rowid,
            'before_value': old_value or '',
            'after_value': new_value or '',
        })
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=['matched_db_rowid', 'before_value', 'after_value'])
        writer.writeheader()
        writer.writerows(rows)
    return path, len(rows)


def export_villages_db_diff():
    path = ARTIFACT_DIR / 'final_value_standardization_villages_db_diff.csv'
    conn = sqlite3.connect(TARGET_DB)
    cur = conn.cursor()
    rows = []
    for rowid, value in cur.execute(
        f"select rowid, \"{TARGET_COLUMN}\" from '{TARGET_TABLE}' where \"{TARGET_COLUMN}\" is not null and trim(cast(\"{TARGET_COLUMN}\" as text)) != ''"
    ):
        new_value = standardize_final_value(value)
        if (value or '') == (new_value or ''):
            continue
        rows.append({
            'rowid': rowid,
            'before_value': value or '',
            'after_value': new_value or '',
        })
    conn.close()
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=['rowid', 'before_value', 'after_value'])
        writer.writeheader()
        writer.writerows(rows)
    return path, len(rows)


def main():
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    rowid_old, rowid_new = build_rowid_values()
    rowid_path, rowid_count = export_rowid_diff(rowid_old, rowid_new)
    villages_path, villages_count = export_villages_db_diff()

    summary = {
        'rowid_diff_count': rowid_count,
        'villages_db_diff_count': villages_count,
        'rowid_diff_path': str(rowid_path),
        'villages_db_diff_path': str(villages_path),
        'rule': 'same-family detail wins; bare family deduplicated; cross-family preserved',
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
