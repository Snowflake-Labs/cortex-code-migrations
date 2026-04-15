#!/usr/bin/env python3
"""
Data Loading Module for HTML Wave Migration Report Generator

Contains all data loading and parsing functions for dependency analysis outputs.
"""
import sys
from pathlib import Path

# Add shared library to path
_scripts_dir = str(Path(__file__).resolve().parent.parent.parent / 'scripts')
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from snowconvert_reports.na_utils import NA_VALUES as _NA_VALUES 


def load_issues_estimation(json_path):
    """Load issues estimation data from JSON file."""
    from snowconvert_reports import load_issues_estimation_json
    issue_map_typed, severity_map_typed = load_issues_estimation_json(json_path)
    issue_map = {code: {'code': e.code, 'severity': e.severity, 'manual_effort': e.manual_effort, 'friendly_name': e.friendly_name}
                 for code, e in issue_map_typed.items()}
    severity_map = {s.severity: s.manual_effort for s in severity_map_typed.values()}
    return issue_map, severity_map


def load_toplevel_code_units(csv_path):
    """Load TopLevelCodeUnits CSV with object metadata.
    Uses CodeUnitId (fully qualified name) as the primary key for matching with partition_membership.
    """
    from snowconvert_reports import load_code_units
    units = load_code_units(csv_path)
    objects_data = {}
    for u in units:
        if u.code_unit_id:
            obj_data = {
                'category': u.category,
                'file_name': u.file_name,
                'code_unit': u.code_unit,
                'has_missing_dependencies': u.has_missing_dependencies,
                'deployment_order': u.deployment_order,
                'conversion_status': u.conversion_status,
                'lines_of_code': str(u.lines_of_code),
                'ewi_count': u.ewi_count,
                'fdm_count': u.fdm_count,
                'prf_count': u.prf_count,
                'highest_ewi_severity': u.highest_ewi_severity,
            }
            objects_data[u.code_unit_id] = obj_data
            if u.code_unit_name:
                objects_data[u.code_unit_name] = obj_data
    return objects_data


def load_partition_membership(csv_path):
    """Load partition membership CSV with object metadata."""
    from snowconvert_reports import load_partition_membership as _load
    members = _load(csv_path)
    return {m.object_name: {
        'partition': m.partition_number,
        'is_root': m.is_root,
        'is_leaf': m.is_leaf,
        'is_picked_scc': m.is_picked_scc,
        'category': m.category,
        'file_name': m.file_name,
        'technology': m.technology,
        'conversion_status': m.conversion_status,
        'subtype': m.subtype,
        'partition_type': m.partition_type,
    } for m in members}


def parse_graph_summary(txt_path):
    """Parse graph_summary.txt for comprehensive statistics."""
    from snowconvert_reports import parse_graph_summary as _parse
    return _parse(txt_path)


def parse_cycles(txt_path):
    """Parse cycles.txt for cyclic dependency information."""
    from snowconvert_reports import parse_cycles as _parse
    return _parse(txt_path)


def parse_excluded_edges(txt_path):
    """Parse excluded_edges_analysis.txt for comprehensive information."""
    from snowconvert_reports import parse_excluded_edges as _parse
    return _parse(txt_path)


def load_toplevel_objects_estimation(csv_path):
    """Load TopLevelObjectsEstimation report with per-object effort data and EWI counts."""
    from snowconvert_reports import load_object_estimations
    estimations = load_object_estimations(csv_path)
    return {e.object_id: {
        'manual_effort_minutes': e.manual_effort_minutes,
        'conversion_status': e.conversion_status,
        'ewis_number': e.ewis_number,
        'highest_ewi_severity': e.highest_ewi_severity,
    } for e in estimations}


def find_estimation_reports(reports_dir):
    """Find estimation report files with NA or timestamp patterns."""
    from snowconvert_reports import ReportFinder
    finder = ReportFinder(reports_dir)
    estimation_files = {}
    mapping = {
        'toplevel_estimation': finder.find_toplevel_objects_estimation,
        'issues_aggregate': finder.find_issues_aggregate,
        'effort_formula': finder.find_effort_formula,
    }
    for key, find_fn in mapping.items():
        path = find_fn()
        if path:
            estimation_files[key] = path
    return estimation_files


def load_estimation_grand_totals(estimation_files):
    """Load grand totals from estimation reports for display in HTML."""
    from snowconvert_reports import load_object_estimations
    from snowconvert_reports.loaders.csv_reader import read_csv_rows

    grand_totals = {}

    if 'toplevel_estimation' in estimation_files:
        try:
            estimations = load_object_estimations(estimation_files['toplevel_estimation'])
            total_objects = len(estimations)
            total_manual_minutes = sum(e.manual_effort_minutes for e in estimations)
            success_count = sum(1 for e in estimations if e.conversion_status == 'Success')

            grand_totals['toplevel'] = {
                'total_objects': total_objects,
                'total_manual_hours': total_manual_minutes / 60.0,
                'success_count': success_count,
                'success_rate': (success_count / total_objects * 100) if total_objects > 0 else 0
            }
        except Exception as e:
            print(f"Error loading toplevel estimation totals: {e}")

    if 'issues_aggregate' in estimation_files:
        try:
            severity_breakdown = {}
            total_issues = 0
            total_issue_minutes = 0.0

            for row in read_csv_rows(estimation_files['issues_aggregate']):
                severity = row.get('Highest EWI Severity', '')
                count = int(row.get('Object Count', '0') or '0')
                manual_effort = row.get('Manual Effort', '0')

                try:
                    effort_minutes = float(manual_effort) if manual_effort else 0.0
                except ValueError:
                    effort_minutes = 0.0

                total_issues += count
                total_issue_minutes += effort_minutes

                if severity:
                    severity_breakdown[severity] = {
                        'count': count,
                        'manual_hours': effort_minutes / 60.0
                    }

            grand_totals['issues_aggregate'] = {
                'total_issues': total_issues,
                'total_manual_hours': total_issue_minutes / 60.0,
                'severity_breakdown': severity_breakdown
            }
        except Exception as e:
            print(f"Error loading issues aggregate totals: {e}")

    if 'effort_formula' in estimation_files:
        try:
            code_unit_breakdown = {}

            for row in read_csv_rows(estimation_files['effort_formula']):
                code_unit = row.get('Code Unit Type', '')
                count = int(row.get('Code Unit Count', '0') or '0')
                manual_effort = row.get('Manual Effort', '0')

                try:
                    effort_minutes = float(manual_effort) if manual_effort else 0.0
                except ValueError:
                    effort_minutes = 0.0

                if code_unit:
                    code_unit_breakdown[code_unit] = {
                        'count': count,
                        'manual_hours': effort_minutes / 60.0
                    }

            grand_totals['effort_formula'] = {
                'code_unit_breakdown': code_unit_breakdown
            }
        except Exception as e:
            print(f"Error loading effort formula totals: {e}")

    return grand_totals


def estimate_hours_for_object(obj_name, objects_data, severity_map, estimation_data=None, conversion_status_override=None):
    """Estimate hours based on conversion status and issues.

    Uses estimation reports if provided, otherwise falls back to severity baseline.
    """
    obj_info = objects_data.get(obj_name, {})
    conversion_status = conversion_status_override if conversion_status_override is not None else obj_info.get('conversion_status', 'Unknown')

    if estimation_data and obj_name in estimation_data:
        return estimation_data[obj_name].get('manual_effort_minutes', 0.0) / 60.0

    if conversion_status == 'Success':
        return 0.0

    return severity_map.get('Medium', 16.5) / 60.0


def load_object_references_as_dicts(reports_dir):
    """Load ObjectReferences CSV as a list of {'caller', 'referenced'} dicts."""
    from snowconvert_reports import ReportFinder, load_object_references

    finder = ReportFinder(reports_dir)
    csv_path = finder.find_object_references()
    if not csv_path:
        return []

    refs = load_object_references(csv_path)
    return [
        {'caller': r.caller_full_name, 'referenced': r.referenced_full_name}
        for r in refs
        if r.caller_full_name and r.referenced_full_name
        and r.caller_full_name not in _NA_VALUES and r.referenced_full_name not in _NA_VALUES
    ]


def load_dependency_counts(analysis_dir):
    """Load per-object dependency counts from object_dependencies.csv."""
    from snowconvert_reports.loaders.csv_reader import read_csv_rows

    csv_path = Path(analysis_dir) / 'object_dependencies.csv'
    if not csv_path.exists():
        return {}

    counts = {}
    for row in read_csv_rows(csv_path):
        obj_name = row.get('object', '')
        if obj_name:
            counts[obj_name] = {
                'direct_dependencies': int(row.get('direct_dependencies_count', 0) or 0),
                'direct_dependents': int(row.get('direct_dependents_count', 0) or 0),
                'total_dependencies': int(row.get('total_dependencies', 0) or 0),
                'total_dependents': int(row.get('total_dependents', 0) or 0),
            }
    return counts


def load_missing_object_references(reports_dir):
    """Load missing object references to identify blocked objects.

    Tries ObjectReferences.*.csv first, then falls back to legacy MissingObjectReferences.*.csv.
    """
    from snowconvert_reports import ReportFinder, load_object_references

    reports_path = Path(reports_dir)
    finder = ReportFinder(reports_dir)

    obj_ref_path = finder.find_object_references()
    if obj_ref_path:
        result = _load_missing_refs_from_object_references(obj_ref_path, load_object_references)
        if result['missing_objects'] or result['details']:
            result['data_source'] = 'ObjectReferences'
            result['warning'] = None
            return result

    missing_ref_matches = list(reports_path.glob('MissingObjectReferences.*.csv'))
    if missing_ref_matches:
        result = _load_missing_refs_from_legacy_csv(missing_ref_matches[0])
        if result['missing_objects'] or result['details']:
            result['data_source'] = 'MissingObjectReferences'
            result['warning'] = None
            return result

    obj_ref_matches = list(reports_path.glob('ObjectReferences.*.csv'))
    warning_msg = None
    if not obj_ref_matches and not missing_ref_matches:
        warning_msg = "Warning: Could not load missing dependencies data. Neither ObjectReferences.csv nor MissingObjectReferences.csv was found in the reports directory. This does not mean there are no missing dependencies - the data source is unavailable."
    elif obj_ref_matches and not missing_ref_matches:
        warning_msg = "Warning: ObjectReferences.csv was found but contains no 'MISSING' entries, and MissingObjectReferences.csv (legacy format) was not found. Cannot determine if there are missing dependencies."

    return {
        'missing_objects': set(),
        'dependents': {},
        'details': [],
        'data_source': 'none',
        'warning': warning_msg
    }


def _accumulate_missing_refs(caller_referenced_pairs):
    """Build missing-refs result dict from (caller, referenced, relation_type, line, file_name) tuples."""
    missing_objects = set()
    dependents = {}
    details = []

    for caller, referenced, relation_type, line, file_name in caller_referenced_pairs:
        if not referenced or not caller or caller in _NA_VALUES or referenced in _NA_VALUES:
            continue

        missing_objects.add(referenced)
        dependents.setdefault(referenced, []).append({
            'caller': caller, 'relation_type': relation_type, 'line': line, 'file_name': file_name
        })
        details.append({
            'missing_object': referenced, 'dependent': caller,
            'relation_type': relation_type, 'line': line, 'file_name': file_name
        })

    return {'missing_objects': missing_objects, 'dependents': dependents, 'details': details}


def _load_missing_refs_from_object_references(csv_path, loader_fn):
    """Filter ObjectReferences for MISSING entries, rolling up ETL callers to package level."""
    refs = loader_fn(csv_path)

    def _iter():
        for ref in refs:
            if not ref.is_missing_reference:
                continue
            caller = ref.caller_full_name
            if ref.caller_code_unit == 'ETL PROCESS' and ref.file_name.endswith('.dtsx'):
                caller = str(Path(ref.file_name).with_suffix(''))
            yield caller, ref.referenced_full_name, ref.relation_type, ref.line, ref.file_name

    return _accumulate_missing_refs(_iter())


def _load_missing_refs_from_legacy_csv(csv_path):
    """Load from legacy MissingObjectReferences.*.csv file."""
    from snowconvert_reports.loaders.csv_reader import read_csv_rows

    def _iter():
        for row in read_csv_rows(csv_path):
            yield (
                row.get('Caller_CodeUnit_FullName', ''),
                row.get('Referenced_Element_FullName', ''),
                row.get('Relation_Type', ''),
                row.get('Line', ''),
                row.get('FileName', ''),
            )

    return _accumulate_missing_refs(_iter())


def load_missing_object_references_from_registry(registry_dir):
    """Load missing object references from SnowConvert registry JSON files.

    Returns the same contract as :func:`load_missing_object_references`::

        {'missing_objects': set, 'dependents': dict, 'details': list,
         'data_source': str, 'warning': str|None}
    """
    import re
    from snowconvert_reports import load_missing_references_from_registry

    _NA_SEG_RE = re.compile(r'\[N/A\]\.')
    _NA_VALS = {"N/A", "n/a", "NA", "na", ""}

    def _clean(val):
        if not val:
            return ""
        return _NA_SEG_RE.sub('', str(val).strip())

    refs = load_missing_references_from_registry(Path(registry_dir))

    def _iter():
        for r in refs:
            caller = _clean(r.caller_full_name)
            referenced = _clean(r.referenced_full_name)
            yield caller, referenced, r.relation_type, r.line, r.file_name

    result = _accumulate_missing_refs(_iter())
    result['data_source'] = 'registry'
    result['warning'] = None
    return result


def load_missing_refs(registry_dir=None, reports_dir=None):
    """Unified loader: picks registry or CSV backend automatically.

    Callers don't need ``if registry_dir … else …`` branching.

    Returns the same contract as :func:`load_missing_object_references`.
    """
    if registry_dir:
        try:
            result = load_missing_object_references_from_registry(registry_dir)
            if result['missing_objects'] or result['details']:
                return result
        except Exception as exc:
            import sys as _sys
            print(f"Warning: registry missing-refs failed, falling back to CSV: {exc}", file=_sys.stderr)

    if reports_dir:
        reports_path = Path(reports_dir)
        dirs_to_try = [reports_path]
        sc_sub = reports_path / 'SnowConvert'
        if sc_sub.exists():
            dirs_to_try.append(sc_sub)
        for d in dirs_to_try:
            if not d.exists():
                continue
            result = load_missing_object_references(d)
            if result['missing_objects'] or result['details']:
                return result
            if result.get('warning'):
                return result

    return {
        'missing_objects': set(),
        'dependents': {},
        'details': [],
        'data_source': 'none',
        'warning': (
            'No data source available for missing references. '
            'Provide --registry-dir or --snowconvert-reports-dir.'
        ),
    }