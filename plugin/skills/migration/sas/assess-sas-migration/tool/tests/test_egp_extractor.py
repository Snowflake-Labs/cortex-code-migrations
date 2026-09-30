"""EGP extractor tests on synthetic archives only. Invented element types (``FancyWizardTask``)
guard against the extractor relying on a list of known task types."""

import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

TOOL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_DIR))

from sas_analyzer import DependencyTracker, SASParser  # noqa: E402
from sas_analyzer import egp_extractor as egp  # noqa: E402
from sas_analyzer.source_io import read_sas_source  # noqa: E402

NS = 'SAS.EG.ProjectElements.'


def _header(item_id: str, label: str, header_type: str, container: str = '',
            inputs: Sequence[str] = ()) -> str:
    return (f'<Element><Label>{label}</Label><Type>{header_type}</Type>'
            f'<Container>{container}</Container><ID>{item_id}</ID>'
            f'<ModifiedByEGVer>8.1.0.1</ModifiedByEGVer>'
            f'<InputIDs>{",".join(inputs)}</InputIDs></Element>')


def task(item_id: str, element_type: str, container: str, label: Optional[str] = None,
         inputs: Sequence[str] = (), body: str = '') -> str:
    return (f'<Element Type="{NS}{element_type}">'
            f'{_header(item_id, label or item_id, "TASK", container, inputs)}{body}</Element>')


def code(item_id: str, parent: str, text: str, begin_user: str = '', end_user: str = '') -> str:
    return (f'<Element Type="{NS}Code">{_header(item_id, item_id, "CODE")}'
            f'<TextElement><Text>{text}</Text></TextElement>'
            f'<Code><Parent>{parent}</Parent><BeginAppCode>ODS _ALL_ CLOSE;</BeginAppCode>'
            f'<BeginUserCode>{begin_user}</BeginUserCode><TaskCode>{text}</TaskCode>'
            f'<EndUserCode>{end_user}</EndUserCode><EndAppCode>quit;run;</EndAppCode></Code></Element>')


def _dep(dep_id: str, flag: Optional[str]) -> str:
    attr = '' if flag is None else f' ResourceDependency="{flag}"'
    return f'<DepID{attr}>{dep_id}</DepID>'


def flow(item_id: str, element_type: str, label: str,
         processes: Sequence[Tuple[str, Sequence[Tuple[str, Optional[str]]]]]) -> str:
    procs = ''
    for node, deps in processes:
        dep_xml = ''.join(_dep(d, flag) for d, flag in deps)
        procs += f'<Process><Element><ID>{node}</ID></Element><Dependencies>{dep_xml}</Dependencies></Process>'
    return (f'<Element Type="{NS}{element_type}">{_header(item_id, label, "CONTAINER")}'
            f'<PFD>{procs}</PFD></Element>')


def link(item_id: str, container: str, src: str, dst: str) -> str:
    return (f'<Element Type="{NS}Link">{_header(item_id, item_id, "LINK", container)}'
            f'<Log><LinkFrom>{src}</LinkFrom><LinkTo>{dst}</LinkTo></Log></Element>')


def project_xml(elements: Sequence[str], data_list: str = '', file_list: str = '',
                extra: str = '') -> str:
    return ('<?xml version="1.0" encoding="utf-16"?>'
            f'<Project><Element><ID>ProjectCollection-x</ID></Element>'
            f'<DataList>{data_list}</DataList><ExternalFileList>{file_list}</ExternalFileList>'
            f'<Elements>{"".join(elements)}</Elements>{extra}</Project>')


def make_egp(directory: Path, xml: str, encoding: str = 'utf-16',
             extra_entries: Optional[Dict[str, bytes]] = None, name: str = 'proj.egp') -> Path:
    raw = b'\xef\xbb\xbf' + xml.encode('utf-8') if encoding == 'utf-8-bom' else xml.encode(encoding)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('project.xml', raw)
        for entry, data in (extra_entries or {}).items():
            zf.writestr(entry, data)
    path = directory / name
    path.write_bytes(buf.getvalue())
    return path


def simple_project() -> str:
    """Setup program -> invented wizard task -> export (no code), in one flow."""
    return project_xml([
        flow('Flow-1', 'ProcessFlowContainer', 'Main flow', [
            ('Prog-aaaaaaaaaaaaaaaa', []),
            ('FancyWizardTask-bbbbbbbbbbbbbbbb', [('Prog-aaaaaaaaaaaaaaaa', 'false')]),
            ('Export-cccccccccccccccc', [('FancyWizardTask-bbbbbbbbbbbbbbbb', 'true')]),
        ]),
        task('Prog-aaaaaaaaaaaaaaaa', 'CodeTask', 'Flow-1', 'Setup'),
        task('FancyWizardTask-bbbbbbbbbbbbbbbb', 'FancyWizardTask', 'Flow-1', 'Build table'),
        task('Export-cccccccccccccccc', 'ExportTask', 'Flow-1', 'Send file',
             body='<EXPORT><OUTPUTFILEPATHNAME>/out/result.csv</OUTPUTFILEPATHNAME></EXPORT>'),
        code('Code-1', 'Prog-aaaaaaaaaaaaaaaa', "%let start='01jan2020'd;"),
        code('Code-2', 'FancyWizardTask-bbbbbbbbbbbbbbbb',
             '%_eg_conditional_dropds(WORK.OUT);\nPROC SQL;\n  CREATE TABLE WORK.OUT AS SELECT * FROM LIB1.SRC;\nQUIT;'),
    ])


class DecodingTests(unittest.TestCase):
    def test_encodings_with_and_without_bom(self):
        xml = '<?xml version="1.0"?><Project/>'
        for raw in (xml.encode('utf-16'), b'\xfe\xff' + xml.encode('utf-16-be'),
                    xml.encode('utf-16-le'), xml.encode('utf-16-be'),
                    xml.encode('utf-8'), b'\xef\xbb\xbf' + xml.encode('utf-8')):
            with self.subTest(raw=raw[:4]):
                self.assertEqual(egp.parse_project_xml(egp.decode_project_xml(raw)).tag, 'Project')

    def test_doctype_rejected(self):
        with self.assertRaises(egp.EgpError):
            egp.parse_project_xml('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><Project/>')

    def test_malformed_rejected(self):
        with self.assertRaises(egp.EgpError):
            egp.parse_project_xml('<Project><Elements></Project>')


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_code_flow_and_order(self):
        for encoding in ('utf-16', 'utf-8-bom', 'utf-8'):
            with self.subTest(encoding=encoding):
                p = egp.load_egp(make_egp(self.dir, simple_project(), encoding))
                self.assertEqual(len(p.code_tasks()), 2)
                self.assertEqual([t.element_type for t in p.no_code_tasks()], ['ExportTask'])
                self.assertEqual(p.flows[0].task_order,
                                 ['Prog-aaaaaaaaaaaaaaaa', 'FancyWizardTask-bbbbbbbbbbbbbbbb',
                                  'Export-cccccccccccccccc'])
                self.assertEqual(p.task_edges(), {('Prog-aaaaaaaaaaaaaaaa', 'FancyWizardTask-bbbbbbbbbbbbbbbb')})
                flags = {(e.src, e.dst): e.resource_dependency for e in p.flows[0].edges}
                self.assertIs(flags[('FancyWizardTask-bbbbbbbbbbbbbbbb', 'Export-cccccccccccccccc')], True)

    def test_user_pre_and_post_code_kept_eg_wrappers_dropped(self):
        xml = project_xml([
            flow('F', 'PFD', 'Flow', [('A-aaaaaaaaaaaaaaaa', [])]),
            task('A-aaaaaaaaaaaaaaaa', 'Query', 'F'),
            code('C1', 'A-aaaaaaaaaaaaaaaa', 'proc sql; quit;', begin_user='%let pre=1;', end_user='%let post=1;'),
        ])
        text = egp.load_egp(make_egp(self.dir, xml)).tasks['A-aaaaaaaaaaaaaaaa'].code
        self.assertEqual(text.split('\n'), ['%let pre=1;', 'proc sql; quit;', '%let post=1;'])
        self.assertNotIn('ODS _ALL_ CLOSE', text)

    def test_flow_detected_by_pfd_child_not_type_name(self):
        xml = project_xml([
            flow('Anything-1', 'SomeFutureFlowType', 'F', [('T-aaaaaaaaaaaaaaaa', [])]),
            task('T-aaaaaaaaaaaaaaaa', 'CodeTask', 'Anything-1'),
            code('C', 'T-aaaaaaaaaaaaaaaa', 'data a; run;'),
        ])
        p = egp.load_egp(make_egp(self.dir, xml))
        self.assertEqual([f.label for f in p.flows], ['F'])

    def test_multiple_flows_and_no_flow(self):
        xml = project_xml([
            flow('F1', 'PFD', 'One', [('A-aaaaaaaaaaaaaaaa', [])]),
            flow('F2', 'PFD', 'Two', [('B-bbbbbbbbbbbbbbbb', [])]),
            task('A-aaaaaaaaaaaaaaaa', 'CodeTask', 'F1'), task('B-bbbbbbbbbbbbbbbb', 'CodeTask', 'F2'),
            code('C1', 'A-aaaaaaaaaaaaaaaa', 'data a; run;'), code('C2', 'B-bbbbbbbbbbbbbbbb', 'data b; run;'),
        ])
        p = egp.load_egp(make_egp(self.dir, xml))
        self.assertEqual({t.flow_id for t in p.tasks.values()}, {'F1', 'F2'})

        no_flow = project_xml([task('A-aaaaaaaaaaaaaaaa', 'CodeTask', ''),
                               code('C1', 'A-aaaaaaaaaaaaaaaa', 'data a; run;')])
        p = egp.load_egp(make_egp(self.dir, no_flow, name='nf.egp'))
        self.assertEqual(p.flows[0].id, egp.UNASSIGNED_FLOW_ID)
        self.assertTrue(any('no process flow' in w for w in p.warnings))

    def test_link_elements_merged_and_deduplicated(self):
        xml = project_xml([
            flow('F', 'PFD', 'Flow', [('A-aaaaaaaaaaaaaaaa', []),
                                      ('B-bbbbbbbbbbbbbbbb', [('A-aaaaaaaaaaaaaaaa', None)])]),
            task('A-aaaaaaaaaaaaaaaa', 'CodeTask', 'F'), task('B-bbbbbbbbbbbbbbbb', 'CodeTask', 'F'),
            task('D-dddddddddddddddd', 'CodeTask', 'F'),
            code('C1', 'A-aaaaaaaaaaaaaaaa', 'x;'), code('C2', 'B-bbbbbbbbbbbbbbbb', 'y;'),
            code('C3', 'D-dddddddddddddddd', 'z;'),
            link('L1', 'F', 'A-aaaaaaaaaaaaaaaa', 'B-bbbbbbbbbbbbbbbb'),
            link('L2', 'F', 'B-bbbbbbbbbbbbbbbb', 'D-dddddddddddddddd'),
        ])
        p = egp.load_egp(make_egp(self.dir, xml))
        pairs = [(e.src, e.dst, e.kind) for e in p.flows[0].edges]
        self.assertEqual(len(pairs), 2)
        self.assertIn(('B-bbbbbbbbbbbbbbbb', 'D-dddddddddddddddd', egp.EdgeKind.LINK), pairs)
        self.assertEqual(p.flows[0].task_order[-1], 'D-dddddddddddddddd')

    def test_task_edges_collapse_through_non_code_nodes(self):
        xml = project_xml([
            flow('F', 'PFD', 'Flow', [('A-aaaaaaaaaaaaaaaa', []), ('Data-1', [('A-aaaaaaaaaaaaaaaa', 'true')]),
                                      ('B-bbbbbbbbbbbbbbbb', [('Data-1', 'true')])]),
            task('A-aaaaaaaaaaaaaaaa', 'CodeTask', 'F'), task('B-bbbbbbbbbbbbbbbb', 'Query', 'F'),
            code('C1', 'A-aaaaaaaaaaaaaaaa', 'x;'), code('C2', 'B-bbbbbbbbbbbbbbbb', 'y;'),
        ], data_list='<Data><Label>OUT</Label><ID>Data-1</ID>'
                     '<DataSourceState>\x7f\x7fMYLIB\x7fOUT</DataSourceState></Data>')
        p = egp.load_egp(make_egp(self.dir, xml))
        self.assertEqual(p.task_edges(), {('A-aaaaaaaaaaaaaaaa', 'B-bbbbbbbbbbbbbbbb')})
        self.assertEqual(p.nodes['Data-1'].label, 'MYLIB.OUT')

    def test_taskcode_preferred_zip_fallback_and_stale_entries(self):
        xml = project_xml([
            flow('F', 'PFD', 'Flow', [('A-aaaaaaaaaaaaaaaa', []), ('B-bbbbbbbbbbbbbbbb', [])]),
            task('A-aaaaaaaaaaaaaaaa', 'CodeTask', 'F'), task('B-bbbbbbbbbbbbbbbb', 'CodeTask', 'F'),
            code('C1', 'A-aaaaaaaaaaaaaaaa', 'data from_xml; run;'),
        ])
        entries = {
            'A-aaaaaaaaaaaaaaaa/code.sas': b'data from_xml; run;',
            'repo/PFD-x/B-bbbbbbbbbbbbbbbb/code.sas': b'\xef\xbb\xbfdata from_zip;\r\nrun;',
            'repo/PFD-x/Gone-zzzzzzzzzzzzzzzz/code.sas': b'data stale; run;',
        }
        p = egp.load_egp(make_egp(self.dir, xml, extra_entries=entries))
        self.assertEqual(p.tasks['A-aaaaaaaaaaaaaaaa'].code_source, egp.CodeSource.PROJECT_XML)
        self.assertEqual(p.tasks['B-bbbbbbbbbbbbbbbb'].code_source, egp.CodeSource.ZIP_ENTRY)
        self.assertEqual(p.tasks['B-bbbbbbbbbbbbbbbb'].code, 'data from_zip;\nrun;')
        self.assertEqual(p.orphaned_zip_code, ['repo/PFD-x/Gone-zzzzzzzzzzzzzzzz/code.sas'])
        written = egp.write_project(p, self.dir / 'out', 'proj')
        self.assertFalse(any('stale' in w.read_text() for w in written))

    def test_cycle_warns_and_keeps_all_tasks(self):
        xml = project_xml([
            flow('F', 'PFD', 'Flow', [('A-aaaaaaaaaaaaaaaa', [('B-bbbbbbbbbbbbbbbb', None)]),
                                      ('B-bbbbbbbbbbbbbbbb', [('A-aaaaaaaaaaaaaaaa', None)])]),
            task('A-aaaaaaaaaaaaaaaa', 'CodeTask', 'F'), task('B-bbbbbbbbbbbbbbbb', 'CodeTask', 'F'),
            code('C1', 'A-aaaaaaaaaaaaaaaa', 'x;'), code('C2', 'B-bbbbbbbbbbbbbbbb', 'y;'),
        ])
        p = egp.load_egp(make_egp(self.dir, xml))
        self.assertEqual(len(p.flows[0].task_order), 2)
        self.assertTrue(any('cycle' in w for w in p.warnings))

    def test_unknown_elements_and_dangling_refs_tolerated(self):
        xml = project_xml([
            flow('F', 'PFD', 'Flow', [('A-aaaaaaaaaaaaaaaa', [('Missing-1', None)])]),
            task('A-aaaaaaaaaaaaaaaa', 'CodeTask', 'F'),
            code('C1', 'A-aaaaaaaaaaaaaaaa', 'x;'),
            f'<Element Type="{NS}HologramWidget">{_header("H-1", "h", "WIDGET")}<Stuff/></Element>',
            '<Element Type="NoHeader"/>',
        ])
        p = egp.load_egp(make_egp(self.dir, xml))
        self.assertEqual(len(p.code_tasks()), 1)
        self.assertTrue(any('Missing-1' in w for w in p.warnings))

    def test_output_hints_and_run_lists(self):
        xml = project_xml([simple_project().split('<Elements>')[1].split('</Elements>')[0],
                           '<Element Type="x.OrderedList"><Element><Label>Nightly</Label><Type>OrderList</Type></Element>'
                           '<ORDERLIST><TASKIDLIST><TASKID>Prog-aaaaaaaaaaaaaaaa</TASKID></TASKIDLIST></ORDERLIST></Element>'])
        p = egp.load_egp(make_egp(self.dir, xml))
        self.assertEqual(p.tasks['Export-cccccccccccccccc'].output_hints,
                         {'OUTPUTFILEPATHNAME': '/out/result.csv'})
        self.assertEqual([(r.label, r.task_ids) for r in p.run_lists], [('Nightly', ['Prog-aaaaaaaaaaaaaaaa'])])

    def test_written_files_are_safe_and_session_grouped(self):
        xml = project_xml([
            flow('F', 'PFD', 'Flow */ &amp; ../../x', [('../../evil-aaaaaaaaaaaaaaaa', [])]),
            task('../../evil-aaaaaaaaaaaaaaaa', 'CodeTask', 'F', label='bad */ label'),
            code('C1', '../../evil-aaaaaaaaaaaaaaaa', 'data a; run;'),
        ])
        out = self.dir / 'out'
        written = egp.write_project(egp.load_egp(make_egp(self.dir, xml)), out, 'proj')
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].parent, out)
        self.assertNotIn('*/ label', written[0].read_text().split('*/', 1)[0])
        manifest = json.loads((out / egp.MANIFEST_NAME).read_text())
        self.assertEqual(manifest['summary']['code_tasks'], 1)
        self.assertTrue((out / egp.MERMAID_NAME).read_text().startswith('flowchart'))

    def test_extracted_names_share_a_work_session(self):
        names = ['/o/p/proj__01001_CodeTask-aaaaaaaaaaaaaaaa.sas', '/o/p/proj__01002_Query-bbbbbbbbbbbbbbbb.sas']
        groups = DependencyTracker.session_groups(names)
        self.assertEqual(len(set(groups.values())), 1)

    def test_eg_generated_macro_is_not_a_block_or_macro(self):
        script = SASParser().parse('%_eg_conditional_dropds(WORK.X);\nPROC SQL;\n'
                                   'CREATE TABLE WORK.X AS SELECT * FROM LIB1.A;\nQUIT;\n')
        self.assertEqual([b.block_type.value for b in script.blocks], ['PROC_SQL'])
        self.assertEqual(script.macros, {})


class HeaderAndLibrefTests(unittest.TestCase):
    def test_provenance_header_not_counted_as_source_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = egp.load_egp(make_egp(Path(tmp), simple_project()))
            written = egp.write_project(project, Path(tmp) / 'out', 'proj')
            wizard = next(p for p in written if 'FancyWizardTask' in p.name)
            text, _ = read_sas_source(wizard)
            self.assertEqual(text, project.tasks['FancyWizardTask-bbbbbbbbbbbbbbbb'].code)
            self.assertEqual(SASParser().parse(text).total_lines, 4)

    def test_server_librefs_from_data_list(self):
        data = ('<Data><ID>D1</ID><DataSourceState>\x7f\x7fSAPLIB\x7fT1</DataSourceState></Data>'
                '<Data><ID>D2</ID><DataSourceState>\x7f\x7fWORK\x7fTMP</DataSourceState></Data>')
        with tempfile.TemporaryDirectory() as tmp:
            project = egp.load_egp(make_egp(Path(tmp), project_xml([], data_list=data)))
        self.assertEqual(project.server_librefs, ['SAPLIB'])
        tracker = DependencyTracker()
        inventory = tracker.build_source_inventory(
            {'f.sas': {'reads': ['SAPLIB.T1'], 'creates': [], 'external_sources': []}},
            {'SAPLIB': DependencyTracker.SERVER_LIBREF_ENGINE})
        self.assertEqual(inventory[0]['engine'], DependencyTracker.SERVER_LIBREF_ENGINE)

        coded = tracker.build_source_inventory(
            {'f.sas': {'reads': ['SAPLIB.T1'], 'creates': [], 'external_sources': [], 'librefs': ['SAPLIB']}},
            {'SAPLIB': DependencyTracker.SERVER_LIBREF_ENGINE})
        self.assertEqual(coded[0]['engine'], 'External SAS library')


class ArchiveSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_not_a_zip(self):
        path = self.dir / 'bad.egp'
        path.write_bytes(b'not a zip')
        with self.assertRaises(egp.EgpError):
            egp.load_egp(path)

    def test_missing_project_xml(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('other.txt', 'x')
        path = self.dir / 'empty.egp'
        path.write_bytes(buf.getvalue())
        with self.assertRaises(egp.EgpError):
            egp.load_egp(path)

    def test_size_limit(self):
        path = make_egp(self.dir, simple_project())
        original = egp.MAX_TOTAL_UNCOMPRESSED_BYTES
        egp.MAX_TOTAL_UNCOMPRESSED_BYTES = 10
        try:
            with self.assertRaises(egp.EgpError):
                egp.load_egp(path)
        finally:
            egp.MAX_TOTAL_UNCOMPRESSED_BYTES = original


class CliTests(unittest.TestCase):
    def test_directory_with_good_and_corrupt_egp(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'src'
            src.mkdir()
            make_egp(src, simple_project(), name='good.egp')
            (src / 'broken.egp').write_bytes(b'garbage')
            out = Path(tmp) / 'out'
            run = subprocess.run([sys.executable, str(TOOL_DIR / 'assess_sas.py'), str(src), '-o', str(out),
                                  '--format', 'json'], capture_output=True, text=True, cwd=TOOL_DIR, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            assessment = json.loads((out / 'assessment.json').read_text())
            section = assessment['egp_projects']
            self.assertEqual(len(section['projects']), 1)
            self.assertEqual(len(section['failed']), 1)
            self.assertEqual(assessment['metadata']['total_files'], 2)
            self.assertEqual(sum(1 for _ in (out / 'egp_extracted' / 'good').glob('*.sas')), 2)


if __name__ == '__main__':
    unittest.main()
