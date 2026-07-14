import csv
import difflib
import json
import re
import sqlite3
import sys
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

NS = {'a': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def normalize_text(value):
    if value is None:
        return ''
    text = unicodedata.normalize('NFKC', str(value)).strip()
    text = re.sub(r'\s+', '', text)
    return text


def strip_suffix(value, suffixes):
    text = normalize_text(value)
    changed = True
    while changed and text:
        changed = False
        for suffix in sorted(suffixes, key=len, reverse=True):
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[:-len(suffix)]
                changed = True
                break
    return text


def detect_suffix(value, base):
    raw = normalize_text(value)
    base = normalize_text(base)
    if raw and base and raw != base and raw.startswith(base):
        return raw[len(base):]
    return ''


def write_csv(path, rows, fieldnames):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def first_suggested_value(suggested):
    if not suggested:
        return ''
    first = suggested.split('|', 1)[0].strip()
    return re.sub(r'\([0-9.]+\)$', '', first).strip()


def load_manual_confirmations(path):
    confirmations = {}
    if not path.exists():
        return confirmations
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            level = normalize_text(row.get('level'))
            parent_scope = normalize_text(row.get('parent_scope'))
            source_value = normalize_text(row.get('source_value'))
            confirmed_value = normalize_text(row.get('confirmed_value'))
            action = normalize_text(row.get('action') or 'confirm')
            source_suggestions = normalize_text(row.get('source_suggestions'))
            row_scope_hint = ''
            if 'user_confirm_row_scope:' in source_suggestions:
                row_scope_hint = source_suggestions.split('user_confirm_row_scope:', 1)[1].split('|', 1)[0].strip()
            elif 'duplicate_min_rowid:' in source_suggestions:
                row_scope_hint = source_suggestions.split('duplicate_min_rowid:', 1)[1].split('from', 1)[0].strip()
                if level == 'natural':
                    row_scope_hint = f'rowid:{row_scope_hint}'
            if level and source_value and confirmed_value and action != 'reject':
                confirmations[(level, parent_scope, source_value)] = {
                    'confirmed_value': confirmed_value,
                    'row_scope_hint': row_scope_hint,
                }
    return confirmations


def apply_manual_confirmation(level, parent_scope, source_value, candidates, confirmations):
    confirmation = confirmations.get((level, normalize_text(parent_scope), normalize_text(source_value)))
    if not confirmation:
        return None
    confirmed = confirmation['confirmed_value']
    normalized_candidates = {normalize_text(candidate): candidate for candidate in candidates}
    if normalize_text(confirmed) in normalized_candidates:
        return 'manual_confirmed', normalized_candidates[normalize_text(confirmed)], [normalized_candidates[normalize_text(confirmed)]], confirmation
    return 'manual_confirmed_out_of_scope', confirmed, [confirmed], confirmation


def load_config(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_xlsx_rows(path):
    with zipfile.ZipFile(path) as zf:
        shared = []
        if 'xl/sharedStrings.xml' in zf.namelist():
            root = ET.fromstring(zf.read('xl/sharedStrings.xml'))
            for si in root.findall('a:si', NS):
                texts = [t.text or '' for t in si.iterfind('.//a:t', NS)]
                shared.append(''.join(texts))

        sheet = ET.fromstring(zf.read('xl/worksheets/sheet1.xml'))
        rows = sheet.find('a:sheetData', NS)

        parsed_rows = []
        for row in rows.findall('a:row', NS):
            row_data = {}
            for cell in row.findall('a:c', NS):
                ref = cell.attrib.get('r', '')
                col = ''.join(ch for ch in ref if ch.isalpha())
                v = cell.find('a:v', NS)
                val = ''
                if v is not None and v.text is not None:
                    if cell.attrib.get('t') == 's':
                        val = shared[int(v.text)]
                    else:
                        val = v.text
                inline = cell.find('a:is', NS)
                if inline is not None:
                    val = ''.join(t.text or '' for t in inline.iterfind('.//a:t', NS))
                row_data[col] = val
            parsed_rows.append(row_data)

    header = parsed_rows[0]
    col_map = {col: header[col] for col in header}
    rows = []
    for idx, row in enumerate(parsed_rows[1:], start=2):
        named = {'xlsx_row_number': idx}
        for col, name in col_map.items():
            named[name] = row.get(col, '')
        rows.append(named)
    return sorted(col_map.values()), rows


def load_db_rows(path, table):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"SELECT rowid, * FROM '{table}'").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def unique_sorted(values):
    return sorted({normalize_text(v) for v in values if normalize_text(v)})


def suggest_candidates(value, candidates, suffixes, limit=8, min_score=0.58):
    raw = normalize_text(value)
    base = strip_suffix(raw, suffixes)
    scored = []
    for candidate in candidates:
        c_raw = normalize_text(candidate)
        c_base = strip_suffix(c_raw, suffixes)
        score = difflib.SequenceMatcher(None, base, c_base).ratio()
        if base and c_base and (base in c_base or c_base in base):
            score = max(score, 0.92)
        if raw and c_raw and (raw in c_raw or c_raw in raw):
            score = max(score, 0.95)
        if score >= min_score:
            scored.append((score, candidate))
    scored.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
    return [f'{candidate}({score:.2f})' for score, candidate in scored[:limit]]


def match_value(value, candidates, suffixes):
    raw = normalize_text(value)
    exact = [c for c in candidates if normalize_text(c) == raw]
    if len(exact) == 1:
        return 'exact', exact[0], exact
    if len(exact) > 1:
        return 'ambiguous_exact', None, exact

    base = strip_suffix(raw, suffixes)
    normalized = [c for c in candidates if strip_suffix(c, suffixes) == base]
    unique_norm = sorted(dict.fromkeys(normalized))
    if len(unique_norm) == 1:
        return 'suffix_normalized', unique_norm[0], unique_norm
    if len(unique_norm) > 1:
        return 'ambiguous_normalized', None, unique_norm
    return 'unmatched', None, []


def status_allows_child(status):
    return status in ('exact', 'suffix_normalized', 'manual_confirmed', 'manual_confirmed_out_of_scope', 'ambiguous_normalized_allowed')


def main(config_path='mapping_config.json'):
    config = load_config(config_path)
    root = Path('.')
    out_dir = root / config['output_dir']
    out_dir.mkdir(exist_ok=True)
    manual_confirmations = load_manual_confirmations(out_dir / 'manual_confirmed_mappings.csv')

    level_specs = {level['name']: level for level in config['levels']}
    xlsx_columns, xlsx_rows = load_xlsx_rows(root / config['xlsx_path'])
    db_rows = load_db_rows(root / config['db_path'], config['table'])

    observed_suffixes = {level['name']: Counter() for level in config['levels']}
    for level in config['levels']:
        for source_rows, key in ((xlsx_rows, level['xlsx_col']), (db_rows, level['db_col'])):
            for val in {normalize_text(r.get(key, '')) for r in source_rows if normalize_text(r.get(key, ''))}:
                base = strip_suffix(val, level['suffixes'])
                suf = detect_suffix(val, base)
                if suf:
                    observed_suffixes[level['name']][suf] += 1

    structure_summary = {
        'xlsx_file': config['xlsx_path'],
        'xlsx_columns': xlsx_columns,
        'xlsx_row_count': len(xlsx_rows),
        'db_file': config['db_path'],
        'db_table': config['table'],
        'db_row_count': len(db_rows),
        'db_identity': config['db_identity'],
        'db_distinct_counts': {level['db_col']: len(unique_sorted(r[level['db_col']] for r in db_rows)) for level in config['levels']},
    }

    rows_by_city = defaultdict(list)
    rows_by_city_town = defaultdict(list)
    rows_by_city_town_admin = defaultdict(list)
    admin_to_scopes = defaultdict(list)
    for row in db_rows:
        city = normalize_text(row[level_specs['city']['db_col']])
        town = normalize_text(row[level_specs['town']['db_col']])
        admin = normalize_text(row[level_specs['admin']['db_col']])
        rows_by_city[city].append(row)
        rows_by_city_town[(city, town)].append(row)
        rows_by_city_town_admin[(city, town, admin)].append(row)
        admin_to_scopes[(city, admin)].append((town, row))

    suggestion_cfg = config.get('suggestion', {})
    suggest_limit = suggestion_cfg.get('limit', 8)
    suggest_min_score = suggestion_cfg.get('min_score', 0.58)

    city_spec = level_specs['city']
    town_spec = level_specs['town']
    admin_spec = level_specs['admin']
    natural_spec = level_specs['natural']

    city_values = unique_sorted(r[city_spec['db_col']] for r in db_rows)
    city_rows = []
    city_state = {}
    for city in sorted({normalize_text(r[city_spec['xlsx_col']]) for r in xlsx_rows if normalize_text(r[city_spec['xlsx_col']])}):
        status, matched, candidates = match_value(city, city_values, city_spec['suffixes'])
        city_state[city] = {'status': status, 'matched': matched, 'candidate_values': [matched] if matched else []}
        city_rows.append({
            'xlsx_city': city,
            'match_status': status,
            'matched_db_city': matched or '',
            'candidate_count': len(candidates),
            'candidates': ' | '.join(candidates),
            'suggested_candidates': ' | '.join(suggest_candidates(city, city_values, city_spec['suffixes'], suggest_limit, suggest_min_score)) if not candidates else '',
        })

    town_rows = []
    town_state = {}
    city_to_towns = defaultdict(set)
    for row in xlsx_rows:
        city_to_towns[normalize_text(row[city_spec['xlsx_col']])].add(normalize_text(row[town_spec['xlsx_col']]))
    for city in sorted(city_to_towns):
        city_info = city_state.get(city, {'status': 'unmatched', 'matched': None, 'candidate_values': []})
        city_ok = status_allows_child(city_info['status'])
        db_towns = unique_sorted(r[town_spec['db_col']] for r in rows_by_city.get(normalize_text(city_info['matched']), [])) if city_ok else []
        for town in sorted(t for t in city_to_towns[city] if t):
            if not city_ok:
                status, matched, candidates = 'blocked_by_parent', None, []
            else:
                manual = apply_manual_confirmation('town', city, town, db_towns, manual_confirmations)
                if manual:
                    status, matched, candidates, _ = manual
                else:
                    status, matched, candidates = match_value(town, db_towns, town_spec['suffixes'])
            candidate_values = candidates if status == 'ambiguous_normalized' else ([matched] if matched else [])
            town_state[(city, town)] = {'status': status, 'matched': matched, 'candidate_values': candidate_values}
            town_rows.append({
                'xlsx_city': city,
                'matched_db_city': city_info['matched'] or '',
                'xlsx_town': town,
                'match_status': status,
                'matched_db_town': matched or '',
                'candidate_count': len(candidates),
                'candidates': ' | '.join(candidates),
                'suggested_candidates': ' | '.join(suggest_candidates(town, db_towns, town_spec['suffixes'], suggest_limit, suggest_min_score)) if not candidates else '',
            })

    admin_rows = []
    admin_state = {}
    grouped_admin = defaultdict(set)
    for row in xlsx_rows:
        grouped_admin[(normalize_text(row[city_spec['xlsx_col']]), normalize_text(row[town_spec['xlsx_col']]))].add(normalize_text(row[admin_spec['xlsx_col']]))
    for (city, town), admins in sorted(grouped_admin.items()):
        city_info = city_state.get(city, {'status': 'unmatched', 'matched': None, 'candidate_values': []})
        town_info = town_state.get((city, town), {'status': 'unmatched', 'matched': None, 'candidate_values': []})
        parent_ok = status_allows_child(city_info['status']) and status_allows_child(town_info['status'])
        db_admins = unique_sorted(r[admin_spec['db_col']] for r in rows_by_city_town.get((normalize_text(city_info['matched']), normalize_text(town_info['matched'])), [])) if parent_ok else []
        for admin in sorted(a for a in admins if a):
            if not parent_ok:
                status, matched, candidates = 'blocked_by_parent', None, []
            else:
                manual = apply_manual_confirmation('admin', f'{city}/{town}', admin, db_admins, manual_confirmations)
                if not manual:
                    manual = apply_manual_confirmation('admin', f'{city} / {town}', admin, db_admins, manual_confirmations)
                if manual:
                    status, matched, candidates, _ = manual
                else:
                    status, matched, candidates = match_value(admin, db_admins, admin_spec['suffixes'])
            effective_status = 'ambiguous_normalized_allowed' if status == 'ambiguous_normalized' else status
            if status == 'ambiguous_normalized':
                candidate_values = candidates
                resolved_scopes = [
                    (normalize_text(city_info['matched']), normalize_text(town_info['matched']), normalize_text(candidate))
                    for candidate in candidates
                ]
            elif status == 'manual_confirmed_out_of_scope':
                candidate_values = candidates if candidates else ([matched] if matched else [])
                resolved_scopes = []
                target_city = normalize_text(city_info['matched'])
                for candidate in candidate_values:
                    for resolved_town, _ in admin_to_scopes.get((target_city, normalize_text(candidate)), []):
                        resolved_scopes.append((target_city, resolved_town, normalize_text(candidate)))
                resolved_scopes = sorted(dict.fromkeys(resolved_scopes))
            else:
                candidate_values = [matched] if matched else []
                resolved_scopes = [
                    (normalize_text(city_info['matched']), normalize_text(town_info['matched']), normalize_text(matched))
                ] if matched else []
            admin_state[(city, town, admin)] = {
                'status': effective_status,
                'matched': matched,
                'candidate_values': candidate_values,
                'original_status': status,
                'resolved_scopes': resolved_scopes,
            }
            admin_rows.append({
                'xlsx_city': city,
                'xlsx_town': town,
                'matched_db_city': city_info['matched'] or '',
                'matched_db_town': town_info['matched'] or '',
                'xlsx_admin_village': admin,
                'match_status': status,
                'matched_db_admin_village': matched or '',
                'candidate_count': len(candidates),
                'candidates': ' | '.join(candidates),
                'suggested_candidates': ' | '.join(suggest_candidates(admin, db_admins, admin_spec['suffixes'], suggest_limit, suggest_min_score)) if not candidates else '',
            })

    natural_rows = []
    for row in xlsx_rows:
        city = normalize_text(row[city_spec['xlsx_col']])
        town = normalize_text(row[town_spec['xlsx_col']])
        admin = normalize_text(row[admin_spec['xlsx_col']])
        natural = normalize_text(row[natural_spec['xlsx_col']])
        matched_rowid = ''
        city_info = city_state.get(city, {'status': 'unmatched', 'matched': None, 'candidate_values': []})
        town_info = town_state.get((city, town), {'status': 'unmatched', 'matched': None, 'candidate_values': []})
        admin_info = admin_state.get((city, town, admin), {'status': 'unmatched', 'matched': None, 'candidate_values': [], 'original_status': 'unmatched', 'resolved_scopes': []})
        parent_ok = status_allows_child(city_info['status']) and status_allows_child(town_info['status']) and status_allows_child(admin_info['status'])

        scoped_rows = []
        if parent_ok:
            if admin_info['resolved_scopes']:
                for resolved_city, resolved_town, resolved_admin in admin_info['resolved_scopes']:
                    scoped_rows.extend(rows_by_city_town_admin.get((resolved_city, resolved_town, resolved_admin), []))
            else:
                for admin_candidate in admin_info['candidate_values']:
                    scoped_rows.extend(rows_by_city_town_admin.get((normalize_text(city_info['matched']), normalize_text(town_info['matched']), normalize_text(admin_candidate)), []))
        unique_scoped_rows = {r['rowid']: r for r in scoped_rows}
        scoped_rows = list(unique_scoped_rows.values())
        natural_values = unique_sorted(r[natural_spec['db_col']] for r in scoped_rows)

        if not parent_ok:
            status, matched, candidates, matched_rows = 'blocked_by_parent', None, [], []
        else:
            manual = apply_manual_confirmation('natural', f'{city}/{town}/{admin}', natural, natural_values, manual_confirmations)
            if not manual:
                manual = apply_manual_confirmation('natural', f'{city} / {town} / {admin}', natural, natural_values, manual_confirmations)
            manual_meta = None
            if manual:
                status, matched, candidates, manual_meta = manual
            else:
                status, matched, candidates = match_value(natural, natural_values, natural_spec['suffixes'])
            if status in ('exact', 'manual_confirmed'):
                matched_rows = [r for r in scoped_rows if normalize_text(r[natural_spec['db_col']]) == normalize_text(matched)]
            elif status == 'suffix_normalized':
                matched_rows = [r for r in scoped_rows if strip_suffix(r[natural_spec['db_col']], natural_spec['suffixes']) == strip_suffix(matched, natural_spec['suffixes'])]
            else:
                matched_rows = []
            if status in ('exact', 'suffix_normalized', 'manual_confirmed'):
                rowids = sorted({r['rowid'] for r in matched_rows})
                if len(rowids) == 1:
                    matched_rowid = rowids[0]
                elif len(rowids) > 1:
                    row_scope_hint = normalize_text((manual_meta or {}).get('row_scope_hint', ''))
                    if row_scope_hint:
                        if row_scope_hint.startswith('rowid:'):
                            target_rowid = row_scope_hint.split(':', 1)[1].strip()
                            hinted_rowids = sorted({r['rowid'] for r in matched_rows if str(r['rowid']) == target_rowid})
                            if len(hinted_rowids) == 1:
                                matched_rowid = hinted_rowids[0]
                            else:
                                status, matched = 'ambiguous_row_scope', None
                                matched_rowid = ''
                        else:
                            scoped_by_hint = [r for r in matched_rows if normalize_text(r.get('区县级')) == row_scope_hint]
                            hinted_rowids = sorted({r['rowid'] for r in scoped_by_hint})
                            if len(hinted_rowids) == 1:
                                matched_rowid = hinted_rowids[0]
                            elif len(hinted_rowids) > 1:
                                signatures = {tuple(str(r.get(field) or '') for field in ['市级', '区县级', '乡镇级', '行政村', '自然村', '拼音', '方言分布', 'longitude', 'latitude', '备注', '暂时不用', '搜索用']) for r in scoped_by_hint}
                                if len(signatures) == 1:
                                    matched_rowid = hinted_rowids[0]
                                else:
                                    status, matched = 'ambiguous_row_scope', None
                                    matched_rowid = ''
                            else:
                                status, matched = 'ambiguous_row_scope', None
                                matched_rowid = ''
                    else:
                        signatures = {tuple(str(r.get(field) or '') for field in ['市级', '区县级', '乡镇级', '行政村', '自然村', '拼音', '方言分布', 'longitude', 'latitude', '备注', '暂时不用', '搜索用']) for r in matched_rows}
                        if len(signatures) == 1:
                            matched_rowid = rowids[0]
                        else:
                            status, matched = 'ambiguous_row_scope', None
                            matched_rowid = ''
                else:
                    status, matched = 'unmatched', None
                    matched_rowid = ''
            else:
                matched_rowid = ''
        natural_rows.append({
            'xlsx_row_number': row['xlsx_row_number'],
            'xlsx_city': city,
            'xlsx_town': town,
            'xlsx_admin_village': admin,
            'matched_db_admin_village': admin_info['matched'] or '',
            'matched_db_admin_village_candidates': ' | '.join(admin_info['candidate_values']),
            'xlsx_natural_village': natural,
            'matched_db_city': city_info['matched'] or '',
            'matched_db_town': town_info['matched'] or '',
            'match_status': status,
            'matched_db_natural_village': matched or '',
            'matched_db_rowid': matched_rowid,
            'candidate_count': len(candidates),
            'candidates': ' | '.join(candidates),
            'suggested_candidates': ' | '.join(suggest_candidates(natural, natural_values, natural_spec['suffixes'], suggest_limit, suggest_min_score)) if not candidates else '',
            'dialect_value': row.get(config['dialect_col'], ''),
        })

    summary = {
        'city_mapping_status': dict(Counter(r['match_status'] for r in city_rows)),
        'town_mapping_status': dict(Counter(r['match_status'] for r in town_rows)),
        'admin_mapping_status': dict(Counter(r['match_status'] for r in admin_rows)),
        'natural_mapping_status': dict(Counter(r['match_status'] for r in natural_rows)),
        'observed_suffixes': {k: dict(v.most_common(40)) for k, v in observed_suffixes.items()},
        'notes': {
            'db_unique_key': 'none_declared',
            'recommended_update_key': config['db_identity'],
            'blocked_by_parent_meaning': 'parent level not uniquely matched, so child level was intentionally not attempted',
            'ambiguous_admin_natural_scope': 'when admin match is village/community dual candidate, natural village matching searches both candidate admin scopes',
        },
    }

    unresolved_town = [r for r in town_rows if r['match_status'] not in ('exact', 'suffix_normalized', 'manual_confirmed')]
    unresolved_admin = [r for r in admin_rows if r['match_status'] not in ('exact', 'suffix_normalized', 'manual_confirmed', 'ambiguous_normalized')]
    unresolved_natural = [r for r in natural_rows if r['match_status'] not in ('exact', 'suffix_normalized', 'manual_confirmed')]

    review_rows = []
    for row in unresolved_town:
        if row['suggested_candidates']:
            review_rows.append({'level': 'town', 'parent_scope': row['xlsx_city'], 'source_value': row['xlsx_town'], 'status': row['match_status'], 'suggested_candidates': row['suggested_candidates'], 'auto_review_hint': 'confirm_parent_city_already_matched', 'recommended_action': 'confirm_or_reject'})
    for row in unresolved_admin:
        if row['suggested_candidates']:
            review_rows.append({'level': 'admin', 'parent_scope': f"{row['xlsx_city']} / {row['xlsx_town']}", 'source_value': row['xlsx_admin_village'], 'status': row['match_status'], 'suggested_candidates': row['suggested_candidates'], 'auto_review_hint': 'confirm_parent_city_town_already_matched', 'recommended_action': 'confirm_or_reject'})
    seen_natural = set()
    for row in unresolved_natural:
        if row['suggested_candidates']:
            key = (row['xlsx_city'], row['xlsx_town'], row['xlsx_admin_village'], row['xlsx_natural_village'], row['suggested_candidates'])
            if key in seen_natural:
                continue
            seen_natural.add(key)
            review_rows.append({'level': 'natural', 'parent_scope': f"{row['xlsx_city']} / {row['xlsx_town']} / {row['xlsx_admin_village']}", 'source_value': row['xlsx_natural_village'], 'status': row['match_status'], 'suggested_candidates': row['suggested_candidates'], 'auto_review_hint': 'confirm_parent_chain_already_matched', 'recommended_action': 'confirm_or_reject'})

    write_csv(out_dir / 'city_mapping.csv', city_rows, ['xlsx_city', 'match_status', 'matched_db_city', 'candidate_count', 'candidates', 'suggested_candidates'])
    write_csv(out_dir / 'town_mapping.csv', town_rows, ['xlsx_city', 'matched_db_city', 'xlsx_town', 'match_status', 'matched_db_town', 'candidate_count', 'candidates', 'suggested_candidates'])
    write_csv(out_dir / 'admin_village_mapping.csv', admin_rows, ['xlsx_city', 'xlsx_town', 'matched_db_city', 'matched_db_town', 'xlsx_admin_village', 'match_status', 'matched_db_admin_village', 'candidate_count', 'candidates', 'suggested_candidates'])
    write_csv(out_dir / 'natural_village_mapping.csv', natural_rows, ['xlsx_row_number', 'xlsx_city', 'xlsx_town', 'xlsx_admin_village', 'matched_db_admin_village', 'matched_db_admin_village_candidates', 'xlsx_natural_village', 'matched_db_city', 'matched_db_town', 'match_status', 'matched_db_natural_village', 'matched_db_rowid', 'candidate_count', 'candidates', 'suggested_candidates', 'dialect_value'])
    write_csv(out_dir / 'town_unresolved.csv', unresolved_town, ['xlsx_city', 'matched_db_city', 'xlsx_town', 'match_status', 'matched_db_town', 'candidate_count', 'candidates', 'suggested_candidates'])
    write_csv(out_dir / 'admin_village_unresolved.csv', unresolved_admin, ['xlsx_city', 'xlsx_town', 'matched_db_city', 'matched_db_town', 'xlsx_admin_village', 'match_status', 'matched_db_admin_village', 'candidate_count', 'candidates', 'suggested_candidates'])
    write_csv(out_dir / 'natural_village_unresolved.csv', unresolved_natural, ['xlsx_row_number', 'xlsx_city', 'xlsx_town', 'xlsx_admin_village', 'matched_db_admin_village', 'matched_db_admin_village_candidates', 'xlsx_natural_village', 'matched_db_city', 'matched_db_town', 'match_status', 'matched_db_natural_village', 'matched_db_rowid', 'candidate_count', 'candidates', 'suggested_candidates', 'dialect_value'])
    write_csv(out_dir / 'manual_review_candidates.csv', review_rows, ['level', 'parent_scope', 'source_value', 'status', 'suggested_candidates', 'auto_review_hint', 'recommended_action'])

    with open(out_dir / 'structure_summary.json', 'w', encoding='utf-8') as f:
        json.dump(structure_summary, f, ensure_ascii=False, indent=2)
    with open(out_dir / 'matching_summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(out_dir / 'unmatched_and_ambiguous.json', 'w', encoding='utf-8') as f:
        json.dump({'city': [r for r in city_rows if r['match_status'] not in ('exact', 'suffix_normalized', 'manual_confirmed')], 'town': unresolved_town, 'admin': unresolved_admin, 'natural_sample': unresolved_natural[:1000]}, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        'xlsx_rows': len(xlsx_rows),
        'db_rows': len(db_rows),
        'city_status': summary['city_mapping_status'],
        'town_status': summary['town_mapping_status'],
        'admin_status': summary['admin_mapping_status'],
        'natural_status': summary['natural_mapping_status'],
        'manual_review_rows': len(review_rows),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    config_path = sys.argv[1] if len(sys.argv) > 1 else 'mapping_config.json'
    main(config_path)
