import importlib.util
import json
import sqlite3
import unittest
from pathlib import Path


def load_module():
    path = Path('scripts/llm_adjudicate_dialects.py')
    spec = importlib.util.spec_from_file_location('llm_adjudicate_dialects', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LlmAdjudicateDialectsTests(unittest.TestCase):
    def test_validate_final_value_requires_known_family(self):
        module = load_module()

        self.assertEqual(module.validate_final_value('粤·四邑话'), [])
        self.assertEqual(module.validate_final_value('客家'), [])
        self.assertEqual(module.validate_final_value('粤·四邑话、客家·涯话'), [])

        errors = module.validate_final_value('四邑话')

        self.assertIn('missing_known_family:四邑话', errors)

    def test_validate_final_value_rejects_wrong_separator(self):
        module = load_module()

        errors = module.validate_final_value('粤-四邑话')

        self.assertIn('missing_known_family:粤-四邑话', errors)

    def test_parse_llm_json_strips_markdown_fence(self):
        module = load_module()
        raw = '```json\n{"final_value":"粤·四邑话","confidence":"high","needs_human_review":false}\n```'

        parsed = module.parse_llm_json(raw)

        self.assertEqual(parsed['final_value'], '粤·四邑话')
        self.assertEqual(parsed['confidence'], 'high')
        self.assertIs(parsed['needs_human_review'], False)

    def test_needs_llm_review_prioritizes_low_medium_mixed_and_ocr(self):
        module = load_module()

        self.assertTrue(module.needs_llm_review({'clean_confidence': 'low', 'primary_family': '粤', 'dialect_raw': '粤方言'}))
        self.assertTrue(module.needs_llm_review({'clean_confidence': 'medium', 'primary_family': '粤', 'dialect_raw': '粤方言'}))
        self.assertTrue(module.needs_llm_review({'clean_confidence': 'high', 'primary_family': '混合', 'dialect_raw': '粤方言、客家方言'}))
        self.assertTrue(module.needs_llm_review({'clean_confidence': 'high', 'primary_family': '粤', 'dialect_raw': '粤方盲'}))
        self.assertFalse(module.needs_llm_review({'clean_confidence': 'high', 'primary_family': '粤', 'dialect_raw': '粤方言四邑话'}))

    def test_build_prompt_contains_rule_contract_and_context(self):
        module = load_module()
        record = {
            'xlsx_row_number': 2,
            'xlsx_city': '江门',
            'xlsx_town': '赤坎镇',
            'xlsx_admin_village': '中庙行政村',
            'xlsx_natural_village': '龙背村',
            'dialect_raw': '粤方言四邑话',
            'primary_family': '粤',
            'primary_subgroup': '四邑话',
            'final_write_value': '粤·四邑话',
            'clean_confidence': 'high',
            '村历史沿革': '清代属开平县平康都',
            '村俗或传统民居或村特色产品': '传统民居为广府民居',
        }

        prompt = module.build_user_prompt(record, 'SPECIAL RULES')

        self.assertIn('必须有方言大类', prompt)
        self.assertIn('大类·小类', prompt)
        self.assertIn('SPECIAL RULES', prompt)
        self.assertIn(json.dumps('龙背村', ensure_ascii=False), prompt)
        self.assertIn(json.dumps('粤方言四邑话', ensure_ascii=False), prompt)

    def test_fetch_records_works_before_final_write_value_column_exists(self):
        module = load_module()
        conn = sqlite3.connect(':memory:')
        conn.executescript('''
            CREATE TABLE jnu_villages (
                xlsx_row_number INTEGER PRIMARY KEY,
                xlsx_city TEXT,
                xlsx_town TEXT,
                xlsx_admin_village TEXT,
                xlsx_natural_village TEXT,
                dialect_raw TEXT,
                match_status TEXT,
                matched_db_rowid INTEGER
            );
            CREATE TABLE jnu_dialect_clean (
                xlsx_row_number INTEGER PRIMARY KEY,
                primary_family TEXT,
                primary_subgroup TEXT,
                mixed_family_text TEXT,
                mixed_subgroup_text TEXT,
                clean_confidence TEXT
            );
            INSERT INTO jnu_villages VALUES (1, '江门', '赤坎镇', '中庙行政村', '龙背村', '粤方言四邑话', 'exact', 71071);
            INSERT INTO jnu_dialect_clean VALUES (1, '粤', '四邑话', '', '', 'medium');
        ''')

        rows = module.fetch_records(conn, limit=1, only_review_candidates=True)

        self.assertEqual(len(rows), 1)
        self.assertIn('final_write_value', rows[0])
        self.assertEqual(rows[0]['final_write_value'], '')


if __name__ == '__main__':
    unittest.main()
