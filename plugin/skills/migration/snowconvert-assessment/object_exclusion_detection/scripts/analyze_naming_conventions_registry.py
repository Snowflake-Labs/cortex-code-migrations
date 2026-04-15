#!/usr/bin/env python3
# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Naming Convention Analyzer (Registry Mode)

Registry-only wrapper for object exclusion analysis.
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from object_exclusion_shared import (
    INVALID_REFERENCE_VALUES,
    NamingConventionAnalyzer,
)

# Add shared library to path
_scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from snowconvert_reports.loaders.registry_loader import (
    load_registry_entries,
    load_object_references_from_registry,
)


class NamingConventionRegistryAnalyzer(NamingConventionAnalyzer):
    """Registry-first analyzer, reusing shared naming-pattern logic."""

    def __init__(
        self,
        registry_directory: Path,
        include_staging_schema: bool = True,
    ):
        super().__init__(
            report_directory=registry_directory,
            include_staging_schema=include_staging_schema,
        )
        self.registry_directory = registry_directory

    @staticmethod
    def _normalize_identifier(value: str) -> str:
        """Normalize object identifiers and drop placeholder DB names like N/A."""
        if not value:
            return ""

        cleaned = value.replace("[", "").replace("]", "").strip()
        if not cleaned:
            return ""

        if "(" in cleaned:
            cleaned = cleaned.split("(")[0].strip()

        parts = [part.strip() for part in cleaned.split(".") if part and part.strip()]
        if parts and parts[0].upper() in {"N/A"}:
            parts = parts[1:]
        return ".".join(parts)

    @staticmethod
    def _parse_source_identity(file_path: str) -> Optional[Tuple[str, str, str]]:
        """
        Parse source file path into (schema, object_name, object_type).

        Expected segment pattern:
            .../<table|view|procedure|function>/<schema>/<object_name>.sql
        """
        path_parts = [part for part in Path(file_path).parts if part]
        if len(path_parts) < 3:
            return None

        type_aliases = {
            "TABLE": {"table", "tables"},
            "VIEW": {"view", "views"},
            "PROCEDURE": {"procedure", "procedures", "proc", "procs"},
            "FUNCTION": {"function", "functions", "fn"},
        }
        alias_to_type = {alias: obj_type for obj_type, aliases in type_aliases.items() for alias in aliases}

        obj_type = None
        type_idx = -1
        for idx, segment in enumerate(path_parts):
            mapped = alias_to_type.get(segment.lower())
            if mapped and idx + 2 < len(path_parts):
                obj_type = mapped
                type_idx = idx

        if obj_type is None or type_idx == -1:
            return None

        schema = path_parts[type_idx + 1].strip()
        object_name = Path(path_parts[-1]).stem.strip()
        if not schema or not object_name:
            return None

        return (schema.lower(), object_name.lower(), obj_type)

    def _read_object_references(self) -> None:
        """Read dependency relationships from registry only."""
        refs = []
        if self.registry_directory and self.registry_directory.is_dir():
            refs = load_object_references_from_registry(self.registry_directory)

        if not refs:
            print("No ObjectReferences found in registry (optional for dependency analysis)")
            self.object_references = {}
            return

        print("Reading dependencies (source: registry)")

        dependencies = defaultdict(set)
        dependents = defaultdict(set)
        row_count = 0

        for ref in refs:
            caller = self._normalize_identifier(ref.caller_full_name)
            referenced = self._normalize_identifier(ref.referenced_full_name)

            if caller in INVALID_REFERENCE_VALUES or referenced in INVALID_REFERENCE_VALUES:
                continue

            if caller and referenced and caller != referenced:
                dependencies[caller].add(referenced)
                dependents[referenced].add(caller)
                row_count += 1

        self.object_references = {
            "dependencies": dependencies,
            "dependents": dependents,
        }
        print(f"     Loaded {row_count} dependency relationships")

    def _read_snowconvert_report(self) -> List[Dict[str, Any]]:
        """Read objects using registry identity and source-file projection."""
        if not self.registry_directory or not self.registry_directory.is_dir():
            print("Error: Registry directory not found")
            return []

        entries = load_registry_entries(self.registry_directory)
        if not entries:
            print("Error: No code units found in registry")
            return []

        print("Loading code units (source: registry + source files)")

        objects: List[Dict[str, Any]] = []
        registry_by_identity: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        registry_file_by_identity: Dict[Tuple[str, str, str], str] = {}

        for entry in entries:
            if not entry.get("inScope", False) or entry.get("isMissing", False):
                continue

            source = entry.get("source", {})
            obj_type = str(source.get("objectType", "")).upper()
            if obj_type not in {"TABLE", "VIEW", "PROCEDURE", "FUNCTION"}:
                continue

            schema = self._normalize_identifier(str(source.get("schema", ""))) or "dbo"
            object_name = self._normalize_identifier(str(source.get("name", "")))
            database = self._normalize_identifier(str(source.get("database", "")))

            if not object_name or object_name in INVALID_REFERENCE_VALUES or object_name.startswith("Error-"):
                continue

            full_name = f"{database}.{schema}.{object_name}" if database else f"{schema}.{object_name}"
            identity_key = (schema.lower(), object_name.lower(), obj_type)

            existing = registry_by_identity.get(identity_key)
            if existing is None:
                registry_file_by_identity[identity_key] = str(entry.get("files", {}).get("source", {}).get("path", "")).strip()
                registry_by_identity[identity_key] = {
                    "name": object_name,
                    "full_name": full_name,
                    "schema": schema,
                    "database": database,
                    "type": obj_type,
                    "source": "Registry",
                    "file": "",
                    "report_file": "registry",
                }
                continue

            # Keep non-empty database/full_name if a later entry has better metadata.
            if not existing.get("database") and database:
                existing["database"] = database
                existing["full_name"] = full_name

        source_root = self.registry_directory.parent / "source"
        files_by_identity: Dict[Tuple[str, str, str], List[str]] = defaultdict(list)
        if source_root.is_dir():
            for sql_path in source_root.rglob("*.sql"):
                rel_file = str(sql_path.relative_to(source_root))
                identity = self._parse_source_identity(rel_file)
                if identity is not None:
                    files_by_identity[identity].append(rel_file)

        for identity_key, base_obj in registry_by_identity.items():
            files = sorted(set(files_by_identity.get(identity_key, [])))
            if files:
                for file_path in files:
                    row = dict(base_obj)
                    row["file"] = file_path
                    objects.append(row)
            else:
                # Keep object coverage even when source tree is unavailable.
                fallback_path = registry_file_by_identity.get(identity_key, "")
                row = dict(base_obj)
                row["file"] = fallback_path
                objects.append(row)

        print(f"Loaded {len(objects)} objects (source: registry)")
        return objects

    def analyze(self) -> Dict[str, Any]:
        """Run shared analysis and tag duplicate detection strategy."""
        results = super().analyze()
        results.setdefault("summary", {})["duplicate_detection_mode"] = "registry_identity_source_files"
        return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze naming conventions using SnowConvert registry",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--registry-dir", required=True, help="Path to SnowConvert registry directory")
    parser.add_argument("--output-dir", "-d", required=True, help="Output base directory")
    parser.add_argument("--include-staging-schema", action="store_true", default=True)
    parser.add_argument("--exclude-staging-schema", action="store_true")
    args = parser.parse_args()

    registry_dir = Path(args.registry_dir)
    output_base_dir = Path(args.output_dir)

    if not registry_dir.exists():
        print(f"Error: Registry directory not found: {registry_dir}", file=sys.stderr)
        sys.exit(1)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = output_base_dir / f"exclusion_analysis_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    include_staging = args.include_staging_schema and not args.exclude_staging_schema
    analyzer = NamingConventionRegistryAnalyzer(
        registry_directory=registry_dir,
        include_staging_schema=include_staging,
    )
    results = analyzer.analyze()

    output_file = output_dir / "naming_conventions.json"
    summary_output = output_dir / "analysis_summary.txt"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    source_label = str(registry_dir)
    analyzer_type = results["summary"].get("analyzer_type", "pattern-based")
    duplicate_count = results["summary"].get("duplicate_objects_count", 0)
    summary_text = f"""Object Exclusion Analysis Summary
{'='*60}
Analyzer Type: {analyzer_type}
Input: {source_label}
Analysis Timestamp: {timestamp}

Results:
  Total Objects: {results['summary']['total_objects_found']}
  Temp/Staging Objects: {results['summary']['temp_staging_objects_count']}
  Deprecated/Legacy Objects: {results['summary']['deprecated_legacy_objects_count']}
  Testing Objects: {results['summary']['testing_objects_count']}
  Duplicate Objects: {duplicate_count}
"""
    with open(summary_output, "w", encoding="utf-8") as f:
        f.write(summary_text)

    print(f"\nResults written to: {output_dir.absolute()}/")
    print(f"   - {output_file.name}")
    print(f"   - {summary_output.name}")


if __name__ == "__main__":
    main()
