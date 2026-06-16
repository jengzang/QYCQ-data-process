import csv
import sqlite3
from collections import Counter
from pathlib import Path

DEDUP_FIELDS = ['市级', '区县级', '乡镇级', '行政村', '自然村', '拼音', '方言分布', 'longitude', 'latitude', '备注', '暂时不用', '搜索用']


def norm(value):
    return '' if value is None else str(value)


def load_csv(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fieldnames):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    review = [r for r in load_csv('outputs/natural_village_reviewable_ambiguous.csv') if r['match_status'] == 'ambiguous_row_scope']
    conn = sqlite3.connect('villages.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    accepted = []
    skipped = []
    for row in review:
        city = row['matched_db_city']
        town = row['matched_db_town']
        admins = [x.strip() for x in (row.get('matched_db_admin_village_candidates') or '').split('|') if x.strip()]
        if not admins and row.get('matched_db_admin_village'):
            admins = [row['matched_db_admin_village']]
        candidate_name = (row.get('matched_db_natural_village') or row.get('candidates') or row['xlsx_natural_village']).split('|')[0].strip()

        db_rows = []
        for admin in admins:
            db_rows.extend(cur.execute(
                "SELECT rowid, * FROM '广东省自然村' WHERE 市级=? AND 乡镇级=? AND 行政村=? AND (自然村=? OR 搜索用=?)",
                (city, town, admin, candidate_name, candidate_name),
            ).fetchall())
        by_rowid = {r['rowid']: dict(r) for r in db_rows}
        vals = list(by_rowid.values())
        if len(vals) <= 1:
            skipped.append({**row, 'reason': 'not_duplicate_after_lookup', 'db_rowids': ' | '.join(str(v['rowid']) for v in vals)})
            continue
        signatures = {tuple(norm(v.get(field)) for field in DEDUP_FIELDS) for v in vals}
        rowids = sorted(v['rowid'] for v in vals)
        if len(signatures) == 1:
            accepted.append({
                **row,
                'chosen_rowid': rowids[0],
                'db_rowids': ' | '.join(str(x) for x in rowids),
                'confirmed_value': candidate_name,
            })
        else:
            skipped.append({**row, 'reason': 'duplicate_rows_not_identical', 'db_rowids': ' | '.join(str(x) for x in rowids)})

    conn.close()

    accepted_path = Path('outputs/natural_duplicate_row_scope_min_rowid_confirmations.csv')
    accepted_fields = list(review[0].keys()) + ['confirmed_value', 'chosen_rowid', 'db_rowids'] if review else ['confirmed_value', 'chosen_rowid', 'db_rowids']
    write_csv(accepted_path, accepted, accepted_fields)
    skipped_path = Path('outputs/natural_duplicate_row_scope_skipped.csv')
    skipped_fields = list(review[0].keys()) + ['reason', 'db_rowids'] if review else ['reason', 'db_rowids']
    write_csv(skipped_path, skipped, skipped_fields)

    confirmations_path = Path('outputs/manual_confirmed_mappings.csv')
    confirmations = load_csv(confirmations_path) if confirmations_path.exists() else []
    idx = {(r['level'], r['parent_scope'], r['source_value']): r for r in confirmations}
    for row in accepted:
        parent = f"{row['xlsx_city']} / {row['xlsx_town']} / {row['xlsx_admin_village']}"
        key = ('natural', parent, row['xlsx_natural_village'])
        idx[key] = {
            'level': 'natural',
            'parent_scope': parent,
            'source_value': row['xlsx_natural_village'],
            'confirmed_value': row['confirmed_value'],
            'action': 'confirm',
            'source_suggestions': f"duplicate_min_rowid:{row['chosen_rowid']} from {row['db_rowids']}",
        }
    fieldnames = ['level', 'parent_scope', 'source_value', 'confirmed_value', 'action', 'source_suggestions']
    final = sorted(idx.values(), key=lambda r: (r['level'], r['parent_scope'], r['source_value'], r['confirmed_value']))
    write_csv(confirmations_path, final, fieldnames)

    print(f'review={len(review)} accepted={len(accepted)} skipped={len(skipped)} confirmations_total={len(final)}')
    print('skipped_reasons=', dict(Counter(r['reason'] for r in skipped)))


if __name__ == '__main__':
    main()
