#!/usr/bin/env python3
"""Emit CUR write edges from Hop transforms that write a database table.

WHY THIS IS A SCRIPT AND NOT SKILL PROSE
----------------------------------------
`lineage.json` only measures `source()` reads in the emitted dbt. Seed walks
CUR *write* edges (`INSERT` / `UPDATE` / `MERGE` / `DELETE`). Hop convert
used to stamp only those reads, so `scai test seed` skipped
`NoWriteDependencies` even when the pipeline had a sink.

This helper is convert, not a miner TABLE factory: it names the sink the
document already states. The skill still resolves that name against the live
registry (or stamps `isMissing: true`). It does not mint table units.

Sink kinds and the verbs each records (what the Hop transform does to the
table, not how the migration translates it):

  TableOutput            INSERT
  InsertUpdate           INSERT + UPDATE; INSERT + MERGE when update_bypassed=Y
                         or no <value> has update=Y (insert only the keys not
                         found)
  Update                 UPDATE
  Delete                 DELETE
  SynchronizeAfterMerge  INSERT / UPDATE / DELETE for each non-empty
                         order_insert / order_update / order_delete
  DimensionLookup        INSERT, UPDATE when update=Y (versioning closes the
                         prior row); update=N is a lookup and writes nothing
  CombinationLookup      INSERT + MERGE (insert only a combination not found,
                         with a new key)

MERGE marks a write that looks the table's existing rows up: its result depends
on the table's rows before the run, so validation compares the whole table from
a shared pre-state (the runner's `mutating` pattern) rather than a window.

InsertUpdate, Update, Delete and SynchronizeAfterMerge name the table under
<lookup>; the others at the transform's top level. Each edge carries the
transform's <connection>: the same schema.table on two connections is two
sinks. Writes to one sink from several transforms collapse into one edge with
the union of their verbs.

Not in scope: Formula owning-table, bulk loaders, ExecSql,
`tablename_in_field=Y` (dynamic table name — skipped, not guessed).

Usage:
  hop_write_deps.py --source <pipeline.hpl>

Prints a JSON array to stdout:
  [{"schema": "dbo", "table": "DeprecatedTasks", "relationTypes": ["INSERT"],
    "transform": "OLE_DST DeprecatedTasks", "kind": "TableOutput",
    "connection": "TaskTracker"}]
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


INSERT = "INSERT"
UPDATE = "UPDATE"
DELETE = "DELETE"
MERGE_VERB = "MERGE"
_VERB_ORDER = (INSERT, UPDATE, DELETE, MERGE_VERB)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el: ET.Element, tag: str) -> ET.Element | None:
    want = tag.casefold()
    for child in el:
        if _local(child.tag).casefold() == want:
            return child
    return None


def _child_text(el: ET.Element, tag: str) -> str:
    child = _child(el, tag)
    return (child.text or "").strip() if child is not None else ""


def _children(el: ET.Element, tag: str) -> list[ET.Element]:
    want = tag.casefold()
    return [child for child in el if _local(child.tag).casefold() == want]


def _yes(value: str) -> bool:
    return value.strip().upper() in {"Y", "YES", "TRUE", "1"}


def _insert_update_verbs(el: ET.Element) -> list[str]:
    if _yes(_child_text(el, "update_bypassed")):
        return [INSERT, MERGE_VERB]
    lookup = _child(el, "lookup")
    values = _children(lookup, "value") if lookup is not None else []
    if any(_yes(_child_text(v, "update")) for v in values):
        return [INSERT, UPDATE]
    return [INSERT, MERGE_VERB]


def _sync_verbs(el: ET.Element) -> list[str]:
    verbs = [
        verb
        for verb, tag in ((INSERT, "order_insert"), (UPDATE, "order_update"), (DELETE, "order_delete"))
        if _child_text(el, tag)
    ]
    return verbs or [INSERT, UPDATE, DELETE]


def _dimension_verbs(el: ET.Element) -> list[str]:
    return [INSERT, UPDATE] if _yes(_child_text(el, "update")) else []


# kind -> (table lives under <lookup>, verbs for this transform)
_SINKS = {
    "TableOutput": (False, lambda el: [INSERT]),
    "InsertUpdate": (True, _insert_update_verbs),
    "Update": (True, lambda el: [UPDATE]),
    "Delete": (True, lambda el: [DELETE]),
    "SynchronizeAfterMerge": (True, _sync_verbs),
    "DimensionLookup": (False, _dimension_verbs),
    "CombinationLookup": (False, lambda el: [INSERT, MERGE_VERB]),
}

SINK_KINDS = frozenset(_SINKS)


def write_targets(source: Path | str) -> list[dict[str, object]]:
    """Table sinks in document order, one per (connection, schema, table)."""
    path = Path(source)
    root = ET.parse(path).getroot()
    by_key: dict[tuple[str, str, str], dict[str, object]] = {}
    for el in root.iter():
        if _local(el.tag) != "transform":
            continue
        kind = _child_text(el, "type")
        sink = _SINKS.get(kind)
        if sink is None:
            continue
        under_lookup, verbs_of = sink
        if _yes(_child_text(el, "tablename_in_field")):
            continue
        holder = _child(el, "lookup") if under_lookup else el
        if holder is None:
            continue
        table = _child_text(holder, "table")
        if not table:
            continue
        verbs = verbs_of(el)
        if not verbs:
            continue
        schema = _child_text(holder, "schema")
        connection = _child_text(el, "connection")
        key = (connection.casefold(), schema.casefold(), table.casefold())
        edge = by_key.get(key)
        if edge is None:
            by_key[key] = {
                "schema": schema,
                "table": table,
                "relationTypes": list(verbs),
                "transform": _child_text(el, "name"),
                "kind": kind,
                "connection": connection,
            }
            continue
        merged = set(edge["relationTypes"]) | set(verbs)  # type: ignore[arg-type]
        edge["relationTypes"] = [v for v in _VERB_ORDER if v in merged]
    return list(by_key.values())


# Write modes `sink_writes` states, i.e. what the transform does to its table on one run:
APPEND = "append"                  # insert every row, keep the rest
REPLACE = "replace"                # empty the table, insert every row
REPLACE_IF_ROWS = "replace_if_rows"  # as REPLACE, but only when the run has a row
MERGE = "merge"                    # match on keys: update some columns, insert the rest
INSERT_ONLY = "insert_only"        # match on keys: insert the rows not found
UPDATE_ONLY = "update_only"        # match on keys: update, never insert
DELETE_ON_KEY = "delete"           # match on keys: delete
SYNCHRONIZE = "synchronize"        # per row, by a flag field: insert / update / delete
SCD2 = "scd2"                      # versioned dimension rows
COMBINATION = "combination"        # insert a new technical key per unseen combination


def _keys(el: ET.Element) -> list[str]:
    lookup = _child(el, "lookup")
    return [_child_text(k, "field") for k in _children(lookup, "key")] if lookup is not None else []


def _sink_write_mode(el: ET.Element, kind: str) -> tuple[str, list[str], list[str]]:
    """(mode, key table columns, columns the mode overwrites)."""
    lookup = _child(el, "lookup")
    values = _children(lookup, "value") if lookup is not None else []
    if kind == "TableOutput":
        if not _yes(_child_text(el, "truncate")):
            return APPEND, [], []
        return (REPLACE_IF_ROWS if _yes(_child_text(el, "only_when_have_rows")) else REPLACE), [], []
    if kind == "InsertUpdate":
        keys = _keys(el)
        updated = [_child_text(v, "name") for v in values if _yes(_child_text(v, "update"))]
        updated = [c for c in updated if c.casefold() not in {k.casefold() for k in keys}]
        if _yes(_child_text(el, "update_bypassed")) or not updated:
            return INSERT_ONLY, keys, []
        return MERGE, keys, updated
    if kind == "Update":
        keys = _keys(el)
        return UPDATE_ONLY, keys, [c for c in (_child_text(v, "name") for v in values)
                                   if c.casefold() not in {k.casefold() for k in keys}]
    if kind == "Delete":
        return DELETE_ON_KEY, _keys(el), []
    if kind == "SynchronizeAfterMerge":
        keys = _keys(el)
        return SYNCHRONIZE, keys, [c for c in (_child_text(v, "name") for v in values if _yes(_child_text(v, "update")))
                                   if c.casefold() not in {k.casefold() for k in keys}]
    fields = _child(el, "fields")
    natural = [_child_text(k, "lookup") for k in _children(fields, "key")] if fields is not None else []
    return (SCD2 if kind == "DimensionLookup" else COMBINATION), natural, []


def sink_writes(source: Path | str) -> list[dict[str, object]]:
    """One entry per sink transform, in document order: the table it writes and how.

    Unlike `write_targets` nothing is collapsed: two transforms writing one table are two
    writes, each with its own mode. Same scope as `write_targets` (a DimensionLookup with
    update=N and a dynamic table name are skipped)."""
    root = ET.parse(Path(source)).getroot()
    out: list[dict[str, object]] = []
    for el in root.iter():
        if _local(el.tag) != "transform":
            continue
        kind = _child_text(el, "type")
        sink = _SINKS.get(kind)
        if sink is None or _yes(_child_text(el, "tablename_in_field")):
            continue
        under_lookup, verbs_of = sink
        holder = _child(el, "lookup") if under_lookup else el
        table = _child_text(holder, "table") if holder is not None else ""
        if not table or not verbs_of(el):
            continue
        mode, keys, columns = _sink_write_mode(el, kind)
        out.append({
            "transform": _child_text(el, "name"),
            "kind": kind,
            "connection": _child_text(el, "connection"),
            "schema": _child_text(holder, "schema"),
            "table": table,
            "mode": mode,
            "keys": keys,
            "columns": columns,
        })
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hop_write_deps.py",
        description=(
            "List Hop table sinks (TableOutput, InsertUpdate, Update, Delete, "
            "SynchronizeAfterMerge, DimensionLookup, CombinationLookup) as "
            "write-deps for update_registry(field=dependencies.dependsOn)."
        ),
    )
    parser.add_argument("--source", required=True, help="Hop .hpl (or .hwf) path")
    args = parser.parse_args(argv)
    path = Path(args.source)
    if not path.is_file():
        print(f"error: source is not a file: {path}", file=sys.stderr)
        return 2
    try:
        targets = write_targets(path)
    except ET.ParseError as exc:
        print(f"error: not well-formed XML: {path}: {exc}", file=sys.stderr)
        return 2
    json.dump(targets, sys.stdout, indent=2, sort_keys=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
