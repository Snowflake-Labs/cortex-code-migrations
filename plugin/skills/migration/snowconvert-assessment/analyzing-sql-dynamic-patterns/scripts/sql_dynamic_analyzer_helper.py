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
SQL Dynamic Analysis Helper

Analyzes SnowConvert Issues.csv file to identify and track SQL Dynamic patterns (SSC-EWI-0030).
Generates a tracking JSON for manual classification and complexity assessment.
Supports updating individual records with status, category, complexity, and notes.
"""

import json
import sys
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import sys as _sys
from pathlib import Path as _Path
_scripts_dir = str(_Path(__file__).resolve().parent.parent.parent / 'scripts')
if _scripts_dir not in _sys.path:
    _sys.path.insert(0, _scripts_dir)

from snowconvert_reports.models import IssueRecord, TopLevelCodeUnit
from snowconvert_reports.loaders import load_issues as _load_issues, load_code_units as _load_code_units
from sql_dynamic_models import AnalysisJSONManager, CodeUnitData, DynamicSQLOccurrence

# Issue code for dynamic SQL patterns
DYNAMIC_SQL_ISSUE_CODE = "SSC-EWI-0030"


class SQLDynamicAnalyzer:
    """Analyzer for SQL Dynamic patterns from SnowConvert Issues.csv."""

    def __init__(self, issues_file: str, top_level_code_units_file: Optional[str] = None, source_dir: Optional[str] = None):
        self.issues_file = Path(issues_file)
        self.top_level_code_units_file = Path(top_level_code_units_file) if top_level_code_units_file else None
        self.source_dir = Path(source_dir) if source_dir else None
        self.issues: List[IssueRecord] = []
        self.grouped_by_file: Dict[str, List[IssueRecord]] = defaultdict(list)
        self.code_units: List[TopLevelCodeUnit] = []
        self.code_units_by_id: Dict[str, TopLevelCodeUnit] = {}

    def load_issues(self, filter_code: Optional[str] = None) -> None:
        """Load issues from CSV file, optionally filtering by code."""
        if not self.issues_file.exists():
            raise FileNotFoundError(f"Issues file not found: {self.issues_file}")

        self.issues = _load_issues(self.issues_file, filter_code=filter_code)

        for issue in self.issues:
            self.grouped_by_file[issue.parent_file].append(issue)

        print(f"Loaded {len(self.issues)} issues from {self.issues_file}")
        if filter_code:
            print(f"Filtered by code: {filter_code}")
        print(f"Found issues in {len(self.grouped_by_file)} files")

    def load_top_level_code_units(self) -> None:
        """Load top-level code units from CSV file."""
        if not self.top_level_code_units_file:
            return

        if not self.top_level_code_units_file.exists():
            print(f"Warning: TopLevelCodeUnits file not found: {self.top_level_code_units_file}")
            return

        self.code_units = _load_code_units(self.top_level_code_units_file)

        for code_unit in self.code_units:
            # Index by CodeUnitId for fast lookup
            if code_unit.code_unit_id:
                self.code_units_by_id[code_unit.code_unit_id] = code_unit

        print(f"Loaded {len(self.code_units)} code units from {self.top_level_code_units_file}")
        print(f"Indexed {len(self.code_units_by_id)} code units by ID")

    def find_code_unit_by_id(self, code_unit_id: str) -> Optional[TopLevelCodeUnit]:
        """Find the code unit by its ID."""
        return self.code_units_by_id.get(code_unit_id)
    
    def detect_encoding(self, file_path: Path) -> str:
        """
        Detect file encoding by trying common encodings.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Detected encoding name
        """
        # Try reading BOM (Byte Order Mark) first
        with open(file_path, 'rb') as f:
            raw_data = f.read(4)
        
        # Check for BOM signatures
        if raw_data.startswith(b'\xff\xfe\x00\x00'):
            return 'utf-32-le'
        elif raw_data.startswith(b'\x00\x00\xfe\xff'):
            return 'utf-32-be'
        elif raw_data.startswith(b'\xff\xfe'):
            return 'utf-16-le'
        elif raw_data.startswith(b'\xfe\xff'):
            return 'utf-16-be'
        elif raw_data.startswith(b'\xef\xbb\xbf'):
            return 'utf-8-sig'
        
        # Try common encodings
        encodings_to_try = ['utf-8', 'utf-16-le', 'utf-16-be', 'latin-1', 'cp1252']
        
        for encoding in encodings_to_try:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    f.read(1024)
                return encoding
            except (UnicodeDecodeError, LookupError):
                continue
        
        # Default fallback
        return 'utf-8'
    
    def extract_procedure_code(self, filename: str, start_line: int, lines_of_code: int) -> str:
        """
        Extract procedure code from source file.
        Automatically detects and handles UTF-8, UTF-16, and other encodings.
        
        Args:
            filename: Relative path to the source file
            start_line: Starting line number (1-indexed)
            lines_of_code: Number of non-empty lines to extract
            
        Returns:
            Formatted procedure code with line numbers (as UTF-8 string)
        """
        if not self.source_dir:
            return ""
        
        source_file = self.source_dir / filename
        if not source_file.exists():
            print(f"Warning: Source file not found: {source_file}")
            return ""
        
        try:
            encoding = self.detect_encoding(source_file)

            with open(source_file, 'r', encoding=encoding, errors='replace') as f:
                all_lines = f.readlines()
            
            # Extract lines starting from start_line (convert to 0-indexed)
            start_idx = start_line - 1
            if start_idx < 0 or start_idx >= len(all_lines):
                return ""
            
            # Extract non-empty lines up to lines_of_code count
            extracted_lines = []
            non_empty_count = 0
            current_idx = start_idx
            
            while non_empty_count < lines_of_code and current_idx < len(all_lines):
                line = all_lines[current_idx]
                if line.strip():
                    # Format: "line_number: content"
                    # The line is already decoded to UTF-8 string
                    formatted_line = f"{current_idx + 1:3d}: {line.rstrip()}"
                    extracted_lines.append(formatted_line)
                    non_empty_count += 1
                current_idx += 1
            
            # Return as UTF-8 string (Python 3 strings are Unicode)
            return '\n'.join(extracted_lines)
            
        except Exception as e:
            print(f"Error reading source file {source_file}: {e}")
            return ""

    def generate_analysis_json(self, output_file: str = "sql_dynamic_analysis.json") -> None:
        """Generate analysis tracking JSON with all occurrences grouped by code unit."""
        code_units_data = {}
        occurrence_id = 1

        # Group by code_unit_id
        code_unit_groups = defaultdict(list)
        for filename in self.grouped_by_file.keys():
            issues_in_file = self.grouped_by_file[filename]
            
            for issue in issues_in_file:
                code_unit_id = issue.code_unit_id
                if not code_unit_id or code_unit_id.upper() == "N/A":
                    code_unit_id = f"unknown_{filename}"
                code_unit_groups[code_unit_id].append(issue)

        # Create code unit data structures
        for code_unit_id, issues in sorted(code_unit_groups.items()):
            # Sort issues by line number
            issues = sorted(issues, key=lambda x: x.line)
            
            # Get metadata from first issue or code unit lookup
            first_issue = issues[0]
            procedure_name = ""
            code_unit_start_line = 0
            lines_of_code = 0
            filename = first_issue.parent_file
            procedure_code = ""
            
            if self.top_level_code_units_file and code_unit_id:
                code_unit = self.find_code_unit_by_id(code_unit_id)
                if code_unit:
                    procedure_name = code_unit.code_unit_name
                    code_unit_start_line = code_unit.line_number
                    lines_of_code = code_unit.lines_of_code
                    filename = code_unit.file_name
                    
                    if self.source_dir and code_unit_start_line > 0 and lines_of_code > 0:
                        procedure_code = self.extract_procedure_code(
                            filename, 
                            code_unit_start_line, 
                            lines_of_code
                        )
            
            # Create occurrences for this code unit
            occurrences = []
            for issue in issues:
                occurrence = DynamicSQLOccurrence(
                    id=occurrence_id,
                    line=issue.line
                )
                occurrences.append(occurrence)
                occurrence_id += 1
            
            # Create code unit data
            code_unit_data = CodeUnitData(
                code_unit_id=code_unit_id,
                procedure_name=procedure_name,
                filename=filename,
                code_unit_start_line=code_unit_start_line,
                lines_of_code=lines_of_code,
                occurrences=occurrences,
                procedure=procedure_code
            )
            
            code_units_data[code_unit_id] = code_unit_data.to_dict()

        # Build final JSON structure
        total_occurrences = sum(len(cu['occurrences']) for cu in code_units_data.values())
        
        output_data = {
            'metadata': {
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'total_occurrences': total_occurrences,
                'total_code_units': len(code_units_data),
                'files': {
                    'issues_csv': str(self.issues_file),
                    'top_level_code_units_csv': str(self.top_level_code_units_file) if self.top_level_code_units_file else None,
                    'source_dir': str(self.source_dir) if self.source_dir else None
                },
                'filter_code': DYNAMIC_SQL_ISSUE_CODE
            },
            'code_units': code_units_data
        }

        # Write to JSON file
        output_path = Path(output_file)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        print(f"\nGenerated analysis JSON: {output_path}")
        print(f"Total code units: {len(code_units_data)}")
        print(f"Total occurrences to analyze: {total_occurrences}")

    def print_summary(self) -> None:
        """Print summary of findings."""
        print("\n" + "=" * 60)
        print("SQL DYNAMIC ANALYSIS SUMMARY")
        print("=" * 60)
        
        print(f"\nTotal Issues: {len(self.issues)}")
        print(f"Total Files: {len(self.grouped_by_file)}")
        
        print("\nTop 10 Files by Occurrence Count:")
        sorted_files = sorted(
            self.grouped_by_file.items(),
            key=lambda x: len(x[1]),
            reverse=True
        )
        
        for filename, issues in sorted_files[:10]:
            print(f"  {filename}: {len(issues)} occurrences")


def print_usage():
    """Print usage information."""
    print("SQL Dynamic Analysis Helper")
    print("\nCommands:")
    print("  generate   Generate initial analysis JSON from Issues.csv")
    print("  update     Update a record in the analysis JSON")
    print("  show       Show a specific record")
    print("  show-file  Show all code units in a file with their occurrences grouped")
    print("  show-code-unit  Show procedure/function code (from JSON metadata) for one code unit")
    print("  stats      Show statistics about the analysis")
    print("\nUsage:")
    print("  Generate:")
    print("    python sql_dynamic_analzer_helper.py generate <issues_csv> --top-level-code-units <tlcu_csv> --source-dir <dir> [--code CODE] [--output OUTPUT]")
    print("\n  Update:")
    print("    python sql_dynamic_analzer_helper.py update <analysis_json> --id ID [--status STATUS] [--category CATEGORY] [--complexity COMPLEXITY] [--notes NOTES] [--generated-sql SQL] [--sql-classification CLASS]")
    print("\n  Show:")
    print("    python sql_dynamic_analzer_helper.py show <analysis_json> --id ID")
    print("\n  Show File:")
    print("    python sql_dynamic_analzer_helper.py show-file <analysis_json> --id ID")
    print("    python sql_dynamic_analzer_helper.py show-file <analysis_json> --filename FILENAME")
    print("    python sql_dynamic_analzer_helper.py show-file <analysis_json> --id ID --include-code")
    print("    (Groups all occurrences by code unit within the file)")
    print("\n  Show Code Unit:")
    print("    python sql_dynamic_analzer_helper.py show-code-unit <analysis_json> --id ID")
    print("    python sql_dynamic_analzer_helper.py show-code-unit <analysis_json> --code-unit-id CODE_UNIT_ID")
    print("\n  Stats:")
    print("    python sql_dynamic_analzer_helper.py stats <analysis_json>")
    print("\nRequired Inputs for Generate:")
    print("  1. Issues.csv (positional) - SnowConvert output with SSC-EWI-0030 occurrences")
    print("  2. --top-level-code-units  - SnowConvert TopLevelCodeUnits.csv")
    print("  3. --source-dir            - Source code directory")
    print("\nExamples:")
    print("  # Generate analysis (ALL THREE INPUTS ARE REQUIRED)")
    print("  python sql_dynamic_analzer_helper.py generate Issues.csv --top-level-code-units TopLevelCodeUnits.csv --source-dir ../source")
    print("  python sql_dynamic_analzer_helper.py generate Issues.csv --top-level-code-units TopLevelCodeUnits.csv --source-dir ../source --output my_analysis.json")
    print("\n  # Update a record")
    print("  python sql_dynamic_analzer_helper.py update sql_dynamic_analysis.json --id 5 --status REVIEWED")
    print("  python sql_dynamic_analzer_helper.py update sql_dynamic_analysis.json --id 10 --status REVIEWED --category \"Parameter-Driven\" --complexity medium")
    print("  python sql_dynamic_analzer_helper.py update sql_dynamic_analysis.json --id 15 --notes \"Uses sp_executesql with parameters\"")
    print("  python sql_dynamic_analzer_helper.py update sql_dynamic_analysis.json --id 20 --generated-sql \"SELECT * FROM Users WHERE Id = @UserId\" --sql-classification \"DQL\"")
    print("\n  # Show a record")
    print("  python sql_dynamic_analzer_helper.py show sql_dynamic_analysis.json --id 5")
    print("\n  # Show all records for a file (by record ID) - grouped by code unit")
    print("  python sql_dynamic_analzer_helper.py show-file sql_dynamic_analysis.json --id 5")
    print("  python sql_dynamic_analzer_helper.py show-file sql_dynamic_analysis.json --id 5 --include-code")
    print("\n  # Show all records for a file (by filename) - grouped by code unit")
    print("  python sql_dynamic_analzer_helper.py show-file sql_dynamic_analysis.json --filename path/to/file.sql")
    print("\n  # Show the full procedure/function text for a code unit (by record ID)")
    print("  python sql_dynamic_analzer_helper.py show-code-unit sql_dynamic_analysis.json --id 5")
    print("\n  # Show the full procedure/function text for a code unit (by code unit id)")
    print("  python sql_dynamic_analzer_helper.py show-code-unit sql_dynamic_analysis.json --code-unit-id \"[DB].[dbo].[ProcName]\"")
    print("\n  # Show statistics")
    print("  python sql_dynamic_analzer_helper.py stats sql_dynamic_analysis.json")


def cmd_generate(args):
    """Generate command: Create initial analysis JSON from Issues.csv."""
    if len(args) < 1:
        print("Error: Missing required Issues.csv file", file=sys.stderr)
        print("Usage: python sql_dynamic_analzer_helper.py generate <issues_csv> --top-level-code-units <tlcu_csv> --source-dir <dir> [--code CODE] [--output OUTPUT]")
        sys.exit(1)

    issues_file = args[0]
    filter_code = DYNAMIC_SQL_ISSUE_CODE
    top_level_code_units_file = None
    source_dir = None
    output_file = "sql_dynamic_analysis.json"

    # Parse optional arguments
    i = 1
    while i < len(args):
        if args[i] == '--code' and i + 1 < len(args):
            filter_code = args[i + 1]
            i += 2
        elif args[i] == '--top-level-code-units' and i + 1 < len(args):
            top_level_code_units_file = args[i + 1]
            i += 2
        elif args[i] == '--source-dir' and i + 1 < len(args):
            source_dir = args[i + 1]
            i += 2
        elif args[i] == '--output' and i + 1 < len(args):
            output_file = args[i + 1]
            i += 2
        else:
            print(f"Warning: Unknown argument '{args[i]}'", file=sys.stderr)
            i += 1

    # Validate all required parameters
    missing_params = []
    if not top_level_code_units_file:
        missing_params.append("--top-level-code-units")
    if not source_dir:
        missing_params.append("--source-dir")
    
    if missing_params:
        print(f"\nError: Missing required parameter(s): {', '.join(missing_params)}", file=sys.stderr)
        print("\nAll three inputs are required for code-unit-based analysis:")
        print("  1. Issues.csv (positional): Contains SSC-EWI-0030 dynamic SQL occurrences")
        print("  2. --top-level-code-units: Provides procedure names and code unit boundaries")
        print("  3. --source-dir: Source code directory for extracting procedure code")
        print("\nUsage: python sql_dynamic_analzer_helper.py generate <issues_csv> --top-level-code-units <tlcu_csv> --source-dir <dir> [--output OUTPUT]")
        sys.exit(1)

    analyzer = SQLDynamicAnalyzer(issues_file, top_level_code_units_file, source_dir)
    analyzer.load_issues(filter_code=filter_code)
    analyzer.load_top_level_code_units()
    analyzer.print_summary()
    analyzer.generate_analysis_json(output_file)

    print("\n✓ Analysis JSON generated successfully!")
    print(f"✓ Procedure code extracted from source directory: {source_dir}")
    print(f"\nNext steps:")
    print(f"  1. Review records: python sql_dynamic_analzer_helper.py show {output_file} --id <ID>")
    print(f"  2. Update records: python sql_dynamic_analzer_helper.py update {output_file} --id <ID> --status REVIEWED --category \"<CATEGORY>\"")
    print(f"  3. View statistics: python sql_dynamic_analzer_helper.py stats {output_file}")


def cmd_update(args):
    """Update command: Update a record in the analysis JSON."""
    if len(args) < 1:
        print("Error: Missing analysis JSON file", file=sys.stderr)
        print("Usage: python sql_dynamic_analzer_helper.py update <analysis_json> --id ID [--status STATUS] [--category CATEGORY] [--complexity COMPLEXITY] [--notes NOTES] [--generated-sql SQL] [--sql-classification CLASS]")
        sys.exit(1)

    json_file = args[0]
    record_id = None
    status = None
    category = None
    complexity = None
    notes = None
    generated_sql = None
    sql_classification = None

    # Parse arguments
    i = 1
    while i < len(args):
        if args[i] == '--id' and i + 1 < len(args):
            record_id = int(args[i + 1])
            i += 2
        elif args[i] == '--status' and i + 1 < len(args):
            status = args[i + 1]
            i += 2
        elif args[i] == '--category' and i + 1 < len(args):
            category = args[i + 1]
            i += 2
        elif args[i] == '--complexity' and i + 1 < len(args):
            complexity = args[i + 1]
            i += 2
        elif args[i] == '--notes' and i + 1 < len(args):
            notes = args[i + 1]
            i += 2
        elif args[i] == '--generated-sql' and i + 1 < len(args):
            generated_sql = args[i + 1]
            i += 2
        elif args[i] == '--sql-classification' and i + 1 < len(args):
            sql_classification = args[i + 1]
            i += 2
        else:
            print(f"Warning: Unknown argument '{args[i]}'", file=sys.stderr)
            i += 1

    if record_id is None:
        print("Error: --id is required", file=sys.stderr)
        sys.exit(1)

    if all(v is None for v in [status, category, complexity, notes, generated_sql, sql_classification]):
        print("Error: At least one of --status, --category, --complexity, --notes, --generated-sql, or --sql-classification is required", file=sys.stderr)
        sys.exit(1)

    manager = AnalysisJSONManager(json_file)
    manager.load()

    if manager.update_record(
        record_id=record_id,
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


def cmd_show(args):
    """Show command: Display a specific record."""
    if len(args) < 1:
        print("Error: Missing analysis JSON file", file=sys.stderr)
        print("Usage: python sql_dynamic_analzer_helper.py show <analysis_json> --id ID")
        sys.exit(1)

    json_file = args[0]
    record_id = None

    # Parse arguments
    i = 1
    while i < len(args):
        if args[i] == '--id' and i + 1 < len(args):
            record_id = int(args[i + 1])
            i += 2
        else:
            print(f"Warning: Unknown argument '{args[i]}'", file=sys.stderr)
            i += 1

    if record_id is None:
        print("Error: --id is required", file=sys.stderr)
        sys.exit(1)

    manager = AnalysisJSONManager(json_file)
    manager.load()
    manager.print_record(record_id)


def cmd_show_file(args):
    """Show-file command: Display all records grouped by code unit for a file."""
    if len(args) < 1:
        print("Error: Missing analysis JSON file", file=sys.stderr)
        print("Usage: python sql_dynamic_analzer_helper.py show-file <analysis_json> --id ID")
        print("   or: python sql_dynamic_analzer_helper.py show-file <analysis_json> --filename FILENAME")
        print("   or: python sql_dynamic_analzer_helper.py show-file <analysis_json> --id ID --include-code")
        sys.exit(1)

    json_file = args[0]
    record_id = None
    filename = None
    include_code = False

    # Parse arguments
    i = 1
    while i < len(args):
        if args[i] == '--id' and i + 1 < len(args):
            record_id = int(args[i + 1])
            i += 2
        elif args[i] == '--filename' and i + 1 < len(args):
            filename = args[i + 1]
            i += 2
        elif args[i] == '--include-code':
            include_code = True
            i += 1
        else:
            print(f"Warning: Unknown argument '{args[i]}'", file=sys.stderr)
            i += 1

    if record_id is None and filename is None:
        print("Error: Either --id or --filename is required", file=sys.stderr)
        sys.exit(1)

    manager = AnalysisJSONManager(json_file)
    manager.load()

    # If ID provided, get filename from that record
    if record_id is not None:
        filename = manager.get_filename_from_record_id(record_id)
        if filename is None:
            print(f"Error: Record ID {record_id} not found", file=sys.stderr)
            sys.exit(1)

    # Show all code units in this file with their occurrences
    manager.print_all_code_units_in_file(filename, include_code=include_code)


def cmd_show_code_unit(args):
    """Show-code-unit command: Display the procedure/function code for a single code unit."""
    if len(args) < 1:
        print("Error: Missing analysis JSON file", file=sys.stderr)
        print("Usage: python sql_dynamic_analzer_helper.py show-code-unit <analysis_json> --id ID")
        print("   or: python sql_dynamic_analzer_helper.py show-code-unit <analysis_json> --code-unit-id CODE_UNIT_ID")
        sys.exit(1)

    json_file = args[0]
    record_id = None
    code_unit_id = None

    # Parse arguments
    i = 1
    while i < len(args):
        if args[i] == '--id' and i + 1 < len(args):
            record_id = int(args[i + 1])
            i += 2
        elif args[i] == '--code-unit-id' and i + 1 < len(args):
            code_unit_id = args[i + 1]
            i += 2
        else:
            print(f"Warning: Unknown argument '{args[i]}'", file=sys.stderr)
            i += 1

    if record_id is None and code_unit_id is None:
        print("Error: Either --id or --code-unit-id is required", file=sys.stderr)
        sys.exit(1)

    manager = AnalysisJSONManager(json_file)
    manager.load()

    if record_id is not None:
        code_unit_id = manager.get_code_unit_id_from_record_id(record_id)
        if code_unit_id is None:
            print(f"Error: Record ID {record_id} not found", file=sys.stderr)
            sys.exit(1)

    manager.print_code_unit(code_unit_id, include_code=True)


def cmd_stats(args):
    """Stats command: Show statistics about the analysis."""
    if len(args) < 1:
        print("Error: Missing analysis JSON file", file=sys.stderr)
        print("Usage: python sql_dynamic_analzer_helper.py stats <analysis_json>")
        sys.exit(1)

    json_file = args[0]
    manager = AnalysisJSONManager(json_file)
    manager.load()
    manager.print_stats()


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    command = sys.argv[1]
    args = sys.argv[2:]

    try:
        if command == 'generate':
            cmd_generate(args)
        elif command == 'update':
            cmd_update(args)
        elif command == 'show':
            cmd_show(args)
        elif command == 'show-file':
            cmd_show_file(args)
        elif command == 'show-code-unit':
            cmd_show_code_unit(args)
        elif command == 'stats':
            cmd_stats(args)
        else:
            print(f"Error: Unknown command '{command}'", file=sys.stderr)
            print("\nAvailable commands: generate, update, show, show-file, show-code-unit, stats")
            print("Run without arguments for full usage information.")
            sys.exit(1)

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()