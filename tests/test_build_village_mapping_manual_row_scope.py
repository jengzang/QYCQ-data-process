import unittest
import importlib.util
from pathlib import Path


def load_module():
    spec = importlib.util.spec_from_file_location('build_village_mapping', Path('scripts/build_village_mapping.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BuildVillageMappingManualRowScopeTest(unittest.TestCase):
    def test_load_manual_confirmations_parses_duplicate_min_rowid_row_scope_hint(self):
        module = load_module()
        fixture = Path('tmp_test_manual_confirmations.csv')
        fixture.write_text(
            'level,parent_scope,source_value,confirmed_value,action,source_suggestions\n'
            'natural,a / b / c,源村,目标村,confirm,"duplicate_min_rowid:245375 from 245375 | 245376"\n',
            encoding='utf-8-sig',
        )
        try:
            confirmations = module.load_manual_confirmations(fixture)
            meta = confirmations[('natural', 'a/b/c', '源村')]
            self.assertEqual(meta['confirmed_value'], '目标村')
            self.assertEqual(meta['row_scope_hint'], 'rowid:245375')
        finally:
            fixture.unlink(missing_ok=True)

    def test_apply_manual_confirmation_duplicate_min_rowid_sets_manual_confirmed(self):
        module = load_module()
        confirmations = {
            ('natural', 'a/b/c', '源村'): {
                'confirmed_value': '目标村',
                'row_scope_hint': '245375',
            }
        }
        result = module.apply_manual_confirmation('natural', 'a / b / c', '源村', ['目标村'], confirmations)
        self.assertIsNotNone(result)
        status, matched, candidates, meta = result
        self.assertEqual(status, 'manual_confirmed')
        self.assertEqual(matched, '目标村')
        self.assertEqual(candidates, ['目标村'])
        self.assertEqual(meta['row_scope_hint'], '245375')


if __name__ == '__main__':
    unittest.main()
