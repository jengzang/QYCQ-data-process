#!/usr/bin/env python3
import json
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
STAGING_DB = WORKDIR / 'villages_fromJNU.db'
TARGET_DB = WORKDIR / 'villages.db'
TARGET_TABLE = '广东省自然村'
TARGET_COLUMN = '方言分布'
BACKUP_DIR = WORKDIR / 'backups'

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


def backup_target_db(tag: str):
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = BACKUP_DIR / f'villages.db.{tag}_{stamp}.db'
    shutil.copy2(TARGET_DB, backup_path)
    wal = TARGET_DB.with_name(TARGET_DB.name + '-wal')
    shm = TARGET_DB.with_name(TARGET_DB.name + '-shm')
    if wal.exists():
        shutil.copy2(wal, BACKUP_DIR / f'villages.db.{tag}_{stamp}.db-wal')
    if shm.exists():
        shutil.copy2(shm, BACKUP_DIR / f'villages.db.{tag}_{stamp}.db-shm')
    return str(backup_path)


def apply_rowid_standardization():
    conn = sqlite3.connect(STAGING_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cols = [r[1] for r in cur.execute("PRAGMA table_info('jnu_dialect_clean')")]
    if 'final_write_value' not in cols:
        cur.execute("ALTER TABLE jnu_dialect_clean ADD COLUMN final_write_value TEXT")
    if 'final_write_value_by_rowid' not in cols:
        cur.execute("ALTER TABLE jnu_dialect_clean ADD COLUMN final_write_value_by_rowid TEXT")

    rows = cur.execute(
        'select rowid as _pk, xlsx_row_number, matched_db_rowid, primary_family, primary_subgroup, mixed_family_text, mixed_subgroup_text from jnu_dialect_clean order by xlsx_row_number'
    ).fetchall()

    rowid_group = defaultdict(list)
    final_value_updates = []
    for row in rows:
        single = render_single_value(row)
        final_value_updates.append((single, row['_pk']))
        if row['matched_db_rowid'] is not None and single:
            rowid_group[row['matched_db_rowid']].append(single)

    cur.executemany('update jnu_dialect_clean set final_write_value=? where rowid=?', final_value_updates)

    updates = 0
    rowid_updates = []
    for rowid, singles in rowid_group.items():
        reduced = reduce_components(singles)
        before_value = '、'.join(reduced) if reduced else None
        after_value = standardize_final_value(before_value)
        if (before_value or '') != (after_value or ''):
            updates += 1
        rowid_updates.append((after_value, rowid))

    cur.executemany('update jnu_dialect_clean set final_write_value_by_rowid=? where matched_db_rowid=?', rowid_updates)
    conn.commit()
    conn.close()
    return {'rowid_updates': updates, 'rowid_count': len(rowid_group)}


def apply_villages_db_standardization():
    conn = sqlite3.connect(TARGET_DB)
    cur = conn.cursor()
    updates = []
    for rowid, value in cur.execute(
        f"select rowid, \"{TARGET_COLUMN}\" from '{TARGET_TABLE}' where \"{TARGET_COLUMN}\" is not null and trim(cast(\"{TARGET_COLUMN}\" as text)) != ''"
    ):
        new_value = standardize_final_value(value)
        if (value or '') != (new_value or ''):
            updates.append((new_value, rowid))
    cur.executemany(
        f"update '{TARGET_TABLE}' set \"{TARGET_COLUMN}\"=? where rowid=?",
        updates,
    )
    conn.commit()
    conn.close()
    return {'villages_db_updates': len(updates)}


def main():
    backup_path = backup_target_db('before_final_value_standardize')
    rowid_summary = apply_rowid_standardization()
    villages_summary = apply_villages_db_standardization()
    print(json.dumps({
        'backup_path': backup_path,
        'rowid_summary': rowid_summary,
        'villages_summary': villages_summary,
        'rule': 'same-family detail wins; bare family deduplicated; cross-family preserved',
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
