#!/usr/bin/env python3
"""Look up database objects in the extraction artifact's CUR catalog.

    query_cur_catalog.py --project-dir <root> --object-type Table \
        --name DimAccount --name DW.dbo.FactSales

Prints one JSON object: per requested name, how many registry units match and a
bounded list of the candidates, projected down to the identity fields matching
actually needs, plus the `comparedFields` the answer is conditioned on.

`--object-type` is required. `enrich` buckets near matches on type *and* name,
so it never matches across types -- and a Procedure's id cited for a Table
reference is not a near miss, it is a wrong edge that `enrich` writes without
complaint, because an `existingCodeUnitId` resolves by id and asks nothing else.
Batch the names of one type per call.

Each candidate is labelled `exact` or `reconcilable`. `reconcilable` is the one
that matters and is easy to miss: `enrich` treats a qualifier left unset on
either side as non-distinguishing, so a registry `Table FactSales` with no
schema recorded collides with a `missingObject` for `dbo.FactSales` and gets the
whole manifest rejected (ASM0042). Reporting strict matches alone would hide
that -- the caller would see nothing, author the stub, and fail the run.

WHY THIS EXISTS
`extraction.json` carries `curCatalog`, a snapshot of *every* code unit in the
workload. On a real migration that is tens of thousands of entries, so an agent
that opens the artifact to resolve one table name pays for the whole registry --
and repeats the cost for the next table. This reads the file in process and
emits only the matches, so what reaches the agent is the size of the question
rather than the size of the project.

It also puts the normalization in one tested place. Matching has to agree with
`PowerBiIdentity.NormalizeComponent` on the C# side -- trim, drop one matched
pair of surrounding double quotes, upper-case -- because that is what the CLI
hashes when it derives ids. Eyeballing that per lookup is how a manifest ends up
referencing the wrong unit.

This is a read-only helper. It never writes, and it is not a CLI command: the
supported surface is `scai assessment powerbi extract` and `... enrich`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ARTIFACT_SUBPATH = ("artifacts", "assessment", "powerbi", "extraction.json")

# Enough candidates to see an ambiguity and judge it; small enough that a name
# matching half the registry cannot flood the agent's context.
DEFAULT_LIMIT = 20

# Mirrors PowerBiIdentity: a report unit is never a dependency target, and
# `enrich` rejects a manifest dependency whose id is one.
_REPORT_ID_PREFIX = "powerbi:report:"
_MISSING_ID_PREFIX = "powerbi:missing:"
_REPORT_CUSTOM_KIND = "POWERBI"

# Qualifiers compared with the unset-is-non-distinguishing rule, matching
# `PowerBiEnrichmentPlanner.QualifiersAreReconcilable`. `objectType` is not one
# of them: `enrich` keys its near-match index on type *and* name, so a type that
# differs is a different bucket, not a reconcilable difference.
_QUALIFIERS = ("database", "schema", "platform", "customKind")


def normalize(value: str | None) -> str:
    """The fold `PowerBiIdentity.NormalizeComponent` applies before it hashes."""
    trimmed = (value or "").strip()
    if len(trimmed) >= 2 and trimmed[0] == '"' and trimmed[-1] == '"':
        trimmed = trimmed[1:-1].strip()
    return trimmed.upper()


def artifact_path(project_dir: Path) -> Path:
    return project_dir.joinpath(*ARTIFACT_SUBPATH)


def name_parts(name: str | None) -> list[str]:
    """Mirrors `PowerBiIdentity.NameParts`.

    A quoted part may itself contain a dot, and a name of more than three parts
    has no single reading. Both come back whole rather than divided, because
    guessing either silently changes which object a comparison is about.
    """
    trimmed = (name or "").strip()
    if '"' in trimmed:
        return [trimmed]
    parts = trimmed.split(".")
    return parts if 2 <= len(parts) <= 3 else [trimmed]


def name_leaf(name: str | None) -> str:
    """The object name with any qualifiers it carries stripped off."""
    return name_parts(name)[-1]


def effective_schema(schema: str | None, name: str | None) -> str | None:
    """The schema an identity is really in -- the field, else what the name says."""
    if (schema or "").strip():
        return schema
    parts = name_parts(name)
    return parts[-2] if len(parts) >= 2 else None


def effective_database(database: str | None, name: str | None) -> str | None:
    if (database or "").strip():
        return database
    parts = name_parts(name)
    return parts[-3] if len(parts) >= 3 else None


def split_qualified(name: str) -> dict[str, str | None]:
    """Split `DW.dbo.FactSales` into its parts; a bare name stays bare.

    M expressions name objects the way the database does, so accepting the
    qualified spelling saves the caller from splitting it -- and from splitting
    it differently than this does. The spellings `name_parts` refuses to divide
    are refused here too, with a message rather than a silent bare name.
    """
    trimmed = name.strip()
    if '"' in trimmed:
        return {
            "database": None,
            "schema": None,
            "name": name,
            "error": "cannot split a quoted name; pass --name, --schema, --database separately",
        }
    parts = trimmed.split(".")
    if len(parts) > 3:
        return {
            "database": None,
            "schema": None,
            "name": name,
            "error": f"{len(parts)}-part name is ambiguous; pass the parts separately",
        }
    if len(parts) == 3:
        return {"database": parts[0], "schema": parts[1], "name": parts[2]}
    if len(parts) == 2:
        return {"database": None, "schema": parts[0], "name": parts[1]}
    return {"database": None, "schema": None, "name": name}


def is_report_unit(unit: dict[str, Any]) -> bool:
    """Mirrors `PowerBiIdentity.IsReportUnit`.

    Standard reports are classified by kind plus customKind; ids are opaque.
    Prefix handling exists only while old records are migrated. A missing
    database object is never a report even if its authored identity carries the
    same customKind or a legacy `powerbi:report:` id.
    """
    if unit.get("isMissing") is True:
        return False

    unit_id = unit.get("id") or ""
    if unit_id.startswith(_REPORT_ID_PREFIX):
        return True
    if unit_id.startswith(_MISSING_ID_PREFIX):
        return False

    source = unit.get("source") or {}
    return (
        normalize(unit.get("kind")) == "CUSTOM"
        and normalize(source.get("customKind")) == _REPORT_CUSTOM_KIND
    )


def _candidate(
    unit: dict[str, Any], match: str, wanted: dict[str, str | None]
) -> dict[str, Any]:
    source = unit.get("source") or {}
    return {
        "id": unit.get("id"),
        "match": match,
        # Whether citing this id would rest on a comparison that was made.
        "fullyComparable": _fully_comparable(unit, wanted),
        "objectType": source.get("objectType"),
        "name": source.get("name"),
        "platform": source.get("platform"),
        "database": source.get("database"),
        "schema": source.get("schema"),
        "customKind": source.get("customKind"),
        "isMissing": bool(unit.get("isMissing")),
    }


def _reconcilable(left: str | None, right: str | None) -> bool:
    """`PowerBiEnrichmentPlanner.Reconcilable`: unset on either side does not
    distinguish, so it cannot rule a candidate out."""
    if not (left or "").strip() or not (right or "").strip():
        return True
    return normalize(left) == normalize(right)


def _classify(unit: dict[str, Any], wanted: dict[str, str | None]) -> str | None:
    """`"exact"`, `"reconcilable"`, or `None` for not a candidate at all.

    Mirrors how `enrich` decides a near match, because a divergence here is not
    a worse answer -- it is a manifest the CLI rejects (ASM0042) or, worse, a
    duplicate stub for an object the registry already holds.

    Two rules do the work. A qualifier either side leaves unset does not
    distinguish, so a registry `Table FactSales` with no schema *collides* with
    a `missingObject` for `dbo.FactSales`. And a qualifier can live inside the
    name -- a CUR routinely holds `dbo.FactSales` -- so names are compared on
    their leaf, with the leading segments folded into schema and database.
    Reporting only strict matches would hide both.
    """
    if is_report_unit(unit):
        return None

    source = unit.get("source") or {}
    if normalize(name_leaf(source.get("name"))) != normalize(name_leaf(wanted["name"])):
        return None
    # Object type is the near-match bucket, not a reconcilable qualifier: `enrich`
    # keys on type *and* name, so a Procedure never matches a Table however the
    # rest lines up, and an unset type on either side is not a wildcard.
    if normalize(source.get("objectType")) != normalize(wanted["objectType"]):
        return None

    # What each side effectively asserts, wherever it wrote it down.
    theirs = {
        "schema": effective_schema(source.get("schema"), source.get("name")),
        "database": effective_database(source.get("database"), source.get("name")),
        "platform": source.get("platform"),
        "customKind": source.get("customKind"),
    }
    ours = {
        "schema": effective_schema(wanted.get("schema"), wanted.get("name")),
        "database": effective_database(wanted.get("database"), wanted.get("name")),
        "platform": wanted.get("platform"),
        "customKind": wanted.get("customKind"),
    }

    if not all(_reconcilable(theirs[field], ours[field]) for field in _QUALIFIERS):
        return None

    # Exact means the *whole* identity matches, spelling included: every
    # qualifier equal, and absent on one side only if absent on the other. Not
    # "equal on the fields the query happened to supply" -- under that reading a
    # candidate asserting `schema: stg` would come back exact to a query that
    # never mentioned a schema, and the caller would cite it as settled on the
    # strength of a comparison nobody made. A dotted registry name is likewise
    # never exact against a bare one, however well the qualifiers reconcile.
    if normalize(source.get("name")) == normalize(wanted["name"]) and all(
        normalize(theirs[field]) == normalize(ours[field]) for field in _QUALIFIERS
    ):
        return "exact"
    return "reconcilable"


def _fully_comparable(unit: dict[str, Any], wanted: dict[str, str | None]) -> bool:
    """Whether the candidate asserts nothing the query left unsaid.

    A candidate recording *fewer* qualifiers than the query is fine -- an unset
    qualifier does not distinguish, and a CUR routinely records less than it
    knows, which is the whole reason `reconcilable` exists. The other direction
    is not: a candidate saying `schema: stg` when the evidence said nothing
    about a schema has not been confirmed to be the object in hand, it has only
    failed to be ruled out.
    """
    source = unit.get("source") or {}
    theirs = {
        "schema": effective_schema(source.get("schema"), source.get("name")),
        "database": effective_database(source.get("database"), source.get("name")),
        "platform": source.get("platform"),
        "customKind": source.get("customKind"),
    }
    ours = {
        "schema": effective_schema(wanted.get("schema"), wanted.get("name")),
        "database": effective_database(wanted.get("database"), wanted.get("name")),
        "platform": wanted.get("platform"),
        "customKind": wanted.get("customKind"),
    }
    return not any(
        (theirs[field] or "").strip() and not (ours[field] or "").strip()
        for field in _QUALIFIERS
    )


def _answer(
    units: list[dict[str, Any]], wanted: dict[str, str | None], limit: int
) -> dict[str, Any]:
    # Copy, so calling twice with the same list gives the same answer twice.
    wanted = dict(wanted)
    error = wanted.pop("error", None)
    if not error and not (wanted.get("name") or "").strip():
        error = "a query needs a name"
    if not error and not (wanted.get("objectType") or "").strip():
        # Without a type the answer spans every kind of object that shares the
        # name, and citing a Procedure's id for a Table reference is a wrong
        # edge that `enrich` will happily write -- it resolves by id and asks
        # nothing else. `enrich` never matches across types either.
        error = "a query needs an objectType (Table / View / Procedure / ...)"
    if error:
        return {
            "query": wanted,
            "comparedFields": [],
            "error": error,
            "matchCount": 0,
            "exactCount": 0,
            "reconcilableCount": 0,
            "candidates": [],
            "truncated": False,
        }

    matched = []
    for unit in units:
        match = _classify(unit, wanted)
        if match:
            matched.append(_candidate(unit, match, wanted))
    # Exact matches first, then a stable order, so two runs over one artifact
    # show the same candidates and the ones that resolve the query lead.
    matched.sort(key=lambda c: (c["match"] != "exact", str(c["id"])))
    return {
        "query": wanted,
        # What was actually compared. A qualifier left off the query is not
        # compared at all, so "no match" means something narrower than it looks
        # -- this says which narrowing was in force.
        "comparedFields": ["objectType", "name"]
        + [field for field in _QUALIFIERS if (wanted.get(field) or "").strip()],
        "error": None,
        "matchCount": len(matched),
        "exactCount": sum(1 for c in matched if c["match"] == "exact"),
        "reconcilableCount": sum(1 for c in matched if c["match"] == "reconcilable"),
        "candidates": matched[:limit],
        "truncated": len(matched) > limit,
    }


def query(
    project_dir: Path,
    wanted: list[dict[str, str | None]],
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    path = artifact_path(project_dir)
    # Every return has the same keys, so a caller never has to branch on
    # whether one is present before reading it.
    report: dict[str, Any] = {
        "artifact": str(path),
        "error": None,
        "catalogSize": 0,
        "limit": limit,
        "queries": [],
    }
    try:
        with path.open("rb") as handle:
            artifact = json.load(handle)
    except FileNotFoundError:
        report["error"] = (
            f"no extraction artifact at {path}; run `scai assessment powerbi extract` first"
        )
        return report
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        report["error"] = f"could not read {path}: {error}"
        return report

    units = [unit for unit in artifact.get("curCatalog") or [] if isinstance(unit, dict)]
    report["catalogSize"] = len(units)
    report["queries"] = [_answer(units, one, limit) for one in wanted]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Query the extraction artifact's CUR catalog for matching objects."
    )
    parser.add_argument("--project-dir", required=True, help="SCAI project root")
    parser.add_argument(
        "--name",
        action="append",
        default=[],
        required=True,
        metavar="NAME",
        help="object name, bare or qualified as [database.][schema.]name (repeatable)",
    )
    parser.add_argument(
        "--object-type",
        required=True,
        help="object type every name is looked up as, e.g. Table / View / Procedure. "
        "Required: a cross-type match is a wrong dependency edge, not a near miss. "
        "Batch names of one type per call.",
    )
    parser.add_argument(
        "--schema",
        default=None,
        help="narrow every name to one schema (use instead of a qualified --name)",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="narrow every name to one database",
    )
    parser.add_argument(
        "--platform",
        default=None,
        help="narrow every name to one source platform, e.g. SqlServer",
    )
    parser.add_argument(
        "--custom-kind",
        default=None,
        help="narrow every name to one custom kind, compared like the other "
        "qualifiers (unset on either side does not distinguish)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"most candidates to return per name (default {DEFAULT_LIMIT})",
    )
    args = parser.parse_args(argv)

    project_dir = Path(args.project_dir).expanduser()
    if not project_dir.is_dir():
        print(f"error: project dir {project_dir} is not a directory", file=sys.stderr)
        return 2

    wanted = []
    for raw in args.name:
        one = split_qualified(raw)
        one["objectType"] = args.object_type
        one["platform"] = args.platform
        one["customKind"] = args.custom_kind
        # An explicit flag wins over what the name happened to carry.
        one["schema"] = args.schema or one.get("schema")
        one["database"] = args.database or one.get("database")
        wanted.append(one)

    report = query(project_dir.resolve(), wanted, max(1, args.limit))
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    # A caller that checks the exit status must not read an unreadable artifact
    # as an empty catalog.
    return 1 if report["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
