"""Unit tests for sf_exec.py (stdlib only, no Snowflake)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sf_exec  # noqa: E402

PROC = """CREATE OR REPLACE PROCEDURE SP_LOAD() RETURNS STRING LANGUAGE SQL EXECUTE AS CALLER AS
$$
BEGIN
  CREATE OR REPLACE TABLE OUT_T AS SELECT * FROM STAGE_T WHERE d >= $START_DT;
  RETURN 'ok';
END;
$$;
CALL SP_LOAD();
"""


class SfExecTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)
        (self.d / 'a_load.sql').write_text(PROC)
        (self.d / 'b_stage.sql').write_text("CREATE OR REPLACE TEMPORARY TABLE STAGE_T AS SELECT * FROM SRC;")
        (self.d / 'z_params.sql').write_text("SET START_DT = '2024-01-01';\nUSE SCHEMA DB.S;")
        tables = self.d / 'tables.json'
        tables.write_text(json.dumps([{'name': 'LIB.SRC', 'role': 'input', 'snowflake_fqn': None,
                                       'location_status': 'not_found', 'columns': [], 'columns_from': 'none'}]))
        self.plan = str(self.d / 'exec_plan_run.json')
        sf_exec.main(['plan', '--dir', str(self.d), '--tables', str(tables), '--mode', 'run'])

    def tearDown(self):
        self._tmp.cleanup()

    def _plan(self):
        return json.loads(Path(self.plan).read_text())

    def test_parameters_first_then_producers(self):
        self.assertEqual(self._plan()['order'], ['z_params.sql', 'b_stage.sql', 'a_load.sql'])

    def test_dollar_body_is_one_step(self):
        kinds = [s['kind'] for s in self._plan()['steps'] if s['file'] == 'a_load.sql']
        self.assertEqual(kinds, ['routine', 'call'])

    def test_failure_classes_and_cascade(self):
        p = self._plan()
        stage = next(s for s in p['steps'] if s['file'] == 'b_stage.sql')
        sf_exec.main(['record', '--plan', self.plan, '--id', str(stage['id']),
                      '--error', "SQL compilation error: Object 'SRC' does not exist or not authorized."])
        self.assertEqual(next(s for s in self._plan()['steps'] if s['id'] == stage['id'])['class'], 'TEST_DATA_GAP')
        for s in self._plan()['steps']:
            if s['status'] is None and s['file'] != 'a_load.sql':
                sf_exec.main(['record', '--plan', self.plan, '--id', str(s['id']), '--ok'])
        sf_exec.main(['next', '--plan', self.plan])
        load = [s for s in self._plan()['steps'] if s['file'] == 'a_load.sql']
        self.assertTrue(all(s.get('class') == 'UPSTREAM_CASCADE' for s in load))
        self.assertEqual(sf_exec.main(['status', '--plan', self.plan]), 2)

    def test_session_var_order_class(self):
        p = self._plan()
        routine = next(s for s in p['steps'] if s['kind'] == 'routine')
        cls, _ = sf_exec.classify(p, routine, "Session variable '$START_DT' does not exist")
        self.assertEqual(cls, 'ORDER')
        cls, _ = sf_exec.classify(p, routine, "Session variable '$NOPE' does not exist")
        self.assertEqual(cls, 'OWN_DEFECT')

    def test_compile_mode_defers_objects_created_upstream(self):
        sf_exec.main(['plan', '--dir', str(self.d), '--mode', 'compile', '--out', str(self.d / 'c.json')])
        p = json.loads((self.d / 'c.json').read_text())
        call = next(s for s in p['steps'] if s['kind'] == 'call')
        cls, _ = sf_exec.classify(p, call, "Object 'STAGE_T' does not exist or not authorized.")
        self.assertEqual(cls, 'DEFERRED')

    def test_call_is_deferred_when_compile_mode(self):
        sf_exec.main(['plan', '--dir', str(self.d), '--mode', 'compile', '--out', str(self.d / 'c.json')])
        call = next(s for s in json.loads((self.d / 'c.json').read_text())['steps'] if s['kind'] == 'call')
        self.assertEqual((call['status'], call['class']), ('deferred', 'DEFERRED'))
        run_call = next(s for s in self._plan()['steps'] if s['kind'] == 'call')
        self.assertIsNone(run_call['status'])

    def test_generated_files_skipped_when_planning(self):
        (self.d / 'synthetic_data.sql').write_text('INSERT INTO SRC VALUES (1);')
        (self.d / 'source_table_ddl.sql').write_text('CREATE TABLE SRC (A INT);')
        sf_exec.main(['plan', '--dir', str(self.d), '--out', str(self.d / 'g.json')])
        order = json.loads((self.d / 'g.json').read_text())['order']
        self.assertEqual(sorted(order), ['a_load.sql', 'b_stage.sql', 'z_params.sql'])

    def test_counts_skip_temp_and_dropped_when_building_query(self):
        (self.d / 'c_keep.sql').write_text("CREATE TABLE KEEP_T AS SELECT 1 a;\nCREATE TABLE GONE_T AS SELECT 1 a;\n"
                                           "DROP TABLE IF EXISTS GONE_T;")
        sf_exec.main(['plan', '--dir', str(self.d), '--out', str(self.d / 'k.json')])
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sf_exec.main(['counts-sql', '--plan', str(self.d / 'k.json')])
        q = buf.getvalue()
        self.assertIn("'KEEP_T'", q)
        self.assertIn("'OUT_T'", q)
        self.assertNotIn('GONE_T', q)
        self.assertNotIn('STAGE_T', q)

    def test_reset_clears_file_and_dependents(self):
        for s in self._plan()['steps']:
            sf_exec.main(['record', '--plan', self.plan, '--id', str(s['id']), '--ok'])
        sf_exec.main(['reset', '--plan', self.plan, '--files', 'b_stage.sql'])
        pending = {s['file'] for s in self._plan()['steps'] if s['status'] is None}
        self.assertEqual(pending, {'b_stage.sql', 'a_load.sql'})

    def _staged(self, mode='run'):
        sf_exec.main(['plan', '--dir', str(self.d), '--mode', mode, '--out', str(self.d / 's.json'),
                      '--stage', '@DB.S.STG/run'])
        return str(self.d / 's.json')

    def _next_out(self, plan):
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sf_exec.main(['next', '--plan', plan])
        return buf.getvalue()

    def test_staged_next_writes_file_group_and_prints_put_when_stage_set(self):
        plan = self._staged()
        for _ in range(2):                                   # params, then b_stage
            out = self._next_out(plan)
            first = int(out.split('#')[1].split('-')[0])
            sf_exec.main(['record', '--plan', plan, '--id', str(first), '--ok'])
        out = self._next_out(plan)
        self.assertIn("PUT 'file://", out)
        self.assertIn('EXECUTE IMMEDIATE FROM @DB.S.STG/run/', out)
        self.assertNotIn('CREATE OR REPLACE PROCEDURE', out)   # the body is never printed
        body = next((self.d / '_steps').glob('*.sql')).parent
        staged = sorted(body.glob('*.sql'))[-1].read_text()
        self.assertIn('$$', staged)
        self.assertIn('CALL SP_LOAD()', staged)

    def test_staged_ok_marks_whole_group_when_recorded(self):
        plan = self._staged()
        out = self._next_out(plan)
        first = int(out.split('#')[1].split('-')[0])
        sf_exec.main(['record', '--plan', plan, '--id', str(first), '--ok'])
        params = [s for s in json.loads(Path(plan).read_text())['steps'] if s['file'] == 'z_params.sql']
        self.assertTrue(len(params) == 2 and all(s['status'] == 'ok' for s in params))

    def test_staged_error_maps_line_to_failing_statement_when_recorded(self):
        plan = self._staged()
        for _ in range(2):
            first = int(self._next_out(plan).split('#')[1].split('-')[0])
            sf_exec.main(['record', '--plan', plan, '--id', str(first), '--ok'])
        first = int(self._next_out(plan).split('#')[1].split('-')[0])
        staged = (self.d / '_steps' / f'{first}.sql').read_text().splitlines()
        call_line = next(i for i, l in enumerate(staged, 1) if l.startswith('CALL'))
        sf_exec.main(['record', '--plan', plan, '--id', str(first), '--error',
                      f"Uncaught exception of type 'STATEMENT_ERROR' in file @STG/run/{first}.sql on line "
                      f"{call_line} at position 0: Object 'STAGE_T' does not exist or not authorized."])
        load = {s['kind']: s for s in json.loads(Path(plan).read_text())['steps'] if s['file'] == 'a_load.sql'}
        self.assertEqual(load['routine']['status'], 'ok')
        self.assertEqual(load['call']['status'], 'error')

    def test_compile_only_steps_stay_inline_when_stage_set(self):
        plan = self._staged('compile')
        p = json.loads(Path(plan).read_text())
        for s in p['steps']:
            if s['file'] != 'b_stage.sql':
                s['status'] = 'ok'
        Path(plan).write_text(json.dumps(p))
        out = self._next_out(plan)
        self.assertIn('run_with=only_compile=true', out)
        self.assertNotIn('EXECUTE IMMEDIATE FROM', out)

    def test_compare_types_and_quotes_columns_when_csv_has_dates_numbers_reserved(self):
        q = sf_exec.compare_query('S.OUT_T', ['ID', 'D', 'AMT', 'default'],
                                  [['a', '2024-01-02', '1.5', 'x'], ['b', '', '', "o'k"]])
        self.assertIn('''TRY_TO_DATE(LEFT(TO_VARCHAR("D"), 10))''', q)
        self.assertIn('''DATEADD('day', TRY_TO_NUMBER(TO_VARCHAR("D")), '1960-01-01'::DATE)''', q)  # SAS day number
        self.assertIn('TRY_TO_DOUBLE(TO_VARCHAR("AMT"))), 6)', q)
        self.assertIn('"DEFAULT"', q)                       # reserved word quoted, upper-cased
        self.assertIn("'o''k'", q)                          # literal escaped
        self.assertIn('NULL', q)                            # empty CSV cell -> NULL
        self.assertIn('ROW_NUMBER() OVER', q)               # duplicates counted, not collapsed

    def test_compare_truncates_timestamps_when_csv_has_datetimes(self):
        q = sf_exec.compare_query('T', ['TS'], [['2024-01-02 08:00:00'], ['2024-01-03 09:30:00.000']])
        self.assertIn('''DATE_TRUNC('second', TRY_TO_TIMESTAMP_NTZ(TO_VARCHAR("TS")))''', q)

    def test_compare_skips_table_when_program_drops_it_last(self):
        (self.d / 'c_tmp.sql').write_text('CREATE TABLE GONE_T AS SELECT 1 a;\nDROP TABLE GONE_T;\n'
                                          'DROP TABLE IF EXISTS BACK_T;\nCREATE TABLE BACK_T AS SELECT 1 a;')
        p = str(self.d / 'd.json')
        sf_exec.main(['plan', '--dir', str(self.d), '--out', p])
        exp = self.d / 'tests' / 'c_tmp' / 'expected'
        exp.mkdir(parents=True)
        (exp / 'expected_GONE_T.csv').write_text('A\n1\n')
        (exp / 'expected_BACK_T.csv').write_text('A\n1\n')
        sf_exec.main(['compare-sql', '--plan', p, '--tests', str(self.d / 'tests')])
        sql = (self.d / '_steps' / 'compare.sql').read_text()
        self.assertIn('FROM BACK_T', sql)
        self.assertNotIn('GONE_T', sql)

    def test_compare_sql_writes_one_statement_when_tests_dir_has_expected_csvs(self):
        exp = self.d / 'tests' / 'a_load' / 'expected'
        exp.mkdir(parents=True)
        (exp / 'expected_OUT_T.csv').write_text('ID,N\n1,2\n')
        (exp / 'expected_EMPTY_T.csv').write_text('ID\n')
        sf_exec.main(['compare-sql', '--plan', self.plan, '--tests', str(self.d / 'tests')])
        sql = (self.d / '_steps' / 'compare.sql').read_text()
        self.assertEqual(sql.count(';'), 1)
        self.assertIn('FROM OUT_T', sql)
        self.assertIn('WHERE FALSE', sql)                   # zero expected rows still compared

    def test_reset_keeps_call_deferred_when_compile_mode(self):
        c = str(self.d / 'c.json')
        sf_exec.main(['plan', '--dir', str(self.d), '--mode', 'compile', '--out', c])
        sf_exec.main(['reset', '--plan', c, '--files', 'a_load.sql'])
        call = next(s for s in json.loads(Path(c).read_text())['steps'] if s['kind'] == 'call')
        self.assertEqual((call['status'], call['class']), ('deferred', 'DEFERRED'))

    def test_empty_outputs_flagged(self):
        res = self.d / 'counts.json'
        res.write_text(json.dumps({'OUT_T': 0, 'STAGE_T': 3}))
        sf_exec.main(['ingest-counts', '--plan', self.plan, str(res)])
        self.assertEqual(self._plan()['empty_outputs'], ['OUT_T'])


if __name__ == '__main__':
    unittest.main()
