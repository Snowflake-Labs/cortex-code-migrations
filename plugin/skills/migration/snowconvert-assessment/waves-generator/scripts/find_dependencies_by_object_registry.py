#!/usr/bin/env python3
"""Find missing dependencies by object using SnowConvert registry JSON."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

from registry_support import (
    build_id_to_object_name_map,
    build_registry_object_id,
    entry_to_object_info,
    is_deployable_entry,
    is_na,
    load_registry_entries,
    missing_dependency_name,
)


def load_missing_dependencies_from_registry(
    registry_dir: str | Path,
) -> Tuple[Dict[str, List[Dict[str, str]]], Dict[str, Dict[str, Any]]]:
    """Load missing dependencies grouped by caller object."""
    entries = load_registry_entries(registry_dir)
    id_to_name = build_id_to_object_name_map(entries)

    deployable_entries = [entry for entry in entries if is_deployable_entry(entry)]
    objects = {
        build_registry_object_id(entry): entry_to_object_info(entry)
        for entry in deployable_entries
    }

    missing_deps: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    missing_counter = 0

    for entry in deployable_entries:
        caller = build_registry_object_id(entry)
        if is_na(caller):
            continue
        file_name = entry.get("files", {}).get("source", {}).get("path", "")

        for dep in entry.get("dependencies", {}).get("dependsOn", []):
            if not dep.get("isMissing", False):
                continue

            missing_counter += 1
            referenced = id_to_name.get(
                (dep.get("id") or "").strip(),
                missing_dependency_name(dep, missing_counter),
            )
            if is_na(referenced):
                continue

            relation_types = dep.get("relationTypes", []) or [""]
            for relation_type in relation_types:
                missing_deps[caller].append(
                    {
                        "referenced": referenced,
                        "relation_type": relation_type,
                        "line": "0",
                        "file": file_name,
                    }
                )

    # Match the legacy script behavior: de-duplicate by referenced object only.
    for caller, deps in list(missing_deps.items()):
        seen = set()
        unique = []
        for dep in deps:
            referenced = dep["referenced"]
            if referenced in seen:
                continue
            seen.add(referenced)
            unique.append(dep)
        missing_deps[caller] = unique

    return missing_deps, objects


def generate_missing_dependencies_report_from_registry(
    registry_dir: str | Path, output_json: str | Path
) -> Dict[str, Any]:
    """Generate missing dependencies JSON with the same contract as CSV mode."""
    missing_deps, objects = load_missing_dependencies_from_registry(registry_dir)

    report: Dict[str, Any] = {}
    for object_id, object_info in objects.items():
        deps = missing_deps.get(object_id, [])
        object_name = object_id.split(".", 1)[1] if "." in object_id else object_id
        report[object_id] = {
            "object_name": object_name,
            "object_category": object_info.get("category", "-"),
            "object_file": object_info.get("file_name", ""),
            "has_missing_dependencies": bool(deps),
            "missing_count": len(deps),
            "missing_dependencies": deps,
        }

    report_with_metadata = {
        "_metadata": {
            "data_source": "registry",
            "warning": None,
        },
        "objects": report,
    }

    output_path = Path(output_json)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(report_with_metadata, handle, indent=2)

    print(f"Report generated: {output_path}")
    print(f"Total objects: {len(report)}")
    print(
        "Objects with missing dependencies: "
        f"{sum(1 for obj in report.values() if obj['has_missing_dependencies'])}"
    )
    return report_with_metadata


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find missing dependencies by object from registry JSON",
    )
    parser.add_argument(
        "--registry-dir",
        "-r",
        required=True,
        help="Directory containing SnowConvert registry JSON files",
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output JSON file path",
    )
    args = parser.parse_args()

    generate_missing_dependencies_report_from_registry(args.registry_dir, args.output)


if __name__ == "__main__":
    main()
