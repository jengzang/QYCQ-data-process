import importlib.util
import json
import os
import sqlite3
import tempfile
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
        self.assertEqual(module.validate_final_value('其他·越南语'), [])
        self.assertEqual(module.validate_final_value('粤·四邑话、客家·涯话'), [])

        errors = module.validate_final_value('四邑话')

        self.assertIn('missing_known_family:四邑话', errors)

    def test_validate_final_value_rejects_wrong_separator(self):
        module = load_module()

        errors = module.validate_final_value('粤-四邑话')

        self.assertIn('missing_known_family:粤-四邑话', errors)

    def test_validate_final_value_allows_historical_transition_arrow(self):
        module = load_module()

        self.assertEqual(module.validate_final_value('客家 → 粤'), [])
        self.assertEqual(module.validate_final_value('客家·涯话 → 粤·阳春白话'), [])
        self.assertEqual(module.validate_final_value('客家 → 粤、少数民族·连山壮话'), [])
        self.assertEqual(module.validate_final_value('客家 -> 粤'), [])

        errors = module.validate_final_value('涯话 → 粤')

        self.assertIn('missing_known_family:涯话', errors)

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

    def test_needs_priority_llm_review_skips_clear_medium_rows(self):
        module = load_module()

        self.assertFalse(module.needs_priority_llm_review({
            'clean_confidence': 'medium',
            'primary_family': '粤',
            'primary_subgroup': '',
            'dialect_raw': '粤方言（广府民系）',
        }))
        self.assertFalse(module.needs_priority_llm_review({
            'clean_confidence': 'medium',
            'primary_family': '闽',
            'primary_subgroup': '雷州话',
            'dialect_raw': '通用雷州话',
        }))

    def test_needs_priority_llm_review_keeps_low_unclear_and_complex_mixed_rows(self):
        module = load_module()

        self.assertTrue(module.needs_priority_llm_review({
            'clean_confidence': 'low',
            'primary_family': '',
            'dialect_raw': '通用方言',
        }))
        self.assertTrue(module.needs_priority_llm_review({
            'clean_confidence': 'medium',
            'primary_family': '混合',
            'mixed_family_text': '客家、粤',
            'dialect_raw': '先辈使用客家方言，现村民使用粤方言',
        }))

    def test_needs_priority_llm_review_keeps_mixed_rows_that_lost_subgroups(self):
        module = load_module()

        self.assertTrue(module.needs_priority_llm_review({
            'clean_confidence': 'medium',
            'primary_family': '混合',
            'mixed_family_text': '客家、粤',
            'mixed_subgroup_text': '涯话、阳春白话',
            'dialect_raw': '客家方言阳春涯话、粤方言阳春白话',
        }))
        self.assertFalse(module.needs_priority_llm_review({
            'clean_confidence': 'medium',
            'primary_family': '混合',
            'mixed_family_text': '粤、客家',
            'mixed_subgroup_text': '',
            'dialect_raw': '粤方言、客家方言',
        }))

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

        prompt = module.build_user_prompt(record)

        self.assertIn('必须有方言大类', prompt)
        self.assertIn('大类·小类', prompt)
        self.assertIn('其他', prompt)
        self.assertNotIn('SPECIAL RULES', prompt)
        self.assertIn('rule_baseline 只是机器规则建议', prompt)
        self.assertIn('relation_type', prompt)
        self.assertIn('广府方言', prompt)
        self.assertIn('不要写作“粤·广府话”', prompt)
        self.assertIn('口音可以保留在小类中', prompt)
        self.assertIn(json.dumps('龙背村', ensure_ascii=False), prompt)
        self.assertIn(json.dumps('粤方言四邑话', ensure_ascii=False), prompt)

    def test_build_prompt_contains_few_shot_examples(self):
        module = load_module()

        prompt = module.build_user_prompt({'xlsx_row_number': 1})

        self.assertIn('判定示例', prompt)
        self.assertIn('先辈使用客家方言，现村民使用粤方言 -> 客家 → 粤', prompt)
        self.assertIn('刘姓使用粤方言台山话；苏姓使用瑶语 -> 粤·台山话、少数民族·瑶语', prompt)
        self.assertIn('越南语（因归侨较多） -> 其他·越南语', prompt)

    def test_build_prompt_does_not_embed_long_rules_document(self):
        module = load_module()

        prompt = module.build_user_prompt({'xlsx_row_number': 1}, 'SHOULD_NOT_APPEAR')

        self.assertNotIn('SHOULD_NOT_APPEAR', prompt)
        self.assertNotIn('## 4. 方言清洗规则', prompt)

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
        conn.close()

        self.assertEqual(len(rows), 1)
        self.assertIn('final_write_value', rows[0])
        self.assertEqual(rows[0]['final_write_value'], '')

    def test_select_records_applies_limit_after_priority_filter(self):
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
            INSERT INTO jnu_villages VALUES (1, '', '', '', '', '粤方言（广府民系）', '', 1);
            INSERT INTO jnu_villages VALUES (2, '', '', '', '', '方言', '', 2);
            INSERT INTO jnu_villages VALUES (3, '', '', '', '', '通用方言', '', 3);
            INSERT INTO jnu_dialect_clean VALUES (1, '粤', '', '', '', 'medium');
            INSERT INTO jnu_dialect_clean VALUES (2, '', '', '', '', 'low');
            INSERT INTO jnu_dialect_clean VALUES (3, '', '', '', '', 'low');
        ''')

        rows = module.select_records(conn, limit=1, all_rows=False, priority_candidates=True)
        conn.close()

        self.assertEqual([row['xlsx_row_number'] for row in rows], [2])

    def test_load_dotenv_sets_values_without_overriding_existing_env(self):
        module = load_module()
        old_key = os.environ.get('DEEPSEEK_API_KEY')
        old_model = os.environ.get('LLM_MODEL')
        os.environ['DEEPSEEK_API_KEY'] = 'already-set'
        os.environ.pop('LLM_MODEL', None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dotenv_path = Path(tmp) / '.env'
                dotenv_path.write_text(
                    '\n'.join([
                        '# local secrets',
                        'DEEPSEEK_API_KEY=from-dotenv',
                        'LLM_MODEL=deepseek-chat',
                        '',
                    ]),
                    encoding='utf-8',
                )

                loaded = module.load_dotenv(dotenv_path)

                self.assertEqual(loaded, {'LLM_MODEL': 'deepseek-chat'})
                self.assertEqual(os.environ['DEEPSEEK_API_KEY'], 'already-set')
                self.assertEqual(os.environ['LLM_MODEL'], 'deepseek-chat')
        finally:
            if old_key is None:
                os.environ.pop('DEEPSEEK_API_KEY', None)
            else:
                os.environ['DEEPSEEK_API_KEY'] = old_key
            if old_model is None:
                os.environ.pop('LLM_MODEL', None)
            else:
                os.environ['LLM_MODEL'] = old_model

    def test_build_chat_completions_request_uses_endpoint_and_messages(self):
        module = load_module()
        messages = [{'role': 'user', 'content': 'hello'}]

        url, body = module.build_llm_request(
            messages=messages,
            model='deepseek-chat',
            base_url='https://api.deepseek.com/v1/chat/completions',
            wire_api='chat_completions',
        )

        self.assertEqual(url, 'https://api.deepseek.com/v1/chat/completions')
        self.assertEqual(body['model'], 'deepseek-chat')
        self.assertEqual(body['messages'], messages)
        self.assertEqual(body['response_format'], {'type': 'json_object'})

    def test_build_responses_request_uses_base_url_and_input(self):
        module = load_module()
        messages = [
            {'role': 'system', 'content': 'system rules'},
            {'role': 'user', 'content': 'user prompt'},
        ]

        url, body = module.build_llm_request(
            messages=messages,
            model='codex-model',
            base_url='http://127.0.0.1:8080/v1',
            wire_api='responses',
        )

        self.assertEqual(url, 'http://127.0.0.1:8080/v1/responses')
        self.assertEqual(body['model'], 'codex-model')
        self.assertEqual(body['input'], messages)
        self.assertEqual(body['text']['format']['type'], 'json_object')

    def test_extract_response_content_supports_responses_output_text(self):
        module = load_module()
        payload = {
            'output': [
                {
                    'content': [
                        {
                            'type': 'output_text',
                            'text': '{"final_value":"其他","confidence":"low"}',
                        }
                    ]
                }
            ]
        }

        content = module.extract_response_content(payload, 'responses')

        self.assertEqual(content, '{"final_value":"其他","confidence":"low"}')

    def test_extract_token_usage_supports_responses_usage(self):
        module = load_module()
        payload = {
            'usage': {
                'input_tokens': 4019,
                'output_tokens': 297,
                'total_tokens': 4316,
            }
        }

        usage = module.extract_token_usage(payload)

        self.assertEqual(usage, {'input_tokens': 4019, 'output_tokens': 297, 'total_tokens': 4316})

    def test_extract_token_usage_supports_chat_completions_usage(self):
        module = load_module()
        payload = {
            'usage': {
                'prompt_tokens': 100,
                'completion_tokens': 20,
                'total_tokens': 120,
            }
        }

        usage = module.extract_token_usage(payload)

        self.assertEqual(usage, {'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120})

    def test_export_run_csv_writes_only_processed_rows(self):
        module = load_module()
        rows = [
            {
                'xlsx_row_number': 1,
                'matched_db_rowid': 10,
                'dialect_raw': '方言',
                'rule_final_value': '',
                'llm_final_value': '其他',
                'llm_confidence': 'low',
                'needs_human_review': 1,
                'validation_errors_json': '[]',
                'evidence_json': '["泛称"]',
                'warnings_json': '[]',
                'model': 'test-model',
                'dry_run': 0,
                'created_at': '2026-07-15T18:00:00',
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'run.csv'

            written = module.export_run_csv(rows, path)

            self.assertEqual(written, 1)
            content = path.read_text(encoding='utf-8-sig')
            self.assertIn('xlsx_row_number', content)
            self.assertIn('其他', content)

    def test_append_run_csv_writes_header_once(self):
        module = load_module()
        row = {
            'xlsx_row_number': 1,
            'matched_db_rowid': 10,
            'dialect_raw': '方言',
            'rule_final_value': '',
            'llm_final_value': '其他',
            'llm_confidence': 'low',
            'needs_human_review': 1,
            'validation_errors_json': '[]',
            'evidence_json': '[]',
            'warnings_json': '[]',
            'model': 'test-model',
            'dry_run': 0,
            'created_at': '2026-07-15T18:00:00',
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'run.csv'

            module.append_run_csv(row, path)
            module.append_run_csv(dict(row, xlsx_row_number=2), path)

            lines = path.read_text(encoding='utf-8-sig').splitlines()
            self.assertEqual(lines[0].count('xlsx_row_number'), 1)
            self.assertEqual(len(lines), 3)

    def test_filter_existing_successful_records_skips_real_rows(self):
        module = load_module()
        conn = sqlite3.connect(':memory:')
        module.create_table(conn)
        conn.execute(f'''
            INSERT INTO {module.TABLE_NAME} (
                xlsx_row_number, matched_db_rowid, dialect_raw, rule_final_value,
                llm_final_value, llm_family, llm_subgroups_json, llm_confidence,
                needs_human_review, evidence_json, applied_rules_json, warnings_json,
                validation_errors_json, prompt_version, model, provider, dry_run,
                raw_response_json, request_payload_json, created_at
            ) VALUES (1, 10, '方言', '', '其他', '其他', '[]', 'low', 1,
                '[]', '[]', '[]', '[]', 'test', 'model', 'provider', 0, '{{}}', '{{}}', '2026-07-15T18:00:00')
        ''')
        records = [{'xlsx_row_number': 1}, {'xlsx_row_number': 2}]

        remaining = module.filter_existing_successful_records(conn, records)
        conn.close()

        self.assertEqual(remaining, [{'xlsx_row_number': 2}])

    def test_select_records_can_limit_after_skip_existing(self):
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
            INSERT INTO jnu_villages VALUES (1, '', '', '', '', '方言', '', 1);
            INSERT INTO jnu_villages VALUES (2, '', '', '', '', '通用方言', '', 2);
            INSERT INTO jnu_villages VALUES (3, '', '', '', '', '使用方言', '', 3);
            INSERT INTO jnu_dialect_clean VALUES (1, '', '', '', '', 'low');
            INSERT INTO jnu_dialect_clean VALUES (2, '', '', '', '', 'low');
            INSERT INTO jnu_dialect_clean VALUES (3, '', '', '', '', 'low');
        ''')
        module.create_table(conn)
        conn.execute(f'''
            INSERT INTO {module.TABLE_NAME} (
                xlsx_row_number, matched_db_rowid, dialect_raw, rule_final_value,
                llm_final_value, llm_family, llm_subgroups_json, llm_confidence,
                needs_human_review, evidence_json, applied_rules_json, warnings_json,
                validation_errors_json, prompt_version, model, provider, dry_run,
                raw_response_json, request_payload_json, created_at
            ) VALUES (1, 1, '方言', '', '其他', '其他', '[]', 'low', 1,
                '[]', '[]', '[]', '[]', 'test', 'model', 'provider', 0, '{{}}', '{{}}', '2026-07-15T18:00:00')
        ''')

        rows = module.select_records(conn, limit=1, all_rows=False, priority_candidates=True, skip_existing=True)
        conn.close()

        self.assertEqual([row['xlsx_row_number'] for row in rows], [2])

    def test_resolve_api_key_falls_back_to_deepseek_key(self):
        module = load_module()
        old_llm = os.environ.get('LLM_API_KEY')
        old_deepseek = os.environ.get('DEEPSEEK_API_KEY')
        os.environ.pop('LLM_API_KEY', None)
        os.environ['DEEPSEEK_API_KEY'] = 'deepseek-key'
        try:
            key = module.resolve_api_key('LLM_API_KEY')

            self.assertEqual(key, ('deepseek-key', 'DEEPSEEK_API_KEY'))
        finally:
            if old_llm is None:
                os.environ.pop('LLM_API_KEY', None)
            else:
                os.environ['LLM_API_KEY'] = old_llm
            if old_deepseek is None:
                os.environ.pop('DEEPSEEK_API_KEY', None)
            else:
                os.environ['DEEPSEEK_API_KEY'] = old_deepseek


if __name__ == '__main__':
    unittest.main()
