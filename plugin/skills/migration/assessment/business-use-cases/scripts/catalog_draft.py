"""Read where data goes and lands, page anchor-group fact sheets and list what a draft leaves unplaced.

Subcommands:
  lineage   summarize data-lineage.json: source systems, pipelines and the systems they write
  landing   list landing objects (anchors), largest flow first, a page at a time
  groups    print fact sheets, a page at a time, without their id lists
  unplaced  list groups catalog-draft.json neither uses nor marks technical, most anchors first
  unevidenced  page the groups no exit and no report backs, most members first: the other-objects search
  check-ai  report every problem in other-objects-draft.json before it is merged
  merge     fold other-objects-draft.json into catalog-draft.json, dropping what a lineage use case holds

Stdlib only. Run from the project directory:
  uv run --project <assessment_skill_dir> python <assessment_skill_dir>/business-use-cases/scripts/catalog_draft.py <subcommand>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from compose_use_cases import check

WAVES_DIR = Path("artifacts") / "assessment" / "waves"
ANCHORS = WAVES_DIR / "anchors.json"
DRAFT = WAVES_DIR / "catalog-draft.json"
AI_DRAFT = WAVES_DIR / "other-objects-draft.json"
LINEAGE = Path("artifacts") / "assessment" / "data-lineage.json"
AI_ANALYSIS = "aiAnalysis"
EVIDENCE_SHAPES = ("exitJob", "report")
DEFAULT_PAGE = 25
DEFAULT_LINEAGE_LIMIT = 30
PIPELINE_SYSTEMS = 8
SHEET_FIELDS = (
    "key",
    "anchorsByShape",
    "detectionsByKind",
    "citations",
    "hintsByKind",
    "memberCount",
    "memberTypes",
    "foundationMemberCount",
    "missingMemberCount",
    "sharedWith",
    "headers",
)


class DraftError(Exception):
    """A file the script cannot read."""


def _load(path: Path, produced_by: str | None = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        hint = f"; run `{produced_by}` first" if produced_by else ""
        raise DraftError(f"{path} does not exist{hint}") from exc
    except json.JSONDecodeError as exc:
        raise DraftError(f"{path} is not valid JSON: {exc}") from exc


def fact_sheet(group: dict[str, Any]) -> dict[str, Any]:
    """Return a fact sheet for one group without its id list."""
    sheet = {field: group[field] for field in SHEET_FIELDS if field in group}
    sheet["anchorCount"] = len(group.get("anchorIds", []))
    sheet["anchorNames"] = [item.get("name") for item in group.get("anchors", {}).get("items", [])]
    return sheet


def page_groups(anchors: dict[str, Any], offset: int, limit: int) -> dict[str, Any]:
    """Return one page of group fact sheets from an anchors artifact."""
    groups = anchors.get("groups", [])
    page = groups[offset : offset + limit]
    following = offset + len(page)
    return {
        "total": len(groups),
        "offset": offset,
        "next": following if following < len(groups) else None,
        "groups": [fact_sheet(group) for group in page],
    }


def lineage(document: dict[str, Any], limit: int) -> dict[str, Any]:
    """Summarize a data-lineage artifact: which systems feed which pipelines, and what they write."""
    canvas = document.get("Canvas") or {}
    nodes = {node["Id"]: node for node in canvas.get("Nodes", [])}
    sources: dict[str, set[str]] = {}
    targets: dict[str, set[str]] = {}
    weight: dict[str, int] = {}
    for edge in canvas.get("Edges", []):
        start, end = nodes.get(edge.get("From")), nodes.get(edge.get("To"))
        if not start or not end:
            continue
        if start["Lane"] == "source" and end["Lane"] == "pipeline":
            sources.setdefault(end["Id"], set()).add(start["Label"])
            weight[end["Id"]] = weight.get(end["Id"], 0) + edge.get("Weight", 1)
        elif start["Lane"] == "pipeline" and end["Lane"] == "target":
            targets.setdefault(start["Id"], set()).add(end["Label"])
            weight[start["Id"]] = weight.get(start["Id"], 0) + edge.get("Weight", 1)

    writers: dict[str, int] = {}
    flows: dict[tuple[str, str], int] = {}
    for pipeline, written in targets.items():
        for system in written:
            writers[system] = writers.get(system, 0) + 1
            for source in sources.get(pipeline, ()):
                flows[(source, system)] = flows.get((source, system), 0) + 1

    pipelines = sorted(weight, key=lambda id_: (-weight[id_], nodes[id_]["Label"]))[:limit]
    return {
        "summary": document.get("Summary", {}),
        "missingInputs": [f"{item.get('Kind')}: {item.get('Ask')}" for item in document.get("MissingInputs", []) or []],
        "targets": [{"system": system, "pipelines": count} for system, count in sorted(writers.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]],
        "flows": [
            {"from": source, "to": system, "pipelines": count}
            for (source, system), count in sorted(flows.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]
        ],
        "pipelines": [
            {
                "name": nodes[id_]["Label"],
                "kind": nodes[id_].get("Kind"),
                "platform": nodes[id_].get("Platform"),
                "sources": sorted(sources.get(id_, ()))[:PIPELINE_SYSTEMS],
                "targets": sorted(targets.get(id_, ()))[:PIPELINE_SYSTEMS],
            }
            for id_ in pipelines
        ],
    }


def landing(anchors: dict[str, Any], group: str | None, offset: int, limit: int) -> dict[str, Any]:
    """Return one page of landing objects, largest flow first, optionally from one group."""
    items = [anchor for anchor in anchors.get("anchors", []) if group is None or anchor.get("groupKey") == group]
    items.sort(key=lambda anchor: (-anchor.get("flowSize", 0), anchor.get("object", {}).get("name") or "", anchor["id"]))
    page = items[offset : offset + limit]
    following = offset + len(page)
    return {
        "total": len(items),
        "offset": offset,
        "next": following if following < len(items) else None,
        "landing": [
            {
                "id": anchor["id"],
                "name": anchor.get("object", {}).get("name"),
                "shape": anchor.get("shape"),
                "groupKey": anchor.get("groupKey"),
                "flowSize": anchor.get("flowSize", 0),
                "sourcePath": anchor.get("object", {}).get("sourcePath"),
                "exits": [detection.get("citation") for detection in anchor.get("detections", [])],
                "hints": [hint.get("kind") for hint in anchor.get("hints", [])],
            }
            for anchor in page
        ],
    }


def unplaced(anchors: dict[str, Any], draft: dict[str, Any]) -> list[dict[str, Any]]:
    """List groups the draft neither uses nor marks technical, most anchors first."""
    placed: set[str] = {entry.get("groupKey") for entry in draft.get("technicalGroups", []) or []}
    anchor_ids: set[str] = set()
    for use_case in draft.get("useCases", []) or []:
        placed.update(use_case.get("groupKeys", []) or [])
        anchor_ids.update(use_case.get("anchorIds", []) or [])
    left = [
        group
        for group in anchors.get("groups", [])
        if group["key"] not in placed and not anchor_ids.intersection(group.get("anchorIds", []))
    ]
    left.sort(key=lambda group: (-len(group.get("anchorIds", [])), group["key"]))
    return [{"key": group["key"], "anchorCount": len(group.get("anchorIds", [])), "memberCount": group.get("memberCount", 0)} for group in left]


def unevidenced(anchors: dict[str, Any], offset: int, limit: int) -> dict[str, Any]:
    """Page the groups no exit and no report backs, most members first, as fact sheets."""
    groups = [
        group
        for group in anchors.get("groups", [])
        if not any((group.get("anchorsByShape") or {}).get(shape, 0) for shape in EVIDENCE_SHAPES)
    ]
    groups.sort(key=lambda group: (-group.get("memberCount", 0), group["key"]))
    page = groups[offset : offset + limit]
    following = offset + len(page)
    return {
        "total": len(groups),
        "members": sum(group.get("memberCount", 0) for group in groups),
        "offset": offset,
        "next": following if following < len(groups) else None,
        "groups": [fact_sheet(group) for group in page],
    }


def _landing(anchors: dict[str, Any]) -> tuple[dict[str, list[str]], set[str]]:
    by_group = {group["key"]: list(group.get("anchorIds", [])) for group in anchors.get("groups", [])}
    return by_group, {anchor["id"] for anchor in anchors.get("anchors", [])} | {id_ for ids in by_group.values() for id_ in ids}


def _held(use_case: dict[str, Any], by_group: dict[str, list[str]]) -> set[str]:
    held = set(use_case.get("anchorIds", []) or [])
    for key in use_case.get("groupKeys", []) or []:
        held.update(by_group.get(key, []))
    return held


def check_ai(anchors: dict[str, Any], draft: dict[str, Any]) -> list[str]:
    """Every problem in an other-objects draft, as `useCases[i].field: …`; empty when it can be merged."""
    by_group, known = _landing(anchors)
    problems: list[str] = []
    use_cases = draft.get("useCases")
    if draft.get("schemaVersion") != 1:
        problems.append("schemaVersion: must be 1")
    if not isinstance(use_cases, list):
        return [*problems, "useCases: a list, empty when nothing outside the evidence holds an outcome"]
    if not use_cases:
        return problems
    bridged = []
    for i, use_case in enumerate(use_cases):
        at = f"useCases[{i}]"
        if use_case.get("origin") != AI_ANALYSIS:
            problems.append(f"{at}.origin: must be {AI_ANALYSIS}")
        keys = use_case.get("groupKeys", []) or []
        ids = use_case.get("anchorIds", []) or []
        if not keys and not ids:
            problems.append(f"{at}: list groupKeys, anchorIds or both")
        problems.extend(f"{at}.groupKeys: '{key}' is not a group in anchors.json" for key in keys if key not in by_group)
        problems.extend(f"{at}.anchorIds: '{id_}' is not an anchor in anchors.json" for id_ in ids if id_ not in known)
        seeds = sorted(_held(use_case, by_group))[:1] or ["none"]
        bridged.append({**use_case, "status": "proposed", "confidence": "low", "seedIds": seeds})
    problems.extend(check({"schemaVersion": 1, "useCases": bridged}))
    return problems


def merge(anchors: dict[str, Any], draft: dict[str, Any], ai_draft: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fold AI analysis use cases into the lineage draft. Return the merged draft and what happened to each.

    A lineage use case or a technical group keeps every landing object it holds. An AI analysis use
    case keeps only landing objects no earlier use case holds: a shared group becomes its free
    anchors, and a use case left with none, or repeating an id or a name, is dropped.
    """
    by_group, known = _landing(anchors)
    lineage = [use_case for use_case in draft.get("useCases", []) or [] if use_case.get("origin") != AI_ANALYSIS]
    technical = draft.get("technicalGroups", []) or []
    held: set[str] = set()
    for use_case in lineage:
        held |= _held(use_case, by_group)
    for group in technical:
        held.update(by_group.get(group.get("groupKey"), []))
    ids = {use_case.get("id") for use_case in lineage}
    names = {" ".join(str(use_case.get("name") or "").lower().split()) for use_case in lineage}

    kept: list[dict[str, Any]] = []
    trimmed: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for use_case in ai_draft.get("useCases", []) or []:
        id_ = use_case.get("id")
        name = " ".join(str(use_case.get("name") or "").lower().split())
        if id_ in ids:
            dropped.append({"id": id_, "reason": "its id is already a use case"})
            continue
        if name in names:
            dropped.append({"id": id_, "reason": "a use case with the same name already exists"})
            continue
        group_keys: list[str] = []
        anchor_ids: list[str] = []
        removed = 0
        for key in use_case.get("groupKeys", []) or []:
            members = by_group.get(key)
            if members is None:
                continue
            free = [anchor for anchor in members if anchor not in held]
            if len(free) == len(members):
                group_keys.append(key)
            else:
                anchor_ids.extend(free)
                removed += len(members) - len(free)
        for anchor in use_case.get("anchorIds", []) or []:
            if anchor not in known:
                continue
            if anchor in held:
                removed += 1
            elif anchor not in anchor_ids:
                anchor_ids.append(anchor)
        if not group_keys and not anchor_ids:
            dropped.append({"id": id_, "reason": "every landing object is already in another use case"})
            continue
        entry = {**use_case, "origin": AI_ANALYSIS, "groupKeys": group_keys, "anchorIds": anchor_ids}
        held |= _held(entry, by_group)
        ids.add(id_)
        names.add(name)
        kept.append(entry)
        if removed:
            trimmed.append({"id": id_, "removedLandingObjects": removed})

    merged = {"schemaVersion": 1, "useCases": [*lineage, *kept], "technicalGroups": technical}
    report = {"lineage": len(lineage), "aiAnalysis": len(kept), "trimmed": trimmed, "dropped": dropped}
    return merged, report


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    flows = sub.add_parser("lineage", help="summarize where data goes, from data-lineage.json")
    flows.add_argument("--limit", type=int, default=DEFAULT_LINEAGE_LIMIT)
    lands = sub.add_parser("landing", help="list landing objects, largest flow first")
    lands.add_argument("--group", default=None)
    lands.add_argument("--offset", type=int, default=0)
    lands.add_argument("--limit", type=int, default=DEFAULT_PAGE)
    groups = sub.add_parser("groups", help="print fact sheets, a page at a time")
    groups.add_argument("--offset", type=int, default=0)
    groups.add_argument("--limit", type=int, default=DEFAULT_PAGE)
    sub.add_parser("unplaced", help="list groups the draft neither uses nor marks technical")
    bare = sub.add_parser("unevidenced", help="page the groups no exit and no report backs, most members first")
    bare.add_argument("--offset", type=int, default=0)
    bare.add_argument("--limit", type=int, default=DEFAULT_PAGE)
    sub.add_parser("check-ai", help="report every problem in other-objects-draft.json")
    sub.add_parser("merge", help="fold other-objects-draft.json into catalog-draft.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run a catalog-draft subcommand and print JSON. Return 0 on success, 1 on a read error."""
    args = _parse(sys.argv[1:] if argv is None else argv)
    try:
        if args.command == "lineage":
            result: Any = lineage(_load(LINEAGE, "scai assessment data-lineage"), max(args.limit, 1))
        elif args.command == "landing":
            result = landing(_load(ANCHORS), args.group, max(args.offset, 0), max(args.limit, 1))
        elif args.command == "groups":
            result = page_groups(_load(ANCHORS), max(args.offset, 0), max(args.limit, 1))
        elif args.command == "unevidenced":
            result = unevidenced(_load(ANCHORS, "scai assessment waves anchors"), max(args.offset, 0), max(args.limit, 1))
        elif args.command == "check-ai":
            problems = check_ai(_load(ANCHORS, "scai assessment waves anchors"), _load(AI_DRAFT))
            print(json.dumps({"problems": problems, "ok": not problems}, indent=2))
            return 1 if problems else 0
        elif args.command == "merge":
            merged, result = merge(_load(ANCHORS, "scai assessment waves anchors"), _load(DRAFT), _load(AI_DRAFT))
            DRAFT.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
        else:
            result = unplaced(_load(ANCHORS), _load(DRAFT))
    except DraftError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
