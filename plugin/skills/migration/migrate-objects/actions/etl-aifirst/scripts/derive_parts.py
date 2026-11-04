#!/usr/bin/env python3
"""Derive a CUR `parts[]` payload from the emitted dbt tree, deterministically.

WHY THIS IS A SCRIPT AND NOT SKILL PROSE
----------------------------------------
Every other AI-First registry write is an agent reading instructions and calling a
tool. That is a weaker guarantee than the native path, where the engine emits
artifacts and records them in the same pass. This script moves the one remaining
derivation that *can* be mechanical out of the agent's hands: the agent runs it and
relays the output, instead of assembling the payload by judgement.

WHY IT READS THE EMITTED TREE AND NOT THE ELEMENT CENSUS
--------------------------------------------------------
`ETL.Elements` looks like the right input -- it is the element inventory, shaped to
match native's -- but its `FullName` is a source element *id* (`'6'`), not a model
name. Joining it to an emitted model would mean re-deriving `model_name`, which is
table-driven (`naming_policy`: `name_from`, `lowercase`,
`replace_whitespace_with`, `qualify_with_container`) and differs per platform.
Re-implementing that here would create a second copy of a rule that already drifted
once in this codebase -- #5606 found the Alteryx table generator silently out of
step with its own committed JSON in two places. The emitted tree is the artifact
those rules already produced, so reading it cannot disagree with them.

The census is still the right source for *which elements exist and how they fared*;
that belongs in the stakeholder report, not in the part list.

PART NAME IS THE STABILITY KEY
------------------------------
`update_registry`'s parts writer matches incoming parts to existing ones by `name`
to carry the part `id` forward, so re-running conversion does not churn ids. The
dbt project directory name is the stable choice for the data-flow part: the driver
derives it from the document's container, so it only changes when the source is
renamed -- the same property the native engine relies on when it matches SSIS task
`Name`.

Usage:
  derive_parts.py --output-root <dbt project dir> --project-dir <project root>
                  [--orchestration <file>] [--issues <issues.json>]

Prints a JSON array to stdout, ready for:
  update_registry(field="parts", objects=["<unit_id>"], value=<this>)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# A dbt model under models/ is a data flow; the orchestration SQL beside the project
# is the control flow. These are the two partType values the canonical ETL unit uses.
DATA_FLOW = "dataFlow"
CONTROL_FLOW = "controlFlow"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--output-root", required=True,
                   help="package root snowflake/_etl/<PACKAGE> (skill contract). "
                        "models/ may sit here or one level down in the copied dbt project.")
    p.add_argument("--project-dir", required=True,
                   help="project root; every target.path is made relative to this")
    p.add_argument("--orchestration",
                   help="orchestration SQL file; defaults to <output-root>/<name>.sql")
    p.add_argument("--issues",
                   help="AiFirstIssues issues.json, to attach per-part issues[]")
    return p.parse_args(argv)


def rel_to_project(path: Path, project_dir: Path) -> str:
    """A project-relative POSIX path.

    Every CUR consumer joins these against the project directory, and
    `update_registry` refuses an absolute value outright, so this is not cosmetic.
    """
    rel = os.path.relpath(path.resolve(), project_dir.resolve())
    return Path(rel).as_posix()


def load_issue_index(issues_path: Path | None) -> dict[str, list[dict]]:
    """Map model file stem -> CUR `Issue` objects, from issues.json.

    An EMIT finding states the generated file it was found in, which is what lets a
    finding be attributed to one part rather than smeared across the whole unit. A
    finding with no model reference is a unit-level fact and is deliberately skipped
    here -- it belongs on the unit, not invented onto an arbitrary part.
    """
    if issues_path is None or not issues_path.is_file():
        return {}
    try:
        payload = json.loads(issues_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # Never fail the derivation over a malformed side file: the parts themselves
        # are the load-bearing output, and a missing issues list degrades honestly.
        print(f"derive_parts: ignoring unreadable issues file {issues_path}: {exc}",
              file=sys.stderr)
        return {}

    instances = payload.get("instances")
    if not isinstance(instances, list):
        instances = payload.get("issues") if isinstance(payload.get("issues"), list) else []

    index: dict[str, dict[tuple[str, str], int]] = {}
    for inst in instances:
        if not isinstance(inst, dict):
            continue
        raw = str(inst.get("element_id") or "")
        model_ref = raw if ("/" in raw or raw.endswith(".sql")) else ""
        if not model_ref:
            continue
        stem = Path(model_ref).stem
        code = str(inst.get("code") or inst.get("rule") or "").strip()
        if not code:
            continue
        severity = str(inst.get("severity") or "medium").strip().lower()
        key = (code, severity)
        index.setdefault(stem, {})
        index[stem][key] = index[stem].get(key, 0) + 1

    return {
        stem: [{"code": c, "severity": s, "count": n} for (c, s), n in sorted(counts.items())]
        for stem, counts in index.items()
    }


def models_dir_for(output_root: Path) -> Path | None:
    """Locate models/ under the skill's --output-root.

    MIGRATE.md Step 4 copies `$STAGE/Output/ETL/<PACKAGE>` to `snowflake/_etl/<PACKAGE>`.
    The driver nests the dbt project one extra level:

        <PACKAGE>/<PACKAGE>.sql          ← control flow (already found here)
        <PACKAGE>/<PACKAGE>/models/      ← data flows

    That is also convert/SKILL.md's native `_etl` layout (`<package>/<data_pipeline>/models`).
    A direct `<PACKAGE>/models` still wins when a tree is already flat, so existing fixtures
    and a caller who passed the inner dbt directory keep working.
    """
    direct = output_root / "models"
    if direct.is_dir():
        return direct
    named = output_root / output_root.name / "models"
    if named.is_dir():
        return named
    nested: list[Path] = []
    try:
        children = sorted(output_root.iterdir())
    except OSError:
        return None
    for child in children:
        if not child.is_dir() or child.name.startswith("."):
            continue
        candidate = child / "models"
        if candidate.is_dir():
            nested.append(candidate)
    if len(nested) == 1:
        return nested[0]
    if len(nested) > 1:
        print(
            f"derive_parts: {len(nested)} nested models/ dirs under {output_root}; "
            "not guessing. Pass the dbt project directory as --output-root.",
            file=sys.stderr,
        )
    return None


def data_flow_parts(output_root: Path, project_dir: Path,
                    issue_index: dict[str, list[dict]],
                    control_name: str | None = None) -> list[dict]:
    """One dbt part per emitted dbt project, the same shape native SSIS writes.

    `scai code deploy` treats a dbt part's `target.path` as the project directory it
    deploys, and only rewrites the task graph's `EXECUTE DBT PROJECT` reference when the
    package has exactly one dbt part. A part per model file therefore fails deploy with
    FileNotFound, and even with a directory path would deploy under a model's name.
    """
    models_dir = models_dir_for(output_root)
    if models_dir is None:
        return []
    models = sorted(models_dir.rglob("*.sql"))
    if not models:
        return []
    dbt_dir = models_dir.parent
    name = dbt_dir.name
    # update_registry carries part ids forward by name, so a data-flow part must not
    # share its name with the orchestration part beside it.
    if name == control_name:
        name = f"{name}_dbt"
    part = {
        "name": name,
        "partType": DATA_FLOW,
        "target": {
            "path": rel_to_project(dbt_dir, project_dir),
            "format": "dbt",
        },
    }
    counts: dict[tuple[str, str], int] = {}
    for sql in models:
        for issue in issue_index.get(sql.stem, []):
            key = (issue["code"], issue["severity"])
            counts[key] = counts.get(key, 0) + issue["count"]
    if counts:
        part["issues"] = [
            {"code": c, "severity": s, "count": n} for (c, s), n in sorted(counts.items())
        ]
    return [part]


def control_flow_part(output_root: Path, project_dir: Path,
                      explicit: Path | None) -> dict | None:
    """The orchestration SQL beside the dbt project, if one was emitted.

    Returns None rather than a targetless part when there is nothing on disk: a part
    with no target is skipped by every consumer that routes on `target.objectType`,
    so emitting one would add a row that looks like coverage and provides none.
    """
    candidate = explicit
    if candidate is None:
        named = output_root / f"{output_root.name}.sql"
        candidate = named if named.is_file() else None
    if candidate is None:
        # Fall back to any top-level .sql that is not inside models/.
        tops = sorted(p for p in output_root.glob("*.sql") if p.is_file())
        candidate = tops[0] if tops else None
    if candidate is None or not candidate.is_file():
        return None
    return {
        "name": candidate.stem,
        "partType": CONTROL_FLOW,
        "target": {
            "path": rel_to_project(candidate, project_dir),
            "format": "snowflakeSQL",
            "objectType": "task",
        },
    }


def derive(output_root: Path, project_dir: Path,
           orchestration: Path | None, issues: Path | None) -> list[dict]:
    issue_index = load_issue_index(issues)
    control = control_flow_part(output_root, project_dir, orchestration)
    parts = data_flow_parts(output_root, project_dir, issue_index,
                            control["name"] if control else None)
    if control is not None:
        parts.append(control)
    return parts


def main(argv=None) -> int:
    args = parse_args(argv)
    output_root = Path(args.output_root)
    project_dir = Path(args.project_dir)

    if not output_root.is_dir():
        print(f"derive_parts: --output-root is not a directory: {output_root}",
              file=sys.stderr)
        return 2

    parts = derive(
        output_root,
        project_dir,
        Path(args.orchestration) if args.orchestration else None,
        Path(args.issues) if args.issues else None,
    )

    if not parts:
        # An empty array is a legal CUR state, but a conversion that emitted nothing is more
        # likely a defect than a job with no models, so say so on stderr.
        print(f"derive_parts: no .sql under {output_root} -- emitting an empty parts "
              "array. If conversion was supposed to produce models, treat this as a "
              "conversion failure, not an empty job.", file=sys.stderr)

    json.dump(parts, sys.stdout, indent=2, sort_keys=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
