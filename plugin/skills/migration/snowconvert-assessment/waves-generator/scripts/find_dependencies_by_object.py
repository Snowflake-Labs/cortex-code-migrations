#!/usr/bin/env python3
"""
Find Missing Dependencies by Object

Analyzes TopLevelCodeUnits and ObjectReferences.csv to determine
which missing dependencies each object has.

Missing references are identified by filtering ObjectReferences.csv
for rows where Referenced_Element_Type='MISSING'.

Falls back to legacy MissingObjectReferences.csv if ObjectReferences.csv
doesn't yield any missing dependencies.
"""
import csv
import json
import argparse
import sys
from pathlib import Path
from collections import defaultdict


def find_csv_files(reports_dir, pattern_prefix):
    """Find CSV files matching pattern (e.g., TopLevelCodeUnits.*.csv)."""
    reports_path = Path(reports_dir)
    
    # Try exact match first
    exact_match = reports_path / f"{pattern_prefix}.NA.csv"
    if exact_match.exists():
        return exact_match
    
    # Try pattern match
    matches = list(reports_path.glob(f"{pattern_prefix}.*.csv"))
    if matches:
        return matches[0]
    
    return None


def load_toplevel_objects(csv_path):
    """Load TopLevelCodeUnits or TopLevelObjectsEstimation CSV and return set of object IDs.
    
    Supports two CSV formats:
    1. TopLevelCodeUnits: Uses 'CodeUnitId', 'CodeUnitName', 'Category' columns
    2. TopLevelObjectsEstimation: Uses 'Object Id', 'ObjectName', 'HighLevelObject' columns
    """
    objects = {}
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Try TopLevelCodeUnits format first
            code_unit_id = row.get('CodeUnitId', '').strip()
            code_unit_name = row.get('CodeUnitName', '').strip()
            category = row.get('Category', '').strip()
            
            # Try TopLevelObjectsEstimation format if CodeUnitId not found
            if not code_unit_id:
                code_unit_id = row.get('Object Id', '').strip()
                code_unit_name = row.get('ObjectName', '').strip()
                category = row.get('HighLevelObject', '').strip()
            
            file_name = row.get('FileName', '').strip()
            
            if code_unit_id and code_unit_id != 'N/A':
                objects[code_unit_id] = {
                    'name': code_unit_name,
                    'category': category,
                    'file': file_name,
                    'full_id': code_unit_id
                }
    
    return objects


def load_missing_dependencies_from_object_refs(csv_path):
    """Load missing dependencies from ObjectReferences.csv and group by caller object.
    
    Filters for rows where Referenced_Element_Type='MISSING'.
    """
    missing_deps = defaultdict(list)
    
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            ref_type = row.get('Referenced_Element_Type', '').strip()
            if ref_type != 'MISSING':
                continue
            
            caller = row.get('Caller_CodeUnit_FullName', '').strip()
            caller_type = row.get('Caller_CodeUnit', '').strip()
            referenced = row.get('Referenced_Element_FullName', '').strip()
            relation_type = row.get('Relation_Type', '').strip()
            line = row.get('Line', '').strip()
            file_name = row.get('FileName', '').strip()
            
            # Roll up ETL components to package level
            if caller_type == 'ETL PROCESS' and file_name.endswith('.dtsx'):
                caller = str(Path(file_name).with_suffix(''))
            
            if not caller or not referenced or caller == 'N/A' or referenced == 'N/A':
                continue
            
            missing_deps[caller].append({
                'referenced': referenced,
                'relation_type': relation_type,
                'line': line,
                'file': file_name
            })
    
    # Deduplicate per caller (ETL roll-up can produce repeats for the same referenced object)
    for caller in missing_deps:
        seen = set()
        unique = []
        for dep in missing_deps[caller]:
            ref = dep['referenced']
            if ref not in seen:
                seen.add(ref)
                unique.append(dep)
        missing_deps[caller] = unique
    
    return missing_deps


def load_missing_dependencies_from_legacy(csv_path):
    """Load missing dependencies from legacy MissingObjectReferences.csv and group by caller object."""
    missing_deps = defaultdict(list)
    
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            caller = row.get('Caller_CodeUnit_FullName', '').strip()
            referenced = row.get('Referenced_Element_FullName', '').strip()
            relation_type = row.get('Relation_Type', '').strip()
            line = row.get('Line', '').strip()
            file_name = row.get('FileName', '').strip()
            
            # Skip rows with missing or N/A caller/referenced values
            if not caller or not referenced or caller == 'N/A' or referenced == 'N/A':
                continue
            
            missing_deps[caller].append({
                'referenced': referenced,
                'relation_type': relation_type,
                'line': line,
                'file': file_name
            })
    
    return missing_deps


def generate_missing_dependencies_report(toplevel_csv, object_refs_csv, legacy_csv, output_json):
    """Generate JSON report of missing dependencies by object.
    
    Args:
        toplevel_csv: Path to TopLevelCodeUnits or TopLevelObjectsEstimation CSV
        object_refs_csv: Path to ObjectReferences.csv (or None if not found)
        legacy_csv: Path to legacy MissingObjectReferences.csv (or None if not found)
        output_json: Path to output JSON file
        
    Returns:
        tuple: (report dict, data_source str, warning str or None)
    """
    
    # Load data
    print(f"Loading TopLevelCodeUnits from: {toplevel_csv}")
    objects = load_toplevel_objects(toplevel_csv)
    print(f"Loaded {len(objects)} objects")
    
    # Try ObjectReferences.csv first (new format)
    missing_deps = {}
    data_source = 'none'
    warning = None
    
    if object_refs_csv:
        print(f"Loading missing dependencies from: {object_refs_csv} (filtering Referenced_Element_Type='MISSING')")
        missing_deps = load_missing_dependencies_from_object_refs(object_refs_csv)
        if missing_deps:
            data_source = 'ObjectReferences'
            print(f"Found {len(missing_deps)} objects with missing dependencies from ObjectReferences.csv")
    
    # Fallback to legacy MissingObjectReferences.csv if no data from ObjectReferences
    if not missing_deps and legacy_csv:
        print(f"No missing dependencies found in ObjectReferences.csv, falling back to: {legacy_csv}")
        missing_deps = load_missing_dependencies_from_legacy(legacy_csv)
        if missing_deps:
            data_source = 'MissingObjectReferences'
            print(f"Found {len(missing_deps)} objects with missing dependencies from MissingObjectReferences.csv")
    
    # If neither source provided data
    if not missing_deps:
        if not object_refs_csv and not legacy_csv:
            warning = "Warning: Could not load missing dependencies data. Neither ObjectReferences.csv nor MissingObjectReferences.csv was found."
        elif object_refs_csv and not legacy_csv:
            # ObjectReferences.csv exists but had no MISSING rows, and no legacy fallback available
            # This likely means older report format where MISSING data was in separate file
            warning = "Warning: ObjectReferences.csv was found but contains no 'MISSING' entries, and MissingObjectReferences.csv (legacy format) was not found. Cannot determine if there are missing dependencies."
        # else: Both files checked OR only legacy file checked - truly no missing deps (no warning)
    
    # Build report
    report = {}
    
    for obj_id, obj_info in objects.items():
        if obj_id in missing_deps:
            deps = missing_deps[obj_id]
            report[obj_id] = {
                'object_name': obj_info['name'],
                'object_category': obj_info['category'],
                'object_file': obj_info['file'],
                'has_missing_dependencies': True,
                'missing_count': len(deps),
                'missing_dependencies': deps
            }
        else:
            report[obj_id] = {
                'object_name': obj_info['name'],
                'object_category': obj_info['category'],
                'object_file': obj_info['file'],
                'has_missing_dependencies': False,
                'missing_count': 0,
                'missing_dependencies': []
            }
    
    # Include ETL packages (not in TopLevelCodeUnits) that have missing deps
    for caller, deps in missing_deps.items():
        if caller not in report:
            report[caller] = {
                'object_name': caller,
                'object_category': 'ETL',
                'object_file': f'{caller}.dtsx' if not caller.endswith('.dtsx') else caller,
                'has_missing_dependencies': True,
                'missing_count': len(deps),
                'missing_dependencies': deps
            }
    
    # Add metadata about data source
    report_with_metadata = {
        '_metadata': {
            'data_source': data_source,
            'warning': warning
        },
        'objects': report
    }
    
    # Write JSON output
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(report_with_metadata, f, indent=2)
    
    print(f"\nReport generated: {output_json}")
    print(f"Data source: {data_source}")
    if warning:
        print(f"WARNING: {warning}")
    print(f"Total objects: {len(report)}")
    print(f"Objects with missing dependencies: {sum(1 for obj in report.values() if obj['has_missing_dependencies'])}")
    print(f"Objects without missing dependencies: {sum(1 for obj in report.values() if not obj['has_missing_dependencies'])}")
    
    return report_with_metadata


def main():
    parser = argparse.ArgumentParser(
        description='Find missing dependencies by object from SnowConvert reports'
    )
    parser.add_argument(
        '--reports-dir', '-r',
        required=True,
        help='Directory containing TopLevelCodeUnits and ObjectReferences CSV files'
    )
    parser.add_argument(
        '--output', '-o',
        required=True,
        help='Output JSON file path'
    )
    
    args = parser.parse_args()
    
    # Find CSV files
    toplevel_csv = find_csv_files(args.reports_dir, 'TopLevelCodeUnits')
    object_refs_csv = find_csv_files(args.reports_dir, 'ObjectReferences')
    legacy_csv = find_csv_files(args.reports_dir, 'MissingObjectReferences')
    
    if not toplevel_csv:
        print("Error: TopLevelCodeUnits CSV not found in reports directory")
        sys.exit(1)
    
    if not object_refs_csv and not legacy_csv:
        print("Error: Neither ObjectReferences CSV nor MissingObjectReferences CSV found in reports directory")
        sys.exit(1)
    
    # Generate report with fallback logic
    generate_missing_dependencies_report(toplevel_csv, object_refs_csv, legacy_csv, args.output)


if __name__ == '__main__':
    main()