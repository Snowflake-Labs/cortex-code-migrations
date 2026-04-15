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
SQL Dynamic Analysis Helper (Registry-Only)

Builds sql_dynamic_analysis.json directly from SnowConvert registry JSON files,
without requiring Issues.csv or TopLevelCodeUnits.csv reports.
"""

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from snowconvert_reports.na_utils import NA_VALUES as _NA_VALUES 

from sql_dynamic_models import (
    AnalysisJSONManager,
    CodeUnitData,
    DynamicSQLOccurrence,
)

DYNAMIC_SQL_ISSUE_CODE = "SSC-EWI-0030"
SCRIPT_NAME = "sql_dynamic_analyzer_registry_helper.py"
DEFAULT_OUTPUT = "sql_dynamic_analysis.json"
TARGET_OBJECT_TYPE = "procedure"


def _bracket(ident: str) -> str:
    ident = (ident or "").strip()
    if not ident:
        return "[]"
    if ident.startswith("[") and ident.endswith("]"):
        return ident
    return f"[{ident}]"


def _code_unit_id_from_entry(entry: Dict[str, Any]) -> str:
    source = entry.get("source", {})
    parts = [
        _bracket(v)
        for v in (source.get("database", ""), source.get("schema", ""), source.get("name", ""))
        if v.strip() not in _NA_VALUES and v.strip("[] ") not in _NA_VALUES
    ]
    return ".".join(parts) if parts else "[]"


class SQLDynamicRegistryAnalyzer:
    """Analyze registry entries for dynamic SQL issue occurrences."""

    def __init__(self, registry_dir: str):
        self.registry_dir = Path(registry_dir)
        self.output_root = self.registry_dir.parent
        self.entries: List[Dict[str, Any]] = []
        self.filtered_entries: List[Dict[str, Any]] = []

    def load_registry(self) -> None:
        """Load registry JSON entries from disk."""
        if not self.registry_dir.exists() or not self.registry_dir.is_dir():
            raise FileNotFoundError(f"Registry directory not found: {self.registry_dir}")

        entries: List[Dict[str, Any]] = []
        for path in sorted(self.registry_dir.glob("*.json")):
            try:
                with path.open("r", encoding="utf-8") as f:
                    entries.append(json.load(f))
            except (json.JSONDecodeError, OSError) as exc:
                print(f"Warning: Skipping malformed registry file {path.name}: {exc}", file=sys.stderr)

        self.entries = entries
        print(f"Loaded {len(self.entries)} registry entries from {self.registry_dir}")

    @staticmethod
    def _dynamic_issue_count(entry: Dict[str, Any], issue_code: str) -> int:
        for issue in entry.get("issues", []):
            if issue.get("code") == issue_code:
                count = issue.get("count", 0)
                return count if isinstance(count, int) else 0
        return 0

    @staticmethod
    def _is_target_entry(entry: Dict[str, Any], issue_code: str) -> bool:
        source = entry.get("source", {})
        if source.get("objectType", "").lower() != TARGET_OBJECT_TYPE:
            return False
        if not entry.get("inScope", False):
            return False
        if entry.get("isMissing", False):
            return False
        return SQLDynamicRegistryAnalyzer._dynamic_issue_count(entry, issue_code) > 0

    @staticmethod
    def _format_non_empty_lines(all_lines: List[str]) -> str:
        extracted: List[str] = []
        for idx, line in enumerate(all_lines, start=1):
            if line.strip():
                extracted.append(f"{idx:3d}: {line.rstrip()}")
        return "\n".join(extracted)

    def _extract_procedure_code(self, entry: Dict[str, Any]) -> str:
        rel_path = entry.get("files", {}).get("source", {}).get("path", "")
        if not rel_path:
            return ""

        source_file = self.output_root / rel_path
        if not source_file.exists():
            return ""

        try:
            with source_file.open("r", encoding="utf-8", errors="replace") as f:
                return self._format_non_empty_lines(f.readlines())
        except OSError as exc:
            print(f"Warning: Failed to read source file {source_file}: {exc}", file=sys.stderr)
            return ""

    def generate_analysis_json(
        self,
        output_file: str = DEFAULT_OUTPUT,
        issue_code: str = DYNAMIC_SQL_ISSUE_CODE,
    ) -> None:
        """Generate analysis JSON using registry entries only."""
        self.filtered_entries = [e for e in self.entries if self._is_target_entry(e, issue_code)]

        code_units_data: Dict[str, Dict[str, Any]] = {}
        occurrence_id = 1

        for entry in self.filtered_entries:
            source = entry.get("source", {})
            file_source_path = entry.get("files", {}).get("source", {}).get("path", "")
            code_unit_id = _code_unit_id_from_entry(entry)
            procedure_code = self._extract_procedure_code(entry)
            lines_of_code = len([line for line in procedure_code.splitlines() if line.strip()])
            issue_count = self._dynamic_issue_count(entry, issue_code)

            occurrences: List[DynamicSQLOccurrence] = []
            for _ in range(issue_count):
                occurrences.append(
                    DynamicSQLOccurrence(
                        id=occurrence_id,
                        line=0,
                    )
                )
                occurrence_id += 1

            code_unit = CodeUnitData(
                code_unit_id=code_unit_id,
                procedure_name=source.get("name", ""),
                filename=file_source_path,
                code_unit_start_line=0,
                lines_of_code=lines_of_code,
                occurrences=occurrences,
                procedure=procedure_code,
            )
            code_units_data[code_unit_id] = code_unit.to_dict()

        total_occurrences = sum(len(cu["occurrences"]) for cu in code_units_data.values())
        output_data = {
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_occurrences": total_occurrences,
                "total_code_units": len(code_units_data),
                "files": {
                    "registry_dir": str(self.registry_dir),
                },
                "filter_code": issue_code,
            },
            "code_units": code_units_data,
        }

        output_path = Path(output_file)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        print(f"\nGenerated analysis JSON: {output_path}")
        print(f"Registry objects analyzed: {len(self.filtered_entries)}")
        print(f"Total procedures with {issue_code}: {len(code_units_data)}")
        print(f"Total occurrences to analyze: {total_occurrences}")

    def print_summary(self, issue_code: str = DYNAMIC_SQL_ISSUE_CODE) -> None:
        """Print summary of registry filtering."""
        object_type_counts = defaultdict(int)
        for entry in self.entries:
            object_type = entry.get("source", {}).get("objectType", "").lower() or "unknown"
            object_type_counts[object_type] += 1

        print("\n" + "=" * 60)
        print("SQL DYNAMIC REGISTRY ANALYSIS SUMMARY")
        print("=" * 60)
        print(f"\nTotal registry entries: {len(self.entries)}")
        print(f"Target object type: {TARGET_OBJECT_TYPE}")
        print(f"Dynamic issue code: {issue_code}")
        print(f"Procedures with matching issues: {len(self.filtered_entries)}")
        print("\nRegistry object type distribution:")
        for object_type, count in sorted(object_type_counts.items()):
            print(f"  {object_type}: {count}")


def print_usage() -> None:
    usage = f"""SQL Dynamic Analysis Helper (Registry-Only)

Commands:
  generate        Generate analysis JSON from registry (no CSV inputs)
  update          Update a record in an existing analysis JSON
  show            Show a specific record
  show-file       Show all code units in a file with occurrences grouped
  show-code-unit  Show procedure/function code for one code unit
  stats           Show analysis statistics

Usage:
  Generate:
    python {SCRIPT_NAME} generate --registry-dir <registry_dir> [--code CODE] [--output OUTPUT]

  Update:
    python {SCRIPT_NAME} update <analysis_json> --id ID [--line LINE] [--status STATUS] [--category CATEGORY] [--complexity COMPLEXITY] [--notes NOTES] [--generated-sql SQL] [--sql-classification CLASS]

  Show:
    python {SCRIPT_NAME} show <analysis_json> --id ID

  Show File:
    python {SCRIPT_NAME} show-file <analysis_json> --id ID
    python {SCRIPT_NAME} show-file <analysis_json> --filename FILENAME
    python {SCRIPT_NAME} show-file <analysis_json> --id ID --include-code

  Show Code Unit:
    python {SCRIPT_NAME} show-code-unit <analysis_json> --id ID
    python {SCRIPT_NAME} show-code-unit <analysis_json> --code-unit-id CODE_UNIT_ID

  Stats:
    python {SCRIPT_NAME} stats <analysis_json>
"""
    print(usage.rstrip())


def _parse_pairs(args: List[str]) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    i = 0
    while i < len(args):
        token = args[i]
        if token.startswith("--"):
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                parsed[token] = args[i + 1]
                i += 2
            else:
                parsed[token] = "true"
                i += 1
        else:
            i += 1
    return parsed


def cmd_generate(args: List[str]) -> None:
    options = _parse_pairs(args)
    registry_dir = options.get("--registry-dir")
    if not registry_dir:
        print("Error: --registry-dir is required", file=sys.stderr)
        print(f"Usage: python {SCRIPT_NAME} generate --registry-dir <registry_dir> [--code CODE] [--output OUTPUT]")
        sys.exit(1)

    issue_code = options.get("--code", DYNAMIC_SQL_ISSUE_CODE)
    output_file = options.get("--output", DEFAULT_OUTPUT)

    analyzer = SQLDynamicRegistryAnalyzer(registry_dir)
    analyzer.load_registry()
    analyzer.generate_analysis_json(output_file=output_file, issue_code=issue_code)
    analyzer.print_summary(issue_code=issue_code)

    print("\n✓ Analysis JSON generated successfully from registry!")
    print(f"\nNext steps:")
    print(f"  1. Review records: python {SCRIPT_NAME} show {output_file} --id <ID>")
    print(
        f"  2. Update records: python {SCRIPT_NAME} update {output_file} "
        '--id <ID> --line <LINE> --status REVIEWED --category "<CATEGORY>"'
    )
    print(f"  3. View statistics: python {SCRIPT_NAME} stats {output_file}")


def cmd_update(args: List[str]) -> None:
    if not args:
        print("Error: Missing analysis JSON file", file=sys.stderr)
        sys.exit(1)

    json_file = args[0]
    options = _parse_pairs(args[1:])
    record_id_str = options.get("--id")
    if not record_id_str:
        print("Error: --id is required", file=sys.stderr)
        sys.exit(1)

    record_id = int(record_id_str)
    status = options.get("--status")
    line_value = options.get("--line")
    category = options.get("--category")
    complexity = options.get("--complexity")
    notes = options.get("--notes")
    generated_sql = options.get("--generated-sql")
    sql_classification = options.get("--sql-classification")
    line = int(line_value) if line_value is not None else None

    if all(
        value is None
        for value in [line, status, category, complexity, notes, generated_sql, sql_classification]
    ):
        print(
            "Error: At least one of --line, --status, --category, --complexity, "
            "--notes, --generated-sql, or --sql-classification is required",
            file=sys.stderr,
        )
        sys.exit(1)

    manager = AnalysisJSONManager(json_file)
    manager.load()
    if manager.update_record(
        record_id=record_id,
        line=line,
        status=status,
        category=category,
        complexity=complexity,
        notes=notes,
        generated_sql=generated_sql,
        sql_classification=sql_classification,
    ):
        manager.save()
        print(f"\nRecord {record_id} updated successfully!")
        manager.print_record(record_id)
    else:
        print(f"Error: Record ID {record_id} not found", file=sys.stderr)
        sys.exit(1)


def cmd_show(args: List[str]) -> None:
    if not args:
        print("Error: Missing analysis JSON file", file=sys.stderr)
        sys.exit(1)

    json_file = args[0]
    options = _parse_pairs(args[1:])
    record_id_str = options.get("--id")
    if not record_id_str:
        print("Error: --id is required", file=sys.stderr)
        sys.exit(1)

    manager = AnalysisJSONManager(json_file)
    manager.load()
    manager.print_record(int(record_id_str))


def cmd_show_file(args: List[str]) -> None:
    if not args:
        print("Error: Missing analysis JSON file", file=sys.stderr)
        sys.exit(1)

    json_file = args[0]
    options = _parse_pairs(args[1:])
    record_id = options.get("--id")
    filename = options.get("--filename")
    include_code = "--include-code" in options

    if record_id is None and filename is None:
        print("Error: Either --id or --filename is required", file=sys.stderr)
        sys.exit(1)

    manager = AnalysisJSONManager(json_file)
    manager.load()

    if record_id is not None:
        filename = manager.get_filename_from_record_id(int(record_id))
        if filename is None:
            print(f"Error: Record ID {record_id} not found", file=sys.stderr)
            sys.exit(1)

    manager.print_all_code_units_in_file(filename, include_code=include_code)


def cmd_show_code_unit(args: List[str]) -> None:
    if not args:
        print("Error: Missing analysis JSON file", file=sys.stderr)
        sys.exit(1)

    json_file = args[0]
    options = _parse_pairs(args[1:])
    record_id = options.get("--id")
    code_unit_id = options.get("--code-unit-id")

    if record_id is None and code_unit_id is None:
        print("Error: Either --id or --code-unit-id is required", file=sys.stderr)
        sys.exit(1)

    manager = AnalysisJSONManager(json_file)
    manager.load()

    if record_id is not None:
        code_unit_id = manager.get_code_unit_id_from_record_id(int(record_id))
        if code_unit_id is None:
            print(f"Error: Record ID {record_id} not found", file=sys.stderr)
            sys.exit(1)

    manager.print_code_unit(code_unit_id, include_code=True)


def cmd_stats(args: List[str]) -> None:
    if not args:
        print("Error: Missing analysis JSON file", file=sys.stderr)
        sys.exit(1)

    manager = AnalysisJSONManager(args[0])
    manager.load()
    manager.print_stats()


COMMAND_HANDLERS = {
    "generate": cmd_generate,
    "update": cmd_update,
    "show": cmd_show,
    "show-file": cmd_show_file,
    "show-code-unit": cmd_show_code_unit,
    "stats": cmd_stats,
}


def main() -> None:
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    command = sys.argv[1]
    args = sys.argv[2:]
    handler = COMMAND_HANDLERS.get(command)
    if not handler:
        print(f"Error: Unknown command '{command}'", file=sys.stderr)
        print("\nAvailable commands: generate, update, show, show-file, show-code-unit, stats")
        sys.exit(1)

    try:
        handler(args)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
