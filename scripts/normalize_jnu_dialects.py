#!/usr/bin/env python3
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

DB_PATH = Path('villages_fromJNU.db')

FAMILY_RULES = [
    ('粤', re.compile(r'粤方言|粤语|白话|广府话|广府方言|四邑话|台山话|恩平话|高州话|吴川话|阳江话|阳春白话|广宁话|德庆话|封川话|石岐话|四会话|连州话|龙门话|开建话|怀集.*话|星子话|袂花话|高要话|鼎湖.*话|沙田话|化州话')),
    ('客家', re.compile(r'客家方言|客家话|客家语言|客家语|客方言|涯话|倔话|涯语|上莞话|清化话|黄村话|叶潭话|蓝口话|仁化董塘话|仁化长江话|四会地豆话|四会迳口话|偃话')),
    ('闽', re.compile(r'闽方言|闽南方言|闽南语|潮州话|潮州语|潮汕话|潮汕方言|潮油话|学佬话|黎话|海话|海丰话|福佬话|雷州话|雷州方言|雷话|隆都话|连滩话|电白黎话|电白海话')),
    ('少数民族', re.compile(r'壮话|壮语|壮方言|瑶话|瑶语|瑶族方言|畲话|畬话|勉语|蓝田话')),
    ('土话', re.compile(r'虱婆声|虱话|潭岭话|黄圃话|土话')),
    ('官话', re.compile(r'普通话|旧时正话|四川话|四川方言|重庆话|重庆方言|军话|军声|官话')),
]

EXPLICIT_FAMILY_PREFIX_RULES = [
    ('客家', re.compile(r'^(?:使用)?客家(?:方言|话|语言|语)')),
    ('粤', re.compile(r'^(?:使用)?粤(?:方言|语)|^(?:使用)?白话|^(?:使用)?广府(?:话|方言)')),
    ('闽', re.compile(r'^(?:使用)?闽(?:方言|南方言|南语)|^(?:使用)?潮(?:州话|州语|汕话)|^(?:使用)?学佬话|^(?:使用)?福佬话|^(?:使用)?雷州方言|^(?:使用)?雷话')),
    ('少数民族', re.compile(r'^(?:使用)?(?:壮话|壮语|壮方言|瑶话|瑶语|瑶族方言|畲话|畬话|蓝田话)')),
    ('土话', re.compile(r'^(?:使用)?(?:土话|虱婆声|虱话|潭岭话|黄圃话)')),
    ('官话', re.compile(r'^(?:使用)?(?:普通话|旧时正话|四川话|四川方言|重庆话|重庆方言|军话|军声|官话)')),
]

SUBGROUP_PATTERNS = [
    '四邑话', '台山话', '恩平话', '阳春白话', '吴川话', '广宁话', '清远白话', '化州白话', '化州话', '德庆话', '电白黎话', '电白海话',
    '开建话', '封川话', '高州话', '沙田话', '高阳片阳江话', '阳江话', '高要话', '鼎湖话', '怀集下坊话', '怀集上坊话', '怀集宁洞话',
    '怀集话', '怀集诗洞标话', '怀集永固标话', '怀集梁村标话', '始兴话', '仁化董塘话', '仁化长江话', '黄村话', '黄圃话', '叶潭话', '蓝口话',
    '蓝田话', '东莞清溪话', '东莞樟木头话', '东莞凤岗话', '雷州话', '潮州话', '潮州语', '潮汕话', '潮油话', '学佬话', '海丰话', '隆都话', '连滩话', '福佬话', '连山壮话', '瑶语', '瑶族方言',
    '畲话', '军话', '军声', '蛇声', '虱婆声', '虱话', '星子话', '袂花话', '石岐话', '龙门话', '连州话', '清化话', '能古话', '涯话', '上莞话', '偃话',
    '潭岭话', '四会话', '旧时正话', '普通话', '四川话', '重庆话', '官话', '尖米话', '惠州地方话', '仁化塞麻话', '黄圃话', '船话', '船婆声', '通用连州阿B声', '四包话', '四色话', '思平话', '罗广话'
]
SUBGROUP_PATTERNS = sorted(set(SUBGROUP_PATTERNS), key=len, reverse=True)

ACCENT_PATTERNS = [
    r'([\u4e00-\u9fff]{1,8}口音)',
    r'([\u4e00-\u9fff]{1,12}标话)',
    r'([\u4e00-\u9fff]{1,12}土话)',
    r'([\u4e00-\u9fff]{1,12}古话)',
    r'([\u4e00-\u9fff]{1,12}蛇声)',
    r'([\u4e00-\u9fff]{1,12}虱婆声)',
]

USAGE_KEYWORDS = ['使用', '通用', '先辈', '现村民', '现使用', '对内', '对外', '部分', '同时', '互通', '能在村民中互通', '以普通话为主', '说重庆话']
IDENTITY_KEYWORDS = ['广府民系', '客家民系', '潮汕民系', '属广府民系', '属客家民系']
MULTI_SEP_RE = re.compile(r'[，、；/]')
PAREN_RE = re.compile(r'[（(](.*?)[）)]')
ALIAS_SUBGROUPS = {
    '高阳片阳江话': '阳江话',
    '潮州话': '潮汕话',
    '潮汕方言': '潮汕话',
    '潮州语': '潮汕话',
    '潮州方言': '潮汕话',
    '闽南方言潮州话': '潮汕话',
    '闽南方言饶平潮州话': '潮汕话',
    '闽方言潮汕话': '潮汕话',
    '闽南语': '闽',
    '粤方言高阳片阳江话': '阳江话',
    '粤方言阳春白话': '阳春白话',
    '粤方言四邑话': '四邑话',
    '粤方言台山话': '台山话',
    '粤方言广宁话': '广宁话',
    '粤方言清远白话': '清远白话',
    '粤方言怀集上坊话': '怀集上坊话',
    '粤方言怀集下坊话': '怀集下坊话',
    '粤方言雷州话': '雷州话',
    '雷州方言': '雷州话',
    '粤方言古话': '能古话',
    '粤方言能古话': '能古话',
    '粤方言催古话': '能古话',
    '粤方言佳古话': '能古话',
    '粤方言候古话': '能古话',
    '粤方言健古话': '能古话',
    '催古话': '能古话',
    '古话（广府民系）': '能古话',
    '使用古话': '能古话',
    '使用古话（广府民系）': '能古话',
    '粤方言东莞虎门话': '东莞虎门话',
    '粤方言东莞万江话': '东莞万江话',
    '粤方言东莞厚街话': '东莞厚街话',
    '粤方言东莞寮步话': '东莞寮步话',
    '粤方言东莞塘厦话': '东莞塘厦话',
    '粤方言东莞清溪话': '东莞清溪话',
    '粤方言东莞凤岗话': '东莞凤岗话',
    '粤方言四会地豆话': '四会地豆话',
    '粤方言四会迳口话': '四会迳口话',
    '粤方言鼎湖话': '鼎湖话',
    '广府话': '粤',
    '广府方言': '粤',
    '粵方言': '粤',
    '粤方盲': '粤',
    '粤方育': '粤',
    '粤方首': '粤',
    '客家方盲': '客家',
    '客家方音': '客家',
    '客家语言': '客家',
    '客方言': '客家',
    '客家方': '客家',
    '客家方官': '客家',
    '客家方宙': '客家',
    '客家语': '客家',
    '偃话': '涯话',
    '畬话': '畲话',
    '畬话方言': '畲话',
    '虱话': '虱婆声',
    '韶关话（虱婆声）': '虱婆声',
    '通用韶关话（虱婆声）': '虱婆声',
    '通用虱话': '虱婆声',
    '通用虱婆声': '虱婆声',
    '使用蓝田话': '蓝田话',
    '使用瑶族方言': '瑶族方言',
    '使用壮方言': '壮方言',
    '东莞方言': '粤',
    '四会话': '四会话',
    '普通话': '普通话',
    '以普通话为主': '普通话',
    '旧时正话': '旧时正话',
    '通用旧时正话': '旧时正话',
    '四川话': '四川话',
    '四川方言': '四川话',
    '重庆话': '重庆话',
    '重庆方言': '重庆话',
    '通用重庆话': '重庆话',
    '说重庆话': '重庆话',
    '军声': '军话',
    '学佬话': '学佬话',
    '潮汕民系，通用学佬话': '学佬话',
    '闽南民系，通用学佬话': '学佬话',
    '潮汕民系，通用潮油话': '潮汕话',
    '闽南话': '闽',
    '雷话': '雷州话',
    '海丰话': '海丰话',
    '四色话': '四邑话',
    '四包话': '四邑话',
    '尊方言四巨话': '四邑话',
    '粤言语四色话': '四邑话',
    '使用粵方言蛇声': '蛇声',
    '容家方盲': '粤',
    '専方言': '粤',
    '專方言': '粤',
    '岑方言': '粤',
    '考方言': '粤',
    '通用萼方言': '粤',
    '等方盲': '粤',
    '粤方盲高阳片阳江方言（广府民系）': '阳江话',
    '粤方语化州话': '化州话',
    '邮方言': '粤',
    '毒方言': '粤',
    '每方台': '粤',
    '广府民系，通用等方言': '粤',
    '广府民系，使用萼方言西邑话': '四邑话',
    '广府民系，使用寿方言': '粤',
    '廣府民系，使用専方言': '粤',
}

DIRECT_RAW_VALUE_MAP = {
    '潮汕方言': ('闽', '潮汕话'),
    '使用潮汕方言': ('闽', '潮汕话'),
    '闽南语': ('闽', None),
    '通用闽南语': ('闽', None),
    '客家方盲': ('客家', None),
    '客家方音': ('客家', None),
    '客家语言': ('客家', None),
    '客方言': ('客家', None),
    '客家方': ('客家', None),
    '客家方官': ('客家', None),
    '客家方宙': ('客家', None),
    '客家语': ('客家', None),
    '粤方盲': ('粤', None),
    '粵方言': ('粤', None),
    '粤方育': ('粤', None),
    '粤方首': ('粤', None),
    '广府话': ('粤', None),
    '广府方言': ('粤', None),
    '广府民系，通用廣府方言': ('粤', None),
    '雷州方言': ('闽', '雷州话'),
    '催古话': ('粤', '能古话'),
    '使用古话': ('粤', '能古话'),
    '使用古话（广府民系）': ('粤', '能古话'),
    '古话（广府民系）': ('粤', '能古话'),
    '广府民系，使用催古话': ('粤', '能古话'),
    '畬话': ('少数民族', '畲话'),
    '畬话方言': ('少数民族', '畲话'),
    '壮方言': ('少数民族', None),
    '使用壮方言': ('少数民族', None),
    '虱婆声': ('土话', '虱婆声'),
    '虱话': ('土话', '虱婆声'),
    '通用虱话': ('土话', '虱婆声'),
    '通用虱婆声': ('土话', '虱婆声'),
    '韶关话（虱婆声）': ('土话', '虱婆声'),
    '通用韶关话（虱婆声）': ('土话', '虱婆声'),
    '潭岭话': ('土话', '潭岭话'),
    '黄圃话': ('土话', '黄圃话'),
    '方言': (None, None),
    '广府民系': ('粤', None),
    '广府民系，使用方言': ('粤', None),
    '使用方言': (None, None),
    '通用方言': (None, None),
    '当地方言': (None, None),
    '方言（广府民系）': ('粤', None),
    '广府民系方言': ('粤', None),
    '广府民系方言，通用方言': ('粤', None),
    '惠州地方话': ('土话', '惠州地方话'),
    '容家方言': ('客家', None),
    '容家方盲': ('客家', None),
    '罗广话': ('粤', '罗广话'),
    '仁化塞麻话': ('土话', '仁化塞麻话'),
    '思平话': ('粤', '思平话'),
    '海丰话': ('闽', '海丰话'),
    '通用高要方言莲塘话': ('粤', '高要方莲塘话'),
    '通用连州阿B声': ('土话', '连州阿B声'),
    '船话': ('土话', '船话'),
    '船婆声': ('土话', '船婆声'),
    '四色话': ('粤', '四邑话'),
    '四包话': ('粤', '四邑话'),
    '尊方言四巨话': ('粤', '四邑话'),
    '専方言': ('粤', None),
    '專方言': ('粤', None),
    '岑方言': ('粤', None),
    '考方言': ('粤', None),
    '湘语': ('湘语', '湘语'),
    '闫方言': ('闽', None),
    '每方台': ('粤', None),
    '毒方言': ('粤', None),
    '闻方言': ('闽', None),
    '霉方言湛江白洁': ('粤', '湛江白话'),
    '闽万言': ('闽', None),
    '粤言语四色话': ('粤', '四邑话'),
    '辱方言': ('粤', None),
    '琴方言': ('粤', None),
    '通基方言（广府民系）': ('粤', None),
    '潮州方言': ('闽', '潮汕话'),
    '潮州语': ('闽', '潮汕话'),
    '闽南话': ('闽', None),
    '雷话': ('闽', '雷州话'),
    '能古话': ('粤', '能古话'),
    '学佬话': ('闽', '学佬话'),
    '潮汕民系，通用学佬话': ('闽', '学佬话'),
    '闽南民系，通用学佬话': ('闽', '学佬话'),
    '潮汕民系，通用潮油话': ('闽', '潮汕话'),
    '军话': ('官话', '军话'),
    '军声': ('官话', '军话'),
    '东莞方言': ('粤', None),
    '瑶族方言': ('少数民族', '瑶族方言'),
    '使用瑶族方言': ('少数民族', '瑶族方言'),
    '蓝田话': ('少数民族', '蓝田话'),
    '使用蓝田话': ('少数民族', '蓝田话'),
    '四会话': ('粤', '四会话'),
    '四川话': ('官话', '四川话'),
    '四川方言': ('官话', '四川话'),
    '重庆话': ('官话', '重庆话'),
    '重庆方言': ('官话', '重庆话'),
    '通用重庆话': ('官话', '重庆话'),
    '普通话': ('官话', '普通话'),
    '以普通话为主': ('官话', '普通话'),
    '旧时正话': ('官话', '旧时正话'),
    '通用旧时正话': ('官话', '旧时正话'),
    '军话': ('官话', '军话'),
    '军声': ('官话', '军话'),
    '尖米话': ('土话', '尖米话'),
    '尖米话（属广府民系）': ('土话', '尖米话'),
    '尖米话（广府民系）': ('土话', '尖米话'),
    '有老人会用粘（尖）米方言唱山歌': ('土话', '尖米话'),
}


def normalize_space(text: str) -> str:
    return re.sub(r'\s+', '', (text or '').strip())


def detect_families(text: str):
    hits = []
    for name, pattern in FAMILY_RULES:
        if pattern.search(text):
            hits.append(name)
    return hits


def detect_subgroups(text: str):
    found = []
    for token in SUBGROUP_PATTERNS:
        if token in text:
            mapped = ALIAS_SUBGROUPS.get(token, token)
            if mapped in {'粤', '客家', '闽', '少数民族', '土话', '官话'}:
                continue
            if mapped not in found:
                found.append(mapped)
    return found


def detect_accents(text: str):
    found = []
    for pattern in ACCENT_PATTERNS:
        for m in re.findall(pattern, text):
            if m not in found:
                found.append(m)
    return found


def detect_identity_tags(text: str):
    return [tag for tag in IDENTITY_KEYWORDS if tag in text]


def detect_usage_notes(text: str):
    notes = []
    if any(k in text for k in USAGE_KEYWORDS):
        notes.append(text)
    return notes


def split_segments(text: str):
    base = normalize_space(text)
    if not base:
        return []
    base = base.replace('及', '和')
    parts = []
    for chunk in MULTI_SEP_RE.split(base):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    if not parts:
        parts = [base]
    return parts


def classify_row(text: str):
    raw = normalize_space(text)
    segments = split_segments(raw)
    accents = detect_accents(raw)
    identity_tags = detect_identity_tags(raw)
    usage_notes = detect_usage_notes(raw)
    paren_notes = [m for m in PAREN_RE.findall(raw) if m]

    explicit_family = None
    for family_name, family_pattern in EXPLICIT_FAMILY_PREFIX_RULES:
        if family_pattern.search(raw):
            explicit_family = family_name
            break

    if raw in DIRECT_RAW_VALUE_MAP:
        forced_family, forced_subgroup = DIRECT_RAW_VALUE_MAP[raw]
        primary_family = forced_family
        primary_subgroup = forced_subgroup
        unique_families = [forced_family] if forced_family else []
        subgroup_tags = [forced_subgroup] if forced_subgroup else []
        mixed_family_text = ''
        mixed_subgroup_text = ''
    else:
        families = detect_families(raw)
        subgroup_tags = detect_subgroups(raw)
        unique_families = []
        for family in families:
            if family not in unique_families:
                unique_families.append(family)

        if explicit_family:
            unique_families = [explicit_family]

        if len(unique_families) == 0:
            primary_family = None
        elif len(unique_families) == 1:
            primary_family = unique_families[0]
        else:
            primary_family = '混合'

        primary_subgroup = subgroup_tags[0] if subgroup_tags else None
        mixed_family_text = '、'.join(unique_families) if len(unique_families) > 1 else ''
        mixed_subgroup_text = '、'.join(subgroup_tags) if len(subgroup_tags) > 1 else ''

    confidence = 'high'
    if primary_family == '混合' or len(segments) > 1:
        confidence = 'medium'
    if usage_notes or paren_notes or identity_tags or len(accents) > 0:
        confidence = 'medium'
    if primary_family is None and primary_subgroup is None:
        confidence = 'low'

    return {
        'dialect_raw_norm': raw,
        'primary_family': primary_family,
        'mixed_family_text': mixed_family_text,
        'family_tags': unique_families,
        'primary_subgroup': primary_subgroup,
        'mixed_subgroup_text': mixed_subgroup_text,
        'subgroup_tags': subgroup_tags,
        'accent_tags': accents,
        'identity_tags': identity_tags,
        'usage_notes': usage_notes,
        'paren_notes': paren_notes,
        'segments': segments,
        'clean_confidence': confidence,
    }


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute('DROP TABLE IF EXISTS jnu_dialect_clean')
    cur.execute('DROP TABLE IF EXISTS jnu_dialect_clean_summary')
    cur.execute('''
        CREATE TABLE jnu_dialect_clean (
            xlsx_row_number INTEGER PRIMARY KEY,
            matched_db_rowid INTEGER,
            match_status TEXT,
            dialect_raw TEXT,
            dialect_raw_norm TEXT,
            primary_family TEXT,
            mixed_family_text TEXT,
            family_tags_json TEXT,
            primary_subgroup TEXT,
            mixed_subgroup_text TEXT,
            subgroup_tags_json TEXT,
            accent_tags_json TEXT,
            identity_tags_json TEXT,
            usage_notes_json TEXT,
            paren_notes_json TEXT,
            segments_json TEXT,
            clean_confidence TEXT,
            FOREIGN KEY (xlsx_row_number) REFERENCES jnu_villages(xlsx_row_number)
        )
    ''')
    cur.execute('''
        CREATE TABLE jnu_dialect_clean_summary (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL
        )
    ''')

    rows = cur.execute('SELECT xlsx_row_number, matched_db_rowid, match_status, dialect_raw FROM jnu_villages').fetchall()
    family_counter = Counter()
    subgroup_counter = Counter()
    confidence_counter = Counter()
    raw_counter = Counter()

    for row in rows:
        parsed = classify_row(row['dialect_raw'] or '')
        family_counter.update(parsed['family_tags'] or ['未识别'])
        subgroup_counter.update(parsed['subgroup_tags'])
        confidence_counter.update([parsed['clean_confidence']])
        raw_counter.update([parsed['dialect_raw_norm']])
        cur.execute('''
            INSERT INTO jnu_dialect_clean (
                xlsx_row_number, matched_db_rowid, match_status, dialect_raw,
                dialect_raw_norm, primary_family, mixed_family_text, family_tags_json,
                primary_subgroup, mixed_subgroup_text, subgroup_tags_json, accent_tags_json,
                identity_tags_json, usage_notes_json, paren_notes_json,
                segments_json, clean_confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            row['xlsx_row_number'],
            row['matched_db_rowid'],
            row['match_status'],
            row['dialect_raw'],
            parsed['dialect_raw_norm'],
            parsed['primary_family'],
            parsed['mixed_family_text'],
            json.dumps(parsed['family_tags'], ensure_ascii=False),
            parsed['primary_subgroup'],
            parsed['mixed_subgroup_text'],
            json.dumps(parsed['subgroup_tags'], ensure_ascii=False),
            json.dumps(parsed['accent_tags'], ensure_ascii=False),
            json.dumps(parsed['identity_tags'], ensure_ascii=False),
            json.dumps(parsed['usage_notes'], ensure_ascii=False),
            json.dumps(parsed['paren_notes'], ensure_ascii=False),
            json.dumps(parsed['segments'], ensure_ascii=False),
            parsed['clean_confidence'],
        ))

    cur.execute('CREATE INDEX idx_dialect_clean_rowid ON jnu_dialect_clean(matched_db_rowid)')
    cur.execute('CREATE INDEX idx_dialect_clean_family ON jnu_dialect_clean(primary_family)')
    cur.execute('CREATE INDEX idx_dialect_clean_subgroup ON jnu_dialect_clean(primary_subgroup)')
    cur.execute('CREATE INDEX idx_dialect_clean_conf ON jnu_dialect_clean(clean_confidence)')

    summary = {
        'total_rows': len(rows),
        'nonempty_norm_rows': sum(1 for k in raw_counter if k),
        'distinct_norm_raw': len([k for k in raw_counter if k]),
        'family_counts': dict(family_counter.most_common()),
        'primary_subgroup_top50': subgroup_counter.most_common(50),
        'confidence_counts': dict(confidence_counter),
        'top_norm_raw_100': raw_counter.most_common(100),
    }
    for key, value in summary.items():
        cur.execute('INSERT INTO jnu_dialect_clean_summary(key, value_json) VALUES (?, ?)', (key, json.dumps(value, ensure_ascii=False)))

    conn.commit()
    conn.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
