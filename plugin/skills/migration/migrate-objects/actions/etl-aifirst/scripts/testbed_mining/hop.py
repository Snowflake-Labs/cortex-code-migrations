"""Apache Hop pipeline (.hpl) adapter.

Child-element XML: a transform's kind is the text of <type>, a hop's endpoints
are the text of <from>/<to>, and <enabled>N</enabled> is not a dataflow. The
document is the only source of facts. metadata/rdbms JSON is not read: a
<connection> name is recorded as context, not resolved into host or schema.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from testbed_mining import types as T
from testbed_mining.model import (
    Branch,
    ColumnRef,
    JoinEdge,
    MinedColumn,
    MinedPackage,
    MinedTable,
    MiningResult,
    PredicateNode,
    TableIdentity,
)
from testbed_mining.predicate import Dialect, decompose
from testbed_mining.sqltext import equi_joins, from_table, where_text

PLATFORM = "hop"
CONSTRUCT_KIND = "FILTER"
ROOT_TAGS = frozenset({"pipeline"})
FILE_TYPES = frozenset(
    {"TextFileInput", "TextFileInput2", "CSVFileInput", "CsvInput", "CSVInput"}
)
UNIQUE_TYPES = frozenset({"Unique", "UniqueRows"})
SCD_TYPES = frozenset({"DimensionLookup", "CombinationLookup"})
_NULL_FUNCS = {
    "IS NULL": "IS NULL",
    "ISNULL": "IS NULL",
    "IS NOT NULL": "IS NOT NULL",
    "ISNOTNULL": "IS NOT NULL",
}
_FLIP = {
    "=": "<>",
    "<>": "=",
    "!=": "=",
    "<": ">=",
    ">": "<=",
    "<=": ">",
    ">=": "<",
    "IS NULL": "IS NOT NULL",
    "IS NOT NULL": "IS NULL",
}

DIALECT = Dialect(
    comparisons={
        "=": "=",
        "<>": "<>",
        "!=": "<>",
        "<": "<",
        ">": ">",
        "<=": "<=",
        ">=": ">=",
    },
    and_tokens=frozenset({"AND"}),
    or_tokens=frozenset({"OR"}),
    string_quotes=('"', "'"),
)

_JOIN_TYPE = {
    "INNER": "inner",
    "LEFT OUTER": "left",
    "LEFT": "left",
    "RIGHT OUTER": "right",
    "RIGHT": "right",
    "FULL OUTER": "full",
    "FULL": "full",
}

_HOP_TYPES = {
    "Integer": ("NUMBER", T.INTEGER),
    "Number": ("FLOAT", T.NUMBER),
    "BigNumber": ("NUMBER", T.NUMBER),
    "String": ("VARCHAR", T.STRING),
    "Boolean": ("BOOLEAN", T.BOOLEAN),
    "Date": ("DATE", T.DATE),
    "Timestamp": ("TIMESTAMP", T.DATE),
    "Binary": ("BINARY", T.BINARY),
}


def sniff(path: str | Path) -> bool:
    try:
        for _, el in ET.iterparse(str(path), events=("start",)):
            tag = el.tag.rsplit("}", 1)[-1]
            return tag in ROOT_TAGS
    except (ET.ParseError, OSError):
        return False
    return False


def map_type(
    hop_type: str | None, length: str | None = None, precision: str | None = None
) -> T.TypeInfo:
    kind = _HOP_TYPES.get((hop_type or "").strip())
    n = int(length) if length and length.lstrip("-").isdigit() and int(length) > 0 else None
    p = (
        int(precision)
        if precision and precision.lstrip("-").isdigit() and int(precision) >= 0
        else None
    )
    if kind is None:
        return T.UNKNOWN
    name, cat = kind
    if cat == T.STRING:
        return T.make_type(name, cat, n)
    if cat == T.NUMBER and name == "NUMBER":
        return T.make_type(name, cat, n, p)
    if cat == T.INTEGER:
        return T.make_type(name, cat, n)
    return T.make_type(name, cat)


def _text(el: ET.Element | None, tag: str) -> str:
    if el is None:
        return ""
    child = el.find(tag)
    if child is None:
        return ""
    return (child.text or "").strip()


def _enabled(hop: ET.Element) -> bool:
    flag = _text(hop, "enabled")
    return flag.upper() != "N"


def _norm(name: str) -> str:
    return (name or "").strip().casefold()


def _fields(el: ET.Element) -> list[ET.Element]:
    return list(el.findall("fields/field"))


def _filename_stem(tr: "_Transform") -> str | None:
    file_el = tr.el.find("file")
    candidates = [
        tr.text("filename"),
        _text(file_el, "filemask"),
        _text(file_el, "name"),
        tr.text("file"),
    ]
    for raw in candidates:
        if not raw:
            continue
        base = re.split(r"[\\/]", raw)[-1]
        if not base or "${" in base or base.startswith("%%"):
            continue
        stem = re.sub(r"\.[^.]*$", "", base) if "." in base.lstrip(".") else base
        if stem:
            return stem
    return None


def _negate_node(node: PredicateNode) -> PredicateNode | None:
    if node.kind == "atom" and node.operator in _FLIP:
        return PredicateNode(
            kind="atom",
            columns=list(node.columns or []),
            operator=_FLIP[node.operator],
            values=list(node.values or []),
        )
    if node.kind in {"and", "or"}:
        kids = [_negate_node(c) for c in node.children or []]
        if any(k is None for k in kids):
            return None
        return PredicateNode(kind="or" if node.kind == "and" else "and", children=kids)
    return None


def _match_field(column: str, types: dict[str, T.TypeInfo]) -> str | None:
    if column in types:
        return column
    want = _norm(column)
    hits = [n for n in types if _norm(n) == want]
    if len(hits) == 1:
        return hits[0]
    if column.startswith("_") and len(column) > 1:
        return _match_field(column[1:], types)
    return None


@dataclass
class _Transform:
    name: str
    type: str
    el: ET.Element

    def text(self, tag: str) -> str:
        return _text(self.el, tag)


class HopMiner:
    def __init__(
        self,
        path: str | Path,
        object_name: str | None = None,
        ir: dict | None = None,
    ) -> None:
        self.path = Path(path)
        self.object_name = object_name or self.path.name
        self.ir = ir
        self.diagnostics: list[str] = []
        self.root = ET.parse(self.path).getroot()
        self.transforms: dict[str, _Transform] = {}
        for el in self.root.findall("transform"):
            name = _text(el, "name")
            if name:
                self.transforms[name] = _Transform(name, _text(el, "type"), el)
        self.hops: list[tuple[str, str]] = []
        for hop in self.root.findall("order/hop"):
            src, dest = _text(hop, "from"), _text(hop, "to")
            src_t, dest_t = self._tr(src), self._tr(dest)
            src_n = src_t.name if src_t else src
            dest_n = dest_t.name if dest_t else dest
            if not _enabled(hop):
                self.diagnostics.append(
                    f"hop {src_n!r} -> {dest_n!r} disabled; not a dataflow"
                )
                continue
            if src_n and dest_n:
                self.hops.append((src_n, dest_n))
        self.incoming: dict[str, list[str]] = {n: [] for n in self.transforms}
        self.outgoing: dict[str, list[str]] = {n: [] for n in self.transforms}
        for src, dest in self.hops:
            self.incoming.setdefault(dest, []).append(src)
            self.outgoing.setdefault(src, []).append(dest)
        self.identities: dict[str, TableIdentity] = {}
        self.field_types: dict[str, dict[str, T.TypeInfo]] = {}
        for name, tr in self.transforms.items():
            ident, fields = self._source(tr)
            self.field_types[name] = fields
            if ident is not None:
                self.identities[name] = ident

    def _note(self, msg: str) -> None:
        self.diagnostics.append(msg)

    def _tr(self, name: str) -> _Transform | None:
        if name in self.transforms:
            return self.transforms[name]
        want = _norm(name)
        hits = [t for n, t in self.transforms.items() if _norm(n) == want]
        return hits[0] if len(hits) == 1 else None

    def _source(
        self, tr: _Transform
    ) -> tuple[TableIdentity | None, dict[str, T.TypeInfo]]:
        fields = {
            _text(f, "name"): map_type(
                _text(f, "type"), _text(f, "length"), _text(f, "precision")
            )
            for f in _fields(tr.el)
            if _text(f, "name")
        }
        if tr.type == "TableInput":
            sql = tr.text("sql")
            name = from_table(sql)
            if not name:
                self._note(f"TableInput {tr.name!r}: no FROM table in sql; identity fallback")
                return TableIdentity(tr.name, is_fallback=True), fields
            return TableIdentity(name), fields
        if tr.type in FILE_TYPES:
            stem = _filename_stem(tr)
            if stem:
                return TableIdentity(stem), fields
            self._note(
                f"{tr.type} {tr.name!r}: no literal filename; identity falls back to the transform name"
            )
            return TableIdentity(tr.name, is_fallback=True), fields
        if tr.type in ("DataGrid", "RowGenerator"):
            return TableIdentity(tr.name, is_fallback=True), fields
        if tr.type == "MappingInput":
            return TableIdentity(tr.name, is_fallback=True), fields
        if tr.type == "DBLookup":
            return None, fields
        return None, fields

    def _renames(self, tr: _Transform) -> dict[str, str]:
        """SelectValues rename -> original name, keyed by normalized rename."""
        out: dict[str, str] = {}
        if tr.type != "SelectValues":
            return out
        for field in _fields(tr.el):
            name, rename = _text(field, "name"), _text(field, "rename")
            if rename and rename != name:
                out[_norm(rename)] = name
        return out

    def _unique_column_bind(self, column: str) -> ColumnRef | None:
        hits: list[ColumnRef] = []
        want = {_norm(column)}
        if column.startswith("_") and len(column) > 1:
            want.add(_norm(column[1:]))
        for name, ident in self.identities.items():
            for col, typ in self.field_types.get(name, {}).items():
                if _norm(col) in want or (
                    col.startswith("_") and _norm(col[1:]) in want
                ):
                    hits.append(ColumnRef(ident, col, typ))
        if len(hits) != 1:
            return None
        ref = hits[0]
        self._note(
            f"branch operand {column!r} bound to the only emitted TABLE that declares "
            f"{ref.column!r} ({ref.table.name})"
        )
        return ref

    def resolve(self, transform: str, column: str, depth: int = 0) -> ColumnRef | None:
        if depth > 64 or not column:
            return None
        tr = self._tr(transform)
        name = tr.name if tr else transform
        types = self.field_types.get(name, {})
        ident = self.identities.get(name)
        matched = _match_field(column, types)
        if ident is not None and matched:
            return ColumnRef(ident, matched, types[matched])
        if ident is not None and not types:
            return ColumnRef(ident, column, T.UNKNOWN)
        if tr is not None and tr.type == "SelectValues":
            original = tr and self._renames(tr).get(_norm(column))
            if original:
                ins = self.incoming.get(name, [])
                return self.resolve(ins[0], original, depth + 1) if len(ins) == 1 else None
        if tr is not None and tr.type == "DBLookup":
            ref = self._dblookup_value_ref(tr, column)
            if ref is not None:
                return ref
        if tr is not None and tr.type == "SimpleMapping":
            ins = self.incoming.get(name, [])
            if len(ins) == 1:
                ref = self.resolve(ins[0], column, depth + 1)
                if ref is not None:
                    return ref
        for pred in self.incoming.get(name, []):
            ref = self.resolve(pred, column, depth + 1)
            if ref is not None:
                return ref
        return None

    def tables(self) -> list[MinedTable]:
        seen: dict[str, MinedTable] = {}
        for name, ident in self.identities.items():
            key = ident.name.casefold()
            cols = [
                MinedColumn(col, typ)
                for col, typ in self.field_types.get(name, {}).items()
            ]
            if key in seen:
                have = {c.name for c in seen[key].columns}
                seen[key].columns.extend(c for c in cols if c.name not in have)
                continue
            extra = ""
            if self.transforms[name].type == "TableInput":
                extra = self.transforms[name].text("connection")
            seen[key] = MinedTable(
                ident,
                cols,
                origin=name + (f" connection={extra}" if extra else ""),
            )
        for tr in self.transforms.values():
            if tr.type != "DBLookup":
                continue
            lookup = tr.el.find("lookup")
            table = _text(lookup, "table") if lookup is not None else ""
            schema = _text(lookup, "schema") if lookup is not None else ""
            if not table:
                continue
            ident = TableIdentity(f"{schema}.{table}" if schema else table)
            cols: list[MinedColumn] = []
            if lookup is not None:
                for key in lookup.findall("key"):
                    field = _text(key, "field")
                    if field:
                        cols.append(MinedColumn(field, T.UNKNOWN))
                for val in lookup.findall("value"):
                    field = _text(val, "name")
                    if field:
                        cols.append(MinedColumn(field, map_type(_text(val, "type"))))
            seen.setdefault(
                ident.name.casefold(),
                MinedTable(ident, cols, origin=tr.name),
            )
        for tr in self.transforms.values():
            if tr.type not in SCD_TYPES:
                continue
            ident = self._dim_table(tr)
            if ident is None:
                continue
            cols: list[MinedColumn] = []
            for key in tr.el.findall("fields/key"):
                field = _text(key, "lookup") or _text(key, "name")
                if field:
                    cols.append(MinedColumn(field, T.UNKNOWN))
            seen.setdefault(
                ident.name.casefold(),
                MinedTable(ident, cols, origin=tr.name),
            )
        return list(seen.values())

    def _dim_table(self, tr: _Transform) -> TableIdentity | None:
        table = tr.text("table")
        if not table:
            return None
        schema = tr.text("schema")
        name = f"{schema}.{table}" if schema else table
        return TableIdentity(name)

    def _dblookup_value_ref(self, tr: _Transform, column: str) -> ColumnRef | None:
        lookup = tr.el.find("lookup")
        if lookup is None:
            return None
        table = _text(lookup, "table")
        schema = _text(lookup, "schema")
        if not table:
            return None
        ident = TableIdentity(f"{schema}.{table}" if schema else table)
        want = _norm(column)
        for val in lookup.findall("value"):
            names = [_text(val, "rename"), _text(val, "name")]
            if any(_norm(n) == want for n in names if n):
                field = _text(val, "name") or column
                return ColumnRef(ident, field, map_type(_text(val, "type")))
        return None

    def _qualify(self, transform: str, column: str) -> str | None:
        ref = self.resolve(transform, column) or self._unique_column_bind(column)
        return f"{ref.table.name}.{ref.column}" if ref else None

    def _leaf_text(self, cond: ET.Element) -> str:
        left = _text(cond, "leftvalue")
        func = _text(cond, "function") or "="
        right = _text(cond, "rightvalue")
        value = cond.find("value")
        literal = _text(value, "text") if value is not None else ""
        rhs = right or literal
        body = f"{left} {func} {rhs}".strip()
        if _text(cond, "negated").upper() == "Y":
            return f"NOT ({body})"
        return body

    def _condition_text(self, cond: ET.Element | None) -> str:
        if cond is None:
            return ""
        kids = cond.findall("conditions/condition")
        if not kids:
            return self._leaf_text(cond)
        parts: list[str] = []
        for i, kid in enumerate(kids):
            piece = self._condition_text(kid)
            if i == 0:
                parts.append(piece)
                continue
            op = _text(kid, "operator") or "AND"
            if op == "-":
                op = "AND"
            parts.append(f"{op} {piece}")
        body = " ".join(parts)
        if _text(cond, "negated").upper() == "Y":
            return f"NOT ({body})"
        return f"({body})" if len(kids) > 1 else body

    def _atom(self, cond: ET.Element, transform: str) -> PredicateNode | None:
        left = _text(cond, "leftvalue")
        func = _text(cond, "function")
        if not left:
            return None
        col = self._qualify(transform, left) or left
        null_op = _NULL_FUNCS.get(func.upper())
        if null_op:
            node = PredicateNode(kind="atom", columns=[col], operator=null_op, values=[])
            if _text(cond, "negated").upper() == "Y":
                return _negate_node(node)
            return node
        if func not in DIALECT.comparisons:
            return None
        if _text(cond, "rightvalue"):
            return None
        value = cond.find("value")
        literal = _text(value, "text") if value is not None else ""
        node = PredicateNode(
            kind="atom",
            columns=[col],
            operator=DIALECT.comparisons[func],
            values=[literal],
        )
        if _text(cond, "negated").upper() == "Y":
            return _negate_node(node)
        return node

    def _condition_node(
        self, cond: ET.Element | None, transform: str
    ) -> PredicateNode | None:
        if cond is None:
            return None
        kids = cond.findall("conditions/condition")
        if not kids:
            return self._atom(cond, transform)
        nodes = [self._condition_node(k, transform) for k in kids]
        if any(n is None for n in nodes):
            return None
        ops = {(_text(k, "operator") or "AND").upper() for k in kids[1:]}
        ops.discard("-")
        if not ops:
            node = nodes[0]
        elif ops == {"OR"}:
            node = PredicateNode(kind="or", children=nodes)
        elif ops <= {"AND"}:
            node = PredicateNode(kind="and", children=nodes)
        else:
            return None
        if _text(cond, "negated").upper() == "Y":
            return _negate_node(node)
        return node

    def _bind_leftvalues(self, cond: ET.Element | None, transform: str) -> list[ColumnRef]:
        refs: dict[str, ColumnRef] = {}
        if cond is None:
            return []
        for left in cond.iter("leftvalue"):
            name = (left.text or "").strip()
            if not name:
                continue
            ref = self.resolve(transform, name) or self._unique_column_bind(name)
            if ref is not None:
                refs[f"{ref.table.name}.{ref.column}"] = ref
            else:
                self._note(
                    f"FilterRows {transform!r}: operand {name!r} does not resolve to a source column; atom kept bare"
                )
        return list(refs.values())

    def filter_branches(self) -> list[Branch]:
        out: list[Branch] = []
        for tr in self.transforms.values():
            if tr.type != "FilterRows":
                continue
            cond = tr.el.find("compare/condition")
            text = self._condition_text(cond)
            if not text:
                self._note(f"FilterRows {tr.name!r}: empty condition; no branch")
                continue
            refs = self._bind_leftvalues(cond, tr.name)
            predicate = self._condition_node(cond, tr.name)
            if predicate is None:
                self._note(
                    f"FilterRows {tr.name!r}: condition not decomposable; predicate_text only"
                )
            true_to = tr.text("send_true_to")
            false_to = tr.text("send_false_to")
            out.append(
                Branch(
                    branch_id=len(out),
                    construct_kind=CONSTRUCT_KIND,
                    predicate_text=text,
                    columns=list(refs),
                    predicate=predicate,
                    origin=f"{tr.name}/true" + (f"->{true_to}" if true_to else ""),
                )
            )
            if false_to:
                rejected = _negate_node(predicate) if predicate is not None else None
                if predicate is not None and rejected is None:
                    self._note(
                        f"FilterRows {tr.name!r}: false hop {false_to!r} has no negated tree; predicate_text only"
                    )
                out.append(
                    Branch(
                        branch_id=len(out),
                        construct_kind=CONSTRUCT_KIND,
                        predicate_text=f"NOT ({text})",
                        columns=list(refs),
                        predicate=rejected,
                        origin=f"{tr.name}/false->{false_to}",
                    )
                )
        return out

    def _side_identity(
        self, transform: str, columns: list[str], source: str
    ) -> tuple[TableIdentity | None, list[str]]:
        refs = [self.resolve(transform, c) for c in columns]
        tables = {r.table for r in refs if r is not None}
        if len(tables) != 1 or any(r is None for r in refs):
            self._note(
                f"{source}: key columns do not resolve to one source table; edge side unresolved"
            )
            tr = self._tr(transform)
            return self.identities.get(tr.name if tr else transform), columns
        return tables.pop(), [r.column for r in refs if r is not None]

    def merge_joins(self) -> list[JoinEdge]:
        edges: list[JoinEdge] = []
        for tr in self.transforms.values():
            if tr.type != "MergeJoin":
                continue
            left_name, right_name = tr.text("transform1"), tr.text("transform2")
            raw = tr.text("join_type").upper()
            join_type = _JOIN_TYPE.get(raw)
            if join_type is None:
                self._note(f"MergeJoin {tr.name!r}: unknown join_type {raw!r}; no edge")
                continue
            if join_type == "full":
                self._note(
                    f"MergeJoin {tr.name!r}: FULL OUTER has no generate atom; edge still emitted as full"
                )
            keys1 = [
                (k.text or "").strip()
                for k in tr.el.findall("keys_1/key")
                if (k.text or "").strip()
            ]
            keys2 = [
                (k.text or "").strip()
                for k in tr.el.findall("keys_2/key")
                if (k.text or "").strip()
            ]
            if not keys1 or not keys2 or len(keys1) != len(keys2):
                self._note(f"MergeJoin {tr.name!r}: missing or uneven keys; no edge")
                continue
            left, left_cols = self._side_identity(
                left_name, keys1, f"MergeJoin {tr.name} left"
            )
            right, right_cols = self._side_identity(
                right_name, keys2, f"MergeJoin {tr.name} right"
            )
            edges.append(
                JoinEdge(left, left_cols, right, right_cols, join_type, origin=tr.name)
            )
        return edges

    def stream_lookups(self) -> list[JoinEdge]:
        edges: list[JoinEdge] = []
        for tr in self.transforms.values():
            if tr.type != "StreamLookup":
                continue
            lookup_from = tr.text("from")
            keys = tr.el.findall("lookup/key")
            if not keys:
                self._note(f"StreamLookup {tr.name!r}: no keys; no edge")
                continue
            left_cols = [_text(k, "name") for k in keys]
            right_cols = [_text(k, "field") for k in keys]
            if any(not c for c in left_cols + right_cols):
                self._note(f"StreamLookup {tr.name!r}: incomplete key; no edge")
                continue
            lookup_tr = self._tr(lookup_from)
            lookup_name = lookup_tr.name if lookup_tr else lookup_from
            mains = [s for s in self.incoming.get(tr.name, []) if _norm(s) != _norm(lookup_name)]
            main = mains[0] if mains else ""
            if not main:
                self._note(f"StreamLookup {tr.name!r}: no main incoming hop; no edge")
                continue
            left, left_resolved = self._side_identity(
                main, left_cols, f"StreamLookup {tr.name} main"
            )
            right, right_resolved = self._side_identity(
                lookup_name, right_cols, f"StreamLookup {tr.name} lookup"
            )
            edges.append(
                JoinEdge(left, left_resolved, right, right_resolved, "inner", origin=tr.name)
            )
        return edges

    def db_lookups(self) -> list[JoinEdge]:
        edges: list[JoinEdge] = []
        for tr in self.transforms.values():
            if tr.type != "DBLookup":
                continue
            lookup = tr.el.find("lookup")
            table = _text(lookup, "table") if lookup is not None else ""
            schema = _text(lookup, "schema") if lookup is not None else ""
            keys = lookup.findall("key") if lookup is not None else []
            if not table or not keys:
                self._note(f"DBLookup {tr.name!r}: no table or keys; no edge")
                continue
            right_ident = TableIdentity(f"{schema}.{table}" if schema else table)
            conds = {_text(k, "condition") or "=" for k in keys}
            if conds != {"="}:
                self._note(f"DBLookup {tr.name!r}: non-equality key {sorted(conds)}; no edge")
                continue
            left_cols = [_text(k, "name") for k in keys]
            right_cols = [_text(k, "field") for k in keys]
            mains = self.incoming.get(tr.name, [])
            main = mains[0] if mains else tr.name
            left, left_resolved = self._side_identity(
                main, left_cols, f"DBLookup {tr.name} stream"
            )
            edges.append(
                JoinEdge(
                    left,
                    left_resolved,
                    right_ident,
                    right_cols,
                    "inner",
                    origin=tr.name,
                )
            )
        return edges

    def scd_lookups(self) -> list[JoinEdge]:
        edges: list[JoinEdge] = []
        for tr in self.transforms.values():
            if tr.type not in SCD_TYPES:
                continue
            ident = self._dim_table(tr)
            keys = tr.el.findall("fields/key")
            if ident is None or not keys:
                self._note(f"{tr.type} {tr.name!r}: no table or keys; no edge")
                continue
            left_cols = [_text(k, "name") for k in keys]
            right_cols = [_text(k, "lookup") or _text(k, "name") for k in keys]
            if any(not c for c in left_cols + right_cols):
                self._note(f"{tr.type} {tr.name!r}: incomplete key; no edge")
                continue
            mains = self.incoming.get(tr.name, [])
            main = mains[0] if mains else tr.name
            left, left_resolved = self._side_identity(
                main, left_cols, f"{tr.type} {tr.name} stream"
            )
            edges.append(
                JoinEdge(
                    left,
                    left_resolved,
                    ident,
                    right_cols,
                    "inner",
                    origin=tr.name,
                )
            )
        return edges

    def _equi_pairs(self, cond: ET.Element | None) -> list[tuple[str, str]]:
        if cond is None:
            return []
        pairs: list[tuple[str, str]] = []
        for node in [cond, *cond.findall(".//condition")]:
            if node.findall("conditions/condition"):
                continue
            left, right, func = (
                _text(node, "leftvalue"),
                _text(node, "rightvalue"),
                _text(node, "function"),
            )
            if left and right and func in {"=", "=="}:
                pairs.append((left, right))
        return pairs

    def join_rows(self) -> tuple[list[JoinEdge], list[Branch]]:
        edges, branches = [], []
        for tr in self.transforms.values():
            if tr.type != "JoinRows":
                continue
            cond = tr.el.find("compare/condition")
            pairs = self._equi_pairs(cond)
            if not pairs:
                self._note(f"JoinRows {tr.name!r}: cartesian product; no join edge")
                continue
            left_cols = [p[0] for p in pairs]
            right_cols = [p[1] for p in pairs]
            ins = self.incoming.get(tr.name, [])
            if len(ins) < 2:
                self._note(f"JoinRows {tr.name!r}: {len(ins)} incoming hop(s); no edge")
                continue
            left, left_resolved = self._side_identity(
                ins[0], left_cols, f"JoinRows {tr.name} main"
            )
            right, right_resolved = self._side_identity(
                ins[1], right_cols, f"JoinRows {tr.name} lookup"
            )
            if (
                left
                and right
                and left.name.casefold() != right.name.casefold()
                and left_resolved
                and right_resolved
            ):
                edges.append(
                    JoinEdge(
                        left, left_resolved, right, right_resolved, "inner", origin=tr.name
                    )
                )
            else:
                self._note(
                    f"JoinRows {tr.name!r}: equality keys do not resolve to two source tables; no edge"
                )
            pred = self._condition_node(cond, tr.name)
            if pred is not None:
                branches.append(
                    Branch(
                        branch_id=0,
                        construct_kind=CONSTRUCT_KIND,
                        predicate_text=self._condition_text(cond),
                        columns=self._bind_leftvalues(cond, tr.name),
                        predicate=pred,
                        origin=f"{tr.name}/join-rows",
                    )
                )
        return edges, branches

    def query_signals(self) -> tuple[list[Branch], list[JoinEdge], list[MinedTable]]:
        branches, edges = [], []
        extra_by_name: dict[str, MinedTable] = {}
        known = {
            ident.name.casefold(): ident for ident in self.identities.values()
        }

        def extra_table(name: str, column: str, origin: str) -> TableIdentity:
            seen = extra_by_name.get(name.casefold())
            if seen is None:
                seen = MinedTable(
                    TableIdentity(name),
                    [MinedColumn(column, T.UNKNOWN)],
                    origin=f"{origin}/sql-join",
                )
                extra_by_name[name.casefold()] = seen
                self._note(
                    f"TableInput {origin}: sql joins {name!r}, which is not a pipeline source; "
                    f"TABLE emitted with key column(s) only"
                )
            elif column not in {c.name for c in seen.columns}:
                seen.columns.append(MinedColumn(column, T.UNKNOWN))
            return seen.identity

        for tr in self.transforms.values():
            if tr.type != "TableInput":
                continue
            sql = tr.text("sql")
            if not sql:
                continue
            if "${" in sql or "?" in sql:
                self._note(
                    f"TableInput {tr.name!r}: sql is parameterized or templated; WHERE/JOIN not mined"
                )
                continue
            where = where_text(sql)
            ident = self.identities.get(tr.name)
            if where and ident is not None:
                refs: dict[str, ColumnRef] = {}

                def qualify(col: str, i: TableIdentity = ident) -> str | None:
                    token = col.split(".")[-1]
                    ref = self.resolve(tr.name, token) or self._unique_column_bind(token)
                    if ref is None:
                        self._note(
                            f"TableInput {tr.name!r}: sql WHERE operand {col!r} is not a source column; atom kept bare"
                        )
                        return None
                    refs[col] = ref
                    return f"{ref.table.name}.{ref.column}"

                predicate = decompose(where, DIALECT, qualify)
                if predicate is None:
                    self._note(
                        f"TableInput {tr.name!r}: sql WHERE {where!r} not a column-vs-literal; predicate_text only"
                    )
                branches.append(
                    Branch(
                        branch_id=0,
                        construct_kind=CONSTRUCT_KIND,
                        predicate_text=where,
                        columns=list(refs.values()),
                        predicate=predicate,
                        origin=f"{tr.name}/sql-where",
                    )
                )
            for left_table, left_col, right_table, right_col, join_type in equi_joins(sql):
                left_id = known.get(left_table.casefold()) or extra_by_name.get(
                    left_table.casefold()
                )
                right_id = known.get(right_table.casefold()) or extra_by_name.get(
                    right_table.casefold()
                )
                if left_id is None:
                    left_id = extra_table(left_table, left_col, tr.name)
                elif isinstance(left_id, MinedTable):
                    left_id = left_id.identity
                if right_id is None:
                    right_id = extra_table(right_table, right_col, tr.name)
                elif isinstance(right_id, MinedTable):
                    right_id = right_id.identity
                if isinstance(left_id, TableIdentity) and isinstance(right_id, TableIdentity):
                    edges.append(
                        JoinEdge(
                            left_id,
                            [left_col],
                            right_id,
                            [right_col],
                            join_type,
                            origin=f"{tr.name}/sql-join",
                        )
                    )
        return branches, edges, list(extra_by_name.values())

    def derived_columns(self) -> list[str]:
        out: list[str] = []

        def add(name: str) -> None:
            if name and name not in out:
                out.append(name)

        for tr in self.transforms.values():
            if tr.type == "SelectValues":
                for meta in _fields(tr.el):
                    rename, name = _text(meta, "rename"), _text(meta, "name")
                    if rename and rename != name:
                        add(rename)
            if tr.type == "Calculator":
                for calc in tr.el.findall("calculation"):
                    field = _text(calc, "field_name")
                    kind = (_text(calc, "calc_type") or "").upper()
                    if field and kind not in {"", "COPY", "NONE"}:
                        add(field)
            if tr.type == "Formula":
                for entry in tr.el.findall("formulas/formula"):
                    field = _text(entry, "field_name") or _text(entry, "replace_field")
                    expr = _text(entry, "formula")
                    if field and expr:
                        add(field)
        return out

    def apply_unique_keys(self, tables: list[MinedTable]) -> list[MinedTable]:
        wanted: set[tuple[str, str]] = set()
        for tr in self.transforms.values():
            if tr.type not in UNIQUE_TYPES:
                continue
            for field in _fields(tr.el):
                col = _text(field, "name")
                if not col:
                    continue
                ref = self.resolve(tr.name, col)
                if ref is None:
                    self._note(
                        f"Unique {tr.name!r}: {col!r} does not resolve; not marked unique"
                    )
                    continue
                wanted.add((ref.table.name.casefold(), ref.column.casefold()))
        if not wanted:
            return tables
        out = []
        for table in tables:
            cols = [
                MinedColumn(
                    c.name,
                    c.type,
                    c.nullable,
                    c.primary_key,
                    True
                    if (table.identity.name.casefold(), c.name.casefold()) in wanted
                    else c.unique,
                )
                for c in table.columns
            ]
            if any(c.unique and not c.primary_key for c in cols) and not any(
                c.unique for c in table.columns
            ):
                self._note(
                    f"table {table.identity.name}: Unique marked "
                    f"{[c.name for c in cols if c.unique]} unique"
                )
            out.append(MinedTable(table.identity, cols, table.origin))
        return out

    def context(self) -> dict:
        lineage: dict[str, dict[str, str | None]] = {}
        for name, fields in self.field_types.items():
            lineage[name] = {}
            for col in fields:
                ref = self.resolve(name, col)
                lineage[name][col] = (
                    f"{ref.table.name}.{ref.column}" if ref is not None else None
                )
        connections = {
            tr.name: tr.text("connection")
            for tr in self.transforms.values()
            if tr.text("connection")
        }
        return {
            "transforms": [
                {"name": tr.name, "type": tr.type} for tr in self.transforms.values()
            ],
            "hops": [{"from": a, "to": b} for a, b in self.hops],
            "sources": [
                {
                    "transform": name,
                    "table": ident.name,
                    "is_fallback": ident.is_fallback,
                }
                for name, ident in self.identities.items()
            ],
            "column_lineage": lineage,
            "connections": connections,
        }

    def mine(self) -> MiningResult:
        q_branches, q_edges, q_tables = self.query_signals()
        jr_edges, jr_branches = self.join_rows()
        branches = self.filter_branches() + q_branches + jr_branches
        for i, b in enumerate(branches):
            b.branch_id = i
        package = MinedPackage(
            object_name=self.object_name,
            branches=branches,
            edges=self.merge_joins()
            + self.stream_lookups()
            + self.db_lookups()
            + self.scd_lookups()
            + jr_edges
            + q_edges,
            derived_columns=self.derived_columns(),
        )
        if self.ir is not None:
            self._note(
                "ir: supplied but not consumed by the hop adapter (document is the only source of facts)"
            )
        ctx = self.context()
        return MiningResult(
            platform=PLATFORM,
            document=str(self.path),
            package=package,
            tables=self.apply_unique_keys(self.tables() + q_tables),
            diagnostics=self.diagnostics,
            inputs={"document": True, "ir": False, "platform_table": False},
            context=ctx,
        )


def mine(
    path: str | Path, object_name: str | None = None, ir_path: str | Path | None = None
) -> MiningResult:
    ir = json.loads(Path(ir_path).read_text(encoding="utf-8")) if ir_path else None
    return HopMiner(path, object_name, ir).mine()
