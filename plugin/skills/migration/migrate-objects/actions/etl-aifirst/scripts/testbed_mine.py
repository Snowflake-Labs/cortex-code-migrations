"""Mine Synthetic Testbed artifacts from an ETL source document.

Usage: python3 testbed_mine.py <source_document> <artifact_root>
           [--ir IR.json] [--existing-tables DIR]... [--existing-table NAME]...
           [--object-name NAME] [--source-root DIR] [--qualify-database]
           [--project-root DIR]

Exit codes: 0 artifacts written (or nothing to mine), 1 mining failed, 2 usage /
no adapter recognizes the document.

The adapter is chosen by SNIFFING the document, not from a platform table, so this
also works for a document whose `platform_<p>.json` is absent (a blind run).
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from testbed_mining import hop, ssis, talend
from testbed_mining.artifacts import ExistingTables, place_for_cur, write_artifacts

# (platform, sniff, mine). A new platform adds one adapter row; serialization is shared.
ADAPTERS = [
    (ssis.PLATFORM, ssis.sniff, ssis.mine),
    (talend.PLATFORM, talend.sniff, talend.mine),
    (hop.PLATFORM, hop.sniff, hop.mine),
]


def _object_name(doc: Path, source_root: str | None, explicit: str | None) -> str:
    if explicit:
        return explicit
    if source_root:
        try:
            return doc.resolve().relative_to(Path(source_root).resolve()).as_posix()
        except ValueError:
            pass
    return doc.name


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("document")
    ap.add_argument("artifact_root")
    ap.add_argument("--ir", help="AI-First IR JSON for cross-checking (optional)")
    ap.add_argument(
        "--existing-tables",
        action="append",
        default=[],
        metavar="DIR",
        help="directory scanned for authoritative TABLE *.testbed.json (repeatable)",
    )
    ap.add_argument(
        "--existing-table",
        action="append",
        default=[],
        metavar="NAME",
        help="table name that already has an authoritative SQL DDL artifact (repeatable)",
    )
    ap.add_argument("--object-name")
    ap.add_argument("--source-root")
    ap.add_argument(
        "--qualify-database",
        action="store_true",
        help="prefix table identities with the connection's Initial Catalog",
    )
    ap.add_argument(
        "--project-root",
        help="also copy artifacts into DIR/artifacts/{etl,tables}/<slug> "
        "(the files.artifacts.path convert stamps / init reads)",
    )
    args = ap.parse_args(argv)

    doc = Path(args.document)
    if not doc.is_file():
        print(f"testbed_mine: no such document: {doc}", file=sys.stderr)
        return 2
    adapter = next(((p, m) for p, s, m in ADAPTERS if s(doc)), None)
    if adapter is None:
        print(
            f"testbed_mine: no mining adapter recognizes {doc.name}; nothing emitted",
            file=sys.stderr,
        )
        return 2
    platform, mine = adapter

    existing = ExistingTables.from_names(args.existing_table).merged(
        ExistingTables.from_artifact_dirs(
            Path(d) for d in args.existing_tables if Path(d).is_dir()
        )
    )
    try:
        result = mine(
            doc, _object_name(doc, args.source_root, args.object_name), args.ir
        )
        report = write_artifacts(
            result, Path(args.artifact_root), existing, args.qualify_database
        )
    except Exception:  # noqa: BLE001 -- any adapter crash must surface as exit 1, never as a partial tree
        traceback.print_exc()
        return 1

    print(f"testbed_mine: platform={platform} document={doc.name}")
    for a in report.written:
        print(f"  wrote {a['object_type']:<7} {a['object']}  ->  {a['path']}")
    for s in report.suppressed:
        print(f"  suppressed TABLE {s['object']}  ({s['reason']})")
    for d in result.diagnostics:
        print(f"  note: {d}")
    print(f"  manifest: {report.manifest_path}")
    if args.project_root:
        placed = place_for_cur(Path(args.artifact_root), Path(args.project_root))
        print(f"  placed under {args.project_root}:")
        for p in placed:
            print(f"    {p['object_type']:<7} {p['object']}  ->  {p['files.artifacts.path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
