# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Derive what the Data Migration & Validation tab can honestly claim.

Aggregate counts and per-type findings only -- per-object detail belongs to the
Overview and Dependencies tabs. Every value traces to a registry field, to the
DDL those fields point at, or to the coverage snapshot in ``type_coverage``.
Row counts and byte sizes appear nowhere: the registry has neither, which is
precisely what the tab's inventory scripts exist to obtain.
"""

from __future__ import annotations

import time
import warnings
from dataclasses import dataclass
from pathlib import Path

from .data_types_scan import (
    ScannedColumn,
    ScannedTable,
    TypeUsage,
    aggregate_usage,
    columns_from_signature,
    scan_ddl_columns,
)
from .loaders.registry_loader import (
    entry_full_name,
    iter_in_scope_non_missing,
    load_registry_entries,
)
from .testing_readiness import normalize_dialect
from .type_coverage import TypeCoverage, coverage_for

# Dialects with a reviewed inventory script. An allow-list, because a script for
# an unlisted dialect would be invented SQL.
INVENTORY_SCRIPT_DIALECTS = frozenset({"sqlserver", "redshift"})


@dataclass(frozen=True)
class TypeFinding:
    """A coverage row, with how much this project uses it when that is known."""

    coverage: TypeCoverage
    usage: TypeUsage | None


@dataclass(frozen=True)
class DataMigrationReadiness:
    """Everything the tab renders from, or ``has_project_state=False``."""

    has_project_state: bool
    source_dialect: str
    dialect_key: str
    table_count: int
    view_count: int
    scanned_tables: int
    distinct_type_count: int
    clean_type_count: int
    findings: tuple[TypeFinding, ...]
    has_inventory_scripts: bool


def _object_type(entry: dict) -> str:
    return (entry.get("source", {}).get("objectType") or "").strip().lower()


def _source_path(entry: dict) -> str:
    return (entry.get("files", {}).get("source", {}).get("path") or "").strip()


def _resolve(project_root: Path, raw_path: str) -> Path | None:
    """Locate a captured source file, or ``None`` when it is not readable.

    Registry paths are project-relative (``source/tables/dbo.Orders.sql``) and
    the registry lives at ``<projectRoot>/registry/``, so the project root is
    the registry's parent. An absolute path is honoured as given.
    """
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate if candidate.is_file() else None


def _scan_tables(
    tables: list[dict],
    project_root: Path,
    columns_by_id: dict[str, tuple[ScannedColumn, ...]] | None = None,
) -> tuple[list[ScannedTable], int, int]:
    """Columns per table, from the registry signature or captured DDL.

    A table with no typed ``signature.columns`` and whose DDL is missing,
    unreadable, or yields no recognizable column contributes no entry: it
    lowers scan coverage rather than inventing a type.
    """
    scanned: list[ScannedTable] = []
    extra = columns_by_id or {}
    from_signature = from_ddl = 0
    for entry in tables:
        columns = extra.get(entry.get("id") or "") or columns_from_signature(entry)
        if columns:
            from_signature += 1
        else:
            path = _resolve(project_root, _source_path(entry))
            if path is None:
                continue
            try:
                ddl = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            columns = scan_ddl_columns(ddl)
            if not columns:
                continue
            from_ddl += 1
        scanned.append(ScannedTable(name=entry_full_name(entry), columns=columns))
    return scanned, from_signature, from_ddl


def _table_columns_via_cur(registry_dir: Path) -> dict[str, tuple[ScannedColumn, ...]]:
    """``id -> columns`` from one indexed table query, or empty if CUR is unusable.

    The HTML loader's first query omits ``signature.columns`` (they are most of
    each document). This query asks only for table columns so the type scan
    does not open tens of thousands of DDL files.
    """
    if registry_dir.name != "registry":
        return {}
    if not any((registry_dir / ".index").glob("*.db")):
        return {}
    try:
        from snowflake_code_unit_registry import CodeUnitRegistry, FindOptions, ScaiError
    except ImportError:
        return {}
    try:
        registry = CodeUnitRegistry.open(str(registry_dir.parent))
        units = registry.find_all(
            FindOptions(
                filter=(
                    "source.objectType = 'table' AND inScope = true "
                    "AND isMissing = false"
                ),
                fields=["id", "signature.columns"],
            )
        )
    except ScaiError as exc:
        warnings.warn(f"Code Unit Registry table-column query failed: {exc}")
        return {}
    by_id: dict[str, tuple[ScannedColumn, ...]] = {}
    for unit in units:
        payload = unit.model_dump(mode="json", by_alias=True, exclude_none=True)
        unit_id = payload.get("id") or ""
        if not unit_id:
            continue
        columns = columns_from_signature(payload)
        if columns:
            by_id[unit_id] = columns
    return by_id


def _reference_findings(coverage: tuple[TypeCoverage, ...]) -> tuple[TypeFinding, ...]:
    """The per-dialect table with no project usage attached to it."""
    return tuple(TypeFinding(row, None) for row in coverage if not row.is_clean)


def load_data_migration_readiness(
    registry_dir: Path | str | None,
    source_dialect: str = "",
) -> DataMigrationReadiness:
    """Read migration readiness from the registry at *registry_dir*.

    Always returns an instance. Dialect fields are populated even without a
    registry, so a CSV-only run still renders the coverage table as per-dialect
    reference and still resolves whether an inventory script exists.
    """
    dialect_key = normalize_dialect(source_dialect)
    coverage = coverage_for(dialect_key)
    dialect_fields = {
        "source_dialect": source_dialect or "",
        "dialect_key": dialect_key,
        "has_inventory_scripts": dialect_key in INVENTORY_SCRIPT_DIALECTS,
    }

    entries: list[dict] = []
    if registry_dir and Path(registry_dir).is_dir():
        entries = load_registry_entries(Path(registry_dir))

    if not entries:
        return DataMigrationReadiness(
            has_project_state=False,
            table_count=0,
            view_count=0,
            scanned_tables=0,
            distinct_type_count=0,
            clean_type_count=0,
            findings=_reference_findings(coverage),
            **dialect_fields,
        )

    in_scope = list(iter_in_scope_non_missing(entries))
    tables = [e for e in in_scope if _object_type(e) == "table"]
    views = [e for e in in_scope if _object_type(e) == "view"]

    started = time.perf_counter()
    registry_path = Path(registry_dir)
    extra_columns: dict[str, tuple[ScannedColumn, ...]] = {}
    if tables and not any(columns_from_signature(entry) for entry in tables[:32]):
        extra_columns = _table_columns_via_cur(registry_path)
    scanned, from_signature, from_ddl = _scan_tables(
        tables, registry_path.parent, extra_columns
    )
    print(
        f"  Data-migration types: {len(scanned):,} tables "
        f"({from_signature:,} registry, {from_ddl:,} DDL) "
        f"in {time.perf_counter() - started:.1f}s",
        flush=True,
    )
    usage = aggregate_usage(scanned)
    by_name = {row.type_name: row for row in coverage}

    # A scanned type with no coverage row is neither a finding nor clean: the
    # scan resolved a name the snapshot cannot speak for, and saying nothing
    # about it is the only honest option.
    findings = tuple(
        TypeFinding(by_name[item.type_name], item)
        for item in usage
        if item.type_name in by_name and not by_name[item.type_name].is_clean
    )
    clean_type_count = sum(
        1 for item in usage if item.type_name in by_name and by_name[item.type_name].is_clean
    )

    return DataMigrationReadiness(
        has_project_state=True,
        table_count=len(tables),
        view_count=len(views),
        scanned_tables=len(scanned),
        distinct_type_count=len(usage),
        clean_type_count=clean_type_count,
        # Two different empty states. Nothing scanned means the coverage table is
        # still worth showing as per-dialect reference; a scan that found only
        # clean types means the honest answer is "nothing needs a decision", and
        # a reference table there would read as a project finding.
        findings=findings if scanned else _reference_findings(coverage),
        **dialect_fields,
    )
