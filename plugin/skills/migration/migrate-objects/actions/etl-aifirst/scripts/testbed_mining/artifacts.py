"""Neutral serialization + on-disk placement of `*.testbed.json`, and the SQL-DDL
de-duplication seam.

PLACEMENT. The Testbed reader resolves `<project>/<CodeUnit.Files.Artifacts.Path>/testbed/`
and fails AmbiguousObject on more than one `*.testbed.json` there. So every object gets
its OWN artifacts dir, mirroring the native per-object layout:

    <root>/packages/<slug>/testbed/<slug>.testbed.json   object_type PACKAGE
    <root>/tables/<slug>/testbed/<slug>.testbed.json     object_type TABLE
    <root>/testbed-mining.json                           manifest (not read by Testbed)

Registering those dirs as a code unit's `files.artifacts.path` is the CUR's job and is
NOT done here.

DE-DUP. A source table whose DDL also arrived as SQL already has an authoritative TABLE
artifact (real keys, constraints, defaults). Emitting a second, weaker one from the ETL
reader would give `scai testbed init` two specs for one table. `ExistingTables` is the
seam: whoever knows the SQL-side tables hands them in; mining only asks `contains()`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from testbed_mining.model import (
    Branch,
    ColumnRef,
    JoinEdge,
    MinedPackage,
    MinedTable,
    MiningResult,
    PredicateNode,
    SemiAnti,
    TableIdentity,
)
from testbed_mining.types import TypeInfo

MANIFEST_NAME = "testbed-mining.json"
CUR_HINTS_NAME = "testbed-cur-hints.json"
ARTIFACT_SUFFIX = ".testbed.json"


def cur_pointer(object_type: str, slug: str) -> str:
    """Project-relative `files.artifacts.path` matching convert/etl-aifirst/SKILL.md.

    PACKAGE -> artifacts/etl/<slug>   (the ETL unit convert stamps)
    TABLE   -> artifacts/tables/<slug> (native-like sibling; needs its own CUR unit)
    """
    kind = "etl" if object_type.upper() == "PACKAGE" else "tables"
    return f"artifacts/{kind}/{slug}"


def name_parts(name: str) -> tuple[str, ...]:
    """`[db].[dbo].[T]`, `"dbo"."T"`, `dbo.T` -> ('db','dbo','t') -- quote- and case-insensitive."""
    parts = re.findall(r'\[([^\]]*)\]|"([^"]*)"|`([^`]*)`|([^.\[\]"`]+)', name)
    return tuple(
        next(p for p in groups if p).strip().lower() for groups in parts if any(groups)
    )


class ExistingTables:
    """Tables that already have an authoritative (SQL DDL) TABLE artifact."""

    def __init__(self, names: Iterable[str] = ()):
        self._names = [name_parts(n) for n in names if name_parts(n)]

    @classmethod
    def from_names(cls, names: Iterable[str]) -> ExistingTables:
        return cls(names)

    @classmethod
    def from_artifact_dirs(cls, dirs: Iterable[Path]) -> ExistingTables:
        names: list[str] = []
        for d in dirs:
            for f in sorted(Path(d).rglob(f"*{ARTIFACT_SUFFIX}")):
                try:
                    doc = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if str(doc.get("object_type") or "").upper() == "TABLE":
                    name = doc.get("object") or doc.get("table")
                    if name:
                        names.append(name)
        return cls(names)

    def merged(self, other: ExistingTables) -> ExistingTables:
        merged = ExistingTables()
        merged._names = self._names + other._names
        return merged

    def contains(self, identity: TableIdentity) -> bool:
        # A fallback identity is the reading element's name, not a table; it can't collide with DDL.
        if identity.is_fallback:
            return False
        mined = name_parts(identity.name)
        if not mined:
            return False
        db = identity.database.lower() if identity.database else None
        for known in self._names:
            n = min(len(known), len(mined))
            if known[-n:] != mined[-n:]:
                continue
            # A database-qualified DDL name only matches when the ETL side binds the same catalog (or none).
            if (
                len(known) >= 3
                and len(mined) < 3
                and db is not None
                and known[-3] != db
            ):
                continue
            return True
        return False


def _slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", ".".join(name_parts(name)) or name).strip(
        "._"
    )
    return slug or "object"


def _type_flags(t: TypeInfo) -> dict:
    return {
        "is_integer": t.is_integer,
        "is_number": t.is_number,
        "is_string": t.is_string,
        "is_date": t.is_date,
        "is_boolean": t.is_boolean,
        "is_binary": t.is_binary,
    }


def _predicate(node: PredicateNode) -> dict:
    out: dict = {"kind": node.kind}
    if node.kind == "atom":
        out.update(
            columns=list(node.columns or []),
            operator=node.operator,
            values=list(node.values or []),
        )
    else:
        out["children"] = [_predicate(c) for c in node.children or []]
    return out


def _column_ref(ref: ColumnRef, qualify: bool) -> dict:
    out = {
        "column": ref.column,
        "table": ref.table.rendered(qualify),
        "type": ref.type.name,
        **_type_flags(ref.type),
    }
    if ref.type.scale is not None and not ref.type.is_integer:
        out["scale"] = ref.type.scale
    return out


def _branch(b: Branch, qualify: bool) -> dict:
    out = {
        "branch_id": b.branch_id,
        "construct_kind": b.construct_kind,
        "line": b.line,
        "predicate_text": b.predicate_text,
        "columns": [_column_ref(c, qualify) for c in b.columns],
    }
    if b.predicate is not None:
        out["predicate"] = _predicate(b.predicate)
    return out


def _edge(e: JoinEdge, qualify: bool) -> dict:
    return {
        "left_table": e.left_table.rendered(qualify),
        "left_columns": list(e.left_columns),
        "right_table": e.right_table.rendered(qualify),
        "right_columns": list(e.right_columns),
        "join_type": e.join_type,
        "is_anti": e.is_anti,
    }


def _semi_anti(s: SemiAnti, qualify: bool) -> dict:
    return {
        "kind": s.kind,
        "table": s.table.rendered(qualify),
        "columns": list(s.columns),
    }


def package_artifact(pkg: MinedPackage, qualify: bool = False) -> dict:
    # ArtifactEdge/ArtifactSemiAntiJoin tables are non-nullable on the reader; an unresolved side is dropped
    # here rather than emitted as null (the adapter records it as a diagnostic).
    return {
        "object": pkg.object_name,
        "object_type": pkg.object_type,
        "branches": [_branch(b, qualify) for b in pkg.branches],
        "predicates": [],
        "edges": [
            _edge(e, qualify) for e in pkg.edges if e.left_table and e.right_table
        ],
        "assignments": [],
        "semi_anti": [_semi_anti(s, qualify) for s in pkg.semi_anti if s.table],
        # Not read by the current TestbedArtifact model; kept for parity with the native emitter.
        "derived_columns": list(pkg.derived_columns),
    }


def table_artifact(table: MinedTable, qualify: bool = False) -> dict:
    columns = []
    for c in table.columns:
        col = {
            "name": c.name,
            "type": c.type.name,
            **_type_flags(c.type),
            # Unless the document declares them, these are honest unknowns, not declared facts.
            "nullable": True if c.nullable is None else c.nullable,
            "primary_key": bool(c.primary_key),
            "foreign_key": False,
            "unique": bool(c.unique),
            "check": False,
            "has_default": False,
        }
        if c.type.precision is not None:
            col["precision"] = c.type.precision
        if c.type.scale is not None:
            col["scale"] = c.type.scale
        columns.append(col)
    return {
        "object": table.identity.rendered(qualify),
        "object_type": "TABLE",
        "columns": columns,
        "primary_key": [c.name for c in table.columns if c.primary_key],
    }


@dataclass
class WriteReport:
    root: Path
    written: list[dict]
    suppressed: list[dict]
    manifest_path: Path


def _remove_previous(root: Path) -> None:
    """Only files a previous run of THIS writer listed are removed; nothing else under root is touched."""
    manifest = root / MANIFEST_NAME
    if not manifest.is_file():
        return
    try:
        previous = json.loads(manifest.read_text(encoding="utf-8"))
    except ValueError:
        return
    for entry in previous.get("artifacts", []):
        p = root / entry.get("path", "")
        if p.is_file() and p.name.endswith(ARTIFACT_SUFFIX):
            p.unlink()


def write_artifacts(
    result: MiningResult,
    root: Path,
    existing: ExistingTables | None = None,
    qualify_with_database: bool = False,
) -> WriteReport:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    _remove_previous(root)
    existing = existing or ExistingTables()
    written: list[dict] = []
    suppressed: list[dict] = []
    used: set[str] = set()

    def place(kind_dir: str, name: str, payload: dict, object_type: str) -> None:
        slug = base = _slug(name)
        i = 2
        while f"{kind_dir}/{slug}" in used:
            slug, i = f"{base}-{i}", i + 1
        used.add(f"{kind_dir}/{slug}")
        artifacts_dir = Path(kind_dir) / slug
        rel = artifacts_dir / "testbed" / f"{slug}{ARTIFACT_SUFFIX}"
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        written.append(
            {
                "object": payload["object"],
                "object_type": object_type,
                "artifacts_path": artifacts_dir.as_posix(),
                "path": rel.as_posix(),
            }
        )

    if result.package.has_signal():
        # The document's file extension is not part of the object's identity on disk.
        place(
            "packages",
            re.sub(r"\.[A-Za-z0-9]+$", "", result.package.object_name),
            package_artifact(result.package, qualify_with_database),
            "PACKAGE",
        )
    for table in result.tables:
        name = table.identity.rendered(qualify_with_database)
        if existing.contains(table.identity):
            suppressed.append(
                {
                    "object": name,
                    "reason": "authoritative SQL DDL TABLE artifact exists",
                    "origin": table.origin,
                }
            )
            continue
        place("tables", name, table_artifact(table, qualify_with_database), "TABLE")

    manifest = {
        "platform": result.platform,
        "document": result.document,
        "inputs": result.inputs,
        "qualify_with_database": qualify_with_database,
        "artifacts": written,
        "suppressed_tables": suppressed,
        "diagnostics": result.diagnostics,
    }
    if result.context:
        manifest["source_context"] = result.context
    manifest_path = root / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    write_cur_hints(root, written)
    return WriteReport(
        root=root, written=written, suppressed=suppressed, manifest_path=manifest_path
    )


def write_cur_hints(root: Path, written: list[dict]) -> Path:
    """Sidecar listing the update_registry calls convert / a POC stamp should make.

    `update_registry` can write `files.artifacts.path`. Init still reads one artifact per CUR unit from
    `<project>/<that path>/testbed/*.testbed.json`. This file does not edit the
    registry; it is the map an agent or `place_for_cur` uses.
    """
    pointers = []
    for a in written:
        slug = Path(a["artifacts_path"]).name
        rel = cur_pointer(a["object_type"], slug)
        pointers.append(
            {
                "object": a["object"],
                "object_type": a["object_type"],
                "mining_path": a["artifacts_path"],
                "files.artifacts.path": rel,
                "update_registry": {
                    "field": "files.artifacts.path",
                    "status": rel,
                },
            }
        )
    payload = {
        "note": (
            "scai testbed init joins projectRoot + CodeUnit.Files.Artifacts.Path "
            "and reads the single *.testbed.json under that dir/testbed/. Convert "
            "skill stamps artifacts/etl/<PACKAGE> on the kind:etl unit. TABLE "
            "objects need their own CUR units (native SQL) or they are skipped."
        ),
        "pointers": pointers,
    }
    path = Path(root) / CUR_HINTS_NAME
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def place_for_cur(mining_root: Path, project_root: Path) -> list[dict]:
    """Copy mined objects into the project layout convert/init resolve.

    packages/<slug>/testbed/*.json -> <project>/artifacts/etl/<slug>/testbed/
    tables/<slug>/testbed/*.json   -> <project>/artifacts/tables/<slug>/testbed/
    """
    mining_root = Path(mining_root)
    project_root = Path(project_root)
    hints_path = mining_root / CUR_HINTS_NAME
    if hints_path.is_file():
        pointers = json.loads(hints_path.read_text(encoding="utf-8")).get("pointers", [])
    else:
        manifest = json.loads((mining_root / MANIFEST_NAME).read_text(encoding="utf-8"))
        write_cur_hints(mining_root, manifest.get("artifacts", []))
        pointers = json.loads(hints_path.read_text(encoding="utf-8")).get("pointers", [])
    placed = []
    for p in pointers:
        src_dir = mining_root / p["mining_path"] / "testbed"
        dest_dir = project_root / p["files.artifacts.path"] / "testbed"
        dest_dir.mkdir(parents=True, exist_ok=True)
        copied = []
        if src_dir.is_dir():
            for src in sorted(src_dir.glob(f"*{ARTIFACT_SUFFIX}")):
                dest = dest_dir / src.name
                dest.write_bytes(src.read_bytes())
                copied.append(dest.relative_to(project_root).as_posix())
        placed.append({**p, "project_files": copied})
    dest_hints = project_root / "artifacts" / CUR_HINTS_NAME
    dest_hints.parent.mkdir(parents=True, exist_ok=True)
    dest_hints.write_bytes(hints_path.read_bytes())
    return placed
