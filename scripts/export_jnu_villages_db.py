#!/usr/bin/env python3
import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path

from build_village_mapping import load_config, load_xlsx_rows


def read_csv(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def create_output_db(config_path='mapping_config.json'):
    root = Path('.')
    config = load_config(config_path)
    out_dir = root / config['output_dir']
    db_path = root / 'villages_fromJNU.db'
    if db_path.exists():
        db_path.unlink()

    _, xlsx_rows = load_xlsx_rows(root / config['xlsx_path'])
    natural_rows = read_csv(out_dir / 'natural_village_mapping.csv')
    mapping_by_row = {int(row['xlsx_row_number']): row for row in natural_rows}

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('PRAGMA journal_mode=WAL')
    cur.execute('''
        CREATE TABLE jnu_villages (
            jnu_rowid INTEGER PRIMARY KEY,
            xlsx_row_number INTEGER NOT NULL UNIQUE,
            xlsx_city TEXT,
            xlsx_town TEXT,
            xlsx_admin_village TEXT,
            xlsx_natural_village TEXT,
            dialect_raw TEXT,
            matched_db_city TEXT,
            matched_db_town TEXT,
            matched_db_admin_village TEXT,
            matched_db_admin_village_candidates TEXT,
            match_status TEXT,
            matched_db_natural_village TEXT,
            matched_db_rowid INTEGER,
            candidate_count INTEGER,
            candidates TEXT,
            suggested_candidates TEXT
        )
    ''')
    cur.execute('''
        CREATE TABLE match_summary (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    xlsx_inserted = 0
    for row in xlsx_rows:
        xlsx_row_number = int(row['xlsx_row_number'])
        mapping = mapping_by_row.get(xlsx_row_number, {})
        matched_rowid = mapping.get('matched_db_rowid') or None
        candidate_count = mapping.get('candidate_count') or None
        cur.execute('''
            INSERT INTO jnu_villages (
                xlsx_row_number, xlsx_city, xlsx_town, xlsx_admin_village,
                xlsx_natural_village, dialect_raw, matched_db_city, matched_db_town,
                matched_db_admin_village, matched_db_admin_village_candidates,
                match_status, matched_db_natural_village, matched_db_rowid,
                candidate_count, candidates, suggested_candidates
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            xlsx_row_number,
            row.get(config['levels'][0]['xlsx_col'], ''),
            row.get(config['levels'][1]['xlsx_col'], ''),
            row.get(config['levels'][2]['xlsx_col'], ''),
            row.get(config['levels'][3]['xlsx_col'], ''),
            row.get(config['dialect_col'], ''),
            mapping.get('matched_db_city', ''),
            mapping.get('matched_db_town', ''),
            mapping.get('matched_db_admin_village', ''),
            mapping.get('matched_db_admin_village_candidates', ''),
            mapping.get('match_status', ''),
            mapping.get('matched_db_natural_village', ''),
            int(matched_rowid) if matched_rowid else None,
            int(candidate_count) if candidate_count else None,
            mapping.get('candidates', ''),
            mapping.get('suggested_candidates', ''),
        ))
        xlsx_inserted += 1

    cur.execute('CREATE INDEX idx_jnu_match_rowid ON jnu_villages(matched_db_rowid)')
    cur.execute('CREATE INDEX idx_jnu_match_status ON jnu_villages(match_status)')
    cur.execute('CREATE INDEX idx_jnu_geo ON jnu_villages(xlsx_city, xlsx_town, xlsx_admin_village, xlsx_natural_village)')
    cur.execute('CREATE INDEX idx_jnu_dialect ON jnu_villages(dialect_raw)')

    status_counts = Counter(row.get('match_status', '') for row in natural_rows)
    matched_count = sum(status_counts.get(status, 0) for status in ('exact', 'suffix_normalized', 'manual_confirmed'))
    duplicate_targets = cur.execute('''
        SELECT COUNT(*) FROM (
            SELECT matched_db_rowid
            FROM jnu_villages
            WHERE matched_db_rowid IS NOT NULL
            GROUP BY matched_db_rowid
            HAVING COUNT(*) > 1
        )
    ''').fetchone()[0]
    summary = {
        'source_xlsx_rows': xlsx_inserted,
        'mapping_rows': len(natural_rows),
        'matched_rows': matched_count,
        'matched_rate': matched_count / xlsx_inserted if xlsx_inserted else 0,
        'match_status': dict(status_counts),
        'duplicate_matched_db_rowid_groups': duplicate_targets,
    }
    for key, value in summary.items():
        cur.execute('INSERT INTO match_summary(key, value) VALUES (?, ?)', (key, json.dumps(value, ensure_ascii=False)))

    conn.commit()
    conn.close()
    return db_path, summary


if __name__ == '__main__':
    db_path, summary = create_output_db()
    print(json.dumps({'db_path': str(db_path), **summary}, ensure_ascii=False, indent=2))
