#!/usr/bin/env python3
import json
import shutil
import sqlite3
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

WORKDIR = Path(__file__).resolve().parents[1]
SOURCE_XLSX_PATH = WORKDIR / 'Village.xlsx'
XLSX_PATH = WORKDIR / 'Village_with_coords.xlsx'
STAGING_DB = WORKDIR / 'villages_fromJNU.db'
TARGET_DB = WORKDIR / 'villages.db'
TARGET_TABLE = '广东省自然村'
BACKUP_DIR = WORKDIR / 'backups'
ORIGINAL_BASELINE = WORKDIR / 'Village_with_coords.xlsx.bak.20260629'

NS = {
    'a': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}
TARGET_SHEET_NAME = 'Village'
LONGITUDE_HEADER = 'db_longitude'
LATITUDE_HEADER = 'db_latitude'


class SheetDataError(RuntimeError):
    pass


def normalize_text(value):
    if value is None:
        return ''
    return str(value).strip()


def backup_file(path: Path, tag: str):
    if not path.exists():
        return None
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    target = BACKUP_DIR / f'{path.name}.{tag}_{stamp}'
    shutil.copy2(path, target)
    return target


def excel_col_name(index: int) -> str:
    result = ''
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def escape_xml(text: str) -> str:
    return (
        text.replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&apos;')
    )


def excel_inline_str(value) -> str:
    text = normalize_text(value)
    if any(ch in text for ch in ['\n', '\r', '\t']) or text != text.strip():
        return f'<is><t xml:space="preserve">{escape_xml(text)}</t></is>'
    return f'<is><t>{escape_xml(text)}</t></is>'


def parse_xlsx_sheet(path: Path, sheet_name: str):
    with zipfile.ZipFile(path) as zf:
        shared = []
        if 'xl/sharedStrings.xml' in zf.namelist():
            root = ET.fromstring(zf.read('xl/sharedStrings.xml'))
            for si in root.findall('a:si', NS):
                shared.append(''.join(t.text or '' for t in si.iterfind('.//a:t', NS)))

        wb = ET.fromstring(zf.read('xl/workbook.xml'))
        rels = ET.fromstring(zf.read('xl/_rels/workbook.xml.rels'))
        rel_map = {rel.attrib['Id']: rel.attrib['Target'] for rel in rels}

        target_sheet = None
        for sheet in wb.find('a:sheets', NS):
            if sheet.attrib.get('name') == sheet_name:
                target_sheet = sheet
                break
        if target_sheet is None:
            raise ValueError(f'Sheet not found: {sheet_name}')

        rid = target_sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
        target = 'xl/' + rel_map[rid]
        root = ET.fromstring(zf.read(target))
        data = root.find('a:sheetData', NS)
        rows = []
        for row in data.findall('a:row', NS):
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
            rows.append(row_data)
        if not rows:
            raise ValueError('Sheet has no rows')
        header_row = rows[0]
        headers = [header_row[col] for col in sorted(header_row, key=excel_col_sort_key)]
        named_rows = []
        for idx, row in enumerate(rows[1:], start=2):
            named = {'xlsx_row_number': idx}
            for col, header in header_row.items():
                named[header] = row.get(col, '')
            named_rows.append(named)
        return headers, named_rows


def excel_col_sort_key(col: str):
    value = 0
    for ch in col:
        value = value * 26 + (ord(ch.upper()) - 64)
    return value


def load_source_template_rows():
    source_headers, source_rows = parse_xlsx_sheet(SOURCE_XLSX_PATH, TARGET_SHEET_NAME)
    output_headers = list(source_headers) + [LONGITUDE_HEADER, LATITUDE_HEADER]
    return source_headers, output_headers, source_rows


def build_coordinate_lookup():
    conn = sqlite3.connect(TARGET_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute(
        f"select rowid, longitude, latitude from '{TARGET_TABLE}'"
    ).fetchall()
    conn.close()
    return {
        int(r['rowid']): {
            'longitude': '' if r['longitude'] is None else str(r['longitude']),
            'latitude': '' if r['latitude'] is None else str(r['latitude']),
        }
        for r in rows
    }


def build_match_lookup():
    conn = sqlite3.connect(STAGING_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute(
        'select xlsx_row_number, matched_db_rowid from jnu_villages order by xlsx_row_number'
    ).fetchall()
    conn.close()
    return {
        int(row['xlsx_row_number']): None if row['matched_db_rowid'] is None else int(row['matched_db_rowid'])
        for row in rows
    }


def build_output_rows(source_rows, match_lookup, coord_lookup):
    output_rows = []
    stats = {
        'source_rows': len(source_rows),
        'matched_rows': 0,
        'matched_rows_with_coords': 0,
        'matched_rows_missing_coords': 0,
        'unmatched_rows': 0,
    }
    samples = []

    for row in source_rows:
        row_number = int(row['xlsx_row_number'])
        matched_rowid = match_lookup.get(row_number)
        coords = {'longitude': '', 'latitude': ''}
        if matched_rowid is None:
            stats['unmatched_rows'] += 1
        else:
            stats['matched_rows'] += 1
            coords = coord_lookup.get(matched_rowid, {'longitude': '', 'latitude': ''})
            if coords['longitude'] and coords['latitude']:
                stats['matched_rows_with_coords'] += 1
            else:
                stats['matched_rows_missing_coords'] += 1

        output_row = {key: normalize_text(value) for key, value in row.items() if key != 'xlsx_row_number'}
        output_row[LONGITUDE_HEADER] = normalize_text(coords['longitude'])
        output_row[LATITUDE_HEADER] = normalize_text(coords['latitude'])
        output_rows.append(output_row)
        if len(samples) < 20:
            samples.append(output_row)
    return output_rows, stats, samples


def build_sheet_xml(headers, rows):
    total_rows = len(rows) + 1
    total_cols = len(headers)
    dimension = f'A1:{excel_col_name(total_cols)}{total_rows}'
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        f'<dimension ref="{dimension}"/>',
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews>',
        '<sheetFormatPr defaultRowHeight="15"/>',
        '<sheetData>',
        '<row r="1">',
    ]
    for idx, header in enumerate(headers, start=1):
        ref = f'{excel_col_name(idx)}1'
        parts.append(f'<c r="{ref}" t="inlineStr">{excel_inline_str(header)}</c>')
    parts.append('</row>')

    for row_index, row in enumerate(rows, start=2):
        parts.append(f'<row r="{row_index}">')
        for col_index, header in enumerate(headers, start=1):
            ref = f'{excel_col_name(col_index)}{row_index}'
            parts.append(f'<c r="{ref}" t="inlineStr">{excel_inline_str(row.get(header, ""))}</c>')
        parts.append('</row>')

    parts.extend(['</sheetData>', '</worksheet>'])
    return ''.join(parts).encode('utf-8')


def write_rebuilt_workbook(template_xlsx: Path, output_xlsx: Path, sheet_name: str, headers, rows):
    sheet_xml = build_sheet_xml(headers, rows)
    with zipfile.ZipFile(template_xlsx) as zin:
        with zipfile.ZipFile(output_xlsx, 'w', zipfile.ZIP_DEFLATED) as zout:
            wb = ET.fromstring(zin.read('xl/workbook.xml'))
            rels = ET.fromstring(zin.read('xl/_rels/workbook.xml.rels'))
            rel_map = {rel.attrib['Id']: rel.attrib['Target'] for rel in rels}
            target_sheet = None
            for sheet in wb.find('a:sheets', NS):
                if sheet.attrib.get('name') == sheet_name:
                    target_sheet = sheet
                    break
            if target_sheet is None:
                raise ValueError(f'Sheet not found: {sheet_name}')
            rid = target_sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
            sheet_target = 'xl/' + rel_map[rid]

            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == sheet_target:
                    zout.writestr(item, sheet_xml)
                else:
                    zout.writestr(item, data)


def verify_output(current_xlsx: Path, baseline_xlsx: Path, expected_headers):
    current_headers, current_rows = parse_xlsx_sheet(current_xlsx, TARGET_SHEET_NAME)
    baseline_headers, baseline_rows = parse_xlsx_sheet(baseline_xlsx, TARGET_SHEET_NAME)
    return {
        'current_header_count': len(current_headers),
        'baseline_header_count': len(baseline_headers),
        'current_row_count': len(current_rows),
        'baseline_row_count': len(baseline_rows),
        'headers_match_expected': current_headers == expected_headers,
        'headers_match_baseline': current_headers == baseline_headers,
        'expected_headers': expected_headers,
        'current_headers': current_headers,
    }


def main():
    if not SOURCE_XLSX_PATH.exists():
        raise FileNotFoundError(f'Missing source xlsx: {SOURCE_XLSX_PATH}')
    if not XLSX_PATH.exists():
        raise FileNotFoundError(f'Missing xlsx template: {XLSX_PATH}')
    if not ORIGINAL_BASELINE.exists():
        raise FileNotFoundError(f'Missing xlsx baseline: {ORIGINAL_BASELINE}')

    _, output_headers, source_rows = load_source_template_rows()
    match_lookup = build_match_lookup()
    coord_lookup = build_coordinate_lookup()
    output_rows, stats, samples = build_output_rows(source_rows, match_lookup, coord_lookup)
    backup_path = backup_file(XLSX_PATH, 'before_rebuild_from_villages_xlsx')
    tmp_output = XLSX_PATH.with_suffix('.tmp.xlsx')
    write_rebuilt_workbook(SOURCE_XLSX_PATH, tmp_output, TARGET_SHEET_NAME, output_headers, output_rows)
    shutil.move(tmp_output, XLSX_PATH)
    verify_summary = verify_output(XLSX_PATH, ORIGINAL_BASELINE, output_headers)

    print(json.dumps({
        'source_xlsx_path': str(SOURCE_XLSX_PATH),
        'xlsx_path': str(XLSX_PATH),
        'sheet_name': TARGET_SHEET_NAME,
        'target_backup': None if backup_path is None else str(backup_path),
        'rebuild_stats': stats,
        'sample_rows': samples,
        'verify_summary': verify_summary,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
