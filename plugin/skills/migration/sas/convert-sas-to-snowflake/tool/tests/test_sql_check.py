"""Unit tests for sql_check.py (stdlib only, fast, synthetic fixtures only)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sql_check as sc  # noqa: E402


class _Dir:
    def __init__(self, files):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name)
        for name, body in files.items():
            p = self.path / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)

    def run(self, check, **kw):
        rep = sc.Report()
        files = sc.sql_files(str(self.path))
        if check == 'xfile':
            sc.check_xfile(files, rep, kw.get('tables'), kw.get('orch'))
        elif check == 'fidelity':
            sc.check_fidelity(files, rep, str(self.path / 'sas'))
        else:
            getattr(sc, f'check_{check}')(files, rep)
        return [(f['rule'], f['severity']) for f in rep.findings]

    def close(self):
        self._tmp.cleanup()


def rules(check, files, **kw):
    d = _Dir(files)
    try:
        return {r for r, _ in d.run(check, **kw)}
    finally:
        d.close()


PROC_OK = """CREATE OR REPLACE PROCEDURE P(A STRING) RETURNS STRING LANGUAGE SQL EXECUTE AS CALLER AS
$$
BEGIN
  INSERT INTO T SELECT 1;  -- a ; inside the body must not split
  RETURN 'x;y';
END;
$$;
"""


class WalkerTests(unittest.TestCase):
    def test_dollar_body_is_one_statement(self):
        self.assertEqual(len(sc.statements(PROC_OK)), 1)

    def test_non_nesting_block_comment_leaks_sas(self):
        bad = "/* SAS: data x; /* inner */ set y; run; */\nSELECT 1;"
        self.assertTrue(sc.malformed(bad))

    def test_masked_keeps_length_and_hides_comments(self):
        m = sc.masked("SELECT 'a -- b' FROM t -- FROM gone\n")
        self.assertEqual(len(m), len("SELECT 'a -- b' FROM t -- FROM gone\n"))
        self.assertEqual(m.count('FROM'), 1)

    def test_dollar_sign_inside_body_does_not_break_masking(self):
        text = "CREATE PROCEDURE P() RETURNS INT LANGUAGE SQL AS\n$$\nBEGIN\n  -- uses $V and EXECUTE IMMEDIATE x INTO :y in a comment\n  RETURN 1;\nEND;\n$$;"
        self.assertNotIn('INTO', sc.masked(text))


class LintTests(unittest.TestCase):
    def test_execute_immediate_into(self):
        self.assertIn('execute_immediate_into', rules('lint', {'a.sql': "EXECUTE IMMEDIATE 'SELECT 1' INTO :v;"}))
        self.assertNotIn('execute_immediate_into', rules('lint', {'a.sql': "EXECUTE IMMEDIATE 'SELECT 1 INTO :v';"}))

    def test_exception_message(self):
        bad = "DECLARE e EXCEPTION (-20001, 'a' || 'b'); BEGIN RETURN 1; END;"
        good = "DECLARE e EXCEPTION (-20001, 'it''s fine'); BEGIN RETURN 1; END;"
        self.assertIn('exception_message_not_literal', rules('lint', {'a.sql': bad}))
        self.assertNotIn('exception_message_not_literal', rules('lint', {'a.sql': good}))

    def test_header_inside_file_format(self):
        self.assertIn('header_in_file_format', rules('lint', {'a.sql': "COPY INTO @s/x FROM t FILE_FORMAT = (TYPE = CSV HEADER = TRUE);"}))
        self.assertNotIn('header_in_file_format', rules('lint', {'a.sql': "COPY INTO @s/x FROM t FILE_FORMAT = (TYPE = CSV) HEADER = TRUE;"}))

    def test_star_argument_outside_select(self):
        bad = "SELECT f.value FROM t, LATERAL FLATTEN(INPUT => OBJECT_CONSTRUCT(*)) f;"
        where = "SELECT a FROM t WHERE HASH(*) <> 0;"
        good = "SELECT OBJECT_CONSTRUCT(*) AS o, COUNT(*) FROM t GROUP BY 1 HAVING COUNT(*) > 1;"
        self.assertIn('star_argument_outside_select', rules('lint', {'a.sql': bad}))
        self.assertIn('star_argument_outside_select', rules('lint', {'a.sql': where}))
        self.assertNotIn('star_argument_outside_select', rules('lint', {'a.sql': good}))

    def test_unquoted_procedure_body(self):
        bad = "CREATE OR REPLACE PROCEDURE P() RETURNS INT LANGUAGE SQL AS BEGIN RETURN 1; END;"
        self.assertIn('procedure_body_not_quoted', rules('lint', {'a.sql': bad}))
        self.assertNotIn('procedure_body_not_quoted', rules('lint', {'a.sql': PROC_OK}))

    def test_copy_xlsx(self):
        self.assertIn('copy_xlsx', rules('lint', {'a.sql': "COPY INTO @s/out.xlsx FROM t;"}))
        self.assertNotIn('copy_xlsx', rules('lint', {'a.sql': "COPY INTO @s/out.csv FROM t;"}))

    def test_session_var_in_procedure_body(self):
        body = PROC_OK.replace("SELECT 1", "SELECT $RUN_DT")
        self.assertIn('session_var_at_create', rules('lint', {'a.sql': body}))
        self.assertNotIn('session_var_at_create', rules('lint', {'a.sql': PROC_OK.replace('-- a', '-- $X in a comment, a')}))

    def test_type_cast_needs_reason(self):
        bare = "SELECT * FROM a JOIN b ON a.k::VARCHAR = b.k::VARCHAR;\nSELECT SUM(TRY_TO_NUMBER(t.amt)) FROM t;"
        reasoned = "-- TYPE: a.k NUMBER, b.k VARCHAR (live)\nSELECT * FROM a JOIN b ON a.k::VARCHAR = b.k::VARCHAR;"
        self.assertEqual(rules('lint', {'a.sql': bare}), {'type_cast_without_reason'})
        self.assertNotIn('type_cast_without_reason', rules('lint', {'a.sql': reasoned}))

    def test_type_reason_found_when_comment_is_up_to_three_lines_above(self):
        expr = "SELECT\n  SUM(\n    TRY_TO_NUMBER(t.amt)) FROM t;"
        self.assertNotIn('type_cast_without_reason', rules('lint', {'a.sql': "-- TYPE: amt VARCHAR (live)\n" + expr}))
        self.assertIn('type_cast_without_reason', rules('lint', {'a.sql': "-- TYPE: amt VARCHAR\n\n\n\n" + expr}))

    def test_identifier_not_a_produced_table_when_name_is_dynamic(self):
        o = sc.parse_objects("CREATE OR REPLACE TABLE IDENTIFIER(:v) AS SELECT 1 a;\nCREATE TABLE T2 AS SELECT 1 a;")
        self.assertEqual([p['name'] for p in o['produces']], ['T2'])

    def test_temp_before_use(self):
        bad = "CREATE TEMPORARY TABLE x AS SELECT 1 a;\nUSE SCHEMA DB.S;"
        good = "USE SCHEMA DB.S;\nCREATE TEMPORARY TABLE x AS SELECT 1 a;"
        self.assertIn('temp_before_use', rules('lint', {'a.sql': bad}))
        self.assertNotIn('temp_before_use', rules('lint', {'a.sql': good}))

    def test_allow_comment_suppresses(self):
        self.assertNotIn('copy_xlsx', rules('lint', {'a.sql': "-- sql_check: allow copy_xlsx\nCOPY INTO @s/out.xlsx FROM t;"}))


class XfileTests(unittest.TestCase):
    def test_qualifier_mismatch(self):
        files = {'a.sql': "CREATE OR REPLACE TABLE DB.S1.ORDERS AS SELECT 1 a;",
                 'b.sql': "CREATE OR REPLACE TABLE DB.S1.R AS SELECT * FROM DB.S2.ORDERS;"}
        self.assertIn('qualifier_mismatch', rules('xfile', files))

    def test_unqualified_read_of_produced_table_is_fine(self):
        files = {'a.sql': "CREATE OR REPLACE TABLE DB.S1.ORDERS AS SELECT 1 a;",
                 'b.sql': "CREATE OR REPLACE TABLE R AS SELECT * FROM ORDERS o JOIN (SELECT 1 x) q ON 1=1;"}
        self.assertEqual(rules('xfile', files), set())

    def test_function_from_and_cte_are_not_tables(self):
        files = {'a.sql': "WITH c AS (SELECT 1 a) SELECT EXTRACT(YEAR FROM d), TRIM(x FROM y) FROM c;"}
        d = _Dir(files)
        try:
            rep = sc.Report()
            sc.check_xfile(sc.sql_files(str(d.path)), rep)
            self.assertEqual(rep.meta['consumed_never_produced'], [])
        finally:
            d.close()

    def test_call_arity_mismatch_and_overload(self):
        files = {'p.sql': PROC_OK.replace('P(A STRING)', 'DO_IT(A STRING, B STRING)'),
                 'c.sql': "CALL DO_IT('x');"}
        self.assertIn('call_arity_mismatch', rules('xfile', files))
        files['c.sql'] = "CALL DO_IT('x', 'y');"
        self.assertNotIn('call_arity_mismatch', rules('xfile', files))

    def test_stub_shadows_real_by_name_and_by_literal(self):
        real = PROC_OK.replace('P(A STRING)', 'SP_WRITE_EXTRACT_7(A STRING)')
        stub = ("CREATE OR REPLACE PROCEDURE SP_WRITE_ANY(M STRING, A STRING) RETURNS STRING LANGUAGE SQL "
                "COMMENT = 'STUB -- MANUAL_REVIEW_REQUIRED' AS\n$$\nBEGIN\n  RETURN 'stub';\nEND;\n$$;\n")
        files = {'real.sql': real, 'stub.sql': stub, 'caller.sql': "CALL SP_WRITE_ANY('WriteExtract_7', 'x');"}
        self.assertIn('stub_shadows_real', rules('xfile', files))
        files['caller.sql'] = "CALL SP_WRITE_ANY('Unrelated', 'x');"
        self.assertNotIn('stub_shadows_real', rules('xfile', files))

    def test_not_invoked_sub_flow(self):
        files = {'child.sql': PROC_OK.replace('P(A STRING)', 'SP_CHILD(A STRING)'),
                 'parent.sql': PROC_OK.replace('P(A STRING)', 'SP_PARENT(A STRING)'),
                 'orchestration/run.sql': "CALL SP_PARENT('x');"}
        d = _Dir(files)
        try:
            found = d.run('xfile', orch=str(d.path / 'orchestration'))
            self.assertIn(('not_invoked', 'warn'), found)
            (d.path / 'parent.sql').write_text(files['parent.sql'].replace("RETURN 'x;y';", "CALL SP_CHILD(A);\n  RETURN 'x;y';"))
            self.assertNotIn(('not_invoked', 'warn'), d.run('xfile', orch=str(d.path / 'orchestration')))
        finally:
            d.close()


SAS = """proc sql;
  create table w1 as
  select a.k, b.v
  from t1 a inner join t2 b on (a.k = b.k);
quit;
proc sql;
  create table w2 as
  select a.k, b.v
  from t1 a left join t3 b on (a.k = b.k and b.flag is missing);
quit;
"""


class FidelityTests(unittest.TestCase):
    def _run(self, sql):
        return rules('fidelity', {'sas/job.sas': SAS, 'job.sql': sql})

    def test_faithful_blocks_pass(self):
        sql = ("-- SAS: job.sas:L1-L5\nCREATE TABLE W1 AS SELECT a.k, b.v FROM T1 a INNER JOIN T2 b ON a.k = b.k;\n"
               "-- SAS: job.sas:L6-L10\nCREATE TABLE W2 AS SELECT a.k, b.v FROM T1 a LEFT JOIN T3 b ON a.k = b.k AND b.flag IS NULL;\n")
        self.assertEqual(self._run(sql), set())

    def test_changed_join_type_added_distinct_and_anti_join(self):
        sql = ("-- SAS: job.sas:L1-L5\nCREATE TABLE W1 AS SELECT DISTINCT a.k, b.v FROM T1 a LEFT JOIN T2 b ON a.k = b.k;\n"
               "-- SAS: job.sas:L6-L10\nCREATE TABLE W2 AS SELECT a.k, b.v FROM T1 a INNER JOIN T3 b ON a.k = b.k "
               "WHERE a.k NOT IN (SELECT k FROM X);\n")
        self.assertEqual(self._run(sql), {'join_type_mismatch', 'distinct_added', 'anti_join_introduced'})

    def test_macro_expansion_multiple_is_accepted(self):
        sql = ("-- SAS: job.sas:L1-L5\nCREATE TABLE W1A AS SELECT * FROM T1 a INNER JOIN T2 b ON a.k = b.k;\n"
               "CREATE TABLE W1B AS SELECT * FROM T1 a INNER JOIN T2 b ON a.k = b.k;\n")
        self.assertEqual(self._run(sql), set())

    def test_missing_anchors_warn(self):
        self.assertEqual(self._run("CREATE TABLE W1 AS SELECT 1 a;"), {'no_sas_anchors'})

    def test_no_anchor_warning_when_file_is_generated(self):
        self.assertEqual(rules('fidelity', {'sas/job.sas': SAS, 'synthetic_data.sql': "INSERT INTO T1 VALUES (1);"}), set())

    def test_no_error_when_construct_only_looks_like_distinct_or_anti_join(self):
        for where in ("WHERE a.k IS DISTINCT FROM b.v", "WHERE a.k IS NOT DISTINCT FROM b.v",
                      "WHERE COALESCE(a.k NOT IN (1, 2), TRUE)", "WHERE a.k NOT IN ('X', 'Y')",
                      "WHERE a.k NOT IN (SELECT TRIM(VALUE) FROM TABLE(SPLIT_TO_TABLE(GETVARIABLE('L'), ',')))"):
            with self.subTest(where):
                sql = f"-- SAS: job.sas:L1-L5\nCREATE TABLE W1 AS SELECT a.k, b.v FROM T1 a INNER JOIN T2 b ON a.k = b.k {where};\n"
                self.assertEqual(self._run(sql), set())

    def test_anti_join_still_flagged_when_not_in_is_outside_coalesce(self):
        sql = "-- SAS: job.sas:L1-L5\nCREATE TABLE W1 AS SELECT a.k FROM T1 a INNER JOIN T2 b ON a.k = b.k WHERE a.k NOT IN (SELECT k FROM X);\n"
        self.assertEqual(self._run(sql), {'anti_join_introduced'})

    def test_anchor_lines_match_assessment_when_sas_has_cr_cr_lf(self):
        sql = "-- SAS: job.sas:L6-L10\nCREATE TABLE W2 AS SELECT a.k, b.v FROM T1 a LEFT JOIN T3 b ON a.k = b.k;\n"
        self.assertEqual(rules('fidelity', {'sas/job.sas': SAS.replace('\n', '\r\r\n'), 'job.sql': sql}), set())

    def test_distinct_allowed_when_nodup_sort_is_the_step_above(self):
        sql = "-- SAS: job.sas:L2-L6\nCREATE TABLE W1 AS SELECT DISTINCT a.k, b.v FROM T1 a INNER JOIN T2 b ON a.k = b.k;\n"
        for sort, expected in (("proc sort data=t1 nodupkey; by k; run;", set()),
                               ("proc sort data=t1 noduprecs; by k; run;", set()),
                               ("proc sort data=t1; by k; run;", {'distinct_added'})):
            with self.subTest(sort):
                self.assertEqual(rules('fidelity', {'sas/job.sas': sort + "\n" + SAS, 'job.sql': sql}), expected)



STATEFUL = """data all;
  set part_a part_b(in=b);
run;
proc sort data=all; by grp pos; run;
data picked;
  set all; by grp;
  retain state;
  if first.grp then state = 0;
  if state = 0 and flag then do; state = 1; output; end;
run;
"""


class ConcatAndTieTests(unittest.TestCase):
    def _run(self, sql):
        return rules('fidelity', {'sas/job.sas': STATEFUL, 'job.sql': sql})

    def test_union_dropped_when_set_concatenation_missing(self):
        self.assertEqual(self._run("-- SAS: job.sas:L1-L3\nCREATE TABLE A AS SELECT * FROM PART_A;\n"), {'union_dropped'})
        self.assertEqual(self._run("-- SAS: job.sas:L1-L3\nCREATE TABLE A AS SELECT * FROM PART_A UNION ALL SELECT * FROM PART_B;\n"), set())

    def test_no_union_error_when_set_has_one_dataset_and_options(self):
        sas = "data x; set lib.a(keep=k rename=(k=j)) end=eof nobs=n; run;"
        self.assertEqual(rules('fidelity', {'sas/job.sas': sas, 'job.sql': "-- SAS: job.sas:L1-L1\nCREATE TABLE X AS SELECT * FROM A;\n"}), set())

    def test_tie_warning_when_stateful_by_ordered_on_one_key(self):
        body = "-- SAS: job.sas:L5-L10\nCREATE TABLE P AS SELECT * FROM A QUALIFY ROW_NUMBER() OVER (PARTITION BY grp ORDER BY pos) = 1;\n"
        self.assertEqual(self._run(body), {'order_tie_unresolved'})
        self.assertEqual(self._run(body.replace('ORDER BY pos', 'ORDER BY pos, _SRC_ROW')), set())

    def test_no_tie_warning_when_plain_sort(self):
        self.assertEqual(self._run("-- SAS: job.sas:L4-L4\nCREATE TABLE S AS SELECT * FROM A ORDER BY grp;\n"), set())


if __name__ == '__main__':
    unittest.main()
