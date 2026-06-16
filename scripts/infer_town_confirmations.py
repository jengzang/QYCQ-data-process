import csv
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

SUFFIXES = [
    '村民委员会', '居民委员会', '行政村', '居民区', '社区', '村委会', '居委会', '管理区',
    '自然村', '村民小组', '小组', '新村', '老村', '村', '里', '社', '巷', '洞', '坪', '岗',
    '围', '屋', '庄', '寨', '坊', '屯'
]


def norm(value):
    return (value or '').strip()


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


def write_csv(path, rows, fieldnames):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_csv(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def load_db_indexes(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    admins_by_city = defaultdict(list)
    naturals_by_city = defaultdict(list)
    for row in conn.execute("select 市级, 乡镇级, 行政村, 自然村 from '广东省自然村'"):
        city = norm(row['市级'])
        town = norm(row['乡镇级'])
        admin = norm(row['行政村'])
        natural = norm(row['自然村'])
        if city and town and admin:
            admins_by_city[city].append((admin, town))
        if city and town and natural:
            naturals_by_city[city].append((natural, town))
    conn.close()
    return admins_by_city, naturals_by_city


def infer_town_candidates():
    out_dir = Path('outputs')
    unresolved = load_csv(out_dir / 'town_unresolved.csv')
    xrows = load_csv(out_dir / 'natural_village_mapping.csv')
    admins_by_city, naturals_by_city = load_db_indexes('villages.db')

    rows = []
    for item in unresolved:
        xlsx_city = norm(item['xlsx_city'])
        db_city = norm(item['matched_db_city'])
        xlsx_town = norm(item['xlsx_town'])
        scoped = [r for r in xrows if norm(r['xlsx_city']) == xlsx_city and norm(r['xlsx_town']) == xlsx_town]
        admins = sorted({norm(r['xlsx_admin_village']) for r in scoped if norm(r['xlsx_admin_village'])})
        naturals = sorted({norm(r['xlsx_natural_village']) for r in scoped if norm(r['xlsx_natural_village'])})

        votes = Counter()
        admin_hits = 0
        natural_hits = 0
        for admin in admins:
            base = strip_suffix(admin)
            for db_admin, db_town in admins_by_city[db_city]:
                if base and base == strip_suffix(db_admin):
                    votes[db_town] += 3
                    admin_hits += 1
        for natural in naturals[:120]:
            base = strip_suffix(natural)
            for db_natural, db_town in naturals_by_city[db_city]:
                if base and base == strip_suffix(db_natural):
                    votes[db_town] += 1
                    natural_hits += 1

        top = votes.most_common(5)
        if top:
            top_town, top_votes = top[0]
            second_votes = top[1][1] if len(top) > 1 else 0
            dominance = round(top_votes / max(second_votes, 1), 3)
            confidence = 'high' if top_votes >= 20 and dominance >= 3 else 'medium' if top_votes >= 8 and dominance >= 2 else 'low'
            candidates = ' | '.join(f'{town}({count})' for town, count in top)
        else:
            top_town = ''
            top_votes = 0
            dominance = 0
            confidence = 'none'
            candidates = ''
        rows.append({
            'level': 'town',
            'parent_scope': xlsx_city,
            'source_value': xlsx_town,
            'inferred_town': top_town,
            'confidence': confidence,
            'top_votes': top_votes,
            'dominance': dominance,
            'admin_hits': admin_hits,
            'natural_hits': natural_hits,
            'candidates': candidates,
            'action': 'confirm' if confidence in ('high', 'medium') and top_town else 'review',
        })
    write_csv(out_dir / 'town_reverse_inference_candidates.csv', rows, [
        'level', 'parent_scope', 'source_value', 'inferred_town', 'confidence', 'top_votes',
        'dominance', 'admin_hits', 'natural_hits', 'candidates', 'action'
    ])
    return rows


def append_confirmations(rows):
    path = Path('outputs/manual_confirmed_mappings.csv')
    existing = []
    if path.exists():
        existing = load_csv(path)
    seen = {(r['level'], r['parent_scope'], r['source_value']) for r in existing}
    additions = []
    for row in rows:
        if row['action'] != 'confirm' or not row['inferred_town']:
            continue
        key = (row['level'], row['parent_scope'], row['source_value'])
        if key in seen:
            continue
        additions.append({
            'level': row['level'],
            'parent_scope': row['parent_scope'],
            'source_value': row['source_value'],
            'confirmed_value': row['inferred_town'],
            'action': 'confirm',
            'source_suggestions': f"reverse_inference:{row['candidates']}",
        })
    fieldnames = ['level', 'parent_scope', 'source_value', 'confirmed_value', 'action', 'source_suggestions']
    write_csv(path, existing + additions, fieldnames)
    return additions


if __name__ == '__main__':
    inferred = infer_town_candidates()
    additions = append_confirmations(inferred)
    print(f'inferred={len(inferred)} appended_confirmations={len(additions)}')
    print('confidence_counts=', dict(Counter(r['confidence'] for r in inferred)))
