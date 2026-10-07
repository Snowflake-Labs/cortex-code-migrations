"""Unit tests for tables.py (stdlib only, fast)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tables  # noqa: E402


class TablesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.path = self.dir / 'tables.json'
        tables.seed(self.path, ['LIB.IN1'], ['OUT.O1'])

    def tearDown(self):
        self._tmp.cleanup()

    def test_seed_rows(self):
        rows = {r['name']: r for r in tables.load(self.path)}
        self.assertEqual(rows['LIB.IN1']['role'], 'input')
        self.assertEqual(rows['OUT.O1']['role'], 'output')
        self.assertEqual(rows['LIB.IN1']['columns_from'], 'none')

    def test_update_changes_fingerprint_and_flags_stale_csv(self):
        tables.update(self.path, 'LIB.IN1', 'convert', [{'name': 'ID', 'type': 'NUMBER'}], 'live')
        csv = self.dir / 'expected' / 'job.csv'
        csv.parent.mkdir()
        csv.write_text('ID\n1\n')
        tables.stamp(self.path, csv, ['LIB.IN1'])
        self.assertEqual(tables.check_stale(self.path, self.dir / 'expected'), [])

        before = tables.load(self.path)[0]['fingerprint']
        row = tables.update(self.path, 'LIB.IN1', 'test', [{'name': 'ID', 'type': 'VARCHAR'}])
        self.assertNotEqual(before, row['fingerprint'])
        stale = tables.check_stale(self.path, self.dir / 'expected')
        self.assertEqual(stale, [{'csv': str(csv), 'changed_tables': ['LIB.IN1']}])

    def test_reseed_keeps_filled_rows(self):
        tables.update(self.path, 'LIB.IN1', 'convert', [{'name': 'ID', 'type': 'NUMBER'}], 'user_file')
        tables.seed(self.path, ['LIB.IN1'], ['OUT.O1'])
        row = next(r for r in tables.load(self.path) if r['name'] == 'LIB.IN1')
        self.assertEqual(row['columns_from'], 'user_file')

    def test_render_ddl_uses_fqn(self):
        tables.update(self.path, 'LIB.IN1', 'convert', [{'name': 'ID', 'type': 'NUMBER'}],
                      'live', snowflake_fqn='DB.SCH.IN1')
        ddl = tables.render_ddl(self.path)
        self.assertIn('CREATE TABLE IF NOT EXISTS DB.SCH.IN1 (\n    ID NUMBER\n);', ddl)
        self.assertIn('-- OUT.O1: no columns recorded', ddl)

    def test_cli_check_stale_exit_code(self):
        self.assertEqual(tables.main(['check-stale', str(self.path), str(self.dir)]), 0)
        json.loads(json.dumps(tables.load(self.path)))  # valid JSON round-trip


if __name__ == '__main__':
    unittest.main()
