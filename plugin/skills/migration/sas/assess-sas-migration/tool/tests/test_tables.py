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

    def test_seed_flags_macro_names_and_dedups_when_input_is_also_output(self):
        rows = tables.seed(self.path, ['LIB.IN1', 'STG.MON&DDB', 'HIST.LOG'], ['HIST.LOG', 'OUT.O1'])
        by = {r['name']: r for r in rows}
        self.assertEqual([r['name'] for r in rows].count('HIST.LOG'), 1)
        self.assertEqual(by['HIST.LOG']['role'], 'input')
        self.assertTrue(by['STG.MON&DDB']['macro_name'])
        self.assertNotIn('macro_name', by['LIB.IN1'])

    def test_seed_skips_sas_metadata_views(self):
        tables.seed(self.path, ['LIB.IN1', 'DICTIONARY.COLUMNS', 'sashelp.vtable'], ['OUT.O1'])
        self.assertEqual(sorted(r['name'] for r in tables.load(self.path)), ['LIB.IN1', 'OUT.O1'])

    def test_probe_is_one_query_and_skips_known_rows(self):
        tables.update(self.path, 'LIB.IN2', 'convert', [{'name': 'A', 'type': 'NUMBER'}], 'live')
        sql = tables.probe_sql(self.path, ['DB.S1', 'DB2.S2'])
        self.assertEqual(sql.count('INFORMATION_SCHEMA.COLUMNS'), 2)
        self.assertIn("'IN1', 'LIB_IN1'", sql)
        self.assertNotIn('IN2', sql)
        self.assertTrue(sql.startswith('SELECT TO_JSON('))

    def test_ingest_marks_found_and_not_found(self):
        tables.seed(self.path, ['LIB.IN1', 'LIB.GONE'], ['OUT.O1'])
        res = self.dir / 'probe.json'
        # exactly what the SQL tool prints: pipes escaped as \|
        res.write_text('[{"fqn": "DB.S1.LIB_IN1", "cols": "ID TEXT(10)\\|AMT NUMBER(12,2)"}]')
        stats = tables.ingest(self.path, res, ['DB.S1'])
        self.assertEqual((stats['found'], stats['not_found']), (1, 1))
        row = tables.get(self.path, 'LIB.IN1')
        self.assertEqual(row['snowflake_fqn'], 'DB.S1.LIB_IN1')
        self.assertEqual(row['columns'], 'ID VARCHAR(10), AMT NUMBER(12,2)')
        self.assertEqual(tables.summary(self.path)['not_found'], ['LIB.GONE'])

    def test_ingest_refuses_to_guess_shared_bare_names(self):
        tables.seed(self.path, ['A.MASTER', 'B.MASTER'], [])
        res = self.dir / 'probe.json'
        res.write_text(json.dumps([{'fqn': 'DB.S.MASTER', 'cols': 'X NUMBER(38,0)'}]))
        stats = tables.ingest(self.path, res)
        self.assertEqual(sorted(stats['ambiguous']), ['A.MASTER', 'B.MASTER'])
        self.assertEqual(tables.get(self.path, 'A.MASTER')['columns_from'], 'none')

    def test_import_ddl_sql_and_csv(self):
        ddl = self.dir / 'ddl.sql'
        ddl.write_text('-- c\nCREATE OR REPLACE TABLE DB.S.IN1 (ID NUMBER(10,0) NOT NULL, NAME VARCHAR(20), '
                       'PRIMARY KEY (ID));\nCREATE TABLE EXTRA (Z DATE);')
        self.assertEqual(tables.import_ddl(self.path, ddl), {'matched': 1, 'added_not_in_sas': 1})
        self.assertEqual(tables.get(self.path, 'LIB.IN1')['columns'], 'ID NUMBER(10,0), NAME VARCHAR(20)')
        c = self.dir / 'ddl.csv'
        c.write_text('table,column,type\nOUT.O1,K,NUMBER\n')
        tables.import_ddl(self.path, c)
        self.assertEqual(tables.get(self.path, 'OUT.O1')['location_status'], 'user_supplied')

    def test_gap_exit_codes(self):
        tables.update(self.path, 'LIB.IN1', 'convert', [{'name': 'ID', 'type': 'NUMBER'}], 'live')
        self.assertEqual(tables.gap(self.path, 'LIB.IN1', 'ID')[0], 0)
        self.assertEqual(tables.gap(self.path, 'LIB.IN1', 'MISSING')[0], tables.GAP_EXIT)
        tables.update(self.path, 'LIB.IN1', 'convert', columns_from='inferred')
        self.assertEqual(tables.gap(self.path, 'LIB.IN1', 'ID')[0], tables.GAP_EXIT)
        self.assertEqual(tables.gap(self.path, 'NOPE.T', 'ID')[0], 4)

    def test_batch_update_and_seed_targets_exclude_non_inputs(self):
        batch = self.dir / 'b.jsonl'
        batch.write_text('{"name": "WORK.STAGE1", "role": "intermediate"}\n'
                         '{"name": "LIB.IN1", "fqn": "DB.S.IN1", "full_data_fqn": "PROD.S.IN1"}\n')
        tables.main(['update', str(self.path), '--batch', str(batch), '--by', 'convert'])
        self.assertEqual(tables.seed_targets(self.path), ['DB.S.IN1'])
        self.assertEqual(tables.get(self.path, 'LIB.IN1')['full_data_fqn'], 'PROD.S.IN1')
        tables.seed(self.path, ['LIB.IN1'], ['OUT.O1'])   # reseed keeps intermediates
        self.assertIsNotNone(tables.get(self.path, 'WORK.STAGE1'))


if __name__ == '__main__':
    unittest.main()
