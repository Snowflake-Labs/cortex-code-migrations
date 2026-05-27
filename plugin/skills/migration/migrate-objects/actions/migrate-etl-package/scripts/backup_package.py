#!/usr/bin/env python3
"""Snapshot a package directory into <package>/.migrate-etl-package/original.

Usage: python backup_package.py <package_dir>

Replaces the previous `rsync -a --exclude .migrate-etl-package` recipe,
which assumed `rsync` (POSIX-only). Skips the `.migrate-etl-package`
sub-tree so the snapshot doesn't recurse into itself.
"""

import shutil
import sys
from pathlib import Path

EXCLUDED = ".migrate-etl-package"


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: backup_package.py <package_dir>", file=sys.stderr)
        return 2

    src = Path(sys.argv[1]).resolve()
    if not src.is_dir():
        print(f"Error: {src} is not a directory", file=sys.stderr)
        return 1

    dst = src / EXCLUDED / "original"
    if dst.exists():
        # Fresh snapshot every time — the dest is a known scratch area.
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)

    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns(EXCLUDED),
        dirs_exist_ok=True,
    )
    print(f"Snapshot saved to: {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
