#!/usr/bin/env python3
import json
import shutil
import sqlite3
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
STAGING_DB = WORKDIR / 'villages_fromJNU.db'
TARGET_DB = WORKDIR / 'villages.db'
TARGET_TABLE = '广东省自然村'
TARGET_COLUMN = '方言分布'
BACKUP_DIR = WORKDIR / 'backups'
NORMALIZE_SCRIPT = WORKDIR / 'scripts' / 'normalize_jnu_dialects.py'
FAMILY_ORDER = {
    '粤': 0,
    '客家': 1,
    '闽': 2,
    '土话': 3,
    '官话': 4,
    '湘语': 5,
    '少数民族': 6,
}


def component_sort_key(component: str):
    family = component.split('·', 1)[0] if component else ''
    is_bare = '·' not in component
    return (FAMILY_ORDER.get(family, 99), 1 if is_bare else 0, component)


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


def normalize_component(component: str):
    return (component or '').strip()


def family_of(component: str):
    return component.split('·', 1)[0] if component else ''


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


def rerun_normalizer():
    proc = subprocess.run(
        ['python3', str(NORMALIZE_SCRIPT)],
        cwd=str(WORKDIR),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


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
    for matched_db_rowid, singles in rowid_group.items():
        reduced = reduce_components(singles)
        if reduced:
            rowid_values[matched_db_rowid] = '、'.join(reduced)
    return rowid_values


def fill_empty_only(rowid_values):
    conn = sqlite3.connect(TARGET_DB)
    cur = conn.cursor()
    pre_nonnull = cur.execute(
        f"select count(*) from '{TARGET_TABLE}' where \"{TARGET_COLUMN}\" is not null and trim(cast(\"{TARGET_COLUMN}\" as text)) != ''"
    ).fetchone()[0]

    updates = []
    blocked_nonempty = 0
    missing_rowid = 0
    for rowid, value in rowid_values.items():
        row = cur.execute(
            f"select \"{TARGET_COLUMN}\" from '{TARGET_TABLE}' where rowid=?",
            (rowid,),
        ).fetchone()
        if row is None:
            missing_rowid += 1
            continue
        current = row[0]
        if current is None or str(current).strip() == '':
            updates.append((value, rowid))
        else:
            blocked_nonempty += 1

    cur.executemany(
        f"update '{TARGET_TABLE}' set \"{TARGET_COLUMN}\"=? where rowid=? and (\"{TARGET_COLUMN}\" is null or trim(cast(\"{TARGET_COLUMN}\" as text))='')",
        updates,
    )
    conn.commit()
    post_nonnull = cur.execute(
        f"select count(*) from '{TARGET_TABLE}' where \"{TARGET_COLUMN}\" is not null and trim(cast(\"{TARGET_COLUMN}\" as text)) != ''"
    ).fetchone()[0]
    conn.close()
    return {
        'candidate_rowids': len(rowid_values),
        'applied_updates': len(updates),
        'blocked_nonempty': blocked_nonempty,
        'missing_rowid': missing_rowid,
        'pre_nonnull': pre_nonnull,
        'post_nonnull': post_nonnull,
        'delta_nonnull': post_nonnull - pre_nonnull,
    }


def verify_against_original_backup(original_backup_path: Path):
    conn = sqlite3.connect(TARGET_DB)
    cur = conn.cursor()
    cur.execute(f"attach database '{original_backup_path}' as bak")
    changed_existing = cur.execute(
        f'''
        select count(*)
        from '{TARGET_TABLE}' a
        join bak.'{TARGET_TABLE}' b on a.rowid=b.rowid
        where b."{TARGET_COLUMN}" is not null and trim(cast(b."{TARGET_COLUMN}" as text)) != ''
          and coalesce(a."{TARGET_COLUMN}", '') != coalesce(b."{TARGET_COLUMN}", '')
        '''
    ).fetchone()[0]
    filled_from_empty = cur.execute(
        f'''
        select count(*)
        from '{TARGET_TABLE}' a
        join bak.'{TARGET_TABLE}' b on a.rowid=b.rowid
        where (b."{TARGET_COLUMN}" is null or trim(cast(b."{TARGET_COLUMN}" as text)) = '')
          and a."{TARGET_COLUMN}" is not null and trim(cast(a."{TARGET_COLUMN}" as text)) != ''
        '''
    ).fetchone()[0]
    conn.close()
    return {
        'changed_existing_should_be_zero': changed_existing,
        'filled_from_empty': filled_from_empty,
    }


def main():
    original_backup = WORKDIR / 'villages.db.bak.20260616_040829'
    if not original_backup.exists():
        raise FileNotFoundError(f'Original backup missing: {original_backup}')

    normalize_summary = rerun_normalizer()
    rowid_values = build_rowid_values()
    backup_path = backup_target_db('before_fill_empty_only_redo')
    fill_summary = fill_empty_only(rowid_values)
    verify_summary = verify_against_original_backup(original_backup)

    print(json.dumps({
        'normalize_summary': normalize_summary,
        'fill_summary': fill_summary,
        'verify_summary': verify_summary,
        'target_backup': backup_path,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
