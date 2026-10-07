"""Extract SAS code and process flows from Enterprise Guide ``.egp`` projects.

Structural rules (flow = any item with ``<PFD>``, code = ``TaskCode`` by ``Parent``)
keep it version-independent; see ``tool/README.md``. Stdlib only.
"""

import json
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .source_io import EGP_HEADER_MARKER, normalise_newlines

PROJECT_XML = 'project.xml'
ZIP_CODE_FILE = 'code.sas'
MAX_PROJECT_XML_BYTES = 256 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_CODE_ENTRY_BYTES = 64 * 1024 * 1024
TASK_HEADER_TYPE = 'TASK'
DATA_SOURCE_SEPARATOR = '\x7f'
UNASSIGNED_FLOW_ID = '_unassigned'
UNASSIGNED_FLOW_LABEL = 'Not in a process flow'
MANIFEST_NAME = 'egp_manifest.json'
MERMAID_NAME = 'egp_flow.mmd'
SESSION_LIBREFS = frozenset({'WORK', 'SASUSER', 'SASHELP'})
USER_CODE_TAGS = ('BeginUserCode', 'TaskCode', 'EndUserCode')

_XML_DECL_RE = re.compile(r'^\s*<\?xml[^>]*\?>', re.S)
_FORBIDDEN_XML_RE = re.compile(r'<!(?:DOCTYPE|ENTITY)', re.I)
_UNSAFE_NAME_RE = re.compile(r'[^A-Za-z0-9._-]+')
_OUTPUT_HINT_RE = re.compile(r'OUTPUT.*(?:FILE|PATH)|(?:FILE|PATH).*OUTPUT', re.I)
MAX_OUTPUT_HINTS = 6
MAX_HINT_CHARS = 400


class EgpError(Exception):
    """The file is not a readable Enterprise Guide project."""


class CodeSource(str, Enum):
    PROJECT_XML = 'project_xml'
    ZIP_ENTRY = 'zip_entry'
    NONE = 'none'


class EdgeKind(str, Enum):
    FLOW = 'flow'
    LINK = 'link'


@dataclass
class EgpTask:
    id: str
    element_type: str
    label: str
    flow_id: str
    code_source: CodeSource
    input_ids: List[str] = field(default_factory=list)
    output_hints: Dict[str, str] = field(default_factory=dict)
    sas_file: Optional[str] = None
    code: Optional[str] = field(default=None, repr=False)

    @property
    def has_code(self) -> bool:
        return bool(self.code and self.code.strip())


@dataclass
class EgpEdge:
    src: str
    dst: str
    kind: EdgeKind
    resource_dependency: Optional[bool] = None


@dataclass
class EgpFlow:
    id: str
    label: str
    node_ids: List[str] = field(default_factory=list)
    task_order: List[str] = field(default_factory=list)
    edges: List[EgpEdge] = field(default_factory=list)
    schedules: List[str] = field(default_factory=list)


@dataclass
class EgpNode:
    """A non-task item that appears in a flow (data, file, note, ...)."""
    id: str
    element_type: str
    label: str


@dataclass
class RunList:
    label: str
    task_ids: List[str]


@dataclass
class EgpProject:
    source: str
    eg_versions: List[str] = field(default_factory=list)
    flows: List[EgpFlow] = field(default_factory=list)
    tasks: Dict[str, EgpTask] = field(default_factory=dict)
    nodes: Dict[str, EgpNode] = field(default_factory=dict)
    run_lists: List[RunList] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    orphaned_zip_code: List[str] = field(default_factory=list)
    # Librefs the project's datasets live in; EG assigns them on the SAS server, not in code.
    server_librefs: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def code_tasks(self) -> List[EgpTask]:
        return [t for t in self.tasks.values() if t.has_code]

    def no_code_tasks(self) -> List[EgpTask]:
        return [t for t in self.tasks.values() if not t.has_code]

    def task_edges(self) -> Set[Tuple[str, str]]:
        """Code-task -> code-task edges, collapsing paths through non-code nodes
        (datasets, exports, shortcuts) so they map onto extracted files."""
        result: Set[Tuple[str, str]] = set()
        for flow in self.flows:
            succ: Dict[str, List[str]] = {}
            for e in flow.edges:
                succ.setdefault(e.src, []).append(e.dst)
            for start in flow.task_order:
                if not self.tasks[start].has_code:
                    continue
                stack, seen = list(succ.get(start, [])), set()
                while stack:
                    node = stack.pop()
                    if node in seen or node == start:
                        continue
                    seen.add(node)
                    task = self.tasks.get(node)
                    if task is not None and task.has_code:
                        result.add((start, node))
                        continue
                    stack.extend(succ.get(node, []))
        return result


@dataclass
class _Item:
    element: ET.Element
    id: str
    element_type: str
    header_type: str
    label: str
    container: str
    input_ids: List[str]


# ---------------------------------------------------------------- reading


def decode_project_xml(raw: bytes) -> str:
    """Decode ``project.xml`` honouring a BOM; without one, infer UTF-16 byte
    order from where the NUL of the leading ``<`` falls, else assume UTF-8."""
    if raw.startswith(b'\xef\xbb\xbf'):
        return raw[3:].decode('utf-8')
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16')
    try:
        if raw[:2] == b'\x00<':
            return raw.decode('utf-16-be')
        if raw[:2] == b'<\x00':
            return raw.decode('utf-16-le')
        return raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise EgpError(f'project.xml has an unsupported encoding: {exc}') from exc


def parse_project_xml(text: str) -> ET.Element:
    if _FORBIDDEN_XML_RE.search(text):
        raise EgpError('project.xml declares a DOCTYPE/ENTITY; refusing to parse')
    try:
        return ET.fromstring(_XML_DECL_RE.sub('', text, count=1))
    except ET.ParseError as exc:
        raise EgpError(f'project.xml is not well-formed XML: {exc}') from exc


def _open_archive(path: Path) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise EgpError(f'not a readable .egp (ZIP) archive: {exc}') from exc
    if sum(info.file_size for info in archive.infolist()) > MAX_TOTAL_UNCOMPRESSED_BYTES:
        archive.close()
        raise EgpError('archive exceeds the uncompressed size limit')
    return archive


def _find_project_xml(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    candidates = [i for i in archive.infolist()
                  if i.filename.replace('\\', '/').split('/')[-1].lower() == PROJECT_XML]
    if not candidates:
        raise EgpError('archive has no project.xml')
    info = min(candidates, key=lambda i: i.filename.count('/'))
    if info.file_size > MAX_PROJECT_XML_BYTES:
        raise EgpError('project.xml exceeds the size limit')
    return info


def _text(node: Optional[ET.Element], path: str) -> str:
    if node is None:
        return ''
    return (node.findtext(path) or '').strip()


def _version_key(version: str) -> Tuple:
    return tuple(int(p) if p.isdigit() else -1 for p in version.split('.'))


def _index_items(root: ET.Element) -> Dict[str, _Item]:
    items: Dict[str, _Item] = {}
    for element in root.iter('Element'):
        element_type = element.get('Type')
        header = element.find('Element')
        if not element_type or header is None:
            continue
        item_id = _text(header, 'ID')
        if not item_id or item_id in items:
            continue
        items[item_id] = _Item(
            element=element,
            id=item_id,
            element_type=element_type.rsplit('.', 1)[-1],
            header_type=_text(header, 'Type').upper(),
            label=_text(header, 'Label') or item_id,
            container=_text(header, 'Container'),
            input_ids=[i.strip() for i in _text(header, 'InputIDs').split(',') if i.strip()],
        )
    return items


def _index_shortcuts(root: ET.Element) -> Dict[str, str]:
    """Shortcut / data / file id -> human-readable name (``LIB.TABLE`` or file label)."""
    resolved: Dict[str, str] = {}
    for list_tag in ('DataList', 'ExternalFileList'):
        container = root.find(list_tag)
        if container is None:
            continue
        for entry in container:
            name = _data_source_name(entry) if list_tag == 'DataList' else _file_name(entry)
            for key in (_text(entry, './/ShortCutID'), _text(entry, './/ID')):
                if key and name:
                    resolved.setdefault(key, name)
    return resolved


def _data_source_name(entry: ET.Element) -> str:
    state = _text(entry, './/DataSourceState') or _text(entry, './/ActiveDataSource')
    parts = [p for p in state.split(DATA_SOURCE_SEPARATOR) if p.strip()]
    if len(parts) >= 2:
        return f'{parts[-2]}.{parts[-1]}'
    return _text(entry, './/Label') or (parts[-1] if parts else '')


def _data_list_librefs(root: ET.Element) -> List[str]:
    container = root.find('DataList')
    librefs: Set[str] = set()
    for entry in (container if container is not None else []):
        state = _text(entry, './/DataSourceState') or _text(entry, './/ActiveDataSource')
        parts = [p for p in state.split(DATA_SOURCE_SEPARATOR) if p.strip()]
        if len(parts) >= 2 and parts[-2].upper() not in SESSION_LIBREFS:
            librefs.add(parts[-2].upper())
    return sorted(librefs)


def _file_name(entry: ET.Element) -> str:
    label = _text(entry, './/Label')
    file_type = _text(entry, './/FileTypeType')
    return f'{label} ({file_type})' if label and file_type else label


def _collect_code(items: Dict[str, _Item], warnings: List[str]) -> Dict[str, str]:
    """Owner task id -> code. ``Parent`` is a sibling of ``TaskCode``; user pre/post-code
    (``BeginUserCode`` / ``EndUserCode``) is kept, EG's ``*AppCode`` wrappers are not."""
    code: Dict[str, str] = {}
    for item in items.values():
        for block in item.element.iter():
            task_code = block.find('TaskCode')
            if task_code is None:
                continue
            owner = _text(block, 'Parent')
            if not owner:
                warnings.append(f'{item.id}: TaskCode without a Parent task; skipped')
                continue
            parts = [(block.findtext(tag) or '') for tag in USER_CODE_TAGS]
            text = '\n'.join(p for p in parts if p.strip())
            if text.strip() and owner not in code:
                code[owner] = normalise_newlines(text)[0]
    return code


def _zip_code_entries(archive: zipfile.ZipFile) -> Dict[str, zipfile.ZipInfo]:
    """Task id (parent folder name) -> ``code.sas`` entry."""
    entries: Dict[str, zipfile.ZipInfo] = {}
    for info in archive.infolist():
        parts = info.filename.replace('\\', '/').split('/')
        if len(parts) >= 2 and parts[-1].lower() == ZIP_CODE_FILE:
            entries.setdefault(parts[-2], info)
    return entries


def _read_zip_code(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    if info.file_size > MAX_CODE_ENTRY_BYTES:
        raise EgpError(f'{info.filename} exceeds the size limit')
    raw = archive.read(info)
    return normalise_newlines(raw.decode('utf-8-sig', errors='replace'))[0]


def _output_hints(element: ET.Element) -> Dict[str, str]:
    hints: Dict[str, str] = {}
    for node in element.iter():
        text = (node.text or '').strip()
        if text and len(text) <= MAX_HINT_CHARS and _OUTPUT_HINT_RE.search(node.tag):
            hints.setdefault(node.tag, text)
            if len(hints) >= MAX_OUTPUT_HINTS:
                break
    return hints


# ---------------------------------------------------------------- flow graph


def _flow_items(items: Dict[str, _Item]) -> List[_Item]:
    return [i for i in items.values() if i.element.find('PFD') is not None]


def _flow_processes(flow: _Item) -> List[Tuple[str, List[Tuple[str, Optional[bool]]]]]:
    processes = []
    for process in flow.element.find('PFD').findall('Process'):
        node_id = _text(process, 'Element/ID')
        if not node_id:
            continue
        deps = []
        for dep in process.findall('Dependencies/DepID'):
            if dep.text and dep.text.strip():
                flag = dep.get('ResourceDependency')
                deps.append((dep.text.strip(), None if flag is None else flag.lower() == 'true'))
        processes.append((node_id, deps))
    return processes


def _link_edges(items: Dict[str, _Item]) -> Iterable[Tuple[str, str]]:
    for item in items.values():
        src = _text(item.element, './/LinkFrom')
        dst = _text(item.element, './/LinkTo')
        if src and dst:
            yield src, dst


def topo_order(nodes: List[str], edges: Iterable[Tuple[str, str]]) -> Tuple[List[str], bool]:
    """Kahn's algorithm; ties broken by input order. Returns ``(order, had_cycle)``."""
    position = {n: i for i, n in enumerate(nodes)}
    indegree = {n: 0 for n in nodes}
    succ: Dict[str, List[str]] = {n: [] for n in nodes}
    for src, dst in edges:
        if src in position and dst in position and src != dst:
            succ[src].append(dst)
            indegree[dst] += 1
    ready = sorted((n for n in nodes if indegree[n] == 0), key=position.get)
    order: List[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for nxt in succ[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
        ready.sort(key=position.get)
    had_cycle = len(order) < len(nodes)
    if had_cycle:
        order.extend(n for n in nodes if n not in set(order))
    return order, had_cycle


# ---------------------------------------------------------------- public API


def load_egp(path: Path) -> EgpProject:
    """Parse an ``.egp`` into an :class:`EgpProject` (no files written)."""
    project = EgpProject(source=str(path))
    with _open_archive(path) as archive:
        root = parse_project_xml(decode_project_xml(archive.read(_find_project_xml(archive))))
        items = _index_items(root)
        shortcuts = _index_shortcuts(root)
        code = _collect_code(items, project.warnings)
        zip_code = _zip_code_entries(archive)

        project.eg_versions = sorted({v.text.strip() for v in root.iter('ModifiedByEGVer')
                                      if v.text and v.text.strip()}, key=_version_key)
        project.orphaned_zip_code = sorted(zip_code[k].filename for k in zip_code if k not in items)
        project.server_librefs = _data_list_librefs(root)

        flows = _flow_items(items)
        if not flows:
            project.warnings.append('no process flow found; tasks kept in project order')
        flow_of: Dict[str, str] = {}
        for flow_item in flows:
            for node_id, _ in _flow_processes(flow_item):
                flow_of.setdefault(node_id, flow_item.id)

        for item in items.values():
            if item.header_type != TASK_HEADER_TYPE:
                continue
            task = EgpTask(
                id=item.id, element_type=item.element_type, label=item.label,
                flow_id=flow_of.get(item.id) or (item.container if item.container in
                                                 {f.id for f in flows} else UNASSIGNED_FLOW_ID),
                code_source=CodeSource.NONE, input_ids=item.input_ids,
            )
            if item.id in code:
                task.code, task.code_source = code[item.id], CodeSource.PROJECT_XML
                if item.id in zip_code and _read_zip_code(archive, zip_code[item.id]).strip() not in task.code:
                    project.warnings.append(f'{item.id}: project.xml TaskCode differs from ZIP code.sas; used project.xml')
            elif item.id in zip_code:
                task.code, task.code_source = _read_zip_code(archive, zip_code[item.id]), CodeSource.ZIP_ENTRY
                project.warnings.append(f'{item.id}: no TaskCode in project.xml; used ZIP {zip_code[item.id].filename}')
            if not task.has_code:
                task.output_hints = _output_hints(item.element)
            project.tasks[item.id] = task

    links = list(_link_edges(items))
    for flow_item in flows:
        project.flows.append(_build_flow(flow_item, items, shortcuts, links, project))
    unassigned = [t.id for t in project.tasks.values() if t.flow_id == UNASSIGNED_FLOW_ID]
    if unassigned:
        project.flows.append(EgpFlow(id=UNASSIGNED_FLOW_ID, label=UNASSIGNED_FLOW_LABEL,
                                     node_ids=list(unassigned), task_order=list(unassigned)))

    # Run lists: read from the raw XML, because some EG versions omit the ID in
    # an ordered list's header, so it never reaches the item index.
    for element in root.iter('Element'):
        order_list = element.find('ORDERLIST')
        if order_list is not None:
            ids = [t.text.strip() for t in order_list.iter('TASKID') if t.text and t.text.strip()]
            project.run_lists.append(RunList(label=_text(element, 'Element/Label') or 'Ordered list',
                                             task_ids=ids))
    for item in items.values():
        ref = _text(item.element, './/ReferenceElement')
        flow = next((f for f in project.flows if f.id == ref), None)
        if flow is not None and item.id != ref:
            flow.schedules.append(item.label)
        if item.element_type.lower() == 'note':
            project.notes.append(item.label)
    return project


def _build_flow(flow_item: _Item, items: Dict[str, _Item], shortcuts: Dict[str, str],
                links: List[Tuple[str, str]], project: EgpProject) -> EgpFlow:
    flow = EgpFlow(id=flow_item.id, label=flow_item.label)
    seen_edges: Set[Tuple[str, str]] = set()
    for node_id, deps in _flow_processes(flow_item):
        if node_id not in flow.node_ids:
            flow.node_ids.append(node_id)
        for dep_id, resource in deps:
            if (dep_id, node_id) not in seen_edges:
                seen_edges.add((dep_id, node_id))
                flow.edges.append(EgpEdge(dep_id, node_id, EdgeKind.FLOW, resource))
            if dep_id not in flow.node_ids:
                flow.node_ids.append(dep_id)
    members = set(flow.node_ids)
    for src, dst in links:
        if (src in members or dst in members) and (src, dst) not in seen_edges:
            seen_edges.add((src, dst))
            flow.edges.append(EgpEdge(src, dst, EdgeKind.LINK))
            for node in (src, dst):
                if node not in members:
                    members.add(node)
                    flow.node_ids.append(node)

    for node_id in flow.node_ids:
        if node_id in project.tasks or node_id in project.nodes:
            continue
        item = items.get(node_id)
        label = shortcuts.get(node_id) or (item.label if item else node_id)
        if item is None and node_id not in shortcuts:
            project.warnings.append(f'{flow.label}: flow node {node_id} not found in project')
        project.nodes[node_id] = EgpNode(id=node_id, element_type=item.element_type if item else 'Unknown',
                                         label=label)

    order, had_cycle = topo_order(flow.node_ids, seen_edges)
    if had_cycle:
        project.warnings.append(f'{flow.label}: cycle in process flow; remaining tasks kept in XML order')
    flow.task_order = [n for n in order if n in project.tasks and project.tasks[n].flow_id == flow.id]
    return flow


# ---------------------------------------------------------------- writing


def safe_name(value: str, limit: int = 60) -> str:
    cleaned = _UNSAFE_NAME_RE.sub('_', value).strip('._-')[:limit]
    return cleaned or 'unnamed'


def _comment_safe(value: str) -> str:
    return value.replace('*/', '* /').replace('\n', ' ')


def write_project(project: EgpProject, out_dir: Path, file_prefix: str) -> List[Path]:
    """Write one ``.sas`` per code task plus manifest and Mermaid; return the .sas paths.
    ``file_prefix`` must be unique per project: files are keyed by basename and task ids repeat."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    upstream: Dict[str, List[str]] = {}
    for flow in project.flows:
        for edge in flow.edges:
            upstream.setdefault(edge.dst, []).append(edge.src)

    # Files are written flat per project: every flow of one EG project runs in
    # the same SAS session (shared WORK), and DependencyTracker groups sessions
    # by folder. The numeric part (flow index + position) keeps run order.
    for flow_index, flow in enumerate(project.flows, start=1):
        for position, task_id in enumerate(flow.task_order, start=1):
            task = project.tasks[task_id]
            if not task.has_code:
                continue
            path = out_dir / f'{file_prefix}__{flow_index:02d}{position:03d}_{safe_name(task_id)}.sas'
            header = (
                f'{EGP_HEADER_MARKER} {_comment_safe(Path(project.source).name)}\n'
                f'   Process flow : {_comment_safe(flow.label)}\n'
                f'   Task         : {_comment_safe(task.label)} ({task.element_type}, {task_id})\n'
                f'   Upstream     : {_comment_safe(", ".join(upstream.get(task_id, [])) or "none")}\n*/\n'
            )
            path.write_text(header + task.code, encoding='utf-8')
            task.sas_file = str(path)
            written.append(path)

    (out_dir / MANIFEST_NAME).write_text(json.dumps(manifest(project), indent=2), encoding='utf-8')
    (out_dir / MERMAID_NAME).write_text(render_mermaid(project), encoding='utf-8')
    return written


def manifest(project: EgpProject) -> Dict:
    def task_dict(task: EgpTask) -> Dict:
        data = asdict(task)
        data.pop('code')
        data['code_source'] = task.code_source.value
        return data

    flows = []
    for flow in project.flows:
        data = asdict(flow)
        data['edges'] = [{**asdict(e), 'kind': e.kind.value} for e in flow.edges]
        flows.append(data)
    return {
        'source': project.source,
        'eg_versions': project.eg_versions,
        'summary': summary(project),
        'flows': flows,
        'tasks': [task_dict(t) for t in project.tasks.values()],
        'nodes': [asdict(n) for n in project.nodes.values()],
        'run_lists': [asdict(r) for r in project.run_lists],
        'notes': project.notes,
        'orphaned_zip_code': project.orphaned_zip_code,
        'warnings': project.warnings,
    }


def summary(project: EgpProject) -> Dict:
    by_type: Dict[str, int] = {}
    for task in project.tasks.values():
        by_type[task.element_type] = by_type.get(task.element_type, 0) + 1
    return {
        'flows': len([f for f in project.flows if f.id != UNASSIGNED_FLOW_ID]),
        'tasks': len(project.tasks),
        'tasks_by_type': dict(sorted(by_type.items())),
        'code_tasks': len(project.code_tasks()),
        'no_code_tasks': len(project.no_code_tasks()),
        'orphaned_zip_code': len(project.orphaned_zip_code),
        'warnings': len(project.warnings),
    }


def _mermaid_label(value: str) -> str:
    return value.replace('"', "'").replace('\n', ' ')[:60]


def render_mermaid(project: EgpProject) -> str:
    lines = ['flowchart LR']
    ids: Dict[str, str] = {}

    def node_ref(node_id: str) -> str:
        if node_id not in ids:
            ids[node_id] = f'n{len(ids)}'
        return ids[node_id]

    for index, flow in enumerate(project.flows):
        lines.append(f'  subgraph flow{index} ["{_mermaid_label(flow.label)}"]')
        for node_id in flow.node_ids:
            task = project.tasks.get(node_id)
            if task is not None:
                shape = ('["', '"]') if task.has_code else ('[/"', '"/]')
                text = f'{task.label} ({task.element_type})'
            else:
                node = project.nodes.get(node_id)
                shape, text = ('[("', '")]'), node.label if node else node_id
            lines.append(f'    {node_ref(node_id)}{shape[0]}{_mermaid_label(text)}{shape[1]}')
        lines.append('  end')
        for edge in flow.edges:
            arrow = '-.->' if edge.kind is EdgeKind.LINK else '-->'
            lines.append(f'  {node_ref(edge.src)} {arrow} {node_ref(edge.dst)}')
    return '\n'.join(lines) + '\n'


def extract_egp(path: Path, out_dir: Path, file_prefix: str) -> Tuple[EgpProject, List[Path]]:
    project = load_egp(path)
    return project, write_project(project, out_dir, file_prefix)
