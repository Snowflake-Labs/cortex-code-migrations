import re
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
from .parser import SASScript, SASBlock, BlockType


class DependencyTracker:

    EXTERNAL_LIBRARIES = {
        'oracle', 'teradata', 'db2', 'sqlsvr', 'odbc', 'oledb',
        'hadoop', 'spark', 'redshift', 'snowflake', 'postgres', 'mysql', 'mssql',
    }

    # Librefs that are local scratch or SAS-supplied metadata, never a data source.
    LOCAL_LIBREFS = {'WORK', 'SWORK'}
    SYSTEM_LIBREFS = {'DICTIONARY', 'SASHELP', 'SASUSER', 'MAPS', 'MAPSGFK', 'MAPSSAS'}
    _LIBREF_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

    def analyze_file(self, script: SASScript) -> Dict:
        creates: Set[str] = set()
        reads: Set[str] = set()
        external_sources: List[Dict] = []

        for block in script.blocks:
            md = block.metadata
            for ds in md.get('output_datasets', []):
                creates.add(self._normalize_dataset(ds))
            for ds in md.get('input_datasets', []):
                reads.add(self._normalize_dataset(ds))

        for lib_name, lib_path in script.libraries.items():
            path_lower = lib_path.lower()
            for engine in self.EXTERNAL_LIBRARIES:
                if engine in path_lower or engine in lib_name.lower():
                    external_sources.append({
                        'libname': lib_name,
                        'engine': engine,
                        'path': lib_path,
                    })
                    break

        full_content = '\n'.join(b.content for b in script.blocks).lower()
        connect_pattern = r'connect\s+to\s+(\w+)'
        for match in re.finditer(connect_pattern, full_content):
            engine = match.group(1)
            if engine in self.EXTERNAL_LIBRARIES:
                external_sources.append({
                    'libname': 'PASSTHROUGH',
                    'engine': engine,
                    'path': f'CONNECT TO {engine}',
                })

        return {
            'creates': sorted(creates),
            'reads': sorted(reads),
            'external_sources': external_sources,
            'librefs': sorted(script.libraries),
        }

    def is_shared(self, dataset: str) -> bool:
        """True if a dataset can be seen by another file (a permanent libref).

        WORK / SWORK and unqualified names live in the session's scratch library,
        so the same name in two files is two different tables — never an edge.
        """
        if '.' not in dataset:
            return False
        lib = dataset.split('.', 1)[0].upper()
        return lib not in self.LOCAL_LIBREFS and lib not in self.SYSTEM_LIBREFS

    @staticmethod
    def _has_macro_ref(dataset: str) -> bool:
        return '&' in dataset or '%' in dataset

    # Tasks extracted from one Enterprise Guide project run in ONE SAS session,
    # so they genuinely share WORK. Names look like ``Query-3TRomiOYpuoBdSZB.sas``,
    # or ``<project>__07_Query-3TRomiOYpuoBdSZB.sas`` when written by egp_extractor.
    _EGP_TASK_RE = re.compile(r'^(?:.+__\d+_)?(?:CodeTask|Query|ImportTask|ExportTask|Program|Task)-[A-Za-z0-9]{16}\.sas$', re.I)

    @classmethod
    def session_groups(cls, paths, overrides: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """filename -> session key. EGP task files in the same folder share one
        session; every other file is its own session. ``overrides`` (filename ->
        key) wins, e.g. for files extracted from one ``.egp`` project."""
        groups = {Path(p).name: (str(Path(p).parent) if cls._EGP_TASK_RE.match(Path(p).name) else Path(p).name)
                  for p in paths}
        groups.update(overrides or {})
        return groups

    EXPLICIT_EDGE_VIA = 'egp_flow'

    @classmethod
    def merge_explicit_edges(cls, graph: Dict, explicit: List[Tuple[str, str]],
                             scope: Optional[Dict[str, str]] = None) -> Dict:
        """Add declared orchestration edges not implied by a shared dataset (``via=egp_flow``).
        Returns ``agreed`` / ``flow_only`` / ``inferred_only``; the last is limited to one ``scope``
        group and flags dataset handoffs the author never linked in the flow."""
        nodes = set(graph['nodes'])
        inferred = {(e['from'], e['to']) for e in graph['edges']}
        declared = {(a, b) for a, b in explicit if a in nodes and b in nodes and a != b}
        for src, dst in sorted(declared - inferred):
            graph['edges'].append({'from': src, 'to': dst, 'via': cls.EXPLICIT_EDGE_VIA, 'source': cls.EXPLICIT_EDGE_VIA})
        scope = scope or {}
        inferred_only = sorted(
            (a, b) for a, b in inferred - declared
            if a in scope and scope.get(a) == scope.get(b))
        return {
            'agreed': len(declared & inferred),
            'flow_only': [{'from': a, 'to': b} for a, b in sorted(declared - inferred)],
            'inferred_only': [{'from': a, 'to': b} for a, b in inferred_only],
        }

    def build_cross_file_graph(self, file_analyses: Dict[str, Dict],
                               sessions: Optional[Dict[str, str]] = None) -> Dict:
        """Cross-file edges over shared datasets; WORK/unqualified names link
        only files in the same SAS session (see ``session_groups``)."""
        sessions = sessions or {}
        session_of = lambda f: sessions.get(f, f)  # noqa: E731
        nodes = list(file_analyses.keys())
        edges: List[Dict] = []
        all_creates: Dict[str, str] = {}
        local_creates: Dict[Tuple[str, str], str] = {}

        for filename, analysis in file_analyses.items():
            for dataset in analysis['creates']:
                if self.is_shared(dataset):
                    all_creates[dataset] = filename
                elif session_of(filename) != filename:
                    local_creates[(session_of(filename), self._local_key(dataset))] = filename

        for filename, analysis in file_analyses.items():
            for dataset in analysis['reads']:
                if self.is_shared(dataset):
                    creator = all_creates.get(dataset)
                else:
                    creator = local_creates.get((session_of(filename), self._local_key(dataset)))
                if creator and creator != filename:
                    edges.append({
                        'from': creator,
                        'to': filename,
                        'via': dataset,
                    })

        # External inputs: shared datasets read but created nowhere in scope.
        # Names built from macro variables cannot be resolved statically; count
        # them separately instead of listing them as tables.
        external_inputs = set()
        macro_refs = set()
        for filename, analysis in file_analyses.items():
            for dataset in analysis['reads']:
                if not self.is_shared(dataset) or dataset in all_creates:
                    continue
                if self._has_macro_ref(dataset):
                    macro_refs.add(dataset)
                else:
                    external_inputs.add(dataset)

        return {
            'nodes': nodes,
            'edges': edges,
            'external_inputs': sorted(external_inputs),
            'unresolvable_macro_reference_count': len(macro_refs),
        }

    @staticmethod
    def _local_key(dataset: str) -> str:
        """``WORK.X`` and ``X`` are the same session table."""
        return dataset.split('.', 1)[1] if dataset.upper().startswith(('WORK.', 'SWORK.')) else dataset

    def build_output_tables(self, file_analyses: Dict[str, Dict]) -> List[str]:
        """Shared datasets created in scope that no file in scope reads."""
        created = set()
        read = set()
        for analysis in file_analyses.values():
            created.update(d for d in analysis['creates'] if self.is_shared(d) and not self._has_macro_ref(d))
            read.update(analysis['reads'])
        return sorted(created - read)

    SERVER_LIBREF_ENGINE = 'Defined on SAS server (Enterprise Guide)'

    def build_source_inventory(self, file_analyses: Dict[str, Dict],
                               engine_hints: Optional[Dict[str, str]] = None) -> List[Dict]:
        """Aggregate qualified external libraries into a source inventory.

        One row per non-local libref (e.g. OWDATA, SFNGGRE) with its table count
        and read/write direction. Local WORK, unqualified, and SAS metadata
        librefs are dropped — they are scratch, not data sources.
        """
        engine_by_lib: Dict[str, str] = {}
        defined_in_code: Set[str] = set()
        for analysis in file_analyses.values():
            defined_in_code.update(analysis.get('librefs', []))
            for src in analysis.get('external_sources', []):
                engine_by_lib[src['libname'].upper()] = src['engine']
        hints = {k: v for k, v in (engine_hints or {}).items() if k not in defined_in_code}

        reads_by_lib: Dict[str, Set[str]] = {}
        writes_by_lib: Dict[str, Set[str]] = {}
        for analysis in file_analyses.values():
            for ds in analysis.get('reads', []):
                lib, table = self._split_libref(ds)
                if lib:
                    reads_by_lib.setdefault(lib, set()).add(table)
            for ds in analysis.get('creates', []):
                lib, table = self._split_libref(ds)
                if lib:
                    writes_by_lib.setdefault(lib, set()).add(table)

        inventory: List[Dict] = []
        for lib in set(reads_by_lib) | set(writes_by_lib):
            if lib in self.LOCAL_LIBREFS or lib in self.SYSTEM_LIBREFS:
                continue
            if not self._LIBREF_RE.match(lib):
                continue
            rd = reads_by_lib.get(lib, set())
            wr = writes_by_lib.get(lib, set())
            direction = 'Read + Write' if rd and wr else ('Read' if rd else 'Write')
            inventory.append({
                'source': lib,
                'engine': engine_by_lib.get(lib) or hints.get(lib, 'External SAS library'),
                'tables': len(rd | wr),
                'direction': direction,
                'table_names': sorted(rd | wr),
            })

        inventory.sort(key=lambda r: (-r['tables'], r['source']))
        return inventory

    def _split_libref(self, name: str):
        if '.' not in name:
            return None, name
        lib, _, table = name.partition('.')
        return lib.upper().strip(), table.strip()

    def generate_mermaid(self, graph: Dict) -> str:
        lines = ['graph LR']

        node_ids = {}
        for i, node in enumerate(graph['nodes']):
            node_id = f'F{i}'
            node_ids[node] = node_id
            safe_label = node.replace('.sas', '').replace(' ', '_')
            lines.append(f'    {node_id}["{safe_label}"]')

        for ext in graph.get('external_inputs', [])[:20]:
            ext_id = f'EXT_{ext.replace(".", "_").replace(" ", "")}'
            lines.append(f'    {ext_id}[("{ext}")]')

        for edge in graph['edges']:
            from_id = node_ids.get(edge['from'], '')
            to_id = node_ids.get(edge['to'], '')
            if from_id and to_id:
                lines.append(f'    {from_id} -->|"{edge["via"]}"| {to_id}')

        for ext in graph.get('external_inputs', [])[:20]:
            ext_id = f'EXT_{ext.replace(".", "_").replace(" ", "")}'
            for filename, analysis in []:
                pass

        return '\n'.join(lines)

    def generate_mermaid_with_externals(self, graph: Dict, file_analyses: Dict[str, Dict]) -> str:
        lines = ['graph LR']

        node_ids = {}
        for i, node in enumerate(graph['nodes']):
            node_id = f'F{i}'
            node_ids[node] = node_id
            safe_label = node.replace('.sas', '').replace(' ', '_')
            lines.append(f'    {node_id}["{safe_label}"]')

        ext_node_ids = {}
        for i, ext in enumerate(graph.get('external_inputs', [])[:20]):
            ext_id = f'EXT{i}'
            ext_node_ids[ext] = ext_id
            lines.append(f'    {ext_id}[("{ext}")]')

        for edge in graph['edges']:
            from_id = node_ids.get(edge['from'], '')
            to_id = node_ids.get(edge['to'], '')
            if from_id and to_id:
                lines.append(f'    {from_id} -->|"{edge["via"]}"| {to_id}')

        for filename, analysis in file_analyses.items():
            file_id = node_ids.get(filename, '')
            if not file_id:
                continue
            for dataset in analysis['reads']:
                if dataset in ext_node_ids:
                    lines.append(f'    {ext_node_ids[dataset]} --> {file_id}')

        return '\n'.join(lines)

    def _normalize_dataset(self, name: str) -> str:
        clean = re.sub(r'\([^)]*\)', '', name).strip()
        # ``data=lib.x;`` / ``out=lib.y)`` captures carry statement punctuation.
        clean = clean.rstrip(';),').strip("'\"")
        return clean.upper()
