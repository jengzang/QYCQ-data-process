#!/usr/bin/env python3
import argparse
import csv
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
STAGING_DB = WORKDIR / 'villages_fromJNU.db'
RULES_DOC = WORKDIR / 'docs' / 'dialect_rules.md'
ARTIFACT_DIR = WORKDIR / 'artifacts' / 'dialect_llm_review'
RUN_ARTIFACT_DIR = ARTIFACT_DIR / 'runs'
OUTPUT_CSV = ARTIFACT_DIR / 'llm_adjudication_review.csv'
TABLE_NAME = 'jnu_dialect_llm_adjudication'
DOTENV_PATH = WORKDIR / '.env'

DEFAULT_PROVIDER = 'deepseek'
DEFAULT_MODEL = 'deepseek-chat'
DEFAULT_BASE_URL = 'https://api.deepseek.com/v1/chat/completions'
DEFAULT_WIRE_API = 'chat_completions'
PROMPT_VERSION = 'dialect_llm_v1'
KNOWN_FAMILIES = {'粤', '客家', '闽', '土话', '官话', '湘语', '少数民族', '其他'}
OCR_SUSPECT_TOKENS = [
    '方盲', '方育', '方首', '方官', '方宙', '専方言', '專方言', '岑方言',
    '考方言', '毒方言', '邮方言', '闫方言', '闻方言', '闽万言', '霉方言',
    '四巨话', '四色话', '四包话',
]
CLEAR_SUBGROUPS = {
    '四邑话', '台山话', '雷州话', '潮汕话', '电白海话', '电白黎话',
    '高要话', '怀集上坊话', '怀集诗洞标话', '怀集下坊话', '怀集永固标话',
    '阳春白话', '恩平话', '封川话', '开建话', '广宁话', '清远白话',
    '吴川话', '化州白话', '化州话', '袂花话', '始兴话', '涯话',
    '瑶语', '连山壮话', '蓝田话', '福佬话', '虱婆声', '星子话',
}
CLEAR_FAMILY_ONLY = {'粤', '客家', '闽', '少数民族', '土话', '官话'}
MIXED_COMPLEX_TERMS = [
    '先辈', '现', '承传', '兼用', '部分', '多数', '少数', '汉族', '壮族',
    '瑶族', '归侨', '互通', '和', '及', '但', '姓', '家族', '内部',
]
OCR_ALREADY_FIXED_TOKENS = ['方盲', '四色话', '四包话', '四巨话']

FEW_SHOT_EXAMPLES = [
    ('粤方言四邑话', '粤·四邑话', '原文已明确大类和小类'),
    ('粤方言四包话', '粤·四邑话', '四包话按规则归一为四邑话'),
    ('闽南方言潮州话', '闽·潮汕话', '潮州话归一到潮汕话'),
    ('通用雷州话', '闽·雷州话', '通用只是使用说明，雷州话属闽'),
    ('客家方言阳春倔话', '客家·阳春涯话', '倔话按既有规则归一为涯话'),
    ('客家方言、粤方言', '客家、粤', '多个真实大类并列时保留多成分'),
    ('使用壮语北部方言连山壮话', '少数民族·连山壮话', '壮语/连山壮话归少数民族'),
    ('越南语（因归侨较多）', '其他·越南语', '无法归入既有大类时使用其他，并尽量保留小类'),
    ('方言', '其他', '仅泛称方言且无足够证据时使用其他并标记人工复核'),
]


def normalize_text(value):
    return str(value or '').strip()


def load_dotenv(path=DOTENV_PATH):
    loaded = {}
    path = Path(path)
    if not path.exists():
        return loaded
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value
        loaded[key] = value
    return loaded


def split_components(value):
    return [part.strip() for part in normalize_text(value).split('、') if part.strip()]


def validate_final_value(value):
    errors = []
    components = split_components(value)
    if not components:
        return ['empty_final_value']
    for component in components:
        family = component.split('·', 1)[0].strip()
        if family not in KNOWN_FAMILIES:
            errors.append(f'missing_known_family:{component}')
        if component.count('·') > 1:
            errors.append(f'too_many_separators:{component}')
        if '·' in component:
            subgroup = component.split('·', 1)[1].strip()
            if not subgroup:
                errors.append(f'empty_subgroup:{component}')
    return errors


def parse_llm_json(text):
    payload = normalize_text(text)
    if payload.startswith('```'):
        lines = payload.splitlines()
        if lines and lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].startswith('```'):
            lines = lines[:-1]
        payload = '\n'.join(lines).strip()
    start = payload.find('{')
    end = payload.rfind('}')
    if start >= 0 and end >= start:
        payload = payload[start:end + 1]
    return json.loads(payload)


def needs_llm_review(row):
    confidence = normalize_text(row.get('clean_confidence'))
    primary_family = normalize_text(row.get('primary_family'))
    dialect_raw = normalize_text(row.get('dialect_raw'))
    if confidence in {'low', 'medium'}:
        return True
    if primary_family == '混合':
        return True
    return any(token in dialect_raw for token in OCR_SUSPECT_TOKENS)


def is_clear_family_only(raw, family):
    if family not in CLEAR_FAMILY_ONLY:
        return False
    return (
        f'{family}方言' in raw
        or f'{family}话' in raw
        or (family == '粤' and '粤语' in raw)
        or (family == '客家' and '客家话' in raw)
        or (family == '闽' and '闽方言' in raw)
    )


def needs_priority_llm_review(row):
    confidence = normalize_text(row.get('clean_confidence'))
    family = normalize_text(row.get('primary_family'))
    subgroup = normalize_text(row.get('primary_subgroup'))
    raw = normalize_text(row.get('dialect_raw'))
    final_value = normalize_text(row.get('final_write_value')) or render_rule_summary(row)
    if confidence == 'low' or not family or not final_value:
        return True
    if family == '混合':
        if any(term in raw for term in MIXED_COMPLEX_TERMS):
            return True
        mixed_subgroup = normalize_text(row.get('mixed_subgroup_text'))
        return bool(mixed_subgroup)
    if any(token in raw for token in OCR_SUSPECT_TOKENS) and not any(token in raw for token in OCR_ALREADY_FIXED_TOKENS):
        return True
    if confidence == 'medium' and family in CLEAR_FAMILY_ONLY:
        if subgroup in CLEAR_SUBGROUPS:
            return False
        if not subgroup and final_value == family and is_clear_family_only(raw, family):
            return False
    return confidence == 'medium'


def render_rule_summary(row):
    family = normalize_text(row.get('primary_family'))
    subgroup = normalize_text(row.get('primary_subgroup'))
    if family and family != '混合':
        return f'{family}·{subgroup}' if subgroup else family
    mixed = normalize_text(row.get('mixed_family_text'))
    mixed_subgroup = normalize_text(row.get('mixed_subgroup_text'))
    if mixed or mixed_subgroup:
        return '、'.join(part for part in [mixed, mixed_subgroup] if part)
    return subgroup or ''


def compact_rules_text(max_chars=12000):
    if not RULES_DOC.exists():
        return ''
    text = RULES_DOC.read_text(encoding='utf-8')
    keep_markers = [
        '## 4. 方言清洗规则',
        '## 5. OCR/错字/异形字处理',
        '## 6. 写回值生成与聚合',
        '## 8. 当前已知待确认点',
    ]
    chunks = []
    for marker in keep_markers:
        start = text.find(marker)
        if start < 0:
            continue
        next_start = text.find('\n## ', start + 1)
        chunks.append(text[start:next_start if next_start > start else len(text)])
    compact = '\n\n'.join(chunks) if chunks else text
    return compact[:max_chars]


def build_user_prompt(record, special_rules):
    payload = {
        'xlsx_row_number': record.get('xlsx_row_number'),
        'geo': {
            'city': record.get('xlsx_city'),
            'town': record.get('xlsx_town'),
            'admin_village': record.get('xlsx_admin_village'),
            'natural_village': record.get('xlsx_natural_village'),
            'matched_db_rowid': record.get('matched_db_rowid'),
            'match_status': record.get('match_status'),
        },
        'dialect_raw': record.get('dialect_raw'),
        'rule_baseline': {
            'primary_family': record.get('primary_family'),
            'primary_subgroup': record.get('primary_subgroup'),
            'mixed_family_text': record.get('mixed_family_text'),
            'mixed_subgroup_text': record.get('mixed_subgroup_text'),
            'final_write_value': record.get('final_write_value') or render_rule_summary(record),
            'clean_confidence': record.get('clean_confidence'),
        },
        'village_context': {
            'village_name_source': record.get('村名来源'),
            'build_time': record.get('建村时间'),
            'resident_surnames': record.get('世居村民姓氏'),
            'ethnicity': record.get('居民民族'),
            'history': record.get('村历史沿革'),
            'customs_architecture_products': record.get('村俗或传统民居或村特色产品'),
            'location': record.get('位置'),
        },
    }
    example_text = '\n'.join(
        f'- {raw} -> {final_value}（{reason}）'
        for raw, final_value, reason in FEW_SHOT_EXAMPLES
    )
    return (
        '你是广东自然村方言数据清洗助手。请根据原始方言文本、村庄上下文、民系/迁徙线索、'
        '已有规则清洗结果和特殊规则，判定该行最终应归一化的方言值。\n\n'
        '硬性要求：\n'
        '1. 必须有方言大类；大类只能是：粤、客家、闽、土话、官话、湘语、少数民族、其他。\n'
        '   如果无法可靠归入前七类，允许使用“其他”。\n'
        '2. 方言小类要尽量给出；如果证据实在不足，小类可以留空。\n'
        '3. 最终值格式只能是“大类”或“大类·小类”；多个成分用“、”连接。\n'
        '4. 原始方言字段是最高优先级证据；村史、民系、建筑、迁徙线索只能辅助，不得随意推翻清晰原文。\n'
        '5. OCR/异形字按特殊规则处理；无法确认时必须 needs_human_review=true。\n'
        '6. 只输出 JSON，不要输出解释性段落。\n\n'
        f'判定示例：\n{example_text}\n\n'
        f'特殊规则：\n{special_rules}\n\n'
        f'输入记录：\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n'
        '请只输出 JSON，字段如下：\n'
        '{\n'
        '  "final_value": "粤·四邑话",\n'
        '  "family": "粤",\n'
        '  "subgroups": ["四邑话"],\n'
        '  "confidence": "high|medium|low",\n'
        '  "needs_human_review": false,\n'
        '  "evidence": ["简短证据"],\n'
        '  "applied_rules": ["命中的规则"],\n'
        '  "warnings": ["不确定点"]\n'
        '}'
    )


def build_system_prompt():
    return (
        '你只做结构化方言归一化。严格遵守用户给定类别、格式和 JSON schema。'
        '不要编造村庄事实；证据不足时降低置信度并标记人工复核。'
    )


def create_table(conn):
    conn.execute(f'''
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            xlsx_row_number INTEGER PRIMARY KEY,
            matched_db_rowid INTEGER,
            dialect_raw TEXT,
            rule_final_value TEXT,
            llm_final_value TEXT,
            llm_family TEXT,
            llm_subgroups_json TEXT,
            llm_confidence TEXT,
            needs_human_review INTEGER,
            evidence_json TEXT,
            applied_rules_json TEXT,
            warnings_json TEXT,
            validation_errors_json TEXT,
            prompt_version TEXT,
            model TEXT,
            provider TEXT,
            dry_run INTEGER,
            raw_response_json TEXT,
            request_payload_json TEXT,
            created_at TEXT
        )
    ''')
    conn.execute(f'CREATE INDEX IF NOT EXISTS idx_llm_dialect_rowid ON {TABLE_NAME}(matched_db_rowid)')
    conn.execute(f'CREATE INDEX IF NOT EXISTS idx_llm_dialect_review ON {TABLE_NAME}(needs_human_review)')


def fetch_records(conn, limit, only_review_candidates=True):
    conn.row_factory = sqlite3.Row
    dialect_cols = {
        row['name'] for row in conn.execute("PRAGMA table_info('jnu_dialect_clean')").fetchall()
    }
    final_write_expr = 'd.final_write_value' if 'final_write_value' in dialect_cols else "''"
    sql = '''
        SELECT
            v.xlsx_row_number,
            v.xlsx_city,
            v.xlsx_town,
            v.xlsx_admin_village,
            v.xlsx_natural_village,
            v.dialect_raw,
            v.match_status,
            v.matched_db_rowid,
            d.primary_family,
            d.primary_subgroup,
            d.mixed_family_text,
            d.mixed_subgroup_text,
            d.clean_confidence,
            {final_write_expr} AS final_write_value
        FROM jnu_villages v
        LEFT JOIN jnu_dialect_clean d ON d.xlsx_row_number = v.xlsx_row_number
        WHERE v.dialect_raw IS NOT NULL AND trim(v.dialect_raw) != ''
        ORDER BY v.xlsx_row_number
    '''.format(final_write_expr=final_write_expr)
    rows = [dict(row) for row in conn.execute(sql)]
    if only_review_candidates:
        rows = [row for row in rows if needs_llm_review(row)]
    if limit is not None:
        rows = rows[:limit]
    return rows


def filter_priority_records(rows):
    return [row for row in rows if needs_priority_llm_review(row)]


def select_records(conn, limit, all_rows=False, priority_candidates=False):
    fetch_limit = None if priority_candidates else limit
    records = fetch_records(conn, limit=fetch_limit, only_review_candidates=not all_rows)
    if priority_candidates:
        records = filter_priority_records(records)
        if limit is not None:
            records = records[:limit]
    return records


def load_xlsx_context_by_row():
    import sys

    sys.path.insert(0, str(WORKDIR / 'scripts'))
    import build_village_mapping

    _, rows = build_village_mapping.load_xlsx_rows(WORKDIR / 'Village.xlsx')
    return {row['xlsx_row_number']: row for row in rows}


def merge_context(record, xlsx_context):
    merged = dict(record)
    merged.update(xlsx_context.get(record['xlsx_row_number'], {}))
    return merged


def normalize_wire_api(wire_api):
    value = normalize_text(wire_api).lower().replace('-', '_')
    aliases = {
        'chat': 'chat_completions',
        'chat_completion': 'chat_completions',
        'chat_completions': 'chat_completions',
        'responses': 'responses',
        'response': 'responses',
    }
    if value not in aliases:
        raise ValueError(f'Unsupported LLM_WIRE_API: {wire_api}')
    return aliases[value]


def responses_endpoint(base_url):
    base = normalize_text(base_url).rstrip('/')
    if base.endswith('/responses'):
        return base
    return f'{base}/responses'


def build_llm_request(messages, model, base_url, wire_api):
    wire_api = normalize_wire_api(wire_api)
    if wire_api == 'chat_completions':
        return base_url, {
            'model': model,
            'messages': messages,
            'temperature': 0,
            'response_format': {'type': 'json_object'},
        }
    return responses_endpoint(base_url), {
        'model': model,
        'input': messages,
        'temperature': 0,
        'text': {'format': {'type': 'json_object'}},
    }


def extract_response_content(parsed, wire_api):
    wire_api = normalize_wire_api(wire_api)
    if wire_api == 'chat_completions':
        return parsed['choices'][0]['message']['content']
    if parsed.get('output_text'):
        return parsed['output_text']
    chunks = []
    for item in parsed.get('output', []):
        for content in item.get('content', []):
            if content.get('type') in {'output_text', 'text'} and content.get('text') is not None:
                chunks.append(content['text'])
    if chunks:
        return ''.join(chunks)
    raise KeyError('No text content found in responses API payload')


def extract_token_usage(parsed):
    usage = parsed.get('usage') if isinstance(parsed, dict) else None
    if not isinstance(usage, dict):
        return {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}
    input_tokens = usage.get('input_tokens', usage.get('prompt_tokens', 0)) or 0
    output_tokens = usage.get('output_tokens', usage.get('completion_tokens', 0)) or 0
    total_tokens = usage.get('total_tokens') or input_tokens + output_tokens
    return {
        'input_tokens': int(input_tokens),
        'output_tokens': int(output_tokens),
        'total_tokens': int(total_tokens),
    }


def resolve_api_key(primary_env):
    key = os.environ.get(primary_env)
    if key:
        return key, primary_env
    if primary_env != 'DEEPSEEK_API_KEY':
        fallback = os.environ.get('DEEPSEEK_API_KEY')
        if fallback:
            return fallback, 'DEEPSEEK_API_KEY'
    return None, primary_env


def call_llm(messages, provider, model, base_url, api_key, timeout, wire_api):
    request_url, request_body = build_llm_request(messages, model, base_url, wire_api)
    data = json.dumps(request_body, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        request_url,
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode('utf-8')
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'{provider} API HTTP {exc.code}: {error_body}') from exc
    parsed = json.loads(body)
    content = extract_response_content(parsed, wire_api)
    return parsed, content, request_body


def dry_run_response(record):
    value = record.get('final_write_value') or render_rule_summary(record)
    if not value or validate_final_value(value):
        family = normalize_text(record.get('primary_family'))
        subgroup = normalize_text(record.get('primary_subgroup'))
        if family in KNOWN_FAMILIES:
            value = f'{family}·{subgroup}' if subgroup else family
    if not value:
        value = ''
    validation_errors = validate_final_value(value) if value else ['empty_final_value']
    return {
        'final_value': value,
        'family': value.split('·', 1)[0].split('、', 1)[0] if value else '',
        'subgroups': [part.split('·', 1)[1] for part in split_components(value) if '·' in part],
        'confidence': 'low' if validation_errors else normalize_text(record.get('clean_confidence')) or 'medium',
        'needs_human_review': bool(validation_errors or needs_llm_review(record)),
        'evidence': ['dry-run: reused rule baseline without API call'],
        'applied_rules': ['dry_run_baseline'],
        'warnings': validation_errors,
    }


def normalize_result(result):
    return {
        'final_value': normalize_text(result.get('final_value')),
        'family': normalize_text(result.get('family')),
        'subgroups': result.get('subgroups') if isinstance(result.get('subgroups'), list) else [],
        'confidence': normalize_text(result.get('confidence')) or 'medium',
        'needs_human_review': bool(result.get('needs_human_review')),
        'evidence': result.get('evidence') if isinstance(result.get('evidence'), list) else [],
        'applied_rules': result.get('applied_rules') if isinstance(result.get('applied_rules'), list) else [],
        'warnings': result.get('warnings') if isinstance(result.get('warnings'), list) else [],
    }


def upsert_result(conn, record, result, validation_errors, metadata):
    conn.execute(f'''
        INSERT INTO {TABLE_NAME} (
            xlsx_row_number, matched_db_rowid, dialect_raw, rule_final_value,
            llm_final_value, llm_family, llm_subgroups_json, llm_confidence,
            needs_human_review, evidence_json, applied_rules_json, warnings_json,
            validation_errors_json, prompt_version, model, provider, dry_run,
            raw_response_json, request_payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(xlsx_row_number) DO UPDATE SET
            matched_db_rowid=excluded.matched_db_rowid,
            dialect_raw=excluded.dialect_raw,
            rule_final_value=excluded.rule_final_value,
            llm_final_value=excluded.llm_final_value,
            llm_family=excluded.llm_family,
            llm_subgroups_json=excluded.llm_subgroups_json,
            llm_confidence=excluded.llm_confidence,
            needs_human_review=excluded.needs_human_review,
            evidence_json=excluded.evidence_json,
            applied_rules_json=excluded.applied_rules_json,
            warnings_json=excluded.warnings_json,
            validation_errors_json=excluded.validation_errors_json,
            prompt_version=excluded.prompt_version,
            model=excluded.model,
            provider=excluded.provider,
            dry_run=excluded.dry_run,
            raw_response_json=excluded.raw_response_json,
            request_payload_json=excluded.request_payload_json,
            created_at=excluded.created_at
    ''', (
        record['xlsx_row_number'],
        record.get('matched_db_rowid'),
        record.get('dialect_raw'),
        record.get('final_write_value') or render_rule_summary(record),
        result['final_value'],
        result['family'],
        json.dumps(result['subgroups'], ensure_ascii=False),
        result['confidence'],
        1 if result['needs_human_review'] or validation_errors else 0,
        json.dumps(result['evidence'], ensure_ascii=False),
        json.dumps(result['applied_rules'], ensure_ascii=False),
        json.dumps(result['warnings'], ensure_ascii=False),
        json.dumps(validation_errors, ensure_ascii=False),
        PROMPT_VERSION,
        metadata['model'],
        metadata['provider'],
        1 if metadata['dry_run'] else 0,
        json.dumps(metadata.get('raw_response'), ensure_ascii=False),
        json.dumps(metadata.get('request_payload'), ensure_ascii=False),
        datetime.now().isoformat(timespec='seconds'),
    ))


def export_review_csv(conn):
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f'''
        SELECT
            xlsx_row_number, matched_db_rowid, dialect_raw, rule_final_value,
            llm_final_value, llm_confidence, needs_human_review,
            validation_errors_json, evidence_json, warnings_json, model, dry_run, created_at
        FROM {TABLE_NAME}
        ORDER BY xlsx_row_number
    ''').fetchall()
    fieldnames = [
        'xlsx_row_number', 'matched_db_rowid', 'dialect_raw', 'rule_final_value',
        'llm_final_value', 'llm_confidence', 'needs_human_review',
        'validation_errors_json', 'evidence_json', 'warnings_json', 'model', 'dry_run', 'created_at',
    ]
    with OUTPUT_CSV.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))
    return len(rows)


def export_run_csv(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=RUN_CSV_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, '') for key in RUN_CSV_FIELDNAMES})
    return len(rows)


RUN_CSV_FIELDNAMES = [
    'xlsx_row_number', 'matched_db_rowid', 'dialect_raw', 'rule_final_value',
    'llm_final_value', 'llm_confidence', 'needs_human_review',
    'validation_errors_json', 'evidence_json', 'warnings_json', 'model', 'dry_run', 'created_at',
]


def append_run_csv(row, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open('a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=RUN_CSV_FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerow({key: row.get(key, '') for key in RUN_CSV_FIELDNAMES})


def filter_existing_successful_records(conn, records):
    if not records:
        return records
    create_table(conn)
    existing = {
        row[0] for row in conn.execute(
            f'SELECT xlsx_row_number FROM {TABLE_NAME} WHERE dry_run = 0 AND llm_final_value IS NOT NULL AND trim(llm_final_value) != ""'
        )
    }
    return [record for record in records if record.get('xlsx_row_number') not in existing]


def parse_args():
    load_dotenv()
    parser = argparse.ArgumentParser(description='Use an LLM to adjudicate normalized dialect values.')
    parser.add_argument('--limit', type=int, default=20, help='Maximum rows to process. Use 0 for all selected rows.')
    parser.add_argument('--all-rows', action='store_true', help='Process all nonempty dialect rows, not just low/medium/mixed/OCR-suspect rows.')
    parser.add_argument('--priority-candidates', action='store_true', help='Process only high-priority ambiguous rows from the review candidate set.')
    parser.add_argument('--dry-run', action='store_true', help='Do not call the API; reuse rule baseline and write review rows.')
    parser.add_argument('--apply', action='store_true', help='Actually call the configured LLM API.')
    parser.add_argument('--provider', default=os.environ.get('LLM_PROVIDER', DEFAULT_PROVIDER))
    parser.add_argument('--model', default=os.environ.get('LLM_MODEL', DEFAULT_MODEL))
    parser.add_argument('--base-url', default=os.environ.get('LLM_BASE_URL', DEFAULT_BASE_URL))
    parser.add_argument('--wire-api', default=os.environ.get('LLM_WIRE_API', DEFAULT_WIRE_API), choices=['chat_completions', 'chat-completions', 'chat', 'responses'])
    parser.add_argument('--api-key-env', default=os.environ.get('LLM_API_KEY_ENV', 'LLM_API_KEY'))
    parser.add_argument('--sleep', type=float, default=0.0, help='Seconds to sleep between API calls.')
    parser.add_argument('--timeout', type=float, default=60.0)
    parser.add_argument('--skip-existing', action='store_true', help='Skip rows that already have a non-dry-run LLM result.')
    parser.add_argument('--progress-every', type=int, default=10, help='Print progress every N processed rows. Use 0 to disable.')
    return parser.parse_args()


def main():
    args = parse_args()
    dry_run = args.dry_run or not args.apply
    limit = None if args.limit == 0 else args.limit
    wire_api = normalize_wire_api(args.wire_api)
    api_key, resolved_key_env = resolve_api_key(args.api_key_env)
    if not dry_run and not api_key:
        raise RuntimeError(f'Missing API key env var: {args.api_key_env}')

    special_rules = compact_rules_text()
    xlsx_context = load_xlsx_context_by_row()

    conn = sqlite3.connect(STAGING_DB)
    create_table(conn)
    records = select_records(conn, limit=limit, all_rows=args.all_rows, priority_candidates=args.priority_candidates)
    selected_before_skip = len(records)
    if args.skip_existing:
        records = filter_existing_successful_records(conn, records)
    processed = 0
    failures = []
    run_rows = []
    run_started_at = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_csv = RUN_ARTIFACT_DIR / f'llm_adjudication_run_{run_started_at}.csv'
    token_usage = {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}

    for base_record in records:
        record = merge_context(base_record, xlsx_context)
        prompt = build_user_prompt(record, special_rules)
        messages = [
            {'role': 'system', 'content': build_system_prompt()},
            {'role': 'user', 'content': prompt},
        ]
        raw_response = None
        request_payload = {'model': args.model, 'messages': messages, 'dry_run': dry_run}
        try:
            if dry_run:
                llm_result = dry_run_response(record)
            else:
                raw_response, content, request_payload = call_llm(
                    messages, args.provider, args.model, args.base_url, api_key, args.timeout, wire_api
                )
                current_usage = extract_token_usage(raw_response)
                for key in token_usage:
                    token_usage[key] += current_usage[key]
                llm_result = parse_llm_json(content)
            result = normalize_result(llm_result)
            validation_errors = validate_final_value(result['final_value'])
            if validation_errors:
                result['needs_human_review'] = True
                result['warnings'] = sorted(set(result['warnings'] + validation_errors))
            upsert_result(conn, record, result, validation_errors, {
                'provider': args.provider,
                'model': args.model,
                'dry_run': dry_run,
                'raw_response': raw_response or llm_result,
                'request_payload': request_payload,
            })
            processed += 1
            run_row = {
                'xlsx_row_number': record['xlsx_row_number'],
                'matched_db_rowid': record.get('matched_db_rowid'),
                'dialect_raw': record.get('dialect_raw'),
                'rule_final_value': record.get('final_write_value') or render_rule_summary(record),
                'llm_final_value': result['final_value'],
                'llm_confidence': result['confidence'],
                'needs_human_review': 1 if result['needs_human_review'] or validation_errors else 0,
                'validation_errors_json': json.dumps(validation_errors, ensure_ascii=False),
                'evidence_json': json.dumps(result['evidence'], ensure_ascii=False),
                'warnings_json': json.dumps(result['warnings'], ensure_ascii=False),
                'model': args.model,
                'dry_run': 1 if dry_run else 0,
                'created_at': datetime.now().isoformat(timespec='seconds'),
            }
            run_rows.append(run_row)
            append_run_csv(run_row, run_csv)
            conn.commit()
            if args.progress_every and processed % args.progress_every == 0:
                print(json.dumps({
                    'progress': processed,
                    'selected': len(records),
                    'failures': len(failures),
                    'total_tokens': token_usage['total_tokens'],
                    'run_csv': str(run_csv.relative_to(WORKDIR)),
                }, ensure_ascii=False), flush=True)
        except Exception as exc:
            failures.append({'xlsx_row_number': record.get('xlsx_row_number'), 'error': str(exc)})
        if args.sleep:
            time.sleep(args.sleep)

    conn.commit()
    exported = export_review_csv(conn)
    exported_run_rows = len(run_rows)
    conn.close()
    print(json.dumps({
        'processed': processed,
        'selected': len(records),
        'selected_before_skip': selected_before_skip,
        'failures': failures,
        'dry_run': dry_run,
        'wire_api': wire_api,
        'api_key_env': resolved_key_env,
        'token_usage': token_usage,
        'avg_tokens_per_processed_row': round(token_usage['total_tokens'] / processed, 2) if processed else 0,
        'table': TABLE_NAME,
        'review_csv': str(OUTPUT_CSV.relative_to(WORKDIR)),
        'exported_review_rows': exported,
        'run_csv': str(run_csv.relative_to(WORKDIR)),
        'exported_run_rows': exported_run_rows,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
