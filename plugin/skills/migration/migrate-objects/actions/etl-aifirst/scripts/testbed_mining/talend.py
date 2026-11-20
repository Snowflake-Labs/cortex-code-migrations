"""Talend (.item ProcessType) adapter: job XML -> neutral MiningResult.

TABLE-INDEPENDENT ON PURPOSE, like the SSIS adapter. It reads the job XML directly
and never reads `platform_talend.json`. The adapter is chosen by the root element
(`ProcessType` in the TalendFile.xsd namespace, or with no namespace at all). Components are recognized by the
PARAMETERS and payloads they carry, never by `componentName`. The component name
is only recorded as context.

Graph. A `<connection>` is a data flow when its `metaname` (or `connectorName`)
names a `<metadata>` schema on its source node. Trigger links (OnSubjobOk, RunIf, ...)
carry no schema and are ignored. A flow is named by its UNIQUE_NAME parameter, else
its `label`.

Structural rules:
  source        node with no incoming data flow that either (a) has an outgoing
                flow and a FLOW schema with columns, or (b) states a TABLE / QUERY /
                FILENAME identity even when the FLOW schema is missing or nothing
                has wired it yet. Table identity, first rule that the document states:
                  1. TABLE parameter, a Java string literal (+ SCHEMA_DB prefix and
                     DBNAME database, when those are literals too)
                  2. the single FROM table of a literal QUERY parameter
                  3. FILE INPUT RULE: the basename of a literal FILENAME, minus its
                     final extension ("E:/in/Orders.csv" -> Orders). A file is not
                     a database object, so it is never database-qualified. It IS
                     matched against SQL DDL, because loading that file is what the
                     DDL table describes.
                  4. otherwise the node's UNIQUE_NAME, flagged as a fallback identity
                     (never qualified, never de-duplicated)
                Columns come from the FLOW schema when present; otherwise from any
                downstream mapper inputTables that name this source. An empty
                schema is still emitted (the identity is a fact; inventing columns
                is not).
  java row      CODE (MEMO_JAVA) parameter on a node with an incoming flow. Comments
                are stripped; `output_row.X = <expr>;` (or `<out flow>.X =`) are
                assignments. X is PASSED THROUGH when every assignment is a bare
                `input_row.Y` (or `<in flow>.Y`). Same Y = pass-through; other Y =
                a rename, which still resolves to Y. Any other assignment makes X
                DERIVED. Java control flow becomes a predicate only through the flag
                substitution below, never as a branch of its own.
  row filter    CONDITIONS table (INPUT_COLUMN / FUNCTION / OPERATOR / RVALUE) joined
                by LOGICAL_OP. The FILTER output is the branch; REJECT is its
                complement and, like an SSIS default output, is not a branch. An atom
                is emitted only when the FUNCTION template is provably the plain
                comparison (see `_condition_atom`). USE_ADVANCED's ADVANCED_COND is
                decomposed only when it is the sole condition.
  flag subst.   a CONDITIONS operand computed by an upstream java row is restated on
                that row's INPUT columns when `javaguard.prove_flag` proves the code is
                "literal default, overwritten by one literal under if-guards". The
                FILTER branch keeps a tree only when every guard leaf is an exact
                column-vs-literal test. A second, REJECT branch then carries the
                strongest provable tree that implies rejection, which drops only
                unprovable OR-disjuncts and so never claims a row is rejected wrongly.
                Each dropped or blocking leaf is reported.
  mapper        nodeData (tMap). inputTables[0] is the main flow and later
                inputTables are lookups. A lookup mapperTableEntries carrying an
                `expression` is a join key: entry name = lookup column, expression =
                `<input table>.<column>`. innerJoin="true" -> inner, else left.
                matchingMode ALL_ROWS with join keys is one-to-many (equality edge);
                ALL_ROWS with no keys is cartesian and yields no edge.
                outputTables@rejectInnerJoin="true" -> ANTI on each inner lookup.
                A joined input table with no incoming flow of its name is UNWIRED: its
                own mapperTableEntries (name + type) are the only schema the document
                states for it, so it becomes a fallback TABLE named after that input
                (never qualified, never de-duplicated) and the edge side binds to it.
                Unwired inputs that take part in no join still emit that fallback
                TABLE, so generate can populate a declared-but-unused side.
                outputTables@expressionFilter (activateExpressionFilter="true") ->
                branch. An output entry whose expression is not a bare
                `<input table>.<column>` -> derived.
  source QUERY  a literal QUERY parameter may add more than the FROM table:
                a simple WHERE (column vs literal) becomes a FILTER branch on
                that source TABLE; `JOIN t ON a.col = b.col` becomes an edge
                and, when `t` is not already a source, a TABLE with the key
                columns only.
  join key tbl  JOIN_KEY parameter (tJoin) on a node with two incoming flows
                and no mapper payload: KEY/INPUT_COLUMN is the main side,
                KEY_COLUMN/LOOKUP_COLUMN the lookup side. USE_INNER_JOIN true
                -> inner, else left.
  unique keys   SOURCE_KEYS (SCD) and UNIQUE_KEY (tUniqRow) NAME/KEY/COLUMN
                values mark those columns unique on any already-emitted TABLE
                that declares them. No table is invented for a key.
  anything else a node without code or mapper payload is assumed to pass columns
                through by name. Each such hop is reported, because it is an
                assumption.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import docmodel

from testbed_mining import javaguard
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
    SemiAnti,
    TableIdentity,
)
from testbed_mining.predicate import Dialect, decompose, operand_columns
from testbed_mining.sqltext import equi_joins, from_table, where_text

PLATFORM = "talend"
TALEND_NS = "platform:/resource/org.talend.model/model/TalendFile.xsd"
ROOT_TAG = f"{{{TALEND_NS}}}ProcessType"
CONSTRUCT_KIND = "FILTER"

# Java boolean expressions as written in tMap filters / tFilterRow advanced mode.
DIALECT = Dialect(
    comparisons={"==": "=", "!=": "<>", "<=": "<=", ">=": ">=", "<": "<", ">": ">"},
    and_tokens=frozenset({"&&"}),
    or_tokens=frozenset({"||"}),
    string_quotes=('"',),
)
# Literal QUERY parameters are SQL, not Java.
SQL_DIALECT = Dialect(
    comparisons={"=": "=", "<>": "<>", "!=": "<>", "<=": "<=", ">=": ">=", "<": "<", ">": ">"},
    and_tokens=frozenset({"AND"}),
    or_tokens=frozenset({"OR"}),
    identifier_quotes=(("[", "]"), ("`", "`"), ('"', '"')),
    string_quotes=("'",),
)

_JAVA_STRING = r'"(?:[^"\\]|\\.)*"'
_BARE_REF = re.compile(r"^\s*([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*$")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")
# tFilterRow FUNCTION templates whose comparison is provably the plain one (see _condition_atom).
_PLAIN = re.compile(r"^\s*\$source\s+\$operator\s+\$target\s*$")
_COMPARE_TO = re.compile(
    r"^\s*\$source\s*==\s*null\s*\?\s*false\s*:\s*\$source(\.to(Lower|Upper)Case\(\))?"
    r"\.compareTo\(\s*\$target\s*\)\s*\$operator\s*0\s*$"
)


def sniff(path: str | Path) -> bool:
    try:
        for _, el in ET.iterparse(str(path), events=("start",)):
            return el.tag in (ROOT_TAG, "ProcessType")
    except (ET.ParseError, OSError):
        return False
    return False


def map_type(
    talend_type: str | None, length: str | None = None, precision: str | None = None
) -> T.TypeInfo:
    """Talend schema `type` (id_*) -> neutral type. For id_BigDecimal Talend's `length` is the
    precision and its `precision` the scale; for strings `length` is the declared width."""
    t = (talend_type or "").strip()
    n = int(length) if length and length.lstrip("-").isdigit() else None
    p = int(precision) if precision and precision.lstrip("-").isdigit() else None
    n = n if n is not None and n > 0 else None
    if t in ("id_Integer", "id_Long", "id_Short", "id_Byte"):
        return T.make_type("NUMBER", T.INTEGER, n)
    if t in ("id_Float", "id_Double"):
        return T.make_type("FLOAT", T.NUMBER, n)
    if t == "id_BigDecimal":
        return T.make_type(
            "NUMBER", T.NUMBER, n, p if p is not None and p >= 0 else None
        )
    if t in ("id_String", "id_Character"):
        return T.make_type("VARCHAR", T.STRING, n)
    if t == "id_Boolean":
        return T.make_type("BOOLEAN", T.BOOLEAN)
    if t == "id_Date":
        return T.make_type("TIMESTAMP", T.DATE)
    if t == "id_byte[]":
        return T.make_type("BINARY", T.BINARY)
    return T.UNKNOWN


def table_name(expr: str | None) -> str | None:
    """TABLE parameter: a Java string literal, or a bare identifier (competence fixtures)."""
    lit = java_literal(expr)
    if lit:
        return lit
    expr = (expr or "").strip()
    if re.fullmatch(r"[A-Za-z_]\w*", expr):
        return expr
    return None


def java_literal(expr: str | None) -> str | None:
    """A Java string literal, or `+`-concatenation of literals only -> its value; else None."""
    expr = (expr or "").strip()
    if not expr or not re.fullmatch(rf"{_JAVA_STRING}(\s*\+\s*{_JAVA_STRING})*", expr):
        return None
    parts = re.findall(_JAVA_STRING, expr)
    return "".join(
        re.sub(
            r"\\(.)",
            lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)),
            p[1:-1],
        )
        for p in parts
    )


def strip_java_comments(code: str) -> str:
    """Remove // and /* */ comments, leaving string and char literals intact."""
    out, i, n = [], 0, len(code)
    while i < n:
        c = code[i]
        if c in "\"'":
            j = i + 1
            while j < n and code[j] != c:
                j += 2 if code[j] == "\\" else 1
            out.append(code[i : j + 1])
            i = j + 1
        elif code.startswith("//", i):
            j = code.find("\n", i)
            i = n if j < 0 else j
        elif code.startswith("/*", i):
            j = code.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def java_assignments(code: str, targets: set[str]) -> list[tuple[str, str]]:
    """(column, rhs) for each `<target>.<column> = <rhs>;` in comment-stripped code, in order."""
    code = strip_java_comments(code)
    alt = "|".join(re.escape(t) for t in sorted(targets, key=len, reverse=True))
    out = []
    for m in re.finditer(rf"(?<![\w.])(?:{alt})\.([A-Za-z_]\w*)\s*=(?!=)", code):
        j, depth, n = m.end(), 0, len(code)
        while j < n:
            ch = code[j]
            if ch in "\"'":
                q, j = ch, j + 1
                while j < n and code[j] != q:
                    j += 2 if code[j] == "\\" else 1
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == ";" and depth <= 0:
                break
            j += 1
        out.append((m.group(1), code[m.end() : j].strip()))
    return out


def _table_rows(param: ET.Element | None) -> list[dict[str, str]]:
    """A TABLE-field elementParameter -> rows; a row restarts at each recurrence of the first elementRef."""
    rows: list[dict[str, str]] = []
    if param is None:
        return rows
    values = param.findall("elementValue")
    first = values[0].get("elementRef") if values else None
    for v in values:
        if v.get("elementRef") == first or not rows:
            rows.append({})
        rows[-1][v.get("elementRef", "")] = v.get("value", "")
    return rows


def _to_node(c: javaguard.Cond) -> PredicateNode:
    if c.kind == "atom":
        return PredicateNode(
            kind="atom", columns=[c.column], operator=c.operator, values=list(c.values)
        )
    return PredicateNode(kind=c.kind, children=[_to_node(x) for x in c.children])


def _node_columns(p: PredicateNode) -> list[str]:
    return list(p.columns or []) + [
        c for ch in p.children or [] for c in _node_columns(ch)
    ]


def _render(c: javaguard.Cond, top: bool = True) -> str:
    """SQL-shaped provenance text; an unprovable leaf is shown as its Java source in braces."""
    if c.kind == "atom":
        vals = ", ".join("'" + v.replace("'", "''") + "'" for v in c.values)
        return f"{c.column} {c.operator}" + (f" {vals}" if c.values else "")
    if c.kind == "opaque":
        return "{" + c.text + "}"
    body = f" {c.kind.upper()} ".join(_render(x, False) for x in c.children)
    return body if top else f"({body})"


@dataclass
class _Node:
    el: ET.Element
    name: str
    component: str
    params: dict[str, ET.Element]
    schemas: dict[str, list[ET.Element]]  # metadata name AND connector -> columns

    def value(self, name: str) -> str | None:
        p = self.params.get(name)
        return p.get("value") if p is not None else None


@dataclass
class _Flow:
    name: str
    source: str
    target: str
    connector: str
    metaname: str


@dataclass
class _JavaRow:
    assignments: dict[str, list[str]] = field(default_factory=dict)
    # output column -> input column
    lineage: dict[str, str] = field(default_factory=dict)
    derived: list[str] = field(default_factory=list)


class TalendMiner:
    def __init__(
        self, path: str | Path, object_name: str | None = None, ir: dict | None = None
    ):
        self.path = Path(path)
        self.root = docmodel.XmlDocument(str(self.path), {"kind": "XML"}).root
        self.object_name = object_name or self.path.name
        self.ir = ir
        self.diagnostics: list[str] = []
        self._noted: set[str] = set()
        self.nodes: dict[str, _Node] = {}
        for el in self.root.findall("node"):
            params = {p.get("name", ""): p for p in el.findall("elementParameter")}
            name = (
                params["UNIQUE_NAME"].get("value") if "UNIQUE_NAME" in params else None
            ) or ""
            schemas: dict[str, list[ET.Element]] = {}
            for md in el.findall("metadata"):
                for key in {md.get("name", ""), md.get("connector", "")} - {""}:
                    schemas.setdefault(key, md.findall("column"))
            self.nodes[name] = _Node(
                el, name, el.get("componentName", ""), params, schemas
            )
        self.flows: list[_Flow] = []
        for c in self.root.findall("connection"):
            src = self.nodes.get(c.get("source", ""))
            meta, conn = c.get("metaname", ""), c.get("connectorName", "")
            if src is None or not (meta in src.schemas or conn in src.schemas):
                continue  # a trigger link: no schema travels on it
            uname = next(
                (
                    p.get("value")
                    for p in c.findall("elementParameter")
                    if p.get("name") == "UNIQUE_NAME"
                ),
                None,
            )
            self.flows.append(
                _Flow(
                    uname or c.get("label", ""),
                    src.name,
                    c.get("target", ""),
                    conn,
                    meta,
                )
            )
        self.java_rows = {
            n.name: self._java_row(n)
            for n in self.nodes.values()
            if n.value("CODE") is not None
            and n.params["CODE"].get("field") == "MEMO_JAVA"
            and self.incoming(n.name)
        }
        self.sources = [n for n in self.nodes.values() if self._is_source(n)]
        self.identities = {n.name: self._identity(n) for n in self.sources}
        # unwired mapper input name -> the TABLE its own declaration states (see _declared_side)
        self.declared_inputs: dict[str, MinedTable] = {}

    # ---- graph ---------------------------------------------------------------------------

    def incoming(self, node: str) -> list[_Flow]:
        return [f for f in self.flows if f.target == node]

    def outgoing(self, node: str) -> list[_Flow]:
        return [f for f in self.flows if f.source == node]

    def flow_schema(self, flow: _Flow) -> list[ET.Element]:
        src = self.nodes[flow.source]
        return src.schemas.get(flow.metaname) or src.schemas.get(flow.connector) or []

    def _note(self, text: str) -> None:
        if text not in self._noted:
            self._noted.add(text)
            self.diagnostics.append(text)

    def _has_stated_identity(self, n: _Node) -> bool:
        if table_name(n.value("TABLE")):
            return True
        query = java_literal(n.value("QUERY"))
        if query and from_table(query):
            return True
        return bool(java_literal(n.value("FILENAME")))

    def _is_source(self, n: _Node) -> bool:
        if self.incoming(n.name):
            return False
        if bool(self.outgoing(n.name)) and bool(n.schemas.get("FLOW")):
            return True
        # A reader that names a table is a source even with no FLOW schema and even
        # if nothing has wired it. Generate needs the identity; columns may arrive
        # from a mapper declaration or stay empty.
        return self._has_stated_identity(n)

    def _identity(self, n: _Node) -> TableIdentity:
        table = table_name(n.value("TABLE"))
        if table:
            schema = java_literal(n.value("SCHEMA_DB"))
            db = java_literal(n.value("DBNAME"))
            return TableIdentity(
                f"{schema}.{table}" if schema else table, database=db or None
            )
        query = java_literal(n.value("QUERY"))
        if query and from_table(query):
            return TableIdentity(
                from_table(query), database=java_literal(n.value("DBNAME")) or None
            )
        filename = java_literal(n.value("FILENAME"))
        if filename:
            base = re.split(r"[\\/]", filename)[-1]
            stem = re.sub(r"\.[^.]*$", "", base) if "." in base.lstrip(".") else base
            if stem:
                return TableIdentity(stem)
        self._note(
            f"source {n.name}: no literal TABLE/QUERY/FILENAME; identity falls back to the node name"
        )
        return TableIdentity(n.name, is_fallback=True)

    # ---- java row --------------------------------------------------------------------------

    def _java_row(self, n: _Node) -> _JavaRow:
        code = n.value("CODE") or ""
        ins = {"input_row"} | {f.name for f in self.incoming(n.name)}
        outs = {"output_row"} | {f.name for f in self.outgoing(n.name)}
        jr = _JavaRow()
        for col, rhs in java_assignments(code, outs):
            jr.assignments.setdefault(col, []).append(rhs)
        schema = [c.get("name", "") for c in n.schemas.get("FLOW", [])]
        for col in jr.assignments:
            if col not in schema:
                self._note(
                    f"java row {n.name}: assigns {col!r}, which its FLOW schema does not declare; ignored"
                )
        for col in schema:
            rhss = jr.assignments.get(col)
            if not rhss:
                self._note(
                    f"java row {n.name}: output {col!r} is never assigned; not resolved"
                )
                continue
            refs = {
                m.group(2)
                for m in map(_BARE_REF.match, rhss)
                if m and m.group(1) in ins
            }
            if len(refs) == 1 and all(_BARE_REF.match(r) for r in rhss):
                jr.lineage[col] = refs.pop()
            else:
                jr.derived.append(col)
                self._note(
                    f"java row {n.name}: output {col!r} is computed ({len(rhss)} assignment(s): "
                    + "; ".join(rhss)
                    + "); marked derived"
                )
        stripped = strip_java_comments(code)
        controls = re.findall(r"\b(if|else|switch|for|while)\b|\?", stripped)
        if controls:
            self._note(
                f"java row {n.name}: code has Java control flow ({len(controls)} construct(s)); "
                "its conditions are translated only where a filter tests a flag they provably set"
            )
        return jr

    # ---- lineage ---------------------------------------------------------------------------

    def resolve(self, flow: _Flow, column: str, depth: int = 0) -> ColumnRef | None:
        """A column carried on `flow` -> the source-table column it originates from, or None."""
        node = self.nodes.get(flow.source)
        if node is None or depth > 64:
            return None
        if node.name in self.identities:
            for c in node.schemas.get("FLOW", []):
                if c.get("name") == column:
                    t = map_type(c.get("type"), c.get("length"), c.get("precision"))
                    return ColumnRef(self.identities[node.name], column, t)
            return None
        if node.name in self.java_rows:
            jr = self.java_rows[node.name]
            upstream = jr.lineage.get(column)
            if upstream is None:
                return None
            ins = self.incoming(node.name)
            return self.resolve(ins[0], upstream, depth + 1) if len(ins) == 1 else None
        mapper = node.el.find("nodeData")
        if mapper is not None:
            return self._resolve_mapper(node, mapper, flow, column, depth)
        ins = self.incoming(node.name)
        if len(ins) != 1:
            return None
        if "CONDITIONS" not in node.params:  # a row filter forwards its input unchanged
            self._note(
                f"lineage through {node.name} ({node.component}) assumed pass-through by column name"
            )
        return self.resolve(ins[0], column, depth + 1)

    def _canon_input(self, node: _Node, prefix: str, names: set[str] | None = None) -> str | None:
        """Map a tMap expression prefix to an inputTables name.

        Talend stores the prefix as the *row / connection label*, which often differs
        from the mapper input name only by case (`workorderRouting` vs
        `WorkOrderRouting`) and may carry trailing spaces on the whole expression.
        """
        if not prefix:
            return None
        if names is None:
            mapper = node.el.find("nodeData")
            names = {
                t.get("name") or ""
                for t in (mapper.findall("inputTables") if mapper is not None else [])
            }
            names.discard("")
        if prefix in names:
            return prefix
        folded = {name.casefold(): name for name in names}
        if prefix.casefold() in folded:
            return folded[prefix.casefold()]
        wanted = prefix.casefold()
        for flow in self.incoming(node.name):
            aliases = {flow.name.casefold(), flow.metaname.casefold()}
            if wanted not in aliases:
                continue
            for candidate in (flow.name, flow.metaname):
                if candidate in names:
                    return candidate
                if candidate.casefold() in folded:
                    return folded[candidate.casefold()]
        return None

    def _input_flow(self, node: _Node, table: str) -> _Flow | None:
        canon = self._canon_input(node, table) or table
        wanted = (canon or "").casefold()
        return next(
            (
                flow
                for flow in self.incoming(node.name)
                if flow.name.casefold() == wanted or flow.metaname.casefold() == wanted
            ),
            None,
        )

    def _resolve_mapper(self, node, mapper, flow, column, depth) -> ColumnRef | None:
        out = next(
            (
                o
                for o in mapper.findall("outputTables")
                if o.get("name") in (flow.metaname, flow.name)
            ),
            None,
        )
        entry = next(
            (
                e
                for e in (out.findall("mapperTableEntries") if out is not None else [])
                if e.get("name") == column
            ),
            None,
        )
        m = (
            _BARE_REF.match(entry.get("expression") or "")
            if entry is not None
            else None
        )
        return self._resolve_ref(node, m.group(1), m.group(2), depth) if m else None

    def _resolve_ref(
        self, node: _Node, table: str, column: str, depth: int = 0
    ) -> ColumnRef | None:
        f = self._input_flow(node, table)
        return self.resolve(f, column, depth + 1) if f is not None else None

    # ---- signals ---------------------------------------------------------------------------

    def _condition_atom(
        self, row: dict[str, str], qualified: str
    ) -> tuple[str, PredicateNode | None, str | None]:
        """One CONDITIONS row -> (rendered Java text, atom or None, reason when None).

        The atom is the plain `column op literal`. It is emitted only when the FUNCTION
        template provably computes that comparison:
          * empty, or literally `$source $operator $target`;
          * the null-guarded `$source.compareTo($target) $operator 0`, under == / != only
            (Java compareTo order is not SQL collation order);
          * the same with toLowerCase()/toUpperCase(), under == / !=, and only when the
            literal is case-invariant: lower(x) == "0" holds exactly when x == "0".
        """
        col, func = row.get("INPUT_COLUMN", ""), row.get("FUNCTION", "") or ""
        op, rvalue = row.get("OPERATOR", "").strip(), row.get("RVALUE", "").strip()
        text = (
            func.replace("$source", col)
            .replace("$operator", op)
            .replace("$target", rvalue)
            if func.strip()
            else f"{col} {op} {rvalue}"
        )
        if op not in DIALECT.comparisons:
            return text, None, f"operator {op!r} is not a comparison"
        lit = java_literal(rvalue)
        value = lit if lit is not None else (rvalue if _NUMBER.match(rvalue) else None)
        if value is None:
            return text, None, f"RVALUE {rvalue!r} is not a literal"
        m = _COMPARE_TO.match(func)
        if func.strip() and not _PLAIN.match(func):
            if not m:
                return (
                    text,
                    None,
                    f"FUNCTION template {func!r} is not a plain comparison",
                )
            if op not in ("==", "!="):
                return text, None, "compareTo ordering is not SQL ordering"
            if m.group(1) and (value.lower() != value or value.upper() != value):
                return (
                    text,
                    None,
                    f"case-folded comparison against case-sensitive literal {value!r}",
                )
        atom = PredicateNode(
            kind="atom",
            columns=[qualified],
            operator=DIALECT.comparisons[op],
            values=[value],
        )
        return text, atom, None

    def _column_ref(self, node: _Node, column: str, where: str) -> ColumnRef | None:
        ins = self.incoming(node.name)
        ref = self.resolve(ins[0], column) if len(ins) == 1 else None
        if ref is None:
            origin = self._origin_of(ins[0], column) if len(ins) == 1 else None
            self._note(
                f"branch operand {column!r} in {where} "
                + (
                    f"is computed by {origin}"
                    if origin
                    else "does not resolve to a source column"
                )
                + "; atom kept bare"
            )
        return ref

    def _origin_of(self, flow: _Flow, column: str) -> str | None:
        """The node that computes `column` upstream of `flow`, for diagnostics."""
        origin = self._origin(flow, column)
        return origin[0] if origin else None

    def _origin(
        self, flow: _Flow, column: str, depth: int = 0
    ) -> tuple[str, str] | None:
        """(node, column as that node names it) for the node computing `column` upstream of `flow`."""
        node = self.nodes.get(flow.source)
        if node is None or depth > 64:
            return None
        if node.name in self.java_rows and column in self.java_rows[node.name].derived:
            return node.name, column
        ins = self.incoming(node.name)
        if node.name in self.java_rows:
            nxt = self.java_rows[node.name].lineage.get(column)
            return (
                self._origin(ins[0], nxt, depth + 1) if nxt and len(ins) == 1 else None
            )
        mapper = node.el.find("nodeData")
        if mapper is not None:
            entry = next(
                (
                    e
                    for o in mapper.findall("outputTables")
                    if o.get("name") in (flow.metaname, flow.name)
                    for e in o.findall("mapperTableEntries")
                    if e.get("name") == column
                ),
                None,
            )
            expr = (entry.get("expression") or "").strip() if entry is not None else ""
            m = _BARE_REF.match(expr)
            f = self._input_flow(node, m.group(1)) if m else None
            if f is not None:
                return self._origin(f, m.group(2), depth + 1)
            return (node.name, column) if expr else None
        return self._origin(ins[0], column, depth + 1) if len(ins) == 1 else None

    def _substitute_flag(
        self, filter_node: _Node, column: str, atom: PredicateNode, refs: dict
    ) -> javaguard.Cond | str:
        """The FILTER-side truth of `column <op> <literal>` restated on source columns, or the reason not."""
        ins = self.incoming(filter_node.name)
        origin = self._origin(ins[0], column) if len(ins) == 1 else None
        if origin is None or origin[0] not in self.java_rows:
            return "its operand is not computed by a java row"
        jname, jcol = origin
        j_ins = self.incoming(jname)
        if len(j_ins) != 1:
            return f"java row {jname} has {len(j_ins)} input flows"
        if atom.operator not in ("=", "<>"):
            return f"operator {atom.operator!r} on a flag is not an equality"

        def numeric(col: str) -> bool:
            ref = self.resolve(j_ins[0], col)
            return bool(ref and ref.type.is_number)

        proof = javaguard.prove_flag(
            strip_java_comments(self.nodes[jname].value("CODE") or ""),
            jcol,
            {"output_row"} | {f.name for f in self.outgoing(jname)},
            {"input_row", j_ins[0].name},
            numeric,
        )
        if isinstance(proof, javaguard.Refusal):
            return f"java row {jname}: {proof.reason}"
        value = atom.values[0]
        if value not in (proof.default, proof.guard_value):
            return f"literal {value!r} is neither the default {proof.default!r} nor the guard value {proof.guard_value!r}"
        guard_fires = (value == proof.guard_value) == (atom.operator == "=")

        def qualify(c: javaguard.Cond) -> javaguard.Cond:
            if c.kind in ("and", "or"):
                return javaguard.Cond(c.kind, children=[qualify(x) for x in c.children])
            if c.kind != "atom":
                return c
            ref = self.resolve(j_ins[0], c.column)
            if ref is None:
                self._note(
                    f"java row {jname}: guard column {c.column!r} does not resolve to a source column"
                )
                return javaguard.Cond(
                    "opaque", text=f"{c.column} {c.operator} {c.values}"
                )
            q = f"{ref.table.name}.{ref.column}"
            refs[q] = ref
            return javaguard.Cond("atom", q, c.operator, list(c.values))

        guard = qualify(proof.guard)
        self._note(
            f"branch operand {column!r} in {filter_node.name} is computed by {jname}: proven "
            f"{proof.default!r} unless any of {len(proof.guard_texts)} guard(s) fires (then "
            f"{proof.guard_value!r}); restated on {', '.join(dict.fromkeys(guard.columns())) or 'no source column'}"
        )
        return guard if guard_fires else guard.negated()

    def filter_branches(self) -> list[Branch]:
        out = []
        for n in self.nodes.values():
            rows = [
                r
                for r in _table_rows(n.params.get("CONDITIONS"))
                if r.get("INPUT_COLUMN")
            ]
            advanced = (n.value("USE_ADVANCED") or "").lower() == "true"
            if "CONDITIONS" not in n.params:
                continue
            if not rows and not advanced:
                continue
            logical = (n.value("LOGICAL_OP") or "&&").strip()
            kind = {"&&": "and", "||": "or"}.get(logical)
            refs: dict[str, ColumnRef] = {}
            texts, conds, reasons = [], [], []
            substituted = False
            for r in rows:
                col = r["INPUT_COLUMN"]
                ins = self.incoming(n.name)
                ref = self.resolve(ins[0], col) if len(ins) == 1 else None
                if ref is not None:
                    refs[f"{ref.table.name}.{ref.column}"] = ref
                text, atom, why = self._condition_atom(
                    r, f"{ref.table.name}.{ref.column}" if ref else col
                )
                texts.append(text)
                if why:
                    reasons.append(f"{col}: {why}")
                if atom is None:
                    conds.append(javaguard.Cond("opaque", text=text))
                    if ref is None:
                        self._column_ref(n, col, n.name)
                    continue
                if ref is None:
                    restated = self._substitute_flag(n, col, atom, refs)
                    if isinstance(restated, str):
                        self._column_ref(n, col, n.name)
                        self._note(
                            f"filter {n.name}: operand {col!r} not restated on source columns ({restated})"
                        )
                    else:
                        substituted = True
                        conds.append(restated)
                        continue
                conds.append(
                    javaguard.Cond("atom", atom.columns[0], atom.operator, atom.values)
                )
            predicate: PredicateNode | None = None
            filter_side: javaguard.Cond | None = None
            if advanced:
                cond = strip_java_comments(n.value("ADVANCED_COND") or "").strip()
                texts.append(cond)
                if rows:
                    reasons.append(
                        "advanced condition combined with CONDITIONS rows is not modelled"
                    )
                else:
                    predicate = self._java_predicate(n, cond, {"input_row"}, refs)
                    if predicate is None:
                        reasons.append(
                            "advanced condition is not a column-vs-literal boolean"
                        )
            elif kind is None:
                reasons.append(f"LOGICAL_OP {logical!r} is not && or ||")
            else:
                filter_side = (
                    javaguard.all_of(conds)
                    if kind == "and"
                    else javaguard.any_of(conds)
                )
                exact = javaguard.exact(filter_side)
                if exact is not None:
                    predicate = _to_node(exact)
                elif substituted:
                    predicate = self._implying_tree(n, "FILTER", filter_side)
                    if predicate is None:
                        reasons.append("no provable condition implies FILTER")
                elif not reasons:
                    reasons += [
                        f"unprovable guard {leaf!r}"
                        for leaf in filter_side.opaque_leaves()
                    ]
            text = f" {logical} ".join(f"({t})" if len(texts) > 1 else t for t in texts)
            if predicate is None:
                self._note(
                    f"filter {n.name} predicate not decomposable ({'; '.join(reasons)}); predicate_text only"
                )
            out.append(
                Branch(
                    0,
                    CONSTRUCT_KIND,
                    text,
                    list(refs.values()),
                    predicate,
                    origin=n.name,
                )
            )
            if substituted and filter_side is not None:
                out += self._reject_branch(n, filter_side, refs)
        return out

    def _implying_tree(
        self, n: _Node, side: str, cond: javaguard.Cond
    ) -> PredicateNode | None:
        """`cond` itself when exact, else the strongest provable tree that implies it (reported), else None."""
        dropped = cond.opaque_leaves()
        tree = javaguard.exact(cond) or javaguard.sufficient(cond)
        if tree is None:
            self._note(
                f"filter {n.name}: no provable condition implies {side} (blocked by {dropped})"
            )
            return None
        if dropped:
            self._note(
                f"filter {n.name}: {side} branch drops unprovable disjunct(s) {dropped}; "
                f"its predicate implies {side} but {side} does not imply it"
            )
        return _to_node(tree)

    def _reject_branch(
        self, n: _Node, filter_side: javaguard.Cond, refs: dict[str, ColumnRef]
    ) -> list[Branch]:
        """The REJECT arm as its own branch, so rejected rows are drawn from source-column values."""
        reject = filter_side.negated()
        tree = self._implying_tree(n, "REJECT", reject)
        if tree is None:
            return []
        used = set(_node_columns(tree))
        flow = next((f for f in self.outgoing(n.name) if f.connector == "REJECT"), None)
        return [
            Branch(
                0,
                CONSTRUCT_KIND,
                _render(reject),
                [r for q, r in refs.items() if q in used],
                tree,
                origin=f"{n.name}/{flow.name if flow else 'REJECT'}",
            )
        ]

    def _java_predicate(
        self, node: _Node, text: str, aliases: set[str], refs: dict[str, ColumnRef]
    ):
        """Decompose a Java boolean; `<alias>.<col>` operands resolve through the node's inputs."""

        def qualify(ident: str) -> str | None:
            m = _BARE_REF.match(ident)
            if not m:
                return None
            table, col = m.groups()
            canon = self._canon_input(node, table) or (
                table if table in aliases else None
            )
            columns = (col, col[1:]) if col.startswith("_") and len(col) > 1 else (col,)
            ref = None
            if canon:
                for candidate in columns:
                    ref = self._resolve_ref(node, canon, candidate)
                    if ref is not None:
                        break
            if ref is None and table in aliases:
                ins = self.incoming(node.name)
                if len(ins) == 1:
                    for candidate in columns:
                        ref = self.resolve(ins[0], candidate)
                        if ref is not None:
                            break
            if ref is None:
                ref = self._unique_column_bind(col)
                if ref is not None:
                    self._note(
                        f"branch operand {ident!r} in {node.name} bound to the only emitted "
                        f"TABLE that declares {ref.column!r} ({ref.table.name})"
                    )
            if ref is None:
                self._note(
                    f"branch operand {ident!r} in {node.name} does not resolve to a source column; atom kept bare"
                )
                return None
            refs[ident] = ref
            return f"{ref.table.name}.{ref.column}"

        for ident in operand_columns(text, DIALECT):
            qualify(ident)
        return decompose(text, DIALECT, qualify)

    def mapper_signals(
        self,
    ) -> tuple[list[Branch], list[JoinEdge], list[SemiAnti], list[str], list[dict]]:
        self._collect_unwired_inputs()
        branches, edges, anti, derived, joins = [], [], [], [], []
        for n in self.nodes.values():
            mapper = n.el.find("nodeData")
            if mapper is None:
                continue
            inputs = mapper.findall("inputTables")
            names = {t.get("name") for t in inputs}
            inner_lookups: list[tuple[TableIdentity, list[str]]] = []
            for lk in inputs[1:]:
                info = {
                    "mapper": n.name,
                    "lookup": lk.get("name"),
                    "matching_mode": lk.get("matchingMode"),
                    "lookup_mode": lk.get("lookupMode"),
                    "inner_join": lk.get("innerJoin") == "true",
                }
                joins.append(info)
                keys = [
                    e
                    for e in lk.findall("mapperTableEntries")
                    if (e.get("expression") or "").strip()
                ]
                where = f"mapper {n.name} lookup {lk.get('name')!r}"
                if not keys:
                    if lk.get("matchingMode") == "ALL_ROWS":
                        self._note(
                            f"{where}: matchingMode ALL_ROWS with no join keys is a cartesian product; no join edge"
                        )
                    else:
                        self._note(f"{where}: no join key expressions; no join edge")
                    continue
                if lk.get("matchingMode") == "ALL_ROWS":
                    self._note(
                        f"{where}: matchingMode ALL_ROWS with join keys is one-to-many; emitting equality edge"
                    )
                parsed = []
                for e in keys:
                    match = _BARE_REF.match(e.get("expression") or "")
                    canon = self._canon_input(n, match.group(1), names) if match else None
                    parsed.append((match, e, canon))
                bad = [
                    e.get("expression")
                    for match, e, canon in parsed
                    if match is None or canon is None
                ]
                ops = {(e.get("operator") or "=").strip() for _, e, _ in parsed}
                if bad or ops != {"="}:
                    self._note(
                        f"{where}: join key(s) {bad or sorted(ops)} not a bare `<input>.<column>` equality; no join edge"
                    )
                    continue
                left_tables = {canon for _, _, canon in parsed}
                if len(left_tables) != 1:
                    self._note(
                        f"{where}: keys reference several input tables {sorted(left_tables)}; no join edge"
                    )
                    continue
                left = self._mapper_side(
                    n, [(canon, match.group(2)) for match, _, canon in parsed], where
                )
                right = self._mapper_side(
                    n, [(lk.get("name"), e.get("name")) for _, e, _ in parsed], where
                )
                join_type = "inner" if info["inner_join"] else "left"
                edges.append(
                    JoinEdge(
                        left[0],
                        left[1],
                        right[0],
                        right[1],
                        join_type,
                        origin=f"{n.name}/{lk.get('name')}",
                    )
                )
                if info["inner_join"] and right[0] is not None:
                    inner_lookups.append(right)
            for index, o in enumerate(mapper.findall("outputTables")):
                if o.get("rejectInnerJoin") == "true":
                    for table, cols in inner_lookups:
                        anti.append(
                            SemiAnti(
                                "ANTI", table, cols, origin=f"{n.name}/{o.get('name')}"
                            )
                        )
                expr = (o.get("expressionFilter") or "").strip()
                if o.get("activateExpressionFilter") == "true" and expr:
                    refs: dict[str, ColumnRef] = {}
                    pred = self._java_predicate(n, expr, set(), refs)
                    if pred is None:
                        self._note(
                            f"mapper {n.name} output {o.get('name')!r} filter not decomposable; predicate_text only"
                        )
                    branches.append(
                        Branch(
                            index,
                            CONSTRUCT_KIND,
                            expr,
                            list(refs.values()),
                            pred,
                            origin=f"{n.name}/{o.get('name')}",
                        )
                    )
                for e in o.findall("mapperTableEntries"):
                    expr_e = (e.get("expression") or "").strip()
                    m = _BARE_REF.match(expr_e)
                    if (
                        expr_e
                        and not (m and m.group(1) in names)
                        and e.get("name") not in derived
                    ):
                        derived.append(e.get("name", ""))
        return branches, edges, anti, derived, joins

    def _source_named(self, name: str) -> TableIdentity | None:
        wanted = (name or "").casefold()
        if not wanted:
            return None
        for src in self.sources:
            ident = self.identities[src.name]
            aliases = {
                ident.name.casefold(),
                ident.name.split(".")[-1].casefold(),
                src.name.casefold(),
            }
            if wanted in aliases:
                return ident
        return None

    def _mapper_entry_columns(self, inp: ET.Element) -> list[MinedColumn]:
        cols = []
        seen: set[str] = set()
        for e in inp.findall("mapperTableEntries"):
            name = e.get("name") or ""
            if not name or name in seen:
                continue
            seen.add(name)
            cols.append(
                MinedColumn(
                    name, map_type(e.get("type"), e.get("length"), e.get("precision"))
                )
            )
        return cols

    def _mapper_declared_columns(self, identity: TableIdentity, node: _Node) -> list[MinedColumn]:
        aliases = {
            node.name.casefold(),
            identity.name.casefold(),
            identity.name.split(".")[-1].casefold(),
        }
        for flow in self.outgoing(node.name):
            aliases.add(flow.name.casefold())
            aliases.add(flow.metaname.casefold())
        cols: dict[str, MinedColumn] = {}
        for n in self.nodes.values():
            mapper = n.el.find("nodeData")
            if mapper is None:
                continue
            for inp in mapper.findall("inputTables"):
                if (inp.get("name") or "").casefold() not in aliases:
                    continue
                for col in self._mapper_entry_columns(inp):
                    cols.setdefault(col.name, col)
        return list(cols.values())

    def _collect_unwired_inputs(self) -> None:
        """Every mapper input with no incoming flow becomes a fallback TABLE.

        Join participants were already emitted this way; unused inputs were dropped.
        Generate cannot populate a side that has no TABLE object.
        """
        for n in self.nodes.values():
            mapper = n.el.find("nodeData")
            if mapper is None:
                continue
            for inp in mapper.findall("inputTables"):
                name = inp.get("name") or ""
                if not name or self._input_flow(n, name) is not None:
                    continue
                if self._source_named(name) is not None:
                    continue
                cols = self._mapper_entry_columns(inp)
                if not cols:
                    self._note(
                        f"mapper {n.name}: unwired input {name!r} declares no columns; no TABLE"
                    )
                    continue
                table = MinedTable(
                    TableIdentity(name, is_fallback=True),
                    cols,
                    origin=f"{n.name}/{name}",
                )
                seen = self.declared_inputs.get(name)
                if seen is not None:
                    if [(c.name, c.type) for c in seen.columns] != [
                        (c.name, c.type) for c in table.columns
                    ]:
                        self._note(
                            f"mapper {n.name}: unwired input {name!r} is declared differently "
                            f"by {seen.origin}; keeping the first declaration"
                        )
                    continue
                used = any(
                    (e.get("expression") or "").strip()
                    for e in inp.findall("mapperTableEntries")
                )
                self.declared_inputs[name] = table
                self._note(
                    f"mapper {n.name}: input {name!r} has no incoming flow; its TABLE is the "
                    f"mapper's own declaration ({len(cols)} column(s), fallback identity"
                    + ("" if used else ", unused")
                    + ")"
                )

    def _catalog_columns(self) -> list[ColumnRef]:
        out: list[ColumnRef] = []
        for src in self.sources:
            ident = self.identities[src.name]
            raw = src.schemas.get("FLOW") or []
            if raw:
                for c in raw:
                    out.append(
                        ColumnRef(
                            ident,
                            c.get("name", ""),
                            map_type(c.get("type"), c.get("length"), c.get("precision")),
                        )
                    )
            else:
                for c in self._mapper_declared_columns(ident, src):
                    out.append(ColumnRef(ident, c.name, c.type))
        for table in self.declared_inputs.values():
            for c in table.columns:
                out.append(ColumnRef(table.identity, c.name, c.type))
        return [c for c in out if c.column]

    def _unique_column_bind(self, column: str) -> ColumnRef | None:
        """Bind `column` only when exactly one emitted TABLE declares it.

        Used for warehouse idioms like `SOR._SOR_ID==4` where the prefix is not an
        inputTables name. Two tables sharing the column stay unresolved.
        """
        wanted = {column.casefold()}
        if column.startswith("_") and len(column) > 1:
            wanted.add(column[1:].casefold())
        hits: dict[tuple[str, str], ColumnRef] = {}
        for ref in self._catalog_columns():
            if ref.column.casefold() not in wanted:
                continue
            hits[(ref.table.name.casefold(), ref.column.casefold())] = ref
        if len(hits) == 1:
            return next(iter(hits.values()))
        return None

    def _mapper_side(self, node, refs: list[tuple[str, str]], where: str):
        if refs and all(self._input_flow(node, t) is None for t, _ in refs):
            return self._declared_side(node, refs, where)
        resolved = [self._resolve_ref(node, t, c) for t, c in refs]
        tables = {r.table for r in resolved if r is not None}
        if len(tables) != 1 or any(r is None for r in resolved):
            self._note(
                f"{where}: key columns do not resolve to one source table; edge side unresolved"
            )
            return None, [c for _, c in refs]
        return tables.pop(), [r.column for r in resolved]

    def _declared_side(self, node, refs: list[tuple[str, str]], where: str):
        """An unwired input's side, bound to a stated source or the mapper's own declaration."""
        names = {t for t, _ in refs}
        if len(names) != 1:
            self._note(
                f"{where}: unwired keys reference several input tables {sorted(names)}; "
                "edge side unresolved"
            )
            return None, [c for _, c in refs]
        name = next(iter(names))
        stated = self._source_named(name)
        if stated is not None:
            return stated, [c for _, c in refs]
        seen = self.declared_inputs.get(name)
        if seen is None:
            decl = next(
                (
                    t
                    for t in node.el.find("nodeData").findall("inputTables")
                    if t.get("name") == name
                ),
                None,
            )
            cols = self._mapper_entry_columns(decl) if decl is not None else []
            missing = [c for _, c in refs if c not in {x.name for x in cols}]
            if decl is None or missing:
                self._note(
                    f"{where}: unwired input {name!r} does not declare key column(s) {missing}; "
                    "edge side unresolved"
                )
                return None, [c for _, c in refs]
            seen = MinedTable(
                TableIdentity(name, is_fallback=True),
                cols,
                origin=f"{node.name}/{name}",
            )
            self.declared_inputs[name] = seen
            self._note(
                f"{where}: input {name!r} has no incoming flow; its TABLE is the mapper's own "
                f"declaration ({len(cols)} column(s), fallback identity)"
            )
        missing = [c for _, c in refs if c not in {x.name for x in seen.columns}]
        if missing:
            self._note(
                f"{where}: unwired input {name!r} does not declare key column(s) {missing}; "
                "edge side unresolved"
            )
            return None, [c for _, c in refs]
        return seen.identity, [c for _, c in refs]

    def tables(self) -> list[MinedTable]:
        out = []
        for n in self.sources:
            raw = n.schemas.get("FLOW") or []
            if raw:
                cols = [
                    MinedColumn(
                        c.get("name", ""),
                        map_type(c.get("type"), c.get("length"), c.get("precision")),
                        nullable=(c.get("nullable") or "").lower() != "false"
                        if c.get("nullable")
                        else None,
                        primary_key=(c.get("key") or "").lower() == "true"
                        if c.get("key")
                        else None,
                    )
                    for c in raw
                ]
            else:
                cols = self._mapper_declared_columns(self.identities[n.name], n)
                if cols:
                    self._note(
                        f"source {n.name}: no FLOW schema; TABLE columns taken from mapper "
                        f"declaration ({len(cols)} column(s))"
                    )
                else:
                    self._note(
                        f"source {n.name}: no FLOW schema and no mapper-declared columns; "
                        "TABLE emitted with identity only"
                    )
            out.append(MinedTable(self.identities[n.name], cols, origin=n.name))
        return out + list(self.declared_inputs.values())

    def context(self, joins: list[dict]) -> dict:
        lineage = {}
        for f in self.flows:
            cols = {}
            for c in self.flow_schema(f):
                ref = self.resolve(f, c.get("name", ""))
                origin = None if ref else self._origin_of(f, c.get("name", ""))
                cols[c.get("name", "")] = (
                    f"{ref.table.name}.{ref.column}"
                    if ref
                    else (f"computed:{origin}" if origin else None)
                )
            lineage[f.name] = cols
        return {
            "nodes": [
                {
                    "name": n.name,
                    "component": n.component,
                    "label": java_literal(n.value("LABEL")) or n.value("LABEL") or "",
                }
                for n in self.nodes.values()
            ],
            "flows": [
                {
                    "name": f.name,
                    "source": f.source,
                    "target": f.target,
                    "connector": f.connector,
                }
                for f in self.flows
            ],
            "sources": [
                {
                    "node": n.name,
                    "table": self.identities[n.name].name,
                    "is_fallback": self.identities[n.name].is_fallback,
                    "filename": java_literal(n.value("FILENAME")),
                }
                for n in self.sources
            ],
            "lookups": joins,
            "column_lineage": lineage,
        }

    def query_signals(self) -> tuple[list[Branch], list[JoinEdge], list[MinedTable]]:
        """WHERE / JOIN clauses written on a source QUERY parameter."""
        branches, edges, extra = [], [], []
        known = {self.identities[n.name].name.casefold(): self.identities[n.name] for n in self.sources}
        extra_by_name: dict[str, MinedTable] = {}
        for n in self.sources:
            sql = java_literal(n.value("QUERY"))
            if not sql:
                continue
            table = self.identities[n.name]
            where = where_text(sql)
            if where:
                refs: dict[str, ColumnRef] = {}
                pred = self._sql_predicate(n, table, where, refs)
                if pred is None:
                    self._note(
                        f"source {n.name}: QUERY WHERE {where!r} not a column-vs-literal; predicate_text only"
                    )
                branches.append(
                    Branch(
                        0,
                        CONSTRUCT_KIND,
                        where,
                        list(refs.values()),
                        pred,
                        origin=f"{n.name}/QUERY",
                    )
                )
            for left_t, left_c, right_t, right_c, join_type in equi_joins(sql):
                left_id = known.get(left_t.casefold()) or extra_by_name.get(left_t.casefold())
                right_id = known.get(right_t.casefold()) or extra_by_name.get(right_t.casefold())
                if left_id is None:
                    left_id = self._query_join_table(left_t, left_c, n.name, extra_by_name)
                elif isinstance(left_id, MinedTable):
                    left_id = left_id.identity
                if right_id is None:
                    right_id = self._query_join_table(right_t, right_c, n.name, extra_by_name)
                elif isinstance(right_id, MinedTable):
                    right_id = right_id.identity
                if isinstance(left_id, TableIdentity) and isinstance(right_id, TableIdentity):
                    edges.append(
                        JoinEdge(
                            left_id,
                            [left_c],
                            right_id,
                            [right_c],
                            join_type,
                            origin=f"{n.name}/QUERY",
                        )
                    )
        extra = list(extra_by_name.values())
        return branches, edges, extra

    def _query_join_table(
        self,
        name: str,
        column: str,
        origin: str,
        extra_by_name: dict[str, MinedTable],
    ) -> TableIdentity:
        seen = extra_by_name.get(name.casefold())
        if seen is None:
            seen = MinedTable(
                TableIdentity(name),
                [MinedColumn(column, T.UNKNOWN)],
                origin=f"{origin}/QUERY",
            )
            extra_by_name[name.casefold()] = seen
            self._note(
                f"source {origin}: QUERY joins {name!r}, which is not a job source; "
                f"TABLE emitted with key column(s) only"
            )
        elif column not in {c.name for c in seen.columns}:
            seen.columns.append(MinedColumn(column, T.UNKNOWN))
        return seen.identity

    def _sql_predicate(
        self,
        node: _Node,
        table: TableIdentity,
        text: str,
        refs: dict[str, ColumnRef],
    ):
        schema = {c.get("name", "") for c in node.schemas.get("FLOW", [])}

        def qualify(ident: str) -> str | None:
            col = ident.split(".")[-1]
            prefix = ident.split(".")[0] if "." in ident else None
            if prefix and prefix.casefold() not in {
                table.name.casefold(),
                table.name.split(".")[-1].casefold(),
                node.name.casefold(),
            }:
                return None
            if col not in schema:
                self._note(
                    f"source {node.name}: QUERY WHERE operand {ident!r} is not a FLOW column; atom kept bare"
                )
                return None
            refs[ident] = ColumnRef(table, col, map_type(None))
            # type from schema if present
            raw = next(
                (c for c in node.schemas.get("FLOW", []) if c.get("name") == col),
                None,
            )
            if raw is not None:
                refs[ident] = ColumnRef(
                    table,
                    col,
                    map_type(raw.get("type"), raw.get("length"), raw.get("precision")),
                )
            return f"{table.name}.{col}"

        for ident in operand_columns(text, SQL_DIALECT):
            qualify(ident)
        return decompose(text, SQL_DIALECT, qualify)

    def join_key_edges(self) -> list[JoinEdge]:
        """tJoin (JOIN_KEY table, two incoming flows, no mapper payload)."""
        edges = []
        for n in self.nodes.values():
            if "JOIN_KEY" not in n.params or n.el.find("nodeData") is not None:
                continue
            ins = self.incoming(n.name)
            if len(ins) < 2:
                self._note(
                    f"join {n.name}: JOIN_KEY present but {len(ins)} incoming flow(s); no edge"
                )
                continue
            rows = _table_rows(n.params["JOIN_KEY"])
            pairs = []
            for row in rows:
                left = row.get("KEY") or row.get("INPUT_COLUMN")
                right = row.get("KEY_COLUMN") or row.get("LOOKUP_COLUMN")
                if left and right:
                    pairs.append((left, right))
            if not pairs:
                self._note(f"join {n.name}: JOIN_KEY has no KEY/KEY_COLUMN pairs; no edge")
                continue
            inner = (
                (n.value("USE_INNER_JOIN") or n.value("INNER_JOIN") or "")
                .strip()
                .lower()
                == "true"
            )
            main, lookup = ins[0], ins[1]
            left = self._side_from_flow(main, [p[0] for p in pairs], f"join {n.name} main")
            right = self._side_from_flow(
                lookup, [p[1] for p in pairs], f"join {n.name} lookup"
            )
            edges.append(
                JoinEdge(
                    left[0],
                    left[1],
                    right[0],
                    right[1],
                    "inner" if inner else "left",
                    origin=n.name,
                )
            )
        return edges

    def _side_from_flow(self, flow: _Flow, columns: list[str], where: str):
        src = self.nodes.get(flow.source)
        if src is not None and src.name in self.identities:
            return self.identities[src.name], columns
        resolved = [self.resolve(flow, c) for c in columns]
        tables = {r.table for r in resolved if r is not None}
        if len(tables) != 1 or any(r is None for r in resolved):
            self._note(f"{where}: columns {columns} do not resolve to one source table")
            return None, columns
        return tables.pop(), [r.column for r in resolved]

    def apply_unique_keys(self, tables: list[MinedTable]) -> list[MinedTable]:
        names: list[str] = []
        for n in self.nodes.values():
            for param in ("SOURCE_KEYS", "UNIQUE_KEY"):
                for row in _table_rows(n.params.get(param)):
                    names += [
                        row[k]
                        for k in ("NAME", "KEY", "COLUMN", "INPUT_COLUMN")
                        if row.get(k)
                    ]
        wanted = {n.casefold() for n in names if n}
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
                    True if c.name.casefold() in wanted else c.unique,
                )
                for c in table.columns
            ]
            if any(c.unique and not c.primary_key for c in cols) and not any(
                c.unique for c in table.columns
            ):
                self._note(
                    f"table {table.identity.name}: SOURCE_KEYS/UNIQUE_KEY marked "
                    f"{[c.name for c in cols if c.unique]} unique"
                )
            out.append(MinedTable(table.identity, cols, table.origin))
        return out

    def mine(self) -> MiningResult:
        branches, edges, anti, mapper_derived, joins = self.mapper_signals()
        q_branches, q_edges, q_tables = self.query_signals()
        derived: list[str] = []
        for jr in self.java_rows.values():
            derived += [c for c in jr.derived if c not in derived]
        derived += [c for c in mapper_derived if c not in derived]
        branches = self.filter_branches() + branches + q_branches
        edges = edges + q_edges + self.join_key_edges()
        for i, b in enumerate(branches):
            b.branch_id = i  # unique per package: the consumer keys rows by `<object>#<branch_id>`
        package = MinedPackage(
            object_name=self.object_name,
            branches=branches,
            edges=edges,
            semi_anti=anti,
            derived_columns=derived,
        )
        tables = self.apply_unique_keys(self.tables() + q_tables)
        context = self.context(joins)
        if self.ir is not None:
            self._note(
                "ir: supplied but not consumed by the talend adapter (document is the only source of facts)"
            )
        return MiningResult(
            platform=PLATFORM,
            document=str(self.path),
            package=package,
            tables=tables,
            diagnostics=self.diagnostics,
            inputs={"document": True, "ir": False, "platform_table": False},
            context=context,
        )


def mine(
    path: str | Path, object_name: str | None = None, ir_path: str | Path | None = None
) -> MiningResult:
    ir = json.loads(Path(ir_path).read_text(encoding="utf-8")) if ir_path else None
    return TalendMiner(path, object_name, ir).mine()
