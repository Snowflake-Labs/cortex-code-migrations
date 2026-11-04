"""Place mined *.testbed.json where scai testbed init / CUR convert resolve them.

Usage:
  python3 testbed_place.py <mining_root> --project-root DIR
      copies packages/<slug> -> DIR/artifacts/etl/<slug>
      copies tables/<slug>   -> DIR/artifacts/tables/<slug>
      writes DIR/artifacts/testbed-cur-hints.json

  python3 testbed_place.py <mining_root> --print
      prints the update_registry field=/status= pairs (does not write CUR)

Does not edit registry/<id>.json.
lets the convert agent stamp files.artifacts.path via update_registry; this
script only puts the files at those relative paths.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from testbed_mining.artifacts import CUR_HINTS_NAME, place_for_cur, write_cur_hints
from testbed_mining.artifacts import MANIFEST_NAME


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("mining_root")
    ap.add_argument("--project-root")
    ap.add_argument("--print", action="store_true", dest="print_hints")
    args = ap.parse_args(argv)

    root = Path(args.mining_root)
    if not (root / MANIFEST_NAME).is_file() and not (root / CUR_HINTS_NAME).is_file():
        print(f"testbed_place: no manifest or hints under {root}", file=sys.stderr)
        return 2

    if args.print_hints or not args.project_root:
        hints = root / CUR_HINTS_NAME
        if not hints.is_file():
            manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
            write_cur_hints(root, manifest.get("artifacts", []))
        doc = json.loads(hints.read_text(encoding="utf-8"))
        for p in doc.get("pointers", []):
            u = p["update_registry"]
            print(
                f"update_registry(field={u['field']!r}, status={u['status']!r})  # {p['object_type']} {p['object']}"
            )
        if not args.project_root:
            return 0

    placed = place_for_cur(root, Path(args.project_root))
    print(f"testbed_place: project={args.project_root}")
    for p in placed:
        files = ", ".join(p.get("project_files") or ["(missing)"])
        print(f"  {p['object_type']:<7} {p['object']}  ->  {p['files.artifacts.path']}  ({files})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
