"""Load SnowConvert data from the registry (flat directory of JSON files)."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

from ..models.code_unit import TopLevelCodeUnit
from ..models.object_reference import ObjectReference
from ..na_utils import NA_VALUES, is_na

VALID_OBJECT_TYPES = {"table", "view", "procedure", "function"}


def _bracket(ident: str) -> str:
    """Ensure an identifier is bracketed, avoiding double-bracketing."""
    ident = (ident or "").strip()
    if not ident:
        return "[]"
    if ident.startswith("[") and ident.endswith("]"):
        return ident
    return f"[{ident}]"


def _entry_full_name(entry: dict) -> str:
    """Build a bracketed identifier from an entry's source block.

    N/A-valued parts (database, schema, name) are omitted so that
    ``[N/A].[dbo].[MyTable]`` becomes ``[dbo].[MyTable]``.
    """
    source = entry.get("source", {})
    parts = [
        _bracket(v)
        for v in (source.get("database", ""), source.get("schema", ""), source.get("name", ""))
        if not is_na(v) and not is_na(v.strip("[]"))
    ]
    return ".".join(parts) if parts else "[]"


def _iter_in_scope_non_missing(entries: list[dict]):
    """Yield entries that are in-scope and not missing."""
    for entry in entries:
        if not entry.get("inScope", False):
            continue
        if entry.get("isMissing", False):
            continue
        yield entry


def load_registry_entries(registry_dir: Path | str) -> list[dict]:
    """Parse all JSON files in *registry_dir*, skipping malformed ones."""
    registry_dir = Path(registry_dir)
    entries: list[dict] = []
    for path in sorted(registry_dir.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as f:
                entries.append(json.load(f))
        except (json.JSONDecodeError, OSError) as exc:
            warnings.warn(f"Skipping malformed registry file {path.name}: {exc}")
    return entries


def build_id_to_name_map(entries: list[dict]) -> dict[str, str]:
    """Build a registry-ID -> ``[DB].[Schema].[Name]`` lookup."""
    mapping: dict[str, str] = {}
    for entry in entries:
        entry_id = entry.get("id") or ""
        if not entry_id:
            continue
        mapping[entry_id] = _entry_full_name(entry)

    return mapping


def load_code_units_from_registry(registry_dir: Path) -> list[TopLevelCodeUnit]:
    """Load in-scope, non-missing code units of valid object types."""
    entries = load_registry_entries(registry_dir)
    units: list[TopLevelCodeUnit] = []
    for entry in _iter_in_scope_non_missing(entries):
        obj_type = entry.get("source", {}).get("objectType", "").lower()
        if obj_type not in VALID_OBJECT_TYPES:
            continue
        units.append(TopLevelCodeUnit.from_registry_entry(entry))
    return units


def load_object_references_from_registry(
    registry_dir: Path | str,
) -> list[ObjectReference]:
    """Load all object references by flattening ``dependsOn`` arrays."""
    entries = load_registry_entries(registry_dir)
    id_map = build_id_to_name_map(entries)

    refs: list[ObjectReference] = []
    for entry in _iter_in_scope_non_missing(entries):
        caller_name = _entry_full_name(entry)
        caller_type = entry.get("source", {}).get("objectType", "").upper()
        caller_file = entry.get("files", {}).get("source", {}).get("path", "")

        for dep in entry.get("dependencies", {}).get("dependsOn", []):
            refs.extend(
                ObjectReference.from_registry_dependency(
                    caller_name, caller_type, caller_file, dep, id_map
                )
            )
    return refs


def load_missing_references_from_registry(
    registry_dir: Path,
) -> list[ObjectReference]:
    """Load only references whose target is missing (``isMissing=True``)."""
    all_refs = load_object_references_from_registry(registry_dir)
    return [r for r in all_refs if r.is_missing_reference]


def load_missing_dependencies_by_object(
    registry_dir: Path | str,
) -> dict[str, list[str]]:
    """Load missing dependencies grouped by object.

    Returns a dict mapping code_unit_id to list of missing dependency names.

    Example:
        {
            '[DB].[Schema].[Table1]': ['[DB].[Schema].[MissingView]'],
            '[DB].[Schema].[Proc1]': ['[OtherDB].[Schema].[MissingTable]', ...]
        }
    """
    entries = load_registry_entries(registry_dir)
    id_map = build_id_to_name_map(entries)

    missing_by_object: dict[str, list[str]] = {}

    for entry in _iter_in_scope_non_missing(entries):
        caller_name = _entry_full_name(entry)

        missing_deps: list[str] = []
        for dep in entry.get("dependencies", {}).get("dependsOn", []):
            if dep.get("isMissing", False):
                dep_id = dep.get("id") or ""
                dep_name = id_map.get(dep_id, dep_id)
                if dep_name and dep_name not in missing_deps:
                    missing_deps.append(dep_name)

        if missing_deps:
            missing_by_object[caller_name] = sorted(missing_deps)

    return missing_by_object
