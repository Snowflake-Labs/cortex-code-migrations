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
Naming Convention Analyzer for SnowConvert Reports

Identifies temporary/staging, deprecated/legacy, testing, and duplicate objects.
This script analyzes SnowConvert report data to detect:
1. Temporary & Transient Objects (Naming-Based)
2. Deprecated Code Indicators (Naming-Based)
3. Testing Objects (Naming-Based: Test, Fake, Mock, Demo, Sample patterns)
4. Duplicate Objects (File-Based: Same object in multiple source files)
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# Add shared library to path
_scripts_dir = str(Path(__file__).resolve().parent.parent.parent / 'scripts')
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from object_exclusion_shared import (
    INVALID_REFERENCE_VALUES,
    NamingConventionAnalyzer as SharedNamingConventionAnalyzer,
)
from snowconvert_reports import ReportFinder, load_object_references, read_csv_rows


class NamingConventionAnalyzer(SharedNamingConventionAnalyzer):
    """CSV-backed naming convention analyzer."""

    def _read_object_references(self) -> None:
        """Read dependency relationships from ObjectReferences CSV"""
        finder = ReportFinder(self.report_directory)
        ref_file = finder.find_object_references()

        if not ref_file:
            print(f"No ObjectReferences CSV found (optional for dependency analysis)")
            self.object_references = {}
            return

        print(f"Reading dependencies from: {ref_file.name}")

        # Build dependency graph: caller -> [list of referenced objects]
        # and reverse graph: referenced -> [list of callers]
        dependencies = defaultdict(set)  # caller -> set of referenced
        dependents = defaultdict(set)    # referenced -> set of callers

        refs = load_object_references(ref_file)
        row_count = 0

        for ref in refs:
            caller = ref.caller_full_name.replace('[', '').replace(']', '')
            referenced = ref.referenced_full_name.replace('[', '').replace(']', '')

            # Skip invalid values
            if caller in INVALID_REFERENCE_VALUES or referenced in INVALID_REFERENCE_VALUES:
                continue

            if caller and referenced and caller != referenced:
                dependencies[caller].add(referenced)
                dependents[referenced].add(caller)
                row_count += 1

        self.object_references = {
            'dependencies': dependencies,
            'dependents': dependents
        }
        print(f"     Loaded {row_count} dependency relationships")
    
    def _read_snowconvert_report(self) -> List[Dict[str, Any]]:
        """Read objects from SnowConvert TopLevelCodeUnits.*.csv report

        Uses direct CSV columns:
        - CodeUnit: Filter for CREATE statements only
        - Category: Object type (TABLE, VIEW, PROCEDURE, FUNCTION)
        - CodeUnitId: Full qualified name (e.g., [DB].[Schema].[Name])
        - SourceDatabase, SourceSchema, CodeUnitName: Object metadata
        """
        finder = ReportFinder(self.report_directory)
        report_file = finder.find_code_units()

        if not report_file:
            print(f"Error: No TopLevelCodeUnits.*.csv found in {self.report_directory}")
            return []

        print(f"Reading: {report_file.name}")

        objects = []

        def clean_brackets(value: str) -> str:
            """Remove SQL Server bracket notation and clean whitespace"""
            if not value:
                return ''
            return value.replace('[', '').replace(']', '').strip()

        for row in read_csv_rows(report_file):
            # Only process CREATE statements (skip ALTER, DROP, etc.)
            code_unit = row.get('CodeUnit', '').upper()
            if not code_unit.startswith('CREATE'):
                continue

            # Get object type from Category field
            obj_type = row.get('Category', '').upper()

            # Only process specific object types (tables, views, procedures, functions)
            allowed_types = {'TABLE', 'VIEW', 'PROCEDURE', 'FUNCTION'}
            if obj_type not in allowed_types:
                continue

            # Use CodeUnitId directly for full_name
            code_unit_id = clean_brackets(row.get('CodeUnitId', ''))
            if not code_unit_id or code_unit_id == 'N/A':
                continue

            # Remove procedure/function parameter list suffix like "()"
            if '(' in code_unit_id:
                code_unit_id = code_unit_id.split('(')[0]

            # Get object name from CodeUnitName
            obj_name = clean_brackets(row.get('CodeUnitName', ''))
            if not obj_name or obj_name == 'N/A':
                continue

            # Remove parameter list from object name
            if '(' in obj_name:
                obj_name = obj_name.split('(')[0]

            # Skip SnowConvert parse error entries (e.g., "Error-PROCEDURE", "Error-FUNCTION")
            # These occur when SnowConvert fails to parse an object
            if obj_name.startswith('Error-'):
                continue

            # Get schema from SourceSchema
            schema = clean_brackets(row.get('SourceSchema', ''))
            if not schema or schema == 'N/A':
                schema = 'dbo'

            # Get database from SourceDatabase
            database = clean_brackets(row.get('SourceDatabase', ''))
            if database == 'N/A':
                database = ''

            # Get source file for reference
            source_file = row.get('FileName', '')

            objects.append({
                "name": obj_name,
                "full_name": code_unit_id,
                "schema": schema,
                "database": database,
                "type": obj_type,
                "source": "SnowConvert Report",
                "file": source_file,
                "report_file": report_file.name
            })

        print(f"  Parsed {report_file.name}: {len(objects)} objects")

        return objects


def main():
    parser = argparse.ArgumentParser(
        description='Analyze SnowConvert reports for naming conventions',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze SnowConvert reports
  python analyze_naming_conventions.py -r /path/to/SnowConvert/Reports -d ./analysis-output
  
  # Exclude staging schema detection
  python analyze_naming_conventions.py -r /path/to/Reports -d ./output --exclude-staging-schema
  
"""
    )
    
    parser.add_argument(
        '--reports', '-r',
        required=True,
        help='Path to SnowConvert Reports directory (containing TopLevelCodeUnits.*.csv)'
    )
    
    parser.add_argument(
        '--output-dir', '-d',
        required=True,
        help='Output directory for results (creates timestamped subdirectory)'
    )
    
    parser.add_argument(
        '--include-staging-schema',
        action='store_true',
        default=True,
        help='Include all objects in Staging/Temp schemas as temporary/staging objects (default: True)'
    )
    
    parser.add_argument(
        '--exclude-staging-schema',
        action='store_true',
        help='Exclude objects in Staging/Temp schemas (only match explicit naming patterns)'
    )
    
    args = parser.parse_args()
    
    report_dir = Path(args.reports)
    output_base_dir = Path(args.output_dir)
    
    if not report_dir.exists():
        print(f"Error: Reports directory not found: {report_dir}", file=sys.stderr)
        sys.exit(1)
    
    # Validate that required report files exist BEFORE creating output directory
    matching_files = list(report_dir.glob("TopLevelCodeUnits.*.csv"))
    if not matching_files:
        print(f"Error: No TopLevelCodeUnits.*.csv found in {report_dir}", file=sys.stderr)
        print(f"   Please ensure the SnowConvert reports directory contains TopLevelCodeUnits.NA.csv or TopLevelCodeUnits.<timestamp>.csv", file=sys.stderr)
        sys.exit(1)
    
    print(f"Found report file: {matching_files[0].name}")
    
    # Create timestamped output directory (like waves-generator)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir = output_base_dir / f'exclusion_analysis_{timestamp}'
    output_dir.mkdir(parents=True, exist_ok=True)
    
    include_staging = args.include_staging_schema and not args.exclude_staging_schema
    
    print("Using Pattern-based Analyzer")
    analyzer = NamingConventionAnalyzer(report_dir, include_staging_schema=include_staging)
    results = analyzer.analyze()
    
    # Output files in timestamped directory
    output_file = output_dir / 'naming_conventions.json'
    summary_output = output_dir / 'analysis_summary.txt'
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, default=str)
    
    # Generate summary text file
    analyzer_type = results['summary'].get('analyzer_type', 'pattern-based')
    duplicate_count = results['summary'].get('duplicate_objects_count', 0)
    summary_text = f"""Object Exclusion Analysis Summary
{'='*60}
Analyzer Type: {analyzer_type}
Report Directory: {report_dir}
Analysis Timestamp: {timestamp}

Results:
  Total Objects: {results['summary']['total_objects_found']}
  Temp/Staging Objects: {results['summary']['temp_staging_objects_count']}
  Deprecated/Legacy Objects: {results['summary']['deprecated_legacy_objects_count']}
  Testing Objects: {results['summary']['testing_objects_count']}
  Duplicate Objects: {duplicate_count}
"""
    if 'workload_type' in results['summary']:
        summary_text += f"  Detected Workload: {results['summary']['workload_type']}\n"
    
    summary_text += f"""
Output Files:
  JSON: {output_file.name}
  Summary: {summary_output.name}
{'='*60}
"""
    
    with open(summary_output, 'w', encoding='utf-8') as f:
        f.write(summary_text)
    
    print(f"\n{'='*60}")
    print(f"Object Exclusion Analysis Summary ({analyzer_type}):")
    print(f"  Report Directory: {report_dir.name}")
    print(f"  Total Objects: {results['summary']['total_objects_found']}")
    if 'workload_type' in results['summary']:
        print(f"  Detected Workload: {results['summary']['workload_type']}")
    print(f"  Temp/Staging Objects: {results['summary']['temp_staging_objects_count']}")
    print(f"  Deprecated/Legacy Objects: {results['summary']['deprecated_legacy_objects_count']}")
    print(f"  Testing Objects: {results['summary']['testing_objects_count']}")
    print(f"  Duplicate Objects: {duplicate_count}")
    print(f"{'='*60}\n")
    print(f"Results written to: {output_dir.absolute()}/")
    print(f"   - {output_file.name}")
    print(f"   - {summary_output.name}")


if __name__ == "__main__":
    main()