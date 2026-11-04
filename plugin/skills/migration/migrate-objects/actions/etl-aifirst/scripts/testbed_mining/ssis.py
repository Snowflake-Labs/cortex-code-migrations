"""SSIS (.dtsx) adapter: data-flow XML -> neutral MiningResult.

TABLE-INDEPENDENT ON PURPOSE. Mining reads the document through the AI-First XML
front-end (`docmodel.XmlDocument`) and recognizes components by STRUCTURE, never by
`platform_ssis.json`. That way the same code runs for an SSIS document forced through
AI-First with no platform table staged. The table-assisted IR is lossy for mining:
it keeps one conditional-split arm, and it has no lookup or merge-join keys. So the IR
is only a cross-check (`ir=`), never a source of facts.

Structural rules (each one cites what the document states, not a component class name):
  source       component with no inputs and a non-error output; its table is the single
               FROM of SqlCommand (AccessMode 2), else OpenRowset, else -- stated by
               nothing -- the component's own name, flagged as a fallback identity
  branch       non-error, non-default output carrying a FriendlyExpression/Expression
  derived      output column carrying a FriendlyExpression/Expression
  lookup edge  input columns carrying JoinToReferenceColumn; NoMatchBehavior=1 -> ANTI
  lookup table the lookup's reference (single FROM of SqlCommand, else OpenRowset) is a
               TABLE too, so the edge and ANTI have a physical endpoint. Its columns are
               the ReferenceMetadataXml referenceColumns when stated (typed by their
               DT_* code); otherwise the join keys (typed by the probing input column)
               plus every CopyFromReferenceColumn (typed by its output column)
  merge edge   a component with exactly two inputs whose columns carry
               cachedSortKeyPosition, plus a JoinType property
Column lineage follows `lineageId` (sync pass-through needs no hop) and any
`#{refId}` property (async bridges such as merge-join InputColumnID). A computed
column does not resolve, so its predicate atom stays bare.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import docmodel

from testbed_mining import types as T
from testbed_mining.artifacts import name_parts
from testbed_mining.model import (
    Branch,
    ColumnRef,
    JoinEdge,
    MinedColumn,
    MinedPackage,
    MinedTable,
    MiningResult,
    SemiAnti,
    TableIdentity,
)
from testbed_mining.predicate import Dialect, decompose, operand_columns
from testbed_mining.sqltext import from_table

PLATFORM = "ssis"
DTS_NS = "www.microsoft.com/SqlServer/Dts"
_D = f"{{{DTS_NS}}}"
CONSTRUCT_KIND = "CONDITIONAL_SPLIT"

DIALECT = Dialect(
    comparisons={"==": "=", "!=": "<>", "<=": "<=", ">=": ">=", "<": "<", ">": ">"},
    and_tokens=frozenset({"&&"}),
    or_tokens=frozenset({"||"}),
    identifier_quotes=(("[", "]"),),
    string_quotes=('"',),
)

_JOIN_TYPES = {"0": "full", "1": "left", "2": "inner"}
_LINEAGE_REF = re.compile(r"^#\{(.+)\}$")


def sniff(path: str | Path) -> bool:
    try:
        for _, el in ET.iterparse(str(path), events=("start",)):
            return el.tag.startswith(_D)
    except (ET.ParseError, OSError):
        return False
    return False


def map_type(
    code: str | None,
    precision: str | None = None,
    scale: str | None = None,
    length: str | None = None,
) -> T.TypeInfo:
    code = (code or "").strip()
    p = int(precision) if precision and precision.isdigit() else None
    s = int(scale) if scale and scale.isdigit() else None
    if re.fullmatch(r"u?i[1248]", code):
        return T.make_type("NUMBER", T.INTEGER)
    if code in ("r4", "r8"):
        return T.make_type("FLOAT", T.NUMBER)
    if code == "cy":
        return T.make_type("NUMBER", T.NUMBER)
    if code in ("numeric", "decimal"):
        return T.make_type("NUMBER", T.NUMBER, p, s)
    if code in ("wstr", "str", "text", "ntext", "guid"):
        n = int(length) if length and length.isdigit() and int(length) > 0 else None
        return T.make_type("VARCHAR", T.STRING, n)
    if code == "bool":
        return T.make_type("BOOLEAN", T.BOOLEAN)
    if code in ("dbDate", "date"):
        return T.make_type("DATE", T.DATE)
    if code.startswith("dbTimeStamp") or code == "filetime":
        return T.make_type("TIMESTAMP", T.DATE)
    if code in ("dbTime", "dbTime2"):
        return T.make_type("TIME", T.DATE)
    if code in ("bytes", "image"):
        return T.make_type("BINARY", T.BINARY)
    return T.UNKNOWN


# ReferenceMetadataXml spells types as DT_* constants; map them onto the pipeline codes map_type reads.
_DT_CODES = {
    f"DT_{code.upper()}": code
    for code in (
        *("i1", "i2", "i4", "i8", "ui1", "ui2", "ui4", "ui8", "r4", "r8", "cy"),
        *("numeric", "decimal", "str", "wstr", "text", "ntext", "guid", "bool"),
        *("date", "dbDate", "dbTime", "dbTime2", "dbTimeStamp", "dbTimeStamp2"),
        *("dbTimeStampOffset", "filetime", "bytes", "image"),
    )
}


def _props(el: ET.Element) -> dict[str, str]:
    return {
        p.get("name", ""): (p.text or "") for p in el.findall("properties/property")
    }


def _expression(props: dict[str, str]) -> str:
    return (props.get("FriendlyExpression") or props.get("Expression") or "").strip()


@dataclass
class _OutCol:
    component: ET.Element
    el: ET.Element
    props: dict[str, str]


class SsisMiner:
    def __init__(
        self, path: str | Path, object_name: str | None = None, ir: dict | None = None
    ):
        self.path = Path(path)
        self.doc = docmodel.XmlDocument(str(self.path), {"kind": "XML"})
        self.root = self.doc.root
        self.object_name = object_name or self.path.name
        self.ir = ir
        self.diagnostics: list[str] = []
        self.components = list(self.root.iter("component"))
        self.databases = self._connection_databases()
        self.out_cols: dict[str, _OutCol] = {}
        self.in_cols: dict[str, ET.Element] = {}
        for c in self.components:
            for o in c.findall("outputs/output"):
                for oc in o.findall("outputColumns/outputColumn"):
                    entry = _OutCol(c, oc, _props(oc))
                    for key in (oc.get("refId"), oc.get("lineageId")):
                        if key:
                            self.out_cols[key] = entry
            for ic in c.findall("inputs/input/inputColumns/inputColumn"):
                if ic.get("refId"):
                    self.in_cols[ic.get("refId")] = ic
        self.sources = [c for c in self.components if self._is_source(c)]
        self.identities = {c.get("refId"): self._identity(c) for c in self.sources}

    # ---- document structure -------------------------------------------------------------

    def _connection_databases(self) -> dict[str, str]:
        out = {}
        for cm in self.root.iter(f"{_D}ConnectionManager"):
            ref = cm.get(f"{_D}refId")
            inner = cm.find(f"{_D}ObjectData/{_D}ConnectionManager")
            cs = inner.get(f"{_D}ConnectionString", "") if inner is not None else ""
            m = re.search(r"(?:^|;)\s*Initial Catalog\s*=\s*([^;]+)", cs, re.IGNORECASE)
            if ref and m:
                out[ref] = m.group(1).strip()
        return out

    @staticmethod
    def _good_outputs(c: ET.Element) -> list[ET.Element]:
        return [
            o
            for o in c.findall("outputs/output")
            if o.get("isErrorOut", "").lower() != "true"
        ]

    def _is_source(self, c: ET.Element) -> bool:
        return not c.findall("inputs/input") and any(
            o.findall("outputColumns/outputColumn") for o in self._good_outputs(c)
        )

    def _identity(self, c: ET.Element) -> TableIdentity:
        props = _props(c)
        sql, rowset, mode = (
            props.get("SqlCommand", ""),
            props.get("OpenRowset", "").strip(),
            props.get("AccessMode", ""),
        )
        name = from_table(sql) if mode == "2" else None
        name = name or rowset or from_table(sql)
        db = None
        for conn in c.findall("connections/connection"):
            db = db or self.databases.get(conn.get("connectionManagerID", ""))
        if not name:
            return TableIdentity(name=c.get("name", ""), is_fallback=True)
        return TableIdentity(name=name, database=db)

    # ---- lineage ---------------------------------------------------------------------------

    def resolve(self, lineage: str | None, depth: int = 0) -> ColumnRef | None:
        """Lineage id -> the source-table column it originates from, or None when computed."""
        entry = self.out_cols.get(lineage or "")
        if entry is None or depth > 64:
            return None
        oc, comp = entry.el, entry.component
        if _expression(entry.props):
            return None
        if comp.get("refId") in self.identities:
            t = map_type(
                oc.get("dataType"),
                oc.get("precision"),
                oc.get("scale"),
                oc.get("length"),
            )
            return ColumnRef(self.identities[comp.get("refId")], oc.get("name", ""), t)
        for value in entry.props.values():
            m = _LINEAGE_REF.match(value.strip())
            if m:
                target = m.group(1)
                ic = self.in_cols.get(target)
                return self.resolve(
                    ic.get("lineageId") if ic is not None else target, depth + 1
                )
        ref_col = entry.props.get("CopyFromReferenceColumn")
        if ref_col:
            t = map_type(
                oc.get("dataType"),
                oc.get("precision"),
                oc.get("scale"),
                oc.get("length"),
            )
            return ColumnRef(self._reference_identity(comp), ref_col, t)
        return None

    def _reference_identity(self, c: ET.Element) -> TableIdentity:
        props = _props(c)
        name = (
            from_table(props.get("SqlCommand", ""))
            or props.get("OpenRowset", "").strip()
        )
        if not name:
            return TableIdentity(name=c.get("name", ""), is_fallback=True)
        db = None
        for conn in c.findall("connections/connection"):
            db = db or self.databases.get(conn.get("connectionManagerID", ""))
        return TableIdentity(name=name, database=db)

    # ---- signals ---------------------------------------------------------------------------

    def branches(self) -> list[Branch]:
        out: list[Branch] = []
        for c in self.components:
            if not c.findall("inputs/input"):
                continue
            by_name = {
                ic.get("cachedName"): ic
                for ic in c.findall("inputs/input/inputColumns/inputColumn")
            }
            for index, o in enumerate(self._good_outputs(c)):
                props = _props(o)
                text = _expression(props)
                if not text or props.get("IsDefaultOut", "").lower() == "true":
                    continue
                refs: dict[str, ColumnRef] = {}
                for name in operand_columns(text, DIALECT):
                    ic = by_name.get(name)
                    ref = self.resolve(ic.get("lineageId")) if ic is not None else None
                    if ref is not None:
                        refs[name] = ref
                    else:
                        self.diagnostics.append(
                            f"branch operand {name!r} in {o.get('refId')} does not resolve to a source column; atom kept bare"
                        )

                def qualify(col: str, refs: dict[str, ColumnRef] = refs) -> str | None:
                    r = refs.get(col)
                    return f"{r.table.name}.{r.column}" if r else None

                order = props.get("EvaluationOrder", "")
                predicate = decompose(text, DIALECT, qualify)
                if predicate is None:
                    self.diagnostics.append(
                        f"branch {o.get('refId')} predicate not decomposable; predicate_text only"
                    )
                out.append(
                    Branch(
                        branch_id=int(order) if order.lstrip("-").isdigit() else index,
                        construct_kind=CONSTRUCT_KIND,
                        predicate_text=text,
                        columns=list(refs.values()),
                        predicate=predicate,
                        origin=o.get("refId", ""),
                    )
                )
        return sorted(
            out, key=lambda b: (b.origin.rsplit(".Outputs[", 1)[0], b.branch_id)
        )

    def derived_columns(self) -> list[str]:
        out: list[str] = []
        for c in self.components:
            for o in self._good_outputs(c):
                for oc in o.findall("outputColumns/outputColumn"):
                    if _expression(_props(oc)) and oc.get("name") not in out:
                        out.append(oc.get("name", ""))
        return out

    def _side(
        self, input_columns: list[ET.Element], what: str
    ) -> tuple[TableIdentity | None, list[str]]:
        refs = [self.resolve(ic.get("lineageId")) for ic in input_columns]
        tables = {r.table for r in refs if r is not None}
        if len(tables) != 1 or any(r is None for r in refs):
            self.diagnostics.append(
                f"{what}: key columns do not resolve to one source table; edge side unresolved"
            )
            return None, [ic.get("cachedName", "") for ic in input_columns]
        return tables.pop(), [r.column for r in refs]

    def lookups(self) -> tuple[list[JoinEdge], list[SemiAnti]]:
        edges, anti = [], []
        for c in self.components:
            probes = [
                (ic, _props(ic)["JoinToReferenceColumn"])
                for ic in c.findall("inputs/input/inputColumns/inputColumn")
                if _props(ic).get("JoinToReferenceColumn")
            ]
            if not probes:
                continue
            left, left_cols = self._side(
                [ic for ic, _ in probes], f"lookup {c.get('refId')}"
            )
            right = self._reference_identity(c)
            right_cols = [ref for _, ref in probes]
            edges.append(
                JoinEdge(
                    left,
                    left_cols,
                    right,
                    right_cols,
                    "inner",
                    origin=c.get("refId", ""),
                )
            )
            if _props(c).get("NoMatchBehavior", "").strip() == "1":
                anti.append(
                    SemiAnti("ANTI", right, right_cols, origin=c.get("refId", ""))
                )
        return edges, anti

    def merge_joins(self) -> list[JoinEdge]:
        edges = []
        for c in self.components:
            inputs = c.findall("inputs/input")
            props = _props(c)
            if len(inputs) != 2 or "JoinType" not in props:
                continue
            keyed = [
                sorted(
                    (
                        ic
                        for ic in i.findall("inputColumns/inputColumn")
                        if (ic.get("cachedSortKeyPosition") or "0").lstrip("-")
                        not in ("", "0")
                    ),
                    key=lambda ic: abs(int(ic.get("cachedSortKeyPosition"))),
                )
                for i in inputs
            ]
            if not all(keyed):
                continue
            n = props.get("NumKeyColumns", "")
            if n.isdigit():
                keyed = [k[: int(n)] for k in keyed]
            # The document states sides by input name; fall back to declaration order.
            order = sorted(
                range(2),
                key=lambda i: (
                    0 if "left" in (inputs[i].get("name") or "").lower() else 1
                ),
            )
            (lt, lc), (rt, rc) = (
                self._side(keyed[i], f"merge join {c.get('refId')}") for i in order
            )
            jt = _JOIN_TYPES.get(props["JoinType"].strip(), "inner")
            edges.append(JoinEdge(lt, lc, rt, rc, jt, origin=c.get("refId", "")))
        return edges

    @staticmethod
    def _out_type(el: ET.Element) -> T.TypeInfo:
        return map_type(
            el.get("dataType"), el.get("precision"), el.get("scale"), el.get("length")
        )

    def _stated_reference_columns(self, c: ET.Element) -> list[MinedColumn] | None:
        """ReferenceMetadataXml's referenceColumns, or None when the lookup does not state them."""
        xml = _props(c).get("ReferenceMetadataXml", "").strip()
        if not xml:
            return None
        try:
            meta = ET.fromstring(xml)
        except ET.ParseError:
            self.diagnostics.append(
                f"lookup {c.get('refId')}: ReferenceMetadataXml does not parse; reference columns taken from the join"
            )
            return None
        cols = [
            MinedColumn(
                rc.get("name", ""),
                map_type(
                    _DT_CODES.get((rc.get("dataType") or "").upper(), ""),
                    rc.get("precision"),
                    rc.get("scale"),
                    rc.get("length"),
                ),
            )
            for rc in meta.iter("referenceColumn")
            if rc.get("name")
        ]
        return cols or None

    def _inferred_reference_columns(self, c: ET.Element) -> list[MinedColumn]:
        """Join keys typed by the probing input column, then copied-out reference columns."""
        cols: dict[str, MinedColumn] = {}
        for ic in c.findall("inputs/input/inputColumns/inputColumn"):
            ref_col = _props(ic).get("JoinToReferenceColumn")
            if ref_col and ref_col not in cols:
                src = self.out_cols.get(ic.get("lineageId") or "")
                t = (
                    self._out_type(src.el)
                    if src
                    else map_type(ic.get("cachedDataType"))
                )
                cols[ref_col] = MinedColumn(ref_col, t)
        for o in self._good_outputs(c):
            for oc in o.findall("outputColumns/outputColumn"):
                ref_col = _props(oc).get("CopyFromReferenceColumn")
                if ref_col and ref_col not in cols:
                    cols[ref_col] = MinedColumn(ref_col, self._out_type(oc))
        return list(cols.values())

    def reference_tables(self) -> list[MinedTable]:
        """One TABLE per lookup reference, so its edge and ANTI resolve to a physical endpoint."""
        out: dict[TableIdentity, MinedTable] = {}
        for c in self.components:
            if not any(
                _props(ic).get("JoinToReferenceColumn")
                for ic in c.findall("inputs/input/inputColumns/inputColumn")
            ):
                continue
            identity = self._reference_identity(c)
            if identity.is_fallback:
                self.diagnostics.append(
                    f"lookup {c.get('refId')}: no reference SqlCommand/OpenRowset; table named after the component"
                )
            cols = self._stated_reference_columns(c)
            if cols is None:
                cols = self._inferred_reference_columns(c)
                self.diagnostics.append(
                    f"lookup {c.get('refId')}: no ReferenceMetadataXml; reference table {identity.name!r} "
                    "carries only the join keys and copied columns"
                )
            existing = out.get(identity)
            if existing is None:
                out[identity] = MinedTable(identity, cols, origin=c.get("refId", ""))
            else:  # several lookups on one reference: union of what each states
                have = {col.name.lower() for col in existing.columns}
                existing.columns += [
                    col for col in cols if col.name.lower() not in have
                ]
        sources = {t.identity for t in self._source_tables()}
        return [t for i, t in out.items() if i not in sources]

    def tables(self) -> list[MinedTable]:
        return self._source_tables() + self.reference_tables()

    def _source_tables(self) -> list[MinedTable]:
        out = []
        for c in self.sources:
            cols = []
            for o in self._good_outputs(c):
                for oc in o.findall("outputColumns/outputColumn"):
                    cols.append(
                        MinedColumn(
                            oc.get("name", ""),
                            map_type(
                                oc.get("dataType"),
                                oc.get("precision"),
                                oc.get("scale"),
                                oc.get("length"),
                            ),
                        )
                    )
            out.append(
                MinedTable(
                    self.identities[c.get("refId")], cols, origin=c.get("refId", "")
                )
            )
        return out

    def _cross_check_ir(self) -> None:
        nodes = {n.get("id"): n for n in (self.ir or {}).get("nodes", [])}
        for ref, identity in self.identities.items():
            node = nodes.get(ref)
            if node is None:
                self.diagnostics.append(f"ir: no node for source {ref}")
                continue
            ir_table = ((node.get("element") or {}).get("TableName") or "").strip()
            if not ir_table:
                continue
            a, b = name_parts(ir_table), name_parts(identity.name)
            n = min(len(a), len(b))
            verdict = "agrees" if n and a[-n:] == b[-n:] else "DISAGREES"
            self.diagnostics.append(
                f"ir: source {ref} TableName {ir_table!r} {verdict} with mined {identity.name!r}"
            )

    def mine(self) -> MiningResult:
        edges, anti = self.lookups()
        package = MinedPackage(
            object_name=self.object_name,
            branches=self.branches(),
            edges=self.merge_joins() + edges,
            semi_anti=anti,
            derived_columns=self.derived_columns(),
        )
        if self.ir is not None:
            self._cross_check_ir()
        return MiningResult(
            platform=PLATFORM,
            document=str(self.path),
            package=package,
            tables=self.tables(),
            diagnostics=self.diagnostics,
            inputs={
                "document": True,
                "ir": self.ir is not None,
                "platform_table": False,
            },
        )


def mine(
    path: str | Path, object_name: str | None = None, ir_path: str | Path | None = None
) -> MiningResult:
    ir = json.loads(Path(ir_path).read_text(encoding="utf-8")) if ir_path else None
    return SsisMiner(path, object_name, ir).mine()
