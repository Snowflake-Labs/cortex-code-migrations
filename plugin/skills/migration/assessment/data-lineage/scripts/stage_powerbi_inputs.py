#!/usr/bin/env python3
"""Stage Power BI templates into a project's ``source/BI/PowerBI/`` directory.

The parent assessment skill runs this once, before it dispatches sub-agents, so
that `scai assessment powerbi extract` — which has no input-path option and only
ever reads that one directory — sees everything the user offered.

**This is the only thing that writes into that directory in this workflow.**
Nothing else — not the parent, not the sub-agent, not the user by hand — should
copy templates there. A second copier means the same template staged under two
names, extracted under two report keys, and analysed twice as if they were two
reports; the no-overwrite and dedupe rules below only hold because one process
applies them.

Contract, in one place because the skill layer depends on all of it:

* Only ``.pbit`` is staged. A ``.pbix`` is reported under ``skipped`` and is
  never copied: the extractor records it as ``unsupported``, so copying one in
  would manufacture a failure row out of a file the user was told is not usable.
* A destination file is **never** overwritten with different bytes. Same name +
  identical SHA-256 is a no-op; same name + different bytes stages the input
  under ``<stem>-<sha256[:8]>.pbit``, which is a function of the content alone
  and so is reproducible across runs and machines.
* Directory inputs are walked recursively without following directory symlinks,
  and every destination is verified to resolve inside the staging directory.
* Discovery is sorted by resolved path, so which of two same-named inputs keeps
  the plain basename does not depend on the order the user listed them.

Run with no ``--input`` to inventory what is already staged.

Output is one JSON object on stdout; diagnostics go to stderr. The exit code is
0 whenever the inventory is trustworthy, even if individual inputs were skipped
— the caller decides what to do about a skip. It is 2 only when an argument is
unusable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

STAGING_SUBPATH = ("source", "BI", "PowerBI")

_PBIT = ".pbit"
_PBIX = ".pbix"

_READ_CHUNK = 1024 * 1024

# Long enough to identify a failure, short enough that a hostile filename cannot
# bury the rest of the report in the parent's context.
_MAX_MESSAGE = 300


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_READ_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def staging_dir(project_dir: Path) -> Path:
    return project_dir.joinpath(*STAGING_SUBPATH)


def _is_regular_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def discover(inputs: list[Path]) -> tuple[list[Path], list[dict[str, str]]]:
    """Resolve every ``.pbit`` reachable from ``inputs``.

    Returns the candidates sorted by resolved path, plus one skip record per
    path that was reachable but not stageable.
    """
    candidates: dict[Path, None] = {}
    skipped: list[dict[str, str]] = []

    def consider(path: Path) -> None:
        suffix = path.suffix.lower()
        if suffix == _PBIT:
            if _is_regular_file(path):
                candidates[path.resolve()] = None
            else:
                skipped.append({"source": str(path), "reason": "not-a-regular-file"})
        elif suffix == _PBIX:
            skipped.append({"source": str(path), "reason": "pbix-unsupported"})

    for raw in inputs:
        # One unreachable path must not cost the rest of the discovery pass.
        try:
            resolved = raw.expanduser().resolve()
            if resolved.is_dir():
                for root, dirnames, filenames in os.walk(resolved, followlinks=False):
                    dirnames.sort()
                    for filename in sorted(filenames):
                        consider(Path(root) / filename)
            elif _is_regular_file(resolved):
                consider(resolved)
            else:
                skipped.append({"source": str(raw), "reason": "not-found"})
        except OSError:
            skipped.append({"source": str(raw), "reason": "unreadable"})

    return sorted(candidates), skipped


def _describe(error: OSError) -> str:
    """One bounded, single-line rendering of an OSError.

    The text lands in a JSON document the parent shows the user, and it can
    carry a filename the user did not choose, so it is flattened and capped
    rather than passed through.
    """
    raw = error.strerror or str(error) or error.__class__.__name__
    if error.errno is not None:
        raw = f"[Errno {error.errno}] {raw}"
    flattened = " ".join(str(raw).split())
    printable = "".join(character for character in flattened if character.isprintable())
    return printable[:_MAX_MESSAGE].rstrip()


def _failure(source: Path | str, error: OSError) -> dict[str, str]:
    return {"source": str(source), "message": _describe(error)}


def inventory(destination: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Every ``.pbit`` already staged, sorted, with its digest.

    Returns the entries it could read plus one error record per file it could
    not, so a template that is present but unreadable is reported rather than
    quietly missing from the count the parent dispatches on.
    """
    try:
        if not destination.is_dir():
            return [], []
        paths = sorted(destination.rglob("*"))
    except OSError as error:
        return [], [_failure(destination, error)]

    staged: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    for path in paths:
        try:
            if path.suffix.lower() != _PBIT or not _is_regular_file(path):
                continue
            staged.append({"path": str(path), "sha256": sha256_of(path)})
        except OSError as error:
            errors.append(_failure(path, error))
    return staged, errors


def _copy_into(source: Path, target: Path) -> None:
    """Copy through a sibling temporary file so a reader never sees a partial."""
    handle, temporary = tempfile.mkstemp(dir=str(target.parent), prefix=".staging-")
    os.close(handle)
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def stage(destination: Path, candidates: list[Path]) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {
        "staged": [],
        "already_present": [],
        "errors": [],
    }
    if not candidates:
        return result

    try:
        destination.mkdir(parents=True, exist_ok=True)
        resolved_destination = destination.resolve()
    except OSError as error:
        # Nothing can be staged, but every candidate still gets a record: the
        # parent has to be able to tell the user which templates were lost.
        result["errors"].extend(_failure(source, error) for source in candidates)
        return result

    # Dedupe on content, not on name: two copies of one template under two names
    # would otherwise extract as two report keys and be analysed twice. A file
    # here we cannot hash simply does not dedupe; `run` reports it separately.
    existing, _ = inventory(destination)
    by_digest = {entry["sha256"]: entry["path"] for entry in existing}

    for source in candidates:
        # One unreadable source, one full disk, one permission denied: the other
        # templates the user handed over are still worth staging.
        try:
            _stage_one(source, resolved_destination, by_digest, result)
        except OSError as error:
            result["errors"].append(_failure(source, error))

    return result


def _stage_one(
    source: Path,
    resolved_destination: Path,
    by_digest: dict[str, str],
    result: dict[str, list[dict[str, str]]],
) -> None:
    digest = sha256_of(source)
    if digest in by_digest:
        result["already_present"].append(
            {
                "source": str(source),
                "destination": by_digest[digest],
                "sha256": digest,
            }
        )
        return

    preferred = resolved_destination / f"{source.stem}{_PBIT}"
    fallback = resolved_destination / f"{source.stem}-{digest[:8]}{_PBIT}"
    for attempt in (preferred, fallback):
        if resolved_destination not in attempt.resolve().parents:
            result["errors"].append(
                {
                    "source": str(source),
                    "message": (
                        f"destination '{attempt}' resolves outside "
                        f"'{resolved_destination}'"
                    ),
                }
            )
            return
        if attempt.exists():
            continue
        _copy_into(source, attempt)
        by_digest[digest] = str(attempt)
        result["staged"].append(
            {"source": str(source), "destination": str(attempt), "sha256": digest}
        )
        return

    result["errors"].append(
        {
            "source": str(source),
            "message": (
                "a different file already occupies both the preferred and the "
                "content-addressed destination name"
            ),
        }
    )


def _empty_report(project_dir: Path) -> dict[str, Any]:
    """Every key the contract promises, with nothing in it."""
    return {
        "project_dir": str(project_dir),
        "destination": str(staging_dir(project_dir)),
        "staged": [],
        "already_present": [],
        "skipped": [],
        "errors": [],
        "pbit_files": [],
        "pbit_count": 0,
    }


def run(project_dir: Path, inputs: list[Path]) -> dict[str, Any]:
    destination = staging_dir(project_dir)
    candidates, skipped = discover(inputs)
    outcome = stage(destination, candidates)
    staged_now, inventory_errors = inventory(destination)
    return {
        "project_dir": str(project_dir),
        "destination": str(destination),
        "staged": outcome["staged"],
        "already_present": outcome["already_present"],
        "skipped": skipped,
        "errors": outcome["errors"] + inventory_errors,
        # `path` is project-relative: that is what the parent records as
        # `data_lineage.staged_pbits` and hands to the sub-agent.
        "pbit_files": [
            {
                "path": Path(entry["path"]).relative_to(project_dir).as_posix(),
                "absolute_path": entry["path"],
                "sha256": entry["sha256"],
            }
            for entry in staged_now
        ],
        "pbit_count": len(staged_now),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stage Power BI .pbit templates into <project-dir>/source/BI/PowerBI/."
    )
    parser.add_argument("--project-dir", required=True, help="SCAI project root")
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        metavar="PATH",
        help="a .pbit file or a directory to search recursively (repeatable)",
    )
    args = parser.parse_args(argv)

    project_dir = Path(args.project_dir).expanduser()
    try:
        if not project_dir.is_dir():
            print(
                f"error: project dir {project_dir} is not a directory", file=sys.stderr
            )
            return 2
        report = run(project_dir.resolve(), [Path(value) for value in args.input])
    except OSError as error:
        # The parent parses stdout as JSON. Even a failure it cannot recover from
        # has to arrive in that shape, or it reads a traceback as a staging report.
        report = _empty_report(project_dir)
        report["errors"] = [_failure(project_dir, error)]

    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
