#!/usr/bin/env python3
"""Snapshot a unit directory into <unit>/stabilization/original.

Usage: python backup_unit.py <unit_dir>

Skips the stabilization/ sub-tree so the snapshot doesn't recurse into itself.
"""

import shutil
import sys
from pathlib import Path

# Pin local skill-script imports to this directory (not CWD / PYTHONPATH).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from path_resolver import original_backup_dir

STABILIZATION_FOLDER = "stabilization"


def snapshot_unit(src: Path, *, refresh: bool = False) -> Path:
    """Copy unit files into stabilization/original/, excluding stabilization/.

    Default refresh=False: never replace an existing converter snapshot with
    Stage-0-rewritten SQL (Planning Step 5 / sync_guard). Pass refresh=True
    only for an explicit wipe-and-resnapshot.
    """
    dst = original_backup_dir(src)
    if dst.exists() and not refresh:
        return dst
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns(STABILIZATION_FOLDER),
        dirs_exist_ok=True,
    )
    return dst


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: backup_unit.py <unit_dir>", file=sys.stderr)
        return 2

    src = Path(sys.argv[1]).resolve()
    if not src.is_dir():
        print(f"Error: {src} is not a directory", file=sys.stderr)
        return 1

    # Default snapshot_unit(refresh=False): Entry Stage-0 and Planning Step 5
    # must not replace converter original/ with post-prepass SQL.
    already = original_backup_dir(src).exists()
    dst = snapshot_unit(src)
    print(f"Snapshot {'preserved at' if already else 'saved to'}: {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
