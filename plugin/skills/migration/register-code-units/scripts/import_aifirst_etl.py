"""Copy an unsupported-ETL source tree into the project and enumerate its units.

Called by the register-code-units skills (`add-code-units`, `extract-code-units`) when
the user says their ETL platform is something other than SSIS or Informatica
PowerCenter — the two the native SnowConvert ETL replatform covers.

The helper does two things and only those:

1. Losslessly copy the user's `--source` directory into
   `<project_dir>/source/_etl_aifirst/<platform>/`. This is a separate root from
   `source/_etl/`, which the native `EtlFileClassifier` owns. Widening that
   classifier to accept `.yxmd` / `.dsx` / `.ktr` / IICS / ADF would route
   unsupported files through the native arranger; keeping them under
   `source/_etl_aifirst/` avoids that.
2. Emit a per-source-document enumeration on stdout (with `--json`) so the
   calling skill can call the MCP `create_registry_unit` tool once per document.
   Each entry carries a deterministic collision-resistant `unit_id`, the
   source-derived `name`, the stated `platform`, the file `format` (extension
   without the dot), and the project-relative vendored `source_file`.

Registry writing is not the helper's job. The Code Unit Registry has its own
`create_registry_unit` tool (`ai/crates/mcp-server/src/registry.rs`) that stamps
`kind: etl`, `source.objectType: workflow`, records unknown platforms truthfully
under `extensions.sourcePlatform`, and refuses to overwrite an id. The helper's
JSON output is the *input* to that tool — it never writes a parallel manifest.

Stdlib-only, OS-agnostic, exit codes:

* `0` — success.
* `2` — usage error (missing/unreadable source, unwritable project dir, bad platform, a
  source tree with no files recognized as that platform's workflow documents — the helper
  fails closed rather than vendoring a companions-only tree that mints zero registry units —
  or a source tree containing a symlink that dangles or resolves outside itself).
* `3` — target directory already contains a *different* tree and `--overwrite` was not passed.

The script never talks to the network, never runs `scai`, and never touches
`source/_etl/`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path


AIFIRST_ROOT_RELPATH = Path("source") / "_etl_aifirst"

# Per-platform extensions that name the source document itself (a single ETL
# workflow/job). Scoped per platform so a Talend tree that also happens to
# carry incidental project XML/JSON does not mint extra registry units for
# those files — only `.item` is a Talend workflow document.
PLATFORM_UNIT_EXTS: dict[str, frozenset[str]] = {
    "talend": frozenset({"item"}),
    "alteryx": frozenset({"yxmd"}),
    "datastage": frozenset({"dsx"}),
    "pentaho": frozenset({"ktr", "kjb"}),
    "adf": frozenset({"xml", "json"}),
    "iics": frozenset({"json"}),
}

# Fallback for platforms with no specific mapping above (a user-entered name
# we don't recognize). We can't know that platform's real document extension,
# so we stay permissive rather than silently enumerating zero units for it.
DEFAULT_UNIT_EXTS: frozenset[str] = frozenset({
    "item", "yxmd", "dsx", "ktr", "kjb", "xml", "json",
})

# Sub-extensions we intentionally leave out of the enumeration even though the
# file may share a matching primary extension. `.properties` sit next to Talend
# `.item` documents but are companion metadata, not the workflow document.
COMPANION_EXTS: frozenset[str] = frozenset({"properties"})


def _unit_exts_for(platform_slug: str) -> frozenset[str]:
    """Which extensions count as a source document for this platform.

    Known platforms get a scoped set (Talend project XML must not mint a
    registry unit). Unmapped/custom platform names fall back to the
    permissive union so we don't fail closed on a real document we can't
    recognize by name.
    """
    return PLATFORM_UNIT_EXTS.get(platform_slug, DEFAULT_UNIT_EXTS)


class UsageError(RuntimeError):
    """Argument or filesystem-shape problem the caller made — exit 2."""


class ConflictError(RuntimeError):
    """A different tree already exists at the target and --overwrite was not set — exit 3."""


@dataclass
class UnitRecord:
    unit_id: str
    name: str
    platform: str
    format: str
    source_file: str

    def to_json(self) -> dict[str, str]:
        return {
            "unit_id": self.unit_id,
            "name": self.name,
            "platform": self.platform,
            "format": self.format,
            "source_file": self.source_file,
        }


@dataclass
class ImportResult:
    platform: str
    project_dir: Path
    target_root: Path
    files: list[str] = field(default_factory=list)
    units: list[UnitRecord] = field(default_factory=list)

    def to_json(self) -> dict[str, object]:
        return {
            "platform": self.platform,
            "project_dir": str(self.project_dir),
            "target_root": str(self.target_root.relative_to(self.project_dir)),
            "file_count": len(self.files),
            "files": self.files,
            "units": [u.to_json() for u in self.units],
        }


def _normalize_platform(raw: str) -> str:
    """Return the slug we use as a directory name.

    Rules: lower-case, alphanumerics plus `_` survive; everything else collapses
    to `-`. Repeated separators collapse to one, and the result is trimmed.
    Empty or whitespace-only input is rejected — the caller has to ask the user
    for a real name.
    """
    if raw is None:
        raise UsageError("platform is required")
    stripped = raw.strip()
    if not stripped:
        raise UsageError("platform is required")
    out_chars: list[str] = []
    prev_sep = False
    for ch in stripped.lower():
        if ch.isalnum() or ch == "_":
            out_chars.append(ch)
            prev_sep = False
        else:
            if not prev_sep:
                out_chars.append("-")
                prev_sep = True
    slug = "".join(out_chars).strip("-")
    if not slug:
        raise UsageError(f"platform {raw!r} has no usable characters")
    return slug


def _resolve_source(source_arg: str) -> Path:
    source = Path(source_arg).expanduser()
    if not source.exists():
        raise UsageError(f"source path does not exist: {source}")
    if not source.is_dir():
        raise UsageError(
            f"source path is not a directory (helper takes a directory of ETL "
            f"documents, not a single file): {source}"
        )
    return source.resolve()


def _resolve_project_dir(project_arg: str | None) -> Path:
    project = Path(project_arg).expanduser() if project_arg else Path.cwd()
    project = project.resolve()
    if not project.is_dir():
        raise UsageError(f"project-dir does not exist or is not a directory: {project}")
    return project


def _validate_source_tree(source: Path) -> None:
    """Fail before copying when the source is empty, cannot be read, or escapes itself.

    The escape check is a confinement proof, not a readability check: the source
    tree is attacker-influenceable input (an unpacked archive, a shared drop), and
    `shutil.copytree(symlinks=False)` silently dereferences every link it meets.
    Without confinement, a symlink entry such as `workflow.item -> /etc/passwd`
    (or a symlinked directory pointing outside the tree) is read and vendored
    into the git-tracked project as real bytes. So every entry must resolve back
    inside the source root; an in-tree symlink stays legal and is dereferenced to
    real content, which is what the lossless-copy contract wants.
    """
    found_file = False
    try:
        for path in source.rglob("*"):
            resolved = path.resolve()
            if not resolved.is_relative_to(source):
                raise UsageError(
                    f"source tree entry escapes the source directory and would "
                    f"vendor an out-of-tree file into the project: {path} -> "
                    f"{resolved}"
                )
            if path.is_symlink() and not resolved.exists():
                raise UsageError(
                    f"source tree contains a dangling symlink: {path} -> "
                    f"{os.readlink(path)}"
                )
            if not path.is_file():
                continue
            found_file = True
            with path.open("rb") as stream:
                stream.read(1)
    except OSError as exc:
        raise UsageError(f"source directory is not readable: {source}: {exc}") from exc

    if not found_file:
        raise UsageError(f"source directory contains no files: {source}")


def _copytree_lossless(src: Path, dst: Path) -> list[str]:
    """Copy every file under `src` into `dst`, preserving relative structure.

    Returns the sorted list of files that ended up under `dst`, relative to
    `dst`. Uses POSIX separators so the paths round-trip across Windows/Unix.
    """
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True, symlinks=False)
    return sorted(
        p.relative_to(dst).as_posix()
        for p in dst.rglob("*")
        if p.is_file()
    )


def _target_would_collide(target: Path, source: Path) -> bool:
    """True when `target` exists, is non-empty, and does not already match `source`.

    Same content → we can re-run the import idempotently. Different content →
    the caller has to pass `--overwrite` on purpose so we don't clobber their
    hand-edits.
    """
    if not target.exists():
        return False
    existing = _tree_fingerprints(target)
    if not existing:
        return False
    incoming = _tree_fingerprints(source)
    return existing != incoming


def _tree_fingerprints(root: Path) -> dict[str, str]:
    """Map each relative file path to its SHA-256 content digest.

    Comparing names alone would silently overwrite a changed source document
    when a re-import used the same filenames. Content is part of the collision
    contract: identical trees are idempotent; changed trees require
    ``--overwrite``.
    """
    fingerprints: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        fingerprints[path.relative_to(root).as_posix()] = digest.hexdigest()
    return fingerprints


def _is_source_document(rel_path: str, unit_exts: frozenset[str]) -> bool:
    """Decide whether a copied file names its own ETL workflow document.

    Companion metadata (Talend `.properties`) travels with an `.item` and does
    not get its own registry unit. Everything else matching this platform's
    document extensions does.
    """
    ext = rel_path.rsplit(".", 1)[-1].lower() if "." in rel_path else ""
    if ext in COMPANION_EXTS:
        return False
    return ext in unit_exts


def _unit_name_for(rel_path: str) -> str:
    """Human-facing name of the unit: the source document's filename stem.

    Preserves the source's own version markers (`fact_workorderrouting_Copy_0.1`
    keeps its dotted version); collapsing them would fold two versions of the
    same document into one registry id.
    """
    stem = Path(rel_path).name
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    return stem


def _unit_id_for(platform_slug: str, project_relpath: str) -> str:
    """Deterministic, collision-resistant unit id.

    Same platform + same vendored path → same id, so re-running the helper is a
    no-op at the registry level. Uses UUID5 over a URL-namespaced key derived
    from the project-relative source path — a rename of the source document
    produces a different id, which is correct.
    """
    key = f"aifirst-etl/{platform_slug}/{project_relpath}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def _enumerate_units(
    platform_slug: str,
    target_root: Path,
    project_dir: Path,
    files: list[str],
) -> list[UnitRecord]:
    """Turn copied files into per-document registry-unit records, sorted for stability."""
    unit_exts = _unit_exts_for(platform_slug)
    records: list[UnitRecord] = []
    seen_ids: dict[str, str] = {}
    for rel in files:
        if not _is_source_document(rel, unit_exts):
            continue
        vendored = (target_root / rel).relative_to(project_dir).as_posix()
        unit_id = _unit_id_for(platform_slug, vendored)
        if unit_id in seen_ids:
            # UUID5 over a project-relative path already collision-resists, so
            # this only fires if the same file is enumerated twice — a defect
            # in the copy step above rather than something to paper over.
            raise UsageError(
                f"internal error: duplicate unit_id {unit_id} for "
                f"{seen_ids[unit_id]} and {vendored}"
            )
        seen_ids[unit_id] = vendored
        ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
        records.append(
            UnitRecord(
                unit_id=unit_id,
                name=_unit_name_for(rel),
                platform=platform_slug,
                format=ext,
                source_file=vendored,
            )
        )
    records.sort(key=lambda r: r.source_file)
    return records


def import_aifirst_etl(
    *,
    project_dir: Path | str | None,
    platform: str,
    source: Path | str,
    overwrite: bool = False,
) -> ImportResult:
    """Programmatic entry point. Same contract as the CLI, raises on error."""
    project = _resolve_project_dir(str(project_dir) if project_dir is not None else None)
    slug = _normalize_platform(platform)
    src = _resolve_source(str(source))
    _validate_source_tree(src)

    target_root = project / AIFIRST_ROOT_RELPATH / slug
    if _target_would_collide(target_root, src) and not overwrite:
        raise ConflictError(
            f"{target_root.relative_to(project)} already exists with different content; "
            f"pass --overwrite to replace"
        )
    if overwrite and target_root.exists():
        shutil.rmtree(target_root)

    files = _copytree_lossless(src, target_root)
    units = _enumerate_units(slug, target_root, project, files)
    if not units:
        shutil.rmtree(target_root)
        raise UsageError(
            f"no source documents recognized for platform {slug!r} in {src}; "
            f"copied {len(files)} companion file(s) but none matched that "
            f"platform's workflow-document extensions"
        )

    return ImportResult(
        platform=slug,
        project_dir=project,
        target_root=target_root,
        files=files,
        units=units,
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="import_aifirst_etl.py",
        description=(
            "Copy an unsupported-ETL source directory into "
            "source/_etl_aifirst/<platform>/ and print a per-source-document "
            "enumeration the calling skill hands to the MCP "
            "`create_registry_unit` tool. Stdlib-only."
        ),
    )
    p.add_argument("--project-dir", dest="project_dir", default=None)
    p.add_argument("--platform", required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
        help="Emit the import summary as JSON on stdout.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        result = import_aifirst_etl(
            project_dir=args.project_dir,
            platform=args.platform,
            source=args.source,
            overwrite=args.overwrite,
        )
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ConflictError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    if args.emit_json:
        print(json.dumps(result.to_json(), indent=2, sort_keys=True))
    else:
        rel_target = result.target_root.relative_to(result.project_dir)
        print(
            f"imported {len(result.files)} file(s) for platform "
            f"{result.platform!r} into {rel_target}; enumerated "
            f"{len(result.units)} unit(s) for create_registry_unit"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
