#!/usr/bin/env python3
"""Upload the flat files an ingestion manifest names into the Snowflake landing stage.

Runs on the POSIX host that owns the original ETL source files. Reads
ingestion-manifest.json directly, so it needs no regeneration when a
re-conversion changes the manifest. Standard library only.

  python3 land-files.py ingestion-manifest.json --connection prod --database MIGRATED

Every upload is uncompressed and overwrites in place, because the generated
COPY names an exact object and treats the prefix as a landing slot.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_SCHEMA_VERSIONS = {"1.0"}

# Two sources claiming one stage object. `OVERWRITE = TRUE` would let the second PUT
# replace the object the generated COPY names, so a plan that records this must not upload.
COLLISION_MARKER = "both land on"

# The stage destination goes into the PUT as a single-quoted literal, so a folder such as
# `2024 Q1` lands as itself. Only a landing_stage path of these characters may pass: no
# quote or backslash can close the literal, so a manifest cannot append another statement.
STAGE_DEST = re.compile(r"^@public\.landing_stage/(?:[A-Za-z0-9_. -]+/)+$")


@dataclass
class Transfer:
    """One `PUT` — a local path or wildcard, and the stage prefix it lands under."""

    source_id: str
    package: str
    local_spec: str
    stage_dest: str
    file_names: list[str] = field(default_factory=list)


@dataclass
class Report:
    transfers: list[Transfer] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[tuple[str, str]] = field(default_factory=list)
    empty: list[tuple[str, str]] = field(default_factory=list)


def stage_destination_ok(stage_dest: str) -> bool:
    return STAGE_DEST.fullmatch(stage_dest) is not None


def parse_path_roots(values: list[str]) -> list[tuple[str, Path]]:
    """`C:=/mnt/c` rewrites a manifest location prefix onto a local root."""
    roots = []
    for value in values:
        original, separator, local = value.partition("=")
        if not separator or not original or not local:
            sys.exit(f"--path-root must look like 'ORIGINAL=LOCAL', got {value!r}")
        roots.append((original.replace("\\", "/").rstrip("/").lower(), Path(local)))
    return roots


def resolve_location(original: str, path_roots: list[tuple[str, Path]]) -> Path | None:
    """Map one manifest location onto this host, preferring an explicit --path-root."""
    normalized = original.replace("\\", "/")
    lowered = normalized.lower()
    for prefix, local_root in path_roots:
        if lowered == prefix or lowered.startswith(prefix + "/"):
            relative = normalized[len(prefix) :].strip("/")
            candidate = local_root / relative if relative else local_root
            if candidate.exists():
                return candidate
    direct = Path(os.path.expandvars(os.path.expanduser(normalized)))
    return direct if direct.exists() else None


def find_root(source: dict, path_roots: list[tuple[str, Path]]) -> Path | None:
    for original in source.get("originalLocations", []):
        resolved = resolve_location(original, path_roots)
        if resolved is not None:
            return resolved
    return None


def matching_files(directory: Path, file_spec: str, recurse: bool) -> list[Path]:
    walker = directory.rglob("*") if recurse else directory.glob("*")
    return sorted(
        path for path in walker if path.is_file() and fnmatch.fnmatchcase(path.name, file_spec)
    )


def plan_exact(source: dict, root: Path, stage_prefix: str, report: Report) -> None:
    file_name = source["selection"].get("fileName")
    if not file_name:
        report.errors.append((source["id"], "exact selection has no fileName"))
        return
    candidate = root if root.is_file() else root / file_name
    if not candidate.is_file():
        report.errors.append((source["id"], f"file does not exist: {candidate}"))
        return
    report.transfers.append(
        Transfer(source["id"], source.get("packageName", ""), str(candidate), stage_prefix, [file_name])
    )


def plan_glob(source: dict, root: Path, stage_prefix: str, report: Report) -> None:
    selection = source["selection"]
    file_spec = selection.get("fileSpec")
    if not file_spec:
        report.errors.append((source["id"], "glob selection has no fileSpec"))
        return
    if not root.is_dir():
        report.errors.append((source["id"], f"directory does not exist: {root}"))
        return

    recurse = selection.get("recurse") is True
    matches = matching_files(root, file_spec, recurse)
    if not matches:
        report.empty.append((source["id"], f"no files match {file_spec!r} under {root}"))
        return

    flatten = source.get("destinationKeyPolicy", "basename") == "basename"

    # One PUT per directory rather than per file: the wildcard uploads the whole
    # directory in parallel, which is what makes hundreds of files practical.
    by_directory: dict[Path, list[Path]] = {}
    for match in matches:
        by_directory.setdefault(match.parent, []).append(match)

    for directory, files in sorted(by_directory.items()):
        if flatten:
            stage_dest = stage_prefix
        else:
            relative = directory.relative_to(root).as_posix()
            stage_dest = stage_prefix if relative == "." else f"{stage_prefix}{relative}/"
        if not stage_destination_ok(stage_dest):
            report.errors.append(
                (source["id"], f"stage path is not a landing_stage path: {stage_dest}")
            )
            continue
        report.transfers.append(
            Transfer(
                source["id"],
                source.get("packageName", ""),
                str(directory / file_spec),
                stage_dest,
                [f.name for f in files],
            )
        )


def build_plan(manifest: dict, path_roots: list[tuple[str, Path]], only: set[str]) -> Report:
    report = Report()
    version = manifest.get("schemaVersion")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        sys.exit(
            f"Manifest schemaVersion {version!r} is not supported by this script "
            f"(expected one of {sorted(SUPPORTED_SCHEMA_VERSIONS)}). Get a newer script "
            "rather than editing this one — the field names may have changed."
        )

    for source in manifest.get("sources", []):
        source_id = source.get("id", "<no id>")
        if only and source_id not in only:
            continue
        if source.get("resolutionState") != "resolved":
            report.skipped.append((source_id, "conversion could not resolve a real path"))
            continue
        stage_prefix = (source.get("mapping") or {}).get("expectedStagePrefix")
        if not stage_prefix:
            report.skipped.append((source_id, "manifest has no mapping.expectedStagePrefix"))
            continue
        if not stage_prefix.endswith("/"):
            stage_prefix += "/"
        if not stage_destination_ok(stage_prefix):
            report.errors.append((source_id, f"stage prefix is not a landing_stage path: {stage_prefix}"))
            continue

        root = find_root(source, path_roots)
        if root is None:
            locations = ", ".join(source.get("originalLocations", [])) or "<none>"
            report.errors.append(
                (source_id, f"none of these exist on this host: {locations} (try --path-root)")
            )
            continue

        kind = (source.get("selection") or {}).get("kind")
        if kind == "exact":
            plan_exact(source, root, stage_prefix, report)
        elif kind == "glob":
            plan_glob(source, root, stage_prefix, report)
        else:
            report.errors.append((source_id, f"unsupported selection kind {kind!r}"))

    flag_collisions(report)
    return report


def flag_collisions(report: Report) -> None:
    """Two different files landing on one stage object means the second wins silently.

    Within one source that is the declared consequence of `basename` plus `recurse`
    — same-named files in sibling directories flatten onto one prefix — so it is a
    loud warning, not a failure. Across two sources it is a contradiction in the
    plan: the error is recorded here, and `main` refuses to upload anything.
    """
    seen: dict[str, tuple[str, str]] = {}
    flattened: dict[str, list[str]] = {}
    for transfer in report.transfers:
        for name in transfer.file_names:
            key = transfer.stage_dest + name
            origin = (transfer.source_id, transfer.local_spec)
            prior = seen.get(key)
            if prior is None:
                seen[key] = origin
            elif prior == origin:
                continue
            elif prior[0] == transfer.source_id:
                flattened.setdefault(transfer.source_id, []).append(name)
            else:
                report.errors.append(
                    (transfer.source_id, f"{prior[0]} and {transfer.source_id} {COLLISION_MARKER} {key}")
                )

    for source_id, names in flattened.items():
        sample = ", ".join(sorted(names)[:3])
        report.warnings.append(
            (
                source_id,
                f"{len(names)} file name(s) repeat across recursed subdirectories and flatten "
                f"onto one prefix (e.g. {sample}) — only the last upload of each survives. "
                "Change destinationKeyPolicy to relativeFromRoot if every file must land.",
            )
        )


def put_query(local_spec: str, stage_dest: str, parallel: int) -> str:
    # Snowflake reads backslash escapes inside a quoted literal (\t in C:\data\temp is a tab),
    # so a Windows path goes into the file:// URI with forward slashes, which PUT accepts.
    escaped = local_spec.replace("\\", "/").replace("'", "''")
    return (
        f"PUT 'file://{escaped}' '{stage_dest}' "
        f"AUTO_COMPRESS = FALSE OVERWRITE = TRUE PARALLEL = {parallel}"
    )


def has_stage_collision(report: Report) -> bool:
    return any(COLLISION_MARKER in reason for _, reason in report.errors)


def run_transfers(report: Report, args: argparse.Namespace) -> set[str]:
    """Returns the source ids that had at least one failed PUT."""
    failed: set[str] = set()
    for transfer in report.transfers:
        query = put_query(transfer.local_spec, transfer.stage_dest, args.parallel)
        command = ["snow", "sql", "-q", query, "-c", args.connection, "--database", args.database]
        if args.schema:
            command += ["--schema", args.schema]
        print(f"[{transfer.source_id}] {len(transfer.file_names)} file(s) -> {transfer.stage_dest}")
        result = subprocess.run(command)
        if result.returncode != 0:
            # Keep going: one unreachable package should not strand the other hundreds.
            failed.add(transfer.source_id)
            print(f"  FAILED (snow exited {result.returncode})", file=sys.stderr)
    return failed


def print_plan(report: Report) -> None:
    for source_id, reason in report.skipped:
        print(f"SKIPPED  {source_id}: {reason}")
    for source_id, reason in report.empty:
        print(f"NO FILES {source_id}: {reason}")
    for source_id, reason in report.warnings:
        print(f"WARN     {source_id}: {reason}")
    for source_id, reason in report.errors:
        print(f"ERROR    {source_id}: {reason}", file=sys.stderr)
    for transfer in report.transfers:
        print(f"UPLOAD   {transfer.local_spec} -> {transfer.stage_dest} ({len(transfer.file_names)} file(s))")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("manifest", type=Path, help="path to ingestion-manifest.json")
    parser.add_argument("--connection", required=True, help="snow CLI named connection")
    parser.add_argument("--database", required=True)
    parser.add_argument("--schema")
    parser.add_argument("--source-id", action="append", default=[], help="limit to these manifest source ids")
    parser.add_argument(
        "--path-root",
        action="append",
        default=[],
        metavar="ORIGINAL=LOCAL",
        help="rewrite a manifest location prefix onto this host, e.g. 'C:=/mnt/c'",
    )
    parser.add_argument("--parallel", type=int, default=8, help="PUT PARALLEL setting (default 8)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan without uploading")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        sys.exit(f"Cannot read manifest {args.manifest}: {error}")

    report = build_plan(manifest, parse_path_roots(args.path_root), set(args.source_id))
    print_plan(report)

    total_files = sum(len(t.file_names) for t in report.transfers)
    sources = len({t.source_id for t in report.transfers})
    print(
        f"\n{'DRY RUN' if args.dry_run else 'UPLOAD'}: {total_files} file(s) from {sources} source(s), "
        f"{len(report.warnings)} warning(s), {len(report.errors)} error(s)"
    )

    if args.dry_run:
        print("Nothing uploaded. Re-run without --dry-run to transfer.")
        return 1 if report.errors else 0

    if has_stage_collision(report):
        print(
            "Stopped before any PUT: two sources claim the same stage object. "
            "OVERWRITE = TRUE would let the last writer replace it.",
            file=sys.stderr,
        )
        return 1

    failed = run_transfers(report, args)
    print(
        f"\nDone. {sources - len(failed)} source(s) uploaded, {len(failed)} failed, "
        f"{len(report.errors)} error(s)."
    )
    return 1 if failed or report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
