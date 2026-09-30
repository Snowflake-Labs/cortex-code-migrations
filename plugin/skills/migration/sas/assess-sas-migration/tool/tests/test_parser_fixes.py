"""Unit tests for the parser / dependency / classifier fixes (stdlib only, fast).

Run from the tool dir:
    python3 -m unittest discover -s tests
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sas_analyzer import SASParser, DependencyTracker, TierClassifier  # noqa: E402
from sas_analyzer.parser import BlockType  # noqa: E402
from sas_analyzer.source_io import normalise_newlines, read_sas_source  # noqa: E402


def _parse(text):
    return SASParser().parse(text)


def _block(text, block_type):
    return next(b for b in _parse(text).blocks if b.block_type == block_type)


class LineEndingTests(unittest.TestCase):
    def test_cr_cr_lf_counts_once(self):
        text, changed = normalise_newlines("a;\r\r\nb;\r\r\nc;")
        self.assertTrue(changed)
        self.assertEqual(_parse(text).total_lines, 3)

    def test_lone_cr_and_crlf(self):
        text, _ = normalise_newlines("a;\rb;\r\nc;\n")
        self.assertEqual(text, "a;\nb;\nc;\n")

    def test_plain_lf_unchanged(self):
        self.assertEqual(normalise_newlines("a;\nb;"), ("a;\nb;", False))

    def test_read_sas_source(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.sas"
            p.write_bytes(b"data a;\r\r\nrun;\r\r\n")
            text, changed = read_sas_source(p)
        self.assertTrue(changed)
        self.assertEqual(text, "data a;\nrun;\n")


class DataHeaderTests(unittest.TestCase):
    def test_nested_dataset_options(self):
        b = _block("data x(rename=(a=b) keep=c); set lib.y(keep=(d e)) end=eof; run;", BlockType.DATA_STEP)
        self.assertEqual(b.metadata['output_datasets'], ['x'])
        self.assertEqual(b.metadata['input_datasets'], ['lib.y'])

    def test_merge_in_flags_and_set_options(self):
        b = _block("data out; merge a(in=ina) b.t(in=inb); by k; run;", BlockType.DATA_STEP)
        self.assertEqual(b.metadata['input_datasets'], ['a', 'b.t'])
        b = _block("data o; set lib.x key=idx / unique; run;", BlockType.DATA_STEP)
        self.assertEqual(b.metadata['input_datasets'], ['lib.x'])

    def test_null_and_equals_dropped(self):
        b = _block("data _null_ = ; set a; run;", BlockType.DATA_STEP)
        self.assertEqual(b.metadata['output_datasets'], [])

    def test_identifier_ending_in_data_is_not_a_data_step(self):
        script = _parse("proc sql; create table m as select * from mast a left join CBData B\n"
                        "  on a.key = b.key; quit;\nproc sort data=m; by key; run;")
        self.assertFalse(any(b.block_type == BlockType.DATA_STEP for b in script.blocks))


class ThreePartNameTests(unittest.TestCase):
    def test_from_join_and_insert(self):
        b = _block("proc sql; execute(insert into DB.STAG.T1 select * from DB.EDW.SRC a "
                   "join DB.EDW.DIM d on 1=1) by snow; quit;", BlockType.PROC_SQL)
        self.assertIn('DB.STAG.T1', b.metadata['output_datasets'])
        self.assertIn('DB.EDW.SRC', b.metadata['input_datasets'])
        self.assertIn('DB.EDW.DIM', b.metadata['input_datasets'])

    def test_create_strips_paren(self):
        b = _block("proc sql; create table LIB.T(bulkload=yes) as select 1 from x; quit;", BlockType.PROC_SQL)
        self.assertEqual(b.metadata['output_datasets'], ['LIB.T'])


class SharedEdgeTests(unittest.TestCase):
    def _graph(self, files):
        t = DependencyTracker()
        return t, {name: t.analyze_file(_parse(src)) for name, src in files.items()}

    def test_work_collision_no_edge(self):
        t, fa = self._graph({
            'a.sas': "data work.tmp; set stg.src; run;",
            'b.sas': "data tmp; set work.tmp; run; data out.final; set tmp; run;",
        })
        g = t.build_cross_file_graph(fa)
        self.assertEqual(g['edges'], [])
        self.assertEqual(g['external_inputs'], ['STG.SRC'])
        self.assertEqual(t.build_output_tables(fa), ['OUT.FINAL'])

    def test_shared_three_part_edge_and_macro_refs(self):
        t, fa = self._graph({
            'a.sas': "proc sql; execute(insert into DB.S.T select * from DB.S.RAW) by snow; quit;",
            'b.sas': "proc sql; create table X.Y as select * from DB.S.T; quit;"
                     " data z; set LIB.M&yyyymm; run;",
        })
        g = t.build_cross_file_graph(fa)
        self.assertEqual(g['edges'], [{'from': 'a.sas', 'to': 'b.sas', 'via': 'DB.S.T'}])
        self.assertEqual(g['external_inputs'], ['DB.S.RAW'])
        self.assertEqual(g['unresolvable_macro_reference_count'], 1)

    def test_egp_tasks_share_work(self):
        a, b = 'Query-3TRomiOYpuoBdSZB.sas', 'CodeTask-Ljsg6UTk2OF1TVPu.sas'
        t, fa = self._graph({
            a: "proc sql; create table work.nstatus as select * from stg.s; quit;",
            b: "data out.x; set nstatus; run;",
        })
        sessions = DependencyTracker.session_groups([f'/p/{a}', f'/p/{b}'])
        g = t.build_cross_file_graph(fa, sessions)
        self.assertEqual(g['edges'], [{'from': a, 'to': b, 'via': 'NSTATUS'}])
        self.assertEqual(t.build_cross_file_graph(fa)['edges'], [])  # separate sessions


class ClassifierTests(unittest.TestCase):
    def _classify(self, text):
        c = TierClassifier()
        return c.classify_file(_parse(text))

    def test_call_execute_is_tier2(self):
        r = self._classify("data _null_; set lib.ctl; call execute('%run('||id||')'); run;")
        self.assertEqual(r['primary_tier'], 'TIER_2_SP')

    def test_call_execute_with_hash_is_tier3(self):
        r = self._classify("data _null_; declare hash h(); call execute('x'); run;")
        self.assertEqual(r['primary_tier'], 'TIER_3_PYSPARK')

    def test_do_loop_of_call_executes_is_tier2(self):
        r = self._classify("data _null_; do until(eof); set lib.c end=eof;"
                           " call execute('a'); call execute('b'); call execute('c'); end; run;")
        self.assertEqual(r['primary_tier'], 'TIER_2_SP')

    def test_unrecognised_proc_low_confidence(self):
        r = self._classify("proc tabulate data=lib.x; class a; table a; run;")
        self.assertEqual(r['confidence'], 'LOW')
        r = self._classify("proc delete data=work.x; run;")
        self.assertEqual(r['confidence'], 'HIGH')


def _io(text):
    blocks = _parse(text).blocks
    return ([d for b in blocks for d in b.metadata.get('input_datasets', [])],
            [d for b in blocks for d in b.metadata.get('output_datasets', [])])


class NameLiteralTests(unittest.TestCase):
    """``lib.'any text'n`` must stay one dataset with its libref, never a bare libref."""

    def test_name_literals_in_every_dataset_position(self):
        cases = [
            ("proc sql; create table work.'out x'n as select * from erp.'/ABC/A.B'n t "
             "join lib.\"my tbl\"n u on 1=1; quit;",
             ["erp.'/ABC/A.B'n", "lib.'my tbl'N"], ["work.'out x'n"]),
            ("proc sql; insert into tgt.'a b'n select * from x; quit;", ['x'], ["tgt.'a b'n"]),
            ("data work.y; set lib.'my tbl'n(keep=a) other end=eof; run;", ["lib.'my tbl'n", 'other'], ['work.y']),
            ("data work.y; merge a.'p q'n b.'r/s'n; by k; run;", ["a.'p q'n", "b.'r/s'n"], ['work.y']),
            ("data w; set work.\"%str(x y)\"n key=k/unique; run;", ["work.'%str(x y)'N"], ['w']),
            ("proc sort data=lib.'s t'n out=work.'u v'n; by a; run;", ["lib.'s t'n"], ["work.'u v'n"]),
        ]
        for text, reads, writes in cases:
            with self.subTest(text=text):
                self.assertEqual(_io(text), (reads, writes))

    def test_libref_alone_is_never_recorded(self):
        reads, _ = _io("proc sql; create table a as select * from erp.'/ABC/X'n; quit;")
        self.assertNotIn('erp', [r.lower() for r in reads])

    def test_macro_built_names_still_captured(self):
        self.assertEqual(_io("proc sort data=&lib..&tbl out=work.s; by a; run;"), (['&lib..&tbl'], ['work.s']))

    def test_literal_tables_become_external_inputs(self):
        tracker = DependencyTracker()
        script = _parse("proc sql; create table work.a as select * from src.'my t'n; quit;")
        graph = tracker.build_cross_file_graph({'f.sas': tracker.analyze_file(script)})
        self.assertEqual(graph['external_inputs'], ["SRC.'MY T'N"])


class IncludeTests(unittest.TestCase):
    def test_static_dynamic_and_fileref_includes(self):
        text = ("%include '/nfs/lib/formats.sas';\n%include \"&root/setup.sas\";\n%include codelib;\n"
                "/* %include 'commented.sas'; */\n")
        self.assertEqual(_parse(text).includes, [
            {'path': '/nfs/lib/formats.sas', 'dynamic': False},
            {'path': '&root/setup.sas', 'dynamic': True},
            {'path': 'codelib', 'dynamic': False},
        ])

    def test_in_scope_when_included_file_is_assessed(self):
        from sas_analyzer import AssessmentReporter
        main = SASParser().parse("%include '/x/Helper.sas';\n%include '/x/gone.sas';\n", filename='main.sas')
        helper = SASParser().parse('data a; run;', filename='helper.sas')
        found = {i['path']: i['in_scope'] for i in AssessmentReporter._external_includes([main, helper])}
        self.assertEqual(found, {'/x/Helper.sas': True, '/x/gone.sas': False})


class SourceDiscoveryTests(unittest.TestCase):
    def test_previous_output_dirs_are_not_reread(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from assess_sas import find_source_files
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'job.sas').write_text('data a; run;')
            for out in ('old_run', 'new_run'):
                (root / out / 'egp_extracted').mkdir(parents=True)
                (root / out / 'egp_extracted' / 'task.sas').write_text('data b; run;')
            (root / 'old_run' / 'assessment.json').write_text('{}')
            sas, _ = find_source_files(str(root), root / 'new_run')
            self.assertEqual([p.name for p in sas], ['job.sas'])

    def test_source_root_with_assessment_json_is_still_read(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from assess_sas import find_source_files
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'job.sas').write_text('data a; run;')
            (root / 'assessment.json').write_text('{}')
            self.assertEqual([p.name for p in find_source_files(str(root))[0]], ['job.sas'])


if __name__ == '__main__':
    unittest.main()
