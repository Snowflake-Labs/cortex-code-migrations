"""Compose and check business-use-cases.json from the bins `scai assessment waves cluster` writes.

Subcommands:
  bins     print the fact sheets of the bins, a page at a time, without their id lists
  compose  write business-use-cases.json from bins plus narratives, or placeholders for a dry run
  check    report every length, count, duplicate-name and repeated-sentence problem in one pass

Stdlib only. Run from the project directory:
  uv run --project <assessment_skill_dir> python <assessment_skill_dir>/business-use-cases/scripts/compose_use_cases.py <subcommand>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WAVES_DIR = Path("artifacts") / "assessment" / "waves"
CLUSTERS = WAVES_DIR / "clusters.json"
USE_CASES = WAVES_DIR / "business-use-cases.json"
DRY_RUN = WAVES_DIR / "business-use-cases.dry-run.json"

# Mirrors BusinessUseCaseContract in SCAI; ai/tests/assessment pins them together.
MAX_USE_CASES = 100
MAX_ID_LENGTH = 64
MAX_NAME_LENGTH = 80
MIN_PURPOSE_LENGTH = 120
MAX_PURPOSE_LENGTH = 320
MIN_NARRATIVE_LENGTH = 240
MAX_NARRATIVE_LENGTH = 700
MAX_SEEDS = 50
MAX_MEMBERS = 2000
MAX_LIST_ITEMS = 5
MAX_LIST_ITEM_LENGTH = 240

NARRATIVE_FIELDS = ("whyFound", "howFound", "enablesOnSnowflake")
UNIQUE_FIELDS = ("whyFound", "enablesOnSnowflake")
TEXT_FIELDS = ("name", "purpose", *NARRATIVE_FIELDS)
STATUSES = ("confirmed", "proposed")
CONFIDENCES = ("high", "medium", "low")
ORIGINS = ("seed", "anchor", "onDemand")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# A name or a narrative that describes the clustering instead of the outcome.
TOKEN_NAME = re.compile(r"\bdata\s*\(", re.IGNORECASE)
TOOL_PHRASES = (
    "scai",
    "waves cluster",
    "structural dry run",
    "layer prefix",
    "bin-",
    "sandbox share",
    "roots that share",
    "subject words",
    "ends of flow",
    "binning",
)
# Evidence must cite a file that was read: a path, or a file name with a source extension.
SOURCE_FILE = re.compile(
    r"[\w$.-]+/[\w$.-]+|\b[\w$-]+\.(?:xml|sql|dtsx|bteq|btq|ddl|tpt|prm|par|sh|ksh|py|pbix|twbx?|rdl|json)\b",
    re.IGNORECASE,
)
SHARED_SENTENCE_WORDS = 6
STATUS_ORDER = {"proposed": 0, "confirmed": 1}
CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


class ComposeError(Exception):
    """A narratives file or base draft the composer cannot turn into a valid file."""


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ComposeError(f"{path} does not exist") from exc
    except json.JSONDecodeError as exc:
        raise ComposeError(f"{path} is not valid JSON: {exc}") from exc


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _bins(clusters: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {bin_["id"]: bin_ for bin_ in clusters.get("bins") or []}


def fact_sheet(bin_: dict[str, Any]) -> dict[str, Any]:
    """A bin without its id lists: what a narrative is written from."""
    metrics = bin_.get("metrics") or {}
    return {
        "id": bin_["id"],
        "label": bin_.get("label"),
        "anchor": bin_.get("anchor"),
        "mixed": bin_.get("mixed", False),
        "rootCount": bin_.get("rootCount", 0),
        "objectCount": metrics.get("objectCount", 0),
        "newObjects": bin_.get("newObjects", 0),
        "sandboxShare": bin_.get("sandboxShare", 0),
        "suggestedStatus": bin_.get("suggestedStatus"),
        "suggestedConfidence": bin_.get("suggestedConfidence"),
        "metrics": metrics,
        "conversion": bin_.get("conversion"),
        "facts": bin_.get("facts"),
    }


def page_bins(clusters: dict[str, Any], offset: int, limit: int) -> dict[str, Any]:
    bins = clusters.get("bins") or []
    page = bins[offset : offset + limit]
    return {
        "summary": clusters.get("summary"),
        "dataOnly": clusters.get("dataOnly"),
        "offset": offset,
        "total": len(bins),
        "truncated": offset + len(page) < len(bins),
        "bins": [fact_sheet(bin_) for bin_ in page],
    }


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _weakest(values: list[str | None], order: dict[str, int], default: str) -> str:
    known = [value for value in values if value in order]
    return min(known, key=order.__getitem__) if known else default


def _ids(bins: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Seeds of every bin first, in bin order, then members; split at the seed cap."""
    ordered: list[str] = []
    seen: set[str] = set()
    for key in ("seedIds", "memberIds"):
        for bin_ in bins:
            for id_ in bin_.get(key) or []:
                if id_ not in seen:
                    seen.add(id_)
                    ordered.append(id_)
    return ordered[:MAX_SEEDS], ordered[MAX_SEEDS:]


def _placeholder(label: str, field: str) -> str:
    sentence = f"Placeholder {field} for the {label} bin, written only to measure the structure of the plan before the narrative exists."
    low, high = (MIN_NARRATIVE_LENGTH, MAX_NARRATIVE_LENGTH) if field in NARRATIVE_FIELDS else (MIN_PURPOSE_LENGTH, MAX_PURPOSE_LENGTH)
    text = sentence
    while len(text) < low:
        text += " " + sentence
    return text[:high].rstrip()


def _from_bins(entry: dict[str, Any], bins: list[dict[str, Any]], placeholder: bool) -> dict[str, Any]:
    seeds, members = _ids(bins)
    extra_seeds = [id_ for id_ in entry.get("seedIds") or [] if id_ not in seeds and id_ not in members]
    extra_members = [id_ for id_ in entry.get("memberIds") or [] if id_ not in seeds and id_ not in members]
    seeds += extra_seeds
    members += extra_members
    if len(seeds) > MAX_SEEDS:
        members = seeds[MAX_SEEDS:] + members
        seeds = seeds[:MAX_SEEDS]
    if len(members) > MAX_MEMBERS:
        raise ComposeError(
            f"use case '{entry.get('id')}' would hold {len(seeds) + len(members)} ids from bins "
            f"{[bin_['id'] for bin_ in bins]}; at most {MAX_SEEDS + MAX_MEMBERS} fit, so split it"
        )

    label = " / ".join(str(bin_.get("label") or bin_["id"]) for bin_ in bins)
    use_case: dict[str, Any] = {
        "id": entry.get("id") or _slug(f"{bins[0]['id']}-{bins[0].get('label') or ''}")[:MAX_ID_LENGTH].strip("-"),
        "name": entry.get("name") or label[:MAX_NAME_LENGTH],
        "purpose": entry.get("purpose"),
        "status": entry.get("status") or _weakest([bin_.get("suggestedStatus") for bin_ in bins], STATUS_ORDER, "proposed"),
        "confidence": entry.get("confidence")
        or _weakest([bin_.get("suggestedConfidence") for bin_ in bins], CONFIDENCE_ORDER, "low"),
        "origin": entry.get("origin") or "anchor",
        "seedIds": seeds,
        "memberIds": members,
        "whyFound": entry.get("whyFound"),
        "howFound": entry.get("howFound"),
        "enablesOnSnowflake": entry.get("enablesOnSnowflake"),
        "evidence": entry.get("evidence"),
        "openQuestions": entry.get("openQuestions"),
    }
    if placeholder:
        for field in ("purpose", *NARRATIVE_FIELDS):
            use_case[field] = use_case[field] or _placeholder(label, field)
        use_case["evidence"] = use_case["evidence"] or [f"Bin {bins[0]['id']} from waves cluster."]
        use_case["openQuestions"] = use_case["openQuestions"] or ["Placeholder: written during the structural dry run."]
    return use_case


def compose(
    clusters: dict[str, Any],
    narratives: list[dict[str, Any]] | None,
    base: dict[str, Any] | None,
    placeholder: bool,
) -> dict[str, Any]:
    """The base draft's use cases, then one per narrative entry (or per bin when there are none)."""
    bins = _bins(clusters)
    entries = narratives if narratives is not None else [{"bins": [bin_id]} for bin_id in bins]
    used: dict[str, str] = {}
    composed: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        names = entry.get("bins") or []
        unknown = [name for name in names if name not in bins]
        if unknown:
            raise ComposeError(f"entry {index} names bins clusters.json does not hold: {unknown}")
        if not names and not entry.get("seedIds"):
            raise ComposeError(f"entry {index} names no bins and no seedIds")
        for name in names:
            if name in used:
                raise ComposeError(f"bin {name} is used by both '{used[name]}' and entry {index}")
            used[name] = str(entry.get("id") or index)
        if names:
            composed.append(_from_bins(entry, [bins[name] for name in names], placeholder))
        else:
            composed.append(_from_bins(entry, [{"id": entry.get("id") or f"entry-{index}"}], placeholder))

    existing = list((base or {}).get("useCases") or [])
    taken = {use_case.get("id") for use_case in existing}
    clashes = [use_case["id"] for use_case in composed if use_case["id"] in taken]
    if clashes:
        raise ComposeError(f"ids already in the base draft: {clashes}")
    use_cases = existing + composed
    if len(use_cases) > MAX_USE_CASES:
        raise ComposeError(
            f"{len(use_cases)} use cases; at most {MAX_USE_CASES} fit. Merge bins (list several in one entry's 'bins')"
        )
    return {"schemaVersion": 1, "useCases": use_cases}


def _sentences(text: str, name: str) -> set[str]:
    """Normalized sentences long enough to say something, the use case's own name swapped out."""
    if name:
        text = re.sub(re.escape(name), "<name>", text, flags=re.IGNORECASE)
    result = set()
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        words = re.findall(r"[a-z0-9<>]+", sentence.lower())
        if len(words) >= SHARED_SENTENCE_WORDS:
            result.add(" ".join(words))
    return result


def _length(problems: list[str], where: str, value: Any, low: int, high: int) -> None:
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{where}: required")
    elif not low <= len(value) <= high:
        problems.append(f"{where}: {len(value)} characters, must be {low}–{high}")


def _items(problems: list[str], where: str, value: Any) -> None:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_LIST_ITEMS:
        problems.append(f"{where}: 1–{MAX_LIST_ITEMS} items required")
        return
    for index, item in enumerate(value):
        _length(problems, f"{where}[{index}]", item, 1, MAX_LIST_ITEM_LENGTH)


def _analysis(problems: list[str], where: str, use_case: dict[str, Any]) -> None:
    """Reject a bin label used as a name, and a narrative that describes the clustering."""
    id_ = str(use_case.get("id") or "")
    if id_.startswith("bin-"):
        problems.append(f"{where}.id: '{id_}' is a bin id; name the outcome and slug that")
    name = str(use_case.get("name") or "")
    if TOKEN_NAME.search(name):
        problems.append(f"{where}.name: '{name}' names a token or a schema, not an outcome")
    for field in TEXT_FIELDS:
        text = str(use_case.get(field) or "").lower()
        found = [phrase for phrase in TOOL_PHRASES if phrase in text]
        if found:
            problems.append(f"{where}.{field}: describes the clustering ({', '.join(found)}), not the outcome")
    evidence = use_case.get("evidence")
    if isinstance(evidence, list) and evidence and not any(SOURCE_FILE.search(str(item)) for item in evidence):
        problems.append(f"{where}.evidence: cites no source file; name a workflow, mapping or view file you read")


def check(document: dict[str, Any]) -> list[str]:
    """Every problem in the file, as `useCases[i].field: …`; empty when it is ready for `waves use-cases`."""
    problems: list[str] = []
    use_cases = document.get("useCases")
    if document.get("schemaVersion") != 1:
        problems.append("schemaVersion: must be 1")
    if not isinstance(use_cases, list):
        return [*problems, "useCases: required"]
    if len(use_cases) > MAX_USE_CASES:
        problems.append(f"useCases: {len(use_cases)}, at most {MAX_USE_CASES}")

    ids: dict[str, int] = {}
    names: dict[str, int] = {}
    placeholders: set[int] = set()
    for i, use_case in enumerate(use_cases):
        at = f"useCases[{i}]"
        id_ = use_case.get("id")
        if not isinstance(id_, str) or not SLUG.match(id_) or len(id_) > MAX_ID_LENGTH:
            problems.append(f"{at}.id: lowercase hyphenated slug of 1–{MAX_ID_LENGTH} characters")
        elif id_ in ids:
            problems.append(f"{at}.id: '{id_}' repeats useCases[{ids[id_]}]")
        else:
            ids[id_] = i
        _length(problems, f"{at}.name", use_case.get("name"), 1, MAX_NAME_LENGTH)
        name_key = " ".join(str(use_case.get("name") or "").lower().split())
        if name_key and name_key in names:
            problems.append(f"{at}.name: '{use_case.get('name')}' repeats useCases[{names[name_key]}]")
        elif name_key:
            names[name_key] = i
        _length(problems, f"{at}.purpose", use_case.get("purpose"), MIN_PURPOSE_LENGTH, MAX_PURPOSE_LENGTH)
        for field in NARRATIVE_FIELDS:
            _length(problems, f"{at}.{field}", use_case.get(field), MIN_NARRATIVE_LENGTH, MAX_NARRATIVE_LENGTH)
        for field, allowed in (("status", STATUSES), ("confidence", CONFIDENCES), ("origin", ORIGINS)):
            if use_case.get(field) not in allowed:
                problems.append(f"{at}.{field}: one of {', '.join(allowed)}")
        seeds = use_case.get("seedIds") or []
        members = use_case.get("memberIds") or []
        if not 1 <= len(seeds) <= MAX_SEEDS:
            problems.append(f"{at}.seedIds: {len(seeds)}, must be 1–{MAX_SEEDS}")
        if len(members) > MAX_MEMBERS:
            problems.append(f"{at}.memberIds: {len(members)}, at most {MAX_MEMBERS}")
        _items(problems, f"{at}.evidence", use_case.get("evidence"))
        _items(problems, f"{at}.openQuestions", use_case.get("openQuestions"))
        if any("Placeholder" in str(use_case.get(field) or "") for field in TEXT_FIELDS):
            placeholders.add(i)
        else:
            _analysis(problems, at, use_case)

    for field in UNIQUE_FIELDS:
        owners: dict[str, int] = {}
        for i, use_case in enumerate(use_cases):
            if i in placeholders:
                continue
            for sentence in _sentences(str(use_case.get(field) or ""), str(use_case.get("name") or "")):
                if sentence in owners and owners[sentence] != i:
                    problems.append(f"useCases[{i}].{field}: repeats a sentence of useCases[{owners[sentence]}]: \"{sentence}\"")
                else:
                    owners.setdefault(sentence, i)
    if placeholders:
        problems.append(f"{len(placeholders)} use case(s) still carry placeholder text from the dry run")
    return problems


@dataclass(frozen=True)
class _Args:
    command: str
    project_dir: Path
    clusters: Path | None
    narratives: Path | None
    base: Path | None
    out: Path | None
    file: Path | None
    placeholder: bool
    offset: int
    limit: int


def _parse(argv: list[str]) -> _Args:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project-dir", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    bins = sub.add_parser("bins", help="print bin fact sheets, a page at a time")
    bins.add_argument("--clusters", type=Path)
    bins.add_argument("--offset", type=int, default=0)
    bins.add_argument("--limit", type=int, default=10)
    comp = sub.add_parser("compose", help="write business-use-cases.json from bins and narratives")
    comp.add_argument("--clusters", type=Path)
    comp.add_argument("--narratives", type=Path, help="JSON list of use cases, each naming its 'bins'")
    comp.add_argument("--base", type=Path, help="a draft whose use cases are kept first")
    comp.add_argument("--placeholder", action="store_true", help="fill missing text for a structural dry run")
    comp.add_argument("--out", type=Path)
    chk = sub.add_parser("check", help="report every problem in a business-use-cases.json")
    chk.add_argument("--file", type=Path)
    ns = parser.parse_args(argv)
    return _Args(
        command=ns.command,
        project_dir=ns.project_dir,
        clusters=getattr(ns, "clusters", None),
        narratives=getattr(ns, "narratives", None),
        base=getattr(ns, "base", None),
        out=getattr(ns, "out", None),
        file=getattr(ns, "file", None),
        placeholder=getattr(ns, "placeholder", False),
        offset=getattr(ns, "offset", 0),
        limit=getattr(ns, "limit", 10),
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    root = args.project_dir
    try:
        if args.command == "bins":
            print(json.dumps(page_bins(_load(args.clusters or root / CLUSTERS), args.offset, args.limit), indent=2))
            return 0
        if args.command == "compose":
            narratives = _load(args.narratives) if args.narratives else None
            if isinstance(narratives, dict):
                narratives = narratives.get("useCases")
            if narratives is None and not args.placeholder:
                raise ComposeError("--narratives is required unless --placeholder writes a dry run")
            base = _load(args.base) if args.base else None
            document = compose(_load(args.clusters or root / CLUSTERS), narratives, base, args.placeholder)
            out = args.out or root / (DRY_RUN if args.placeholder else USE_CASES)
            _write(out, document)
            problems = [] if args.placeholder else check(document)
            print(json.dumps({"output": str(out), "useCases": len(document["useCases"]), "problems": problems}, indent=2))
            return 1 if problems else 0
        problems = check(_load(args.file or root / USE_CASES))
        print(json.dumps({"problems": problems, "ok": not problems}, indent=2))
        return 1 if problems else 0
    except ComposeError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
