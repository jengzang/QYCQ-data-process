import csv
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


def infer_admin_candidates():
    out_dir = Path('outputs')
    unresolved = load_csv(out_dir / 'admin_village_core_unresolved.csv')
    natural_rows = load_csv(out_dir / 'natural_village_mapping.csv')

    grouped_natural = defaultdict(list)
    for row in natural_rows:
        grouped_natural[(norm(row['xlsx_city']), norm(row['xlsx_town']), norm(row['xlsx_admin_village']))].append(row)

    by_scope_admin = defaultdict(lambda: defaultdict(set))
    for row in natural_rows:
        city = norm(row['matched_db_city'])
        town = norm(row['matched_db_town'])
        admin = norm(row.get('matched_db_admin_village') or '')
        candidates = [norm(x) for x in (row.get('matched_db_admin_village_candidates') or '').split('|') if norm(x)]
        natural = norm(row['matched_db_natural_village'])
        if not natural:
            continue
        if admin:
            by_scope_admin[(city, town)][admin].add(natural)
        for candidate in candidates:
            by_scope_admin[(city, town)][candidate].add(natural)

    result_rows = []
    for row in unresolved:
        city = norm(row['xlsx_city'])
        town = norm(row['xlsx_town'])
        db_city = norm(row['matched_db_city'])
        db_town = norm(row['matched_db_town'])
        admin = norm(row['xlsx_admin_village'])
        naturals = [norm(r['xlsx_natural_village']) for r in grouped_natural[(city, town, admin)] if norm(r['xlsx_natural_village'])]
        votes = Counter()
        for candidate_admin, db_naturals in by_scope_admin[(db_city, db_town)].items():
            for natural in naturals:
                base = strip_suffix(natural)
                for db_natural in db_naturals:
                    if base and base == strip_suffix(db_natural):
                        votes[candidate_admin] += 1
        top = votes.most_common(5)
        if top:
            top_admin, top_votes = top[0]
            second_votes = top[1][1] if len(top) > 1 else 0
            dominance = round(top_votes / max(second_votes, 1), 3)
            confidence = 'high' if top_votes >= 4 and dominance >= 2 else 'medium' if top_votes >= 3 and dominance >= 1.5 else 'low'
            candidates = ' | '.join(f'{admin_name}({count})' for admin_name, count in top)
        else:
            top_admin = ''
            top_votes = 0
            dominance = 0
            confidence = 'none'
            candidates = ''
        result_rows.append({
            'level': 'admin',
            'parent_scope': f'{city} / {town}',
            'source_value': admin,
            'inferred_admin': top_admin,
            'confidence': confidence,
            'top_votes': top_votes,
            'dominance': dominance,
            'natural_sample_count': len(naturals),
            'candidates': candidates,
            'action': 'confirm' if confidence in ('high', 'medium') and top_admin else 'review',
        })

    write_csv(out_dir / 'admin_reverse_inference_candidates.csv', result_rows, [
        'level', 'parent_scope', 'source_value', 'inferred_admin', 'confidence', 'top_votes',
        'dominance', 'natural_sample_count', 'candidates', 'action'
    ])
    return result_rows


def append_confirmations(rows):
    path = Path('outputs/manual_confirmed_mappings.csv')
    existing = load_csv(path) if path.exists() else []
    seen = {(r['level'], r['parent_scope'], r['source_value']) for r in existing}
    additions = []
    for row in rows:
        if row['action'] != 'confirm' or not row['inferred_admin']:
            continue
        key = (row['level'], row['parent_scope'], row['source_value'])
        if key in seen:
            continue
        additions.append({
            'level': row['level'],
            'parent_scope': row['parent_scope'],
            'source_value': row['source_value'],
            'confirmed_value': row['inferred_admin'],
            'action': 'confirm',
            'source_suggestions': f"reverse_inference:{row['candidates']}",
        })
    fieldnames = ['level', 'parent_scope', 'source_value', 'confirmed_value', 'action', 'source_suggestions']
    write_csv(path, existing + additions, fieldnames)
    return additions


if __name__ == '__main__':
    rows = infer_admin_candidates()
    additions = append_confirmations(rows)
    print(f'inferred={len(rows)} appended_confirmations={len(additions)}')
    counts = Counter(r['confidence'] for r in rows)
    print('confidence_counts=', dict(counts))
