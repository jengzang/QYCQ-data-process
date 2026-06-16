#!/usr/bin/env python3
import csv
import json
import sqlite3
from collections import defaultdict, Counter
from pathlib import Path

DB_PATH = Path('villages_fromJNU.db')
ARTIFACT_DIR = Path('artifacts/dialect_review')

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

    # cross-family keep_as_is: retain bare family if another family only has detail
    return sorted(dict.fromkeys(reduced), key=component_sort_key)


def write_csv(path: Path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cols = [r['name'] for r in cur.execute("PRAGMA table_info('jnu_dialect_clean')").fetchall()]
    if 'final_write_value' not in cols:
        cur.execute("ALTER TABLE jnu_dialect_clean ADD COLUMN final_write_value TEXT")
    if 'final_write_value_by_rowid' not in cols:
        cur.execute("ALTER TABLE jnu_dialect_clean ADD COLUMN final_write_value_by_rowid TEXT")

    rows = cur.execute("SELECT rowid as _pk, * FROM jnu_dialect_clean ORDER BY xlsx_row_number").fetchall()
    raw_group = defaultdict(list)
    rowid_group = defaultdict(list)
    raw_counter = Counter()

    for row in rows:
        single = render_single_value(row)
        cur.execute("UPDATE jnu_dialect_clean SET final_write_value=? WHERE rowid=?", (single, row['_pk']))
        raw = row['dialect_raw'] or ''
        raw_group[raw].append(single)
        raw_counter[raw] += 1
        if row['matched_db_rowid']:
            rowid_group[row['matched_db_rowid']].append({
                'xlsx_row_number': row['xlsx_row_number'],
                'raw': raw,
                'single': single,
                'family': row['primary_family'],
                'subgroup': row['primary_subgroup'],
                'confidence': row['clean_confidence'],
            })

    rowid_final = {}
    complex_rows = []
    for matched_db_rowid, items in rowid_group.items():
        singles = [item['single'] for item in items if item['single']]
        reduced = reduce_components(singles)
        final_value_by_rowid = '、'.join(reduced) if reduced else None
        rowid_final[matched_db_rowid] = final_value_by_rowid

        family_count = len({family_of(c) for c in reduced if family_of(c)})
        reason = []
        if family_count > 1:
            reason.append('multi_family')
        if len(reduced) > 2:
            reason.append('multi_component')
        has_bare_and_detail = False
        fam_detail = defaultdict(set)
        fam_bare = defaultdict(set)
        for comp in reduced:
            fam = family_of(comp)
            if '·' in comp:
                fam_detail[fam].add(comp)
            else:
                fam_bare[fam].add(comp)
        for fam in set(fam_detail) & set(fam_bare):
            has_bare_and_detail = True
            break
        if has_bare_and_detail:
            reason.append('bare_and_detail_mixed_keep_as_is')

        if reason:
            source_values = sorted(dict.fromkeys(item['single'] for item in items if item['single']))
            complex_rows.append({
                'matched_db_rowid': matched_db_rowid,
                'final_write_value_by_rowid': final_value_by_rowid or '',
                'component_count': len(reduced),
                'family_count': family_count,
                'source_rows': len(items),
                'source_value_count': len(source_values),
                'source_values': ','.join(source_values),
                'reason': ' | '.join(reason),
            })

    for matched_db_rowid, final_value in rowid_final.items():
        cur.execute("UPDATE jnu_dialect_clean SET final_write_value_by_rowid=? WHERE matched_db_rowid=?", (final_value, matched_db_rowid))

    raw_group_rows = []
    for raw, singles in raw_group.items():
        cnt = Counter(x for x in singles if x)
        if cnt:
            suggestion, suggestion_count = cnt.most_common(1)[0]
            suggestion_type = 'stable_single_mapping' if len(cnt) == 1 else 'multi_candidate_mapping'
        else:
            suggestion, suggestion_count = '', 0
            suggestion_type = 'no_mapping'
        matched_rowids = cur.execute("SELECT COUNT(DISTINCT matched_db_rowid) FROM jnu_dialect_clean WHERE dialect_raw=? AND matched_db_rowid IS NOT NULL", (raw,)).fetchone()[0]
        family_mix = Counter()
        subgroup_mix = Counter()
        conf_mix = Counter()
        for r in cur.execute("SELECT primary_family, primary_subgroup, clean_confidence, final_write_value FROM jnu_dialect_clean WHERE dialect_raw=?", (raw,)).fetchall():
            if r['primary_family']:
                family_mix[r['primary_family']] += 1
            if r['primary_subgroup']:
                subgroup_mix[r['primary_subgroup']] += 1
            if r['clean_confidence']:
                conf_mix[r['clean_confidence']] += 1
        raw_group_rows.append({
            'dialect_raw': raw,
            'raw_count': raw_counter[raw],
            'matched_rowid_count': matched_rowids,
            'suggestion_type': suggestion_type,
            'suggested_final_write_value': suggestion,
            'suggested_final_count': suggestion_count,
            'family_mix': ','.join(f'{k}::{v}' for k, v in family_mix.items()),
            'subgroup_mix': ','.join(f'{k}::{v}' for k, v in subgroup_mix.items()),
            'clean_confidence_mix': ','.join(f'{k}::{v}' for k, v in conf_mix.items()),
            'candidate_final_values': ','.join(f'{k}::{v}' for k, v in cnt.items()),
        })

    complex_summary_counter = Counter(r['final_write_value_by_rowid'] for r in complex_rows if r['final_write_value_by_rowid'])
    complex_summary_rows = []
    for value, count in complex_summary_counter.most_common():
        example_rowids = [r['matched_db_rowid'] for r in complex_rows if r['final_write_value_by_rowid'] == value][:8]
        complex_summary_rows.append({
            'final_write_value_by_rowid': value,
            'rowid_count': count,
            'example_rowids': json.dumps(example_rowids, ensure_ascii=False),
        })

    write_csv(
        ARTIFACT_DIR / 'dialect_raw_grouping_review.csv',
        raw_group_rows,
        ['dialect_raw', 'raw_count', 'matched_rowid_count', 'suggestion_type', 'suggested_final_write_value', 'suggested_final_count', 'family_mix', 'subgroup_mix', 'clean_confidence_mix', 'candidate_final_values'],
    )
    write_csv(
        ARTIFACT_DIR / 'complex_mixed_rowid_review.csv',
        complex_rows,
        ['matched_db_rowid', 'final_write_value_by_rowid', 'component_count', 'family_count', 'source_rows', 'source_value_count', 'source_values', 'reason'],
    )
    write_csv(
        ARTIFACT_DIR / 'complex_mixed_value_summary.csv',
        complex_summary_rows,
        ['final_write_value_by_rowid', 'rowid_count', 'example_rowids'],
    )

    summary = {
        'confirmed_rules': {
            '客家方言阳春倔话': '客家·阳春涯话',
            '客家方言阳春涯话': '客家·阳春涯话',
            'coarse_fine_mixed_values': 'keep_as_is',
            'component_order': ['粤', '客家', '闽', '土话', '官话', '湘语', '少数民族'],
        },
        'complex_rowid_count': len(complex_rows),
        'complex_distinct_value_count': len(complex_summary_rows),
        'top_complex_values': [
            {
                'final_write_value_by_rowid': row['final_write_value_by_rowid'],
                'rowid_count': row['rowid_count'],
                'example_rowids': json.loads(row['example_rowids']),
            }
            for row in complex_summary_rows[:30]
        ],
        'top_raw_grouping_suggestions': raw_group_rows[:50],
    }
    (ARTIFACT_DIR / 'dialect_review_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

    conn.commit()
    conn.close()
    print(json.dumps({
        'complex_rowid_count': len(complex_rows),
        'complex_distinct_value_count': len(complex_summary_rows),
        'raw_group_rows': len(raw_group_rows),
        'artifact_dir': str(ARTIFACT_DIR),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
