import csv
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

SUFFIXES = [
    '村民委员会', '居民委员会', '行政村', '居民区', '社区', '村委会', '居委会', '管理区',
    '自然村', '村民小组', '小组', '新村', '老村', '村', '里', '社', '巷', '洞', '坪', '岗',
    '围', '屋', '庄', '寨', '坊', '屯'
]


EXACT_WEIGHT = 3
SUFFIX_WEIGHT = 2
MIN_HIGH_SCORE = 8
MIN_MEDIUM_SCORE = 5
MIN_HIGH_COVERAGE = 0.5
MIN_MEDIUM_COVERAGE = 0.35
MIN_HIGH_DOMINANCE = 2.0
MIN_MEDIUM_DOMINANCE = 1.5


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


def unique_keep_order(values):
    seen = set()
    out = []
    for value in values:
        text = norm(value)
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def write_csv(path, rows, fieldnames):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_csv(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def load_db_scope_admin_naturals(db_path='villages.db', table='广东省自然村'):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    db_scope_admin_naturals = defaultdict(lambda: defaultdict(list))
    for row in cur.execute(f"SELECT 市级, 乡镇级, 行政村, 自然村 FROM '{table}'"):
        db_city = norm(row['市级'])
        db_town = norm(row['乡镇级'])
        db_admin = norm(row['行政村'])
        db_natural = norm(row['自然村'])
        if not db_city or not db_town or not db_admin or not db_natural:
            continue
        db_scope_admin_naturals[(db_city, db_town)][db_admin].append(db_natural)
    conn.close()
    for scope, admin_map in db_scope_admin_naturals.items():
        for admin, naturals in list(admin_map.items()):
            admin_map[admin] = unique_keep_order(naturals)
    return db_scope_admin_naturals


def build_scope_indexes(natural_rows, db_scope_admin_naturals):
    grouped_natural = defaultdict(list)

    for row in natural_rows:
        x_city = norm(row['xlsx_city'])
        x_town = norm(row['xlsx_town'])
        x_admin = norm(row['xlsx_admin_village'])
        grouped_natural[(x_city, x_town, x_admin)].append(row)

        db_city = norm(row['matched_db_city'])
        db_town = norm(row['matched_db_town'])
        db_admin = norm(row.get('matched_db_admin_village') or '')
        db_admin_candidates = [norm(x) for x in (row.get('matched_db_admin_village_candidates') or '').split('|') if norm(x)]
        db_natural = norm(row.get('matched_db_natural_village') or '')
        if not db_city or not db_town or not db_natural:
            continue
        if db_admin:
            db_scope_admin_naturals[(db_city, db_town)][db_admin].append(db_natural)
        for candidate in db_admin_candidates:
            db_scope_admin_naturals[(db_city, db_town)][candidate].append(db_natural)

    for scope, admin_map in db_scope_admin_naturals.items():
        for admin, naturals in list(admin_map.items()):
            admin_map[admin] = unique_keep_order(naturals)
    return grouped_natural, db_scope_admin_naturals


def score_candidate(source_naturals, candidate_naturals):
    candidate_set = set(candidate_naturals)
    candidate_base_map = defaultdict(list)
    for item in candidate_naturals:
        candidate_base_map[strip_suffix(item)].append(item)

    score = 0
    exact_hits = []
    suffix_hits = []
    unmatched_source = []

    for source in source_naturals:
        if source in candidate_set:
            score += EXACT_WEIGHT
            exact_hits.append(source)
            continue
        source_base = strip_suffix(source)
        if source_base and source_base in candidate_base_map:
            score += SUFFIX_WEIGHT
            suffix_hits.append({
                'source': source,
                'matched_candidates': unique_keep_order(candidate_base_map[source_base])
            })
            continue
        unmatched_source.append(source)

    matched_natural_count = len({*exact_hits, *(hit['source'] for hit in suffix_hits)})
    coverage_ratio = round(matched_natural_count / len(source_naturals), 4) if source_naturals else 0
    return {
        'score': score,
        'exact_hits': exact_hits,
        'suffix_hits': suffix_hits,
        'matched_natural_count': matched_natural_count,
        'coverage_ratio': coverage_ratio,
        'unmatched_source': unmatched_source,
    }


def classify_confidence(top_score, second_score, coverage_ratio):
    dominance = round(top_score / max(second_score, 1), 3) if top_score else 0
    if top_score >= MIN_HIGH_SCORE and coverage_ratio >= MIN_HIGH_COVERAGE and dominance >= MIN_HIGH_DOMINANCE:
        return 'high', dominance
    if top_score >= MIN_MEDIUM_SCORE and coverage_ratio >= MIN_MEDIUM_COVERAGE and dominance >= MIN_MEDIUM_DOMINANCE:
        return 'medium', dominance
    if top_score > 0:
        return 'low', dominance
    return 'none', 0


def infer_admin_candidates():
    out_dir = Path('outputs')
    unresolved = load_csv(out_dir / 'admin_village_unresolved.csv')
    natural_rows = load_csv(out_dir / 'natural_village_mapping.csv')

    db_scope_admin_naturals = load_db_scope_admin_naturals()
    grouped_natural, db_scope_admin_naturals = build_scope_indexes(natural_rows, db_scope_admin_naturals)

    summary_rows = []
    detail_rows = []
    for row in unresolved:
        city = norm(row['xlsx_city'])
        town = norm(row['xlsx_town'])
        db_city = norm(row['matched_db_city'])
        db_town = norm(row['matched_db_town'])
        admin = norm(row['xlsx_admin_village'])
        source_naturals = unique_keep_order(
            norm(r['xlsx_natural_village'])
            for r in grouped_natural[(city, town, admin)]
            if norm(r['xlsx_natural_village'])
        )

        candidates = []
        admin_map = db_scope_admin_naturals.get((db_city, db_town), {})
        for candidate_admin, candidate_naturals in admin_map.items():
            scored = score_candidate(source_naturals, candidate_naturals)
            if scored['score'] <= 0:
                continue
            candidates.append({
                'candidate_admin': candidate_admin,
                'candidate_natural_count': len(candidate_naturals),
                **scored,
            })

        candidates.sort(key=lambda x: (-x['score'], -x['matched_natural_count'], x['candidate_admin']))
        top_score = candidates[0]['score'] if candidates else 0
        second_score = candidates[1]['score'] if len(candidates) > 1 else 0
        top_coverage = candidates[0]['coverage_ratio'] if candidates else 0
        confidence, dominance = classify_confidence(top_score, second_score, top_coverage)
        inferred_admin = candidates[0]['candidate_admin'] if candidates else ''

        summary_rows.append({
            'level': 'admin',
            'parent_scope': f'{city} / {town}',
            'source_value': admin,
            'source_natural_count': len(source_naturals),
            'source_naturals': ' | '.join(source_naturals[:30]),
            'inferred_admin': inferred_admin,
            'confidence': confidence,
            'top_score': top_score,
            'second_score': second_score,
            'dominance': dominance,
            'top_matched_natural_count': candidates[0]['matched_natural_count'] if candidates else 0,
            'top_coverage_ratio': top_coverage,
            'top_exact_hit_count': len(candidates[0]['exact_hits']) if candidates else 0,
            'top_suffix_hit_count': len(candidates[0]['suffix_hits']) if candidates else 0,
            'candidate_count': len(candidates),
            'top_candidates': ' | '.join(
                f"{c['candidate_admin']}(score={c['score']},cover={c['coverage_ratio']},exact={len(c['exact_hits'])},suffix={len(c['suffix_hits'])})"
                for c in candidates[:5]
            ),
            'action': 'confirm' if confidence in ('high', 'medium') and inferred_admin else 'review',
        })

        for rank, candidate in enumerate(candidates[:10], start=1):
            detail_rows.append({
                'parent_scope': f'{city} / {town}',
                'source_admin': admin,
                'rank': rank,
                'candidate_admin': candidate['candidate_admin'],
                'score': candidate['score'],
                'matched_natural_count': candidate['matched_natural_count'],
                'coverage_ratio': candidate['coverage_ratio'],
                'exact_hits': ' | '.join(candidate['exact_hits']),
                'suffix_hits': ' | '.join(
                    f"{item['source']}=>{'/'.join(item['matched_candidates'])}"
                    for item in candidate['suffix_hits']
                ),
                'unmatched_source': ' | '.join(candidate['unmatched_source'][:20]),
                'candidate_natural_count': candidate['candidate_natural_count'],
            })

    summary_fields = [
        'level', 'parent_scope', 'source_value', 'source_natural_count', 'source_naturals',
        'inferred_admin', 'confidence', 'top_score', 'second_score', 'dominance',
        'top_matched_natural_count', 'top_coverage_ratio', 'top_exact_hit_count',
        'top_suffix_hit_count', 'candidate_count', 'top_candidates', 'action'
    ]
    detail_fields = [
        'parent_scope', 'source_admin', 'rank', 'candidate_admin', 'score',
        'matched_natural_count', 'coverage_ratio', 'exact_hits', 'suffix_hits',
        'unmatched_source', 'candidate_natural_count'
    ]

    write_csv(out_dir / 'admin_reverse_inference_candidates.csv', summary_rows, summary_fields)
    write_csv(out_dir / 'admin_reverse_inference_candidate_details.csv', detail_rows, detail_fields)
    return summary_rows, detail_rows


if __name__ == '__main__':
    summary_rows, detail_rows = infer_admin_candidates()
    counts = Counter(r['confidence'] for r in summary_rows)
    print(f'inferred={len(summary_rows)}')
    print('confidence_counts=', dict(counts))
    print('confirmable_rows=', sum(1 for r in summary_rows if r['action'] == 'confirm'))
