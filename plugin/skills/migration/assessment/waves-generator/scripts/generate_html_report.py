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
HTML Wave Migration Report Generator

Generates comprehensive interactive HTML report from dependency analysis outputs.
Includes: analysis summary, wave statistics, object details, and hour estimations.
"""
import json
import argparse
import re
from datetime import datetime
from pathlib import Path
from collections import defaultdict

from load_data_html_report import (
    load_toplevel_code_units,
    load_toplevel_objects_estimation,
    find_estimation_reports,
    load_estimation_grand_totals,
    estimate_hours_for_object,
    load_object_references_as_dicts,
)
from registry_support import (
    is_na,
    strip_na_identifier,
)

# Add shared library to path
_scripts_dir = str(Path(__file__).resolve().parent.parent.parent / 'scripts')
import sys
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from snowconvert_reports.issue_docs import ISSUE_DOCUMENTATION_URL_JS
from snowconvert_reports.loaders.waves_json import WavesJsonAdapter
from pdf_print import print_note

# What the waves total counts; other assessment totals count the registry with
# other rules. The multi-report and dashboard use the same copy.
WAVE_PLAN_TOTAL_SCOPE = "Every object in the wave plan, missing references included"


def _sanitize_str(val):
    """Return ``'-'`` for None, empty, or ``'N/A'`` values; otherwise the trimmed string."""
    if val is None:
        return '-'
    s = str(val).strip()
    return '-' if not s or s.upper() == 'N/A' else s


def _sanitize_missing_deps_data(missing_deps_data):
    """Sanitize N/A / empty values in missing_deps_data in-place."""
    for obj_data in missing_deps_data.values():
        if not isinstance(obj_data, dict):
            continue
        sanitized = []
        for dep in obj_data.get('missing_dependencies', []):
            raw_ref = strip_na_identifier(dep.get('referenced') or dep.get('missing_object') or '')
            dep['referenced'] = _sanitize_str(raw_ref)
            dep['relation_type'] = _sanitize_str(dep.get('relation_type'))
            dep['line'] = _sanitize_str(dep.get('line'))
            dep['file'] = _sanitize_str(dep.get('file') or dep.get('file_name'))
            if dep['referenced'] != '-':
                sanitized.append(dep)
        obj_data['missing_dependencies'] = sanitized
        obj_data['has_missing_dependencies'] = bool(sanitized)


def _is_temporal_table(obj_name, obj_info, mem_info):
    """Return True if the object represents a temporary/temporal table.

    Detection checks (in order):
    1. ``code_unit`` contains ``TEMPORARY`` (e.g. ``CREATE TEMPORARY TABLE``).
    2. ``category`` / ``objectType`` explicitly indicates a temporary table.
    3. SQL Server ``#`` / ``##``-prefixed temp table names.
    """
    code_unit = (obj_info.get('code_unit') or '').upper()
    if 'TEMPORARY' in code_unit:
        return True
    category = (mem_info.get('category') or obj_info.get('category', '')).upper()
    if 'TEMPORARY' in category or category == 'TEMP TABLE':
        return True
    if _bare_object_name(obj_name).startswith('#'):
        return True
    return False


_BRACKET_GROUP = re.compile(r"\[([^\[\]]*)\]")
_QUOTED_PART = re.compile(r'"([^"]*)"')
_UNRESOLVED_OBJECT_TYPES = {"", "OTHER", "UNKNOWN"}
_READ_RELATIONS = {"read", "reads", "select"}
_WRITE_RELATIONS = {"write", "writes", "insert", "update", "merge", "delete", "truncate", "drop"}
_LOOKUP_RELATIONS = {"lookup", "lookups"}
_TABLE_REFERENCE_LABELS = {"read", "write", "lookup"}


def _identifier_parts(raw: str) -> list[str]:
    """Split a bracketed identifier, including a quoted name nested in one group."""
    parts: list[str] = []
    for group in _BRACKET_GROUP.findall(raw):
        quoted = [part for part in _QUOTED_PART.findall(group) if part]
        if quoted:
            parts.extend(quoted)
            continue
        piece = group.strip().strip('"')
        if piece:
            parts.append(piece)
    return parts


def _bare_object_name(raw: str) -> str:
    """Last identifier part. A quoted ``#temp`` is still a temp table."""
    parts = _identifier_parts(raw or "")
    if parts:
        return parts[-1]
    text = (raw or "").strip()
    return text.rsplit(".", 1)[-1].strip().strip('"')


def _display_schema_name(raw: str) -> str:
    """SCHEMA.NAME for a bracketed identifier. A single part stays unqualified."""
    text = (raw or "").strip()
    if "[" not in text:
        return text
    parts = _identifier_parts(text)
    if len(parts) >= 2:
        return f"{parts[-2]}.{parts[-1]}"
    if len(parts) == 1:
        return parts[0]
    return text


def _reference_label(relation_type: str) -> str:
    """Collapse a dependency verb to read, write, or lookup."""
    head = (relation_type or "").split("-", 1)[0].strip().lower()
    if not head or head == "-":
        return ""
    if head in _READ_RELATIONS:
        return "read"
    if head in _WRITE_RELATIONS:
        return "write"
    if head in _LOOKUP_RELATIONS:
        return "lookup"
    return head


def _origin_file(dependents: list) -> str:
    """Referencing file (or caller) plus its reference type, one entry per file."""
    grouped: dict[str, list[str]] = {}
    order: list[str] = []
    for dep in dependents:
        if not isinstance(dep, dict):
            continue
        place = (
            dep.get("file_name") or dep.get("file") or dep.get("caller") or ""
        ).strip()
        if not place or place == "-":
            continue
        label = _reference_label(dep.get("relation_type") or dep.get("relationType") or "")
        if place not in grouped:
            grouped[place] = []
            order.append(place)
        if label and label not in grouped[place]:
            grouped[place].append(label)
    parts = []
    for place in order:
        labels = grouped[place]
        if labels:
            parts.append(f"{place} ({', '.join(labels)})")
        else:
            parts.append(place)
    return ", ".join(parts)


def _infer_missing_type(current: str, labels: list[str]) -> str:
    """A read, write, or lookup of an unresolved object is a table."""
    normalized = (current or "").strip().upper()
    if normalized not in _UNRESOLVED_OBJECT_TYPES:
        return current
    if any(label in _TABLE_REFERENCE_LABELS for label in labels):
        return "TABLE"
    return current or "OTHER"


def _blank_file(value: str) -> bool:
    if is_na(value):
        return True
    return str(value).strip() == "-"


def _relation_labels(dependents: list) -> list[str]:
    labels: list[str] = []
    for dep in dependents:
        if not isinstance(dep, dict):
            continue
        label = _reference_label(dep.get("relation_type") or dep.get("relationType") or "")
        if label and label not in labels:
            labels.append(label)
    return labels


def _apply_missing_origin(row: dict, dependents_map: dict) -> None:
    """Fill a Missing row from the callers that reference it.

    The stub has no source file of its own. The caller's missing-dependency
    edge is what names the mapping and the reference type. The row keeps its
    raw name so dependency lookup still matches; the table shows SCHEMA.NAME.
    """
    dependents = dependents_map.get(row.get("name"), []) or []
    labels = _relation_labels(dependents)
    origin = _origin_file(dependents)
    if origin and _blank_file(row.get("file", "")):
        row["file"] = origin
    row["type"] = _infer_missing_type(row.get("type", ""), labels)
    row["display_name"] = _display_schema_name(row.get("name", ""))


def generate_html_report(waves_json, output_path=None, reports_dir=None, registry_dir=None):
    """Generate comprehensive HTML wave report with accurate analysis data.

    Missing objects are loaded from registry entries where ``isMissing: true``.
    Registry directory (--registry-dir) is required for missing dependencies analysis.
    """

    adapter = WavesJsonAdapter(Path(waves_json))

    toplevel_csv_path = None
    search_dirs = []
    if reports_dir:
        search_dirs.append(Path(reports_dir))
    waves_json_parent = Path(waves_json).parent
    search_dirs.extend([
        waves_json_parent,
        waves_json_parent.parent,
        waves_json_parent.parent / "Reports",
        waves_json_parent.parent / "out" / "Reports",
    ])
    for search_dir in search_dirs:
        if search_dir.exists():
            matches = list(search_dir.glob("TopLevelCodeUnits.*.csv"))
            if matches:
                toplevel_csv_path = matches[0]
                break

    if toplevel_csv_path is None:
        print("Error: TopLevelCodeUnits CSV not found in expected locations")
        return

    estimation_data = None
    grand_totals_data = None
    estimation_source = "Estimation Reports"

    reports_dir = toplevel_csv_path.parent
    estimation_files = find_estimation_reports(reports_dir)

    if "toplevel_estimation" in estimation_files:
        print(f"Found estimation report: {estimation_files['toplevel_estimation']}")
        estimation_data = load_toplevel_objects_estimation(estimation_files["toplevel_estimation"])
        estimation_source = f"Estimation Reports ({estimation_files['toplevel_estimation'].name})"
        grand_totals_data = load_estimation_grand_totals(estimation_files)

    severity_map = {}
    objects_data = load_toplevel_code_units(toplevel_csv_path)

    membership = adapter.partition_membership()
    graph_summary = adapter.graph_summary()
    cycles = adapter.cycles()
    excluded_edges = adapter.excluded_edges()
    for item in excluded_edges.get("top_undefined_referenced", []):
        item["object"] = strip_na_identifier(item.get("object", ""))
    missing_deps_data = adapter.missing_dependencies()
    _sanitize_missing_deps_data(missing_deps_data)
    dependency_counts = adapter.dependency_counts()

    if registry_dir:
        from snowconvert_reports.loaders.registry_loader import load_object_references_from_registry
        refs = load_object_references_from_registry(registry_dir)
        object_references = [
            {"caller": r.caller_full_name, "referenced": r.referenced_full_name}
            for r in refs
            if r.caller_full_name and r.referenced_full_name
        ]
    else:
        object_references = load_object_references_as_dicts(toplevel_csv_path.parent)
    for ref in object_references:
        ref["caller"] = strip_na_identifier(ref["caller"])
        ref["referenced"] = strip_na_identifier(ref["referenced"])
    missing_obj_refs = adapter.missing_object_refs()

    waves_data = defaultdict(list)
    for obj_name, mem_info in membership.items():
        partition = mem_info['partition']
        obj_info = objects_data.get(obj_name, {})

        category = mem_info.get('category', obj_info.get('category', 'Unknown'))
        if _is_temporal_table(obj_name, obj_info, mem_info):
            category = 'TEMPORAL TABLE'
        file_name = mem_info.get('file_name', obj_info.get('file_name', ''))
        technology = mem_info.get('technology', obj_info.get('technology', ''))
        conversion_status = mem_info.get('conversion_status', obj_info.get('conversion_status', 'Unknown'))
        subtype = mem_info.get('subtype', '')

        estimated_hours = estimate_hours_for_object(obj_name, objects_data, severity_map, estimation_data, conversion_status)

        obj_missing_deps = missing_deps_data.get(obj_name, {})
        missing_deps_list = obj_missing_deps.get('missing_dependencies', [])
        has_missing = obj_missing_deps.get('has_missing_dependencies', False)

        dep_counts = dependency_counts.get(obj_name, {})

        ewi_count = obj_info.get('ewi_count', 0) if obj_info else 0
        fdm_count = obj_info.get('fdm_count', 0) if obj_info else 0
        prf_count = obj_info.get('prf_count', 0) if obj_info else 0
        raw_severity = obj_info.get('highest_ewi_severity', '') if obj_info else ''
        highest_ewi_severity = '' if is_na(raw_severity) else raw_severity
        
        waves_data[partition].append({
            'name': obj_name,
            'category': category,
            'file_name': file_name,
            'has_missing_dependencies': has_missing,
            'conversion_status': conversion_status,
            'estimated_hours': estimated_hours,
            'is_root': mem_info['is_root'],
            'is_leaf': mem_info['is_leaf'],
            'is_picked_scc': mem_info.get('is_picked_scc', False),
            'missing_dependencies': missing_deps_list,
            'dependency_count': dep_counts.get('total_dependencies', 0),
            'dependent_count': dep_counts.get('total_dependents', 0),
            'technology': technology,
            'subtype': subtype,
            'partition_type': mem_info.get('partition_type', 'regular'),
            'ewi_count': ewi_count,
            'fdm_count': fdm_count,
            'prf_count': prf_count,
            'highest_ewi_severity': highest_ewi_severity,
            'issues': mem_info.get('issues') or [],
        })
    
    total_objects = len(membership)
    total_waves = len(waves_data)
    total_with_missing = sum(1 for obj_name in membership
                            if missing_deps_data.get(obj_name, {}).get('has_missing_dependencies', False))
    total_without_missing = total_objects - total_with_missing
    total_estimated_hours = sum(
        estimate_hours_for_object(
            obj_name,
            objects_data,
            severity_map,
            estimation_data,
            membership[obj_name].get('conversion_status', objects_data.get(obj_name, {}).get('conversion_status', 'Unknown'))
        )
        for obj_name in membership
    )

    success_count = sum(1 for obj_name in membership
                       if membership[obj_name].get('conversion_status', objects_data.get(obj_name, {}).get('conversion_status', '')) == 'Success')
    conversion_percentage = (success_count / total_objects * 100) if total_objects > 0 else 0

    total_objects_with_ewis = sum(1 for obj_name in membership
                                  if objects_data.get(obj_name, {}).get('ewi_count', 0) > 0)
    total_ewis = sum(objects_data.get(obj_name, {}).get('ewi_count', 0)
                     for obj_name in membership)

    # Calculate top dependencies/dependents for statistics section
    top_dependencies = sorted(
        [(obj, dependency_counts[obj]['total_dependencies'], membership[obj]['partition'])
         for obj in dependency_counts if obj in membership and dependency_counts[obj]['total_dependencies'] > 0],
        key=lambda x: x[1],
        reverse=True
    )[:5]

    top_dependents = sorted(
        [(obj, dependency_counts[obj]['total_dependents'], membership[obj]['partition'])
         for obj in dependency_counts if obj in membership and dependency_counts[obj]['total_dependents'] > 0],
        key=lambda x: x[1],
        reverse=True
    )[:5]

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    if output_path is None:
        output_path = Path(waves_json).parent / f'wave_report_{timestamp}.html'

    html_content = generate_html_content(
        graph_summary, cycles, excluded_edges, waves_data,
        total_objects, total_waves, total_with_missing, total_without_missing,
        total_estimated_hours, conversion_percentage, timestamp, estimation_source, grand_totals_data,
        object_references, missing_obj_refs, total_objects_with_ewis, total_ewis,
        top_dependencies, top_dependents, membership, dependency_counts,
        objects_data,
    )
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"HTML report generated: {output_path}")
    return output_path


def generate_html_content(graph_summary, cycles, excluded_edges, waves_data,
                         total_objects, total_waves, total_with_missing, total_without_missing,
                         total_estimated_hours, conversion_percentage, timestamp, estimation_source, grand_totals_data=None,
                         object_references=None, missing_obj_refs=None, total_objects_with_ewis=0, total_ewis=0,
                         top_dependencies=None, top_dependents=None,
                         membership=None, dependency_counts=None,
                         objects_data=None):
    """Generate complete HTML content."""

    if object_references is None:
        object_references = []

    if missing_obj_refs is None:
        missing_obj_refs = {
            'missing_objects': set(),
            'dependents': {},
            'details': [],
            'data_source': 'none',
            'warning': None
        }

    if top_dependencies is None:
        top_dependencies = []

    if top_dependents is None:
        top_dependents = []

    if membership is None:
        membership = {}

    if dependency_counts is None:
        dependency_counts = {}

    if objects_data is None:
        objects_data = {}

    # Build comprehensive objects list for All Objects table
    all_objects_data = []
    for wave_num, objects in waves_data.items():
        for obj in objects:
            obj_name = obj['name']
            dep_info = dependency_counts.get(obj_name, {})

            obj_type = obj.get('category', 'Unknown')
            if _is_temporal_table(obj_name, objects_data.get(obj_name, {}), membership.get(obj_name, {})):
                obj_type = 'TEMPORAL TABLE'

            all_objects_data.append({
                'name': obj_name,
                'type': obj_type,
                'file': obj.get('file_name', ''),
                'wave': wave_num,
                'dependencies': dep_info.get('total_dependencies', 0),
                'dependents': dep_info.get('total_dependents', 0),
                'is_missing': 'No',  # Objects in workload are not missing
                'conversion_status': obj.get('conversion_status', 'Unknown'),
                'has_missing_deps': obj.get('has_missing_dependencies', False),
                'missing_dependencies': obj.get('missing_dependencies', []),
                'issues': obj.get('issues') or [],
            })

    # A first-class missing stub has no source file. The caller's
    # missing-dependency edge names the mapping and the reference type.
    missing_objects = missing_obj_refs.get('missing_objects', set())
    dependents_map = missing_obj_refs.get('dependents', {})
    for row in all_objects_data:
        if row.get('conversion_status') == 'Missing':
            _apply_missing_origin(row, dependents_map)

    already_rendered = {obj['name'] for obj in all_objects_data}

    for missing_obj_name in missing_objects:
        if missing_obj_name in already_rendered:
            continue
        dependent_list = dependents_map.get(missing_obj_name, [])

        missing_type = 'Unknown'
        if _is_temporal_table(missing_obj_name, {}, {}):
            missing_type = 'TEMPORAL TABLE'

        row = {
            'name': missing_obj_name,
            'type': missing_type,
            'file': '',
            'wave': '-',  # Missing objects are not assigned to waves
            'dependencies': 0,  # Missing objects have no tracked dependencies
            'dependents': len(dependent_list),  # Number of objects that reference this
            'is_missing': 'Yes',
            'conversion_status': 'Missing',
            'has_missing_deps': False,  # Missing objects themselves don't have missing deps
            'issues': [],
            'missing_dependencies': [],
        }
        _apply_missing_origin(row, dependents_map)
        if _blank_file(row['file']):
            row['file'] = '-'
        all_objects_data.append(row)

    # Sort by wave, then by name (missing objects with wave='-' come last)
    all_objects_data.sort(key=lambda x: (float('inf') if x['wave'] == '-' else x['wave'], x['name']))

    # Count the card from the rows the All Objects table lists, so the two agree:
    # a missing temp table the waves JSON also emits as an object row is one row.
    temporal_table_count = sum(1 for obj in all_objects_data if obj['type'] == 'TEMPORAL TABLE')

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Wave Migration Report - {timestamp}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Helvetica', 'Arial', sans-serif;
            background-color: #EEF6F7;
            color: #333;
            line-height: 1.6;
            display: flex;
            min-height: 100vh;
        }}
        
        /* Side Navigation Panel */
        .side-nav {{
            position: fixed;
            left: 0;
            top: 0;
            width: 280px;
            height: 100vh;
            background: linear-gradient(180deg, #005C8F 0%, #003D5C 100%);
            padding: 20px 0;
            overflow-y: auto;
            box-shadow: 4px 0 12px rgba(0, 0, 0, 0.15);
            z-index: 1000;
        }}
        
        .side-nav-header {{
            padding: 0 20px 20px 20px;
            border-bottom: 2px solid rgba(182, 213, 243, 0.3);
            margin-bottom: 20px;
        }}
        
        .side-nav-title {{
            color: #FCFFFE;
            font-size: 1.3em;
            font-weight: 700;
            margin-bottom: 5px;
        }}
        
        .side-nav-subtitle {{
            color: #CFECEF;
            font-size: 0.85em;
        }}
        
        .side-nav-section {{
            margin-bottom: 8px;
        }}
        
        .side-nav-link {{
            display: block;
            padding: 12px 20px;
            color: #CFECEF;
            text-decoration: none;
            font-size: 0.9em;
            transition: all 0.2s;
            border-left: 3px solid transparent;
        }}
        
        .side-nav-link:hover {{
            background-color: rgba(182, 213, 243, 0.15);
            color: #FCFFFE;
            border-left-color: #B6D5F3;
        }}
        
        .side-nav-link.active {{
            background-color: rgba(182, 213, 243, 0.25);
            color: #FCFFFE;
            border-left-color: #FCFFFE;
            font-weight: 600;
        }}
        
        .side-nav-subsection {{
            padding-left: 40px;
        }}
        
        .side-nav-subsection .side-nav-link {{
            font-size: 0.85em;
            padding: 8px 20px;
        }}
        
        /* Main Content Area */
        .main-content {{
            margin-left: 280px;
            flex: 1;
            padding: 20px;
        }}
        
        .container {{
            max-width: 1600px;
            margin: 0 auto;
            background-color: #FCFFFE;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            padding: 40px;
        }}
        
        /* Scroll behavior */
        html {{
            scroll-behavior: smooth;
            scroll-padding-top: 20px;
        }}
        
        h1 {{
            color: #005C8F;
            font-size: 2.2em;
            margin-bottom: 10px;
            border-bottom: 3px solid #B6D5F3;
            padding-bottom: 15px;
        }}
        
        h2 {{
            color: #005C8F;
            font-size: 1.6em;
            margin-top: 40px;
            margin-bottom: 20px;
            border-left: 4px solid #B6D5F3;
            padding-left: 15px;
            scroll-margin-top: 20px;
        }}
        
        h3 {{
            color: #005C8F;
            font-size: 1.2em;
            margin-top: 25px;
            margin-bottom: 15px;
        }}

        .info-tooltip:hover .tooltip-content {{
            display: block !important;
            visibility: visible !important;
            opacity: 1 !important;
        }}

        .tooltip-content {{
            display: none;
            visibility: hidden;
            opacity: 0;
            transition: opacity 0.2s, visibility 0.2s;
        }}

        .info-tooltip svg {{
            transition: all 0.2s;
        }}
        .info-tooltip:hover svg {{
            transform: scale(1.1);
        }}
        
        .metric-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
            margin: 16px 0;
        }}
        
        .metric-card {{
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            border: 1px solid #E2E8F0;
            transition: all 0.2s;
            cursor: help;
            position: relative;
        }}

        /* Metric-card tooltip is rendered via JS near cursor */
        .metric-card[data-tooltip]::before {{
            content: none;
            opacity: 0;
            pointer-events: none;
        }}

        .metric-card[data-tooltip]::after {{
            content: none;
            opacity: 0;
            pointer-events: none;
        }}
        
        .metric-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.15);
            border-color: rgb(41, 181, 232);
        }}

        .metric-tooltip-cursor {{
            position: fixed;
            background: rgba(255, 255, 255, 0.78);
            color: #102E46;
            border: 1px solid rgba(16, 46, 70, 0.10);
            border-radius: 8px;
            padding: 8px 10px;
            font-size: 0.875rem;
            line-height: 1.4;
            max-width: 300px;
            z-index: 10000;
            box-shadow: 0 8px 24px rgba(16, 46, 70, 0.12);
            backdrop-filter: blur(2px);
            pointer-events: none;
        }}
        
        .metric-card .metric-label {{
            font-size: 0.85rem;
            font-weight: 600;
            color: #64748B;
            text-transform: uppercase;
            margin-bottom: 0.25rem;
            line-height: 1.2;
        }}
        
        .metric-card .metric-value {{
            font-size: 2rem;
            font-weight: 800;
            color: #102E46;
            margin-top: 4px;
        }}
        
        .metric-card .metric-description {{
            font-size: 0.875rem;
            color: #8A999E;
            margin-top: 0.5rem;
        }}

        .info-icon {{
            cursor: help;
            color: #71D3DC;
            font-size: 0.9em;
            margin-left: 4px;
            display: inline-block;
        }}

        .info-icon:hover {{
            color: #005C8F;
        }}

        /* JS-driven tooltip appended to body */
        .info-tooltip {{
            position: fixed;
            background: #102E46;
            color: white;
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 0.85rem;
            white-space: normal;
            max-width: 280px;
            z-index: 10000;
            box-shadow: 0 4px 12px rgba(0,0,0,0.25);
            pointer-events: none;
            line-height: 1.4;
            font-weight: 400;
            text-align: left;
        }}

        .info-tooltip::after {{
            content: '';
            position: absolute;
            top: 100%;
            left: 50%;
            transform: translateX(-50%);
            border: 6px solid transparent;
            border-top-color: #102E46;
        }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin: 25px 0;
        }}
        
        .stat-card {{
            background: linear-gradient(135deg, #CFECEF 0%, #B6D5F3 100%);
            border-radius: 8px;
            padding: 25px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        
        .stat-card:hover {{
            transform: translateY(-3px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }}
        
        .stat-label {{
            font-size: 0.9em;
            color: #005C8F;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 10px;
        }}
        
        .stat-value {{
            font-size: 2.2em;
            font-weight: 700;
            color: #005C8F;
        }}
        
        .stat-value.large {{
            font-size: 2.8em;
        }}
        
        .filters {{
            background-color: #EEF6F7;
            border-radius: 8px;
            padding: 15px;
            margin: 20px 0;
            border: 1px solid #CFECEF;
        }}
        
        .filter-group {{
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            align-items: flex-start;
        }}
        
        .filter-item {{
            display: flex;
            flex-direction: column;
            gap: 5px;
            min-width: 180px;
        }}
        
        .filter-item-input-wrapper {{
            display: flex;
            flex-direction: column;
            gap: 6px;
        }}
        
        .filter-item label {{
            font-size: 0.85em;
            font-weight: 600;
            color: #005C8F;
        }}
        
        .filter-item input,
        .filter-item select {{
            padding: 8px 12px;
            border: 1px solid #B6D5F3;
            border-radius: 4px;
            font-size: 0.9em;
            background-color: #FCFFFE;
            transition: border-color 0.2s;
        }}
        
        .filter-item input:focus,
        .filter-item select:focus {{
            outline: none;
            border-color: #005C8F;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 25px 0;
            background-color: #FFFFFF;
            border-radius: 6px;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
        }}

        thead {{
            background-color: #F9FAFB;
            color: #374151;
        }}

        th {{
            padding: 8px 10px;
            text-align: left;
            font-weight: 600;
            font-size: 0.75rem;
            cursor: pointer;
            user-select: none;
            transition: background-color 0.15s;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #6B7280;
        }}

        th:hover {{
            background-color: #F3F4F6;
        }}

        td {{
            padding: 8px 10px;
            border-bottom: 1px solid #F3F4F6;
            font-size: 0.8125rem;
            color: #374151;
        }}

        tbody tr:hover {{
            background-color: #F9FAFB;
        }}

        tbody tr:last-child td {{
            border-bottom: none;
        }}
        
        .object-row {{
            cursor: pointer;
            transition: background-color 0.1s;
        }}

        .object-row:hover {{
            background-color: #F9FAFB !important;
        }}
        
        .picked-scc-row {{
            background-color: #FFFACD !important;
            border-left: 4px solid #FFD700 !important;
        }}
        
        .picked-scc-row:hover {{
            background-color: #FFF4B0 !important;
        }}
        
        .expandable-row {{
            display: none;
            background-color: #F8FBFC;
        }}
        
        .expandable-row.show {{
            display: table-row;
        }}
        
        .expandable-content {{
            padding: 15px 20px;
            max-height: 300px;
            overflow-y: auto;
            border-left: 4px solid #005C8F;
            background-color: #FCFFFE;
            border-radius: 4px;
        }}
        
        .expandable-content h4 {{
            color: #005C8F;
            margin-bottom: 10px;
            font-size: 0.95em;
        }}
        
        .missing-dep-item {{
            padding: 8px 12px;
            margin: 5px 0;
            background-color: #FFF3CD;
            border-left: 3px solid #856404;
            border-radius: 3px;
            font-size: 0.85em;
        }}
        
        .missing-dep-item strong {{
            color: #856404;
        }}
        
        .no-info-text {{
            color: #666;
            font-style: italic;
            padding: 10px;
        }}
        
        .badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 0.7rem;
            font-weight: 500;
        }}

        .badge-success {{
            background-color: #F0FDF4;
            color: #166534;
        }}

        .badge-warning {{
            background-color: #FFFBEB;
            color: #92400E;
        }}

        .badge-danger {{
            background-color: #FEF2F2;
            color: #991B1B;
        }}

        .badge-info {{
            background-color: #F3F4F6;
            color: #374151;
        }}
        
        .modal-overlay {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 92, 143, 0.4);
            z-index: 1000;
            justify-content: center;
            align-items: center;
            backdrop-filter: blur(3px);
        }}
        
        .modal-overlay.show {{
            display: flex;
            animation: fadeIn 0.3s ease-out;
        }}
        
        .modal-content {{
            background-color: #FCFFFE;
            border-radius: 12px;
            width: 95%;
            max-width: 1400px;
            max-height: 90vh;
            display: flex;
            flex-direction: column;
            box-shadow: 0 10px 40px rgba(0, 92, 143, 0.3);
            animation: slideUp 0.3s ease-out;
            border: 3px solid #005C8F;
        }}
        
        .modal-header {{
            padding: 20px 25px;
            background: linear-gradient(135deg, #005C8F 0%, #0074A8 100%);
            border-radius: 9px 9px 0 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 3px solid #CFECEF;
        }}
        
        .modal-title {{
            display: flex;
            align-items: center;
            gap: 15px;
        }}
        
        .modal-wave-label {{
            font-weight: 700;
            color: #FCFFFE;
            font-size: 1.3em;
            text-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
        }}
        
        .modal-wave-badge {{
            background-color: #FDF9DC;
            color: #005C8F;
            padding: 6px 16px;
            border-radius: 18px;
            font-size: 0.9em;
            font-weight: 700;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
        }}
        
        .modal-nav-btn {{
            background-color: transparent;
            border: 1px solid #FCFFFE;
            color: #FCFFFE;
            font-size: 0.9em;
            cursor: pointer;
            padding: 4px 10px;
            border-radius: 4px;
            font-weight: 600;
            transition: all 0.2s;
        }}
        
        .modal-nav-btn:hover:not(:disabled) {{
            background-color: #FCFFFE;
            color: #005C8F;
        }}
        
        .modal-nav-btn:disabled {{
            opacity: 0.3;
            cursor: not-allowed;
        }}
        
        .modal-close {{
            background-color: transparent;
            border: 1px solid #FCFFFE;
            color: #FCFFFE;
            font-size: 1.1em;
            cursor: pointer;
            padding: 4px 12px;
            border-radius: 4px;
            font-weight: 600;
            transition: all 0.2s;
        }}
        
        .modal-close:hover {{
            background-color: #FCFFFE;
            color: #005C8F;
        }}
        
        .modal-body {{
            padding: 25px;
            overflow-y: auto;
            overflow-x: auto;
            flex: 1;
        }}
        
        .modal-body table {{
            width: 100%;
            min-width: 800px;
            table-layout: fixed;
        }}
        
        .modal-body table th,
        .modal-body table td {{
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        
        .modal-body table th:nth-child(1),
        .modal-body table td:nth-child(1) {{
            width: 8%;
        }}
        
        .modal-body table th:nth-child(2),
        .modal-body table td:nth-child(2) {{
            width: 10%;
        }}
        
        .modal-body table th:nth-child(3),
        .modal-body table td:nth-child(3) {{
            width: 22%;
        }}
        
        .modal-body table th:nth-child(4),
        .modal-body table td:nth-child(4) {{
            width: 20%;
        }}
        
        .modal-body table th:nth-child(5),
        .modal-body table td:nth-child(5) {{
            width: 8%;
        }}
        
        .modal-body table th:nth-child(6),
        .modal-body table td:nth-child(6) {{
            width: 14%;
        }}
        
        .modal-body table th:nth-child(7),
        .modal-body table td:nth-child(7) {{
            width: 13%;
        }}
        
        @keyframes fadeIn {{
            from {{
                opacity: 0;
            }}
            to {{
                opacity: 1;
            }}
        }}
        
        @keyframes slideUp {{
            from {{
                transform: translateY(50px);
                opacity: 0;
            }}
            to {{
                transform: translateY(0);
                opacity: 1;
            }}
        }}
        
        .wave-dropdown {{
            background-color: #FCFFFE;
            border: 2px solid #B6D5F3;
            border-radius: 8px;
            margin-bottom: 16px;
            overflow: hidden;
            transition: all 0.3s;
            box-shadow: 0 2px 6px rgba(0, 92, 143, 0.1);
        }}
        
        .wave-dropdown:hover {{
            box-shadow: 0 4px 12px rgba(0, 92, 143, 0.15);
            border-color: #005C8F;
        }}
        
        .wave-header {{
            padding: 16px 20px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: linear-gradient(135deg, #005C8F 0%, #0074A8 100%);
            transition: all 0.2s;
            position: relative;
        }}
        
        .wave-header:hover {{
            background: linear-gradient(135deg, #004570 0%, #005C8F 100%);
        }}
        
        .wave-header-title {{
            display: flex;
            align-items: center;
            gap: 15px;
        }}
        
        .wave-label {{
            font-weight: 700;
            color: #FCFFFE;
            font-size: 1.1em;
            text-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
        }}
        
        .wave-badge {{
            background-color: #FDF9DC;
            color: #005C8F;
            padding: 5px 14px;
            border-radius: 16px;
            font-size: 0.85em;
            font-weight: 700;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
        }}
        
        
        @keyframes slideDown {{
            from {{
                opacity: 0;
                max-height: 0;
            }}
            to {{
                opacity: 1;
                max-height: 5000px;
            }}
        }}
        
        .object-table {{
            width: 100%;
            margin-top: 10px;
        }}

        .object-table th {{
            background-color: #F9FAFB;
            color: #6B7280;
            font-size: 0.7rem;
        }}
        
        .scrollable-table-container {{
            max-height: 350px;
            overflow-y: auto;
            overflow-x: hidden;
            border: 1px solid #B6D5F3;
            border-top: none;
            border-radius: 0 0 6px 6px;
            margin: 0 0 20px 0;
            position: relative;
        }}
        
        
        .filter-buttons {{
            display: flex;
            gap: 8px;
            margin-top: 10px;
        }}
        
        .filter-btn {{
            padding: 8px 16px;
            border: 1px solid #B6D5F3;
            background-color: #005C8F;
            color: #FCFFFE;
            border-radius: 4px;
            cursor: pointer;
            font-weight: 600;
            font-size: 0.85em;
            transition: all 0.2s;
        }}
        
        .filter-btn:hover {{
            background-color: #003D5C;
        }}
        
        .filter-btn.secondary {{
            background-color: #FCFFFE;
            color: #005C8F;
        }}
        
        .filter-btn.secondary:hover {{
            background-color: #EEF6F7;
        }}
        
        .copy-icon {{
            cursor: pointer;
            display: inline-block;
            margin-left: 6px;
            padding: 2px 6px;
            background: #EEF6F7;
            border-radius: 3px;
            font-size: 0.85em;
            color: #005C8F;
            transition: all 0.2s;
            vertical-align: middle;
        }}
        
        .copy-icon:hover {{
            background: #B6D5F3;
            transform: scale(1.1);
        }}
        
        .copy-icon:active {{
            transform: scale(0.95);
        }}
        
        .copy-success {{
            display: inline-block;
            margin-left: 6px;
            padding: 2px 6px;
            background: #D4EDDA;
            color: #155724;
            border-radius: 3px;
            font-size: 0.75em;
            animation: fadeOut 2s forwards;
        }}
        
        @keyframes fadeOut {{
            0% {{ opacity: 1; }}
            70% {{ opacity: 1; }}
            100% {{ opacity: 0; }}
        }}
        
        .cycle-item {{
            background-color: #FFF3CD;
            border-left: 3px solid #FFC107;
            padding: 15px;
            margin: 10px 0;
            border-radius: 4px;
        }}
        
        .cycle-item h4 {{
            color: #856404;
            margin-bottom: 8px;
        }}
        
        .cycle-nodes {{
            font-size: 0.9em;
            color: #666;
            margin-top: 8px;
            max-height: 200px;
            overflow-y: auto;
            padding: 10px;
            background-color: #f8f9fa;
            border-radius: 4px;
        }}
        
        .cycle-nodes ul {{
            list-style-type: none;
            padding-left: 0;
            margin: 0;
        }}
        
        .cycle-nodes li {{
            padding: 4px 0;
            border-bottom: 1px solid #e0e0e0;
        }}
        
        .cycle-nodes li:last-child {{
            border-bottom: none;
        }}
        
        .info-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }}
        
        .info-item {{
            background-color: #EEF6F7;
            padding: 15px;
            border-radius: 6px;
            border-left: 3px solid #B6D5F3;
        }}
        
        .info-item strong {{
            color: #005C8F;
            display: block;
            margin-bottom: 5px;
        }}
        
        /* Blocked Objects Section Styles */
        .blocked-objects-section {{
            background: #FFF8E1;
            border: 2px solid #FFAB00;
            border-radius: 8px;
            padding: 20px;
            margin: 30px 0;
            max-height: 400px;
        }}
        
        .blocked-section-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            position: sticky;
            top: 0;
            background: #FFF8E1;
            z-index: 10;
            padding-bottom: 10px;
        }}
        
        .blocked-section-title {{
            color: #005C8F;
            font-size: 1.6em;
            margin: 0;
            border-left: 4px solid #B6D5F3;
            padding-left: 15px;
        }}
        
        .blocked-objects-list-container {{
            max-height: 300px;
            overflow-y: auto;
            padding-right: 10px;
        }}
        
        .blocked-objects-list-container::-webkit-scrollbar {{
            width: 8px;
        }}
        
        .blocked-objects-list-container::-webkit-scrollbar-track {{
            background: #f1f1f1;
            border-radius: 4px;
        }}
        
        .blocked-objects-list-container::-webkit-scrollbar-thumb {{
            background: #FFAB00;
            border-radius: 4px;
        }}
        
        .blocked-objects-list-container::-webkit-scrollbar-thumb:hover {{
            background: #FF9800;
        }}
        
        .blocked-filter-toggle {{
            display: flex;
            align-items: center;
            gap: 10px;
            background: white;
            padding: 10px 15px;
            border-radius: 6px;
            border: 1px solid #ddd;
        }}
        
        .blocked-filter-toggle label {{
            font-size: 0.9em;
            color: #333;
            cursor: pointer;
            margin: 0;
        }}
        
        .blocked-filter-toggle input[type="checkbox"] {{
            cursor: pointer;
            width: 18px;
            height: 18px;
        }}
        
        .blocked-object-card {{
            background: white;
            border: 1px solid #FFAB00;
            border-radius: 6px;
            margin-bottom: 10px;
            overflow: hidden;
        }}
        
        .blocked-object-header {{
            background: linear-gradient(135deg, #FFAB00 0%, #FFD54F 100%);
            color: #333;
            padding: 12px 15px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-weight: 600;
        }}
        
        .blocked-object-header:hover {{
            background: linear-gradient(135deg, #FF9800 0%, #FFAB00 100%);
        }}
        
        .blocked-dependents-list {{
            padding: 15px;
            display: none;
        }}
        
        .blocked-dependents-list.active {{
            display: block;
        }}
        
        .blocked-dependent-item {{
            background: #F5F5F5;
            border-left: 3px solid #005C8F;
            padding: 10px 12px;
            margin-bottom: 8px;
            border-radius: 4px;
        }}
        
        .blocked-dependent-name {{
            font-weight: 600;
            color: #005C8F;
            margin-bottom: 4px;
        }}
        
        .blocked-dependent-wave {{
            display: inline-block;
            background: #005C8F;
            color: white;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 0.85em;
            margin-right: 8px;
        }}
        
        .blocked-no-objects {{
            background: #E8F5E9;
            border: 2px solid #4CAF50;
            border-radius: 6px;
            padding: 20px;
            text-align: center;
            color: #2E7D32;
            font-size: 1.1em;
        }}

        /* Improved Table Styles */
        .object-table {{
            table-layout: fixed;
            width: 100%;
        }}

        /* Keep header visible while scrolling table body */
        .object-table thead,
        .object-table tbody tr {{
            display: table;
            width: 100%;
            table-layout: fixed;
        }}

        .object-table tbody {{
            display: block;
            max-height: 560px;
            overflow-y: auto;
            overflow-x: hidden;
        }}

        .object-table thead th {{
            background-color: rgb(16, 46, 70) !important;
            color: #FFFFFF !important;
            position: sticky;
            top: 0;
            z-index: 100;
            padding: 6px 8px !important;
            font-size: 0.6875rem !important;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            border-bottom: 1px solid #E5E7EB;
            white-space: nowrap !important;
            overflow: hidden;
            text-overflow: ellipsis;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        .object-table thead th > span {{
            display: inline;
            vertical-align: middle;
        }}

        /* All columns are now sortable - filters moved to search bar */
        .object-table thead th:hover {{
            background-color: rgb(14, 40, 61) !important;
        }}

        .object-table tbody td {{
            padding: 6px 8px;
            font-size: 0.8rem;
            border-bottom: 1px solid #F3F4F6;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            color: #374151;
            font-weight: 400;
        }}

        .object-table tbody tr {{
            transition: background-color 0.1s ease;
        }}

        .object-table tbody tr:hover {{
            background-color: #F9FAFB;
        }}

        .object-table th.col-checkbox,
        .object-table td:nth-child(1) {{
            padding-left: 0 !important;
            padding-right: 0 !important;
        }}

        .object-table #selectAllCheckbox,
        .object-table .row-checkbox {{
            display: block;
            margin: 0 auto;
        }}

        /* Tooltips for All Objects cells are rendered by JS near cursor */
        .object-table td {{
            position: relative;
        }}

        .object-table [data-tooltip] {{
            position: relative;
            cursor: default;
        }}

        .object-table [data-tooltip]:hover::after,
        .object-table [data-tooltip]:hover::before {{
            content: none;
        }}

        /* Column resizer */
        .column-resizer {{
            position: absolute;
            top: 0;
            right: 0;
            width: 8px;
            height: 100%;
            cursor: col-resize;
            user-select: none;
            z-index: 100;
        }}

        .column-resizer:hover {{
            background-color: rgba(41, 181, 232, 0.3);
            border-right: 2px solid #29B5E8;
        }}

        .object-table thead th {{
            position: sticky;
            top: 0;
            z-index: 100;
        }}

        /* Ensure column resizer is on top of dropdown wrapper */

        /* Column widths prioritize object and file names */
        .col-checkbox {{ width: 40px; min-width: 40px; max-width: 40px; text-align: center; }}
        .col-object-name {{ width: 260px; min-width: 220px; text-align: left; }}
        .col-type {{ width: 80px; min-width: 70px; }}
        .col-file {{ width: 240px; min-width: 200px; text-align: left; }}
        .col-wave {{ width: 60px; min-width: 55px; text-align: center; }}
        .col-deps {{ width: 88px; min-width: 70px; text-align: center; }}
        .col-dependents {{ width: 88px; min-width: 70px; text-align: center; }}
        .col-status {{ width: 96px; min-width: 80px; }}
        .col-missing {{ width: 96px; min-width: 80px; text-align: center; }}

        .object-table td:nth-child(1) {{ width: 40px; min-width: 40px; max-width: 40px; text-align: center; }}
        .object-table td:nth-child(2) {{ width: 260px; min-width: 220px; text-align: left; }}
        .object-table td:nth-child(3) {{ width: 80px; min-width: 70px; text-align: left; }}
        .object-table td:nth-child(4) {{ width: 240px; min-width: 200px; text-align: left; }}
        .object-table td:nth-child(5) {{ width: 60px; min-width: 55px; text-align: center; }}
        .object-table td:nth-child(6) {{ width: 88px; min-width: 70px; text-align: center; }}
        .object-table td:nth-child(7) {{ width: 88px; min-width: 70px; text-align: center; }}
        .object-table td:nth-child(8) {{ width: 96px; min-width: 80px; text-align: left; }}
        .object-table td:nth-child(9) {{ width: 96px; min-width: 80px; text-align: center; }}

        /* Sort arrow styling - appears on the right */
        .object-table thead th {{
            position: sticky;
            top: 0;
            z-index: 100;
        }}

        .object-table thead th.sortable {{
            padding-right: 20px !important;
        }}

        .object-table thead th .sort-arrow {{
            position: absolute;
            right: 6px;
            top: 50%;
            transform: translateY(-50%);
            font-size: 9px;
            color: rgba(255, 255, 255, 0.8);
            opacity: 1;
            transition: color 0.2s;
            display: inline-flex;
            align-items: center;
            padding-left: 2px;
        }}

        .object-table thead th .sort-arrow sub {{
            font-size: 7px;
            margin-left: 1px;
            vertical-align: sub;
        }}

        .object-table thead th.sorted .sort-arrow {{
            color: #FFFFFF;
        }}

        /* Tooltip styling */
        .tooltip {{
            position: relative;
            display: inline-block;
        }}

        .tooltip .tooltiptext {{
            visibility: hidden;
            background-color: #1F2937;
            color: #fff;
            text-align: left;
            border-radius: 4px;
            padding: 6px 10px;
            position: absolute;
            z-index: 1000;
            bottom: 125%;
            left: 50%;
            transform: translateX(-50%);
            white-space: nowrap;
            font-size: 0.75em;
            opacity: 0;
            transition: opacity 0.2s;
            max-width: 400px;
            word-wrap: break-word;
            white-space: normal;
        }}

        .tooltip:hover .tooltiptext {{
            visibility: visible;
            opacity: 1;
        }}

        .tooltip .tooltiptext::after {{
            content: "";
            position: absolute;
            top: 100%;
            left: 50%;
            margin-left: -5px;
            border-width: 5px;
            border-style: solid;
            border-color: #1F2937 transparent transparent transparent;
        }}
    </style>
</head>
<body>
    <!-- Side Navigation Panel -->
    <nav class="side-nav" id="sideNav">
        <div class="side-nav-header">
            <div class="side-nav-title">Dependencies Report</div>
            <div class="side-nav-subtitle">Migration Analysis</div>
        </div>

        <div class="side-nav-section">
            <a href="#overview" class="side-nav-link">Overview</a>
        </div>

        <div class="side-nav-section">
            <a href="#dependency-stats" class="side-nav-link">Top Objects by Dependency Impact</a>
        </div>

        <div class="side-nav-section">
            <a href="#all-objects" class="side-nav-link">All Objects</a>
        </div>

    </nav>
    
    <!-- Main Content Area -->
    <div class="main-content">
        <div class="container">
            <div style="margin-bottom: 32px;">
                <h1 id="overview" style="font-size: 1.875rem; font-weight: 800; color: #102E46; margin-bottom: 12px;">Dependencies Report</h1>
                <p style="color: #64748B; font-size: 1.1rem;">Comprehensive dependency analysis with objects table and statistics.</p>
            </div>

            <div class="metric-grid">
                <div class="metric-card" data-tooltip="{WAVE_PLAN_TOTAL_SCOPE}">
                    <div class="metric-label">
                        Total Objects to Migrate
                    </div>
                    <div class="metric-value">{total_objects}</div>
                </div>
                <div class="metric-card" data-tooltip="Number of sequential deployment waves based on dependency analysis">
                    <div class="metric-label">
                        Total Waves
                    </div>
                    <div class="metric-value">{total_waves}</div>
                </div>
                <div class="metric-card" data-tooltip="Objects that reference external dependencies not found in the migration scope">
                    <div class="metric-label">
                        Objects With Missing Dependencies
                    </div>
                    <div class="metric-value">{total_with_missing}</div>
                </div>
                <div class="metric-card" data-tooltip="Number of circular dependency chains detected in the codebase">
                    <div class="metric-label">
                        Cyclic Dependencies
                    </div>
                    <div class="metric-value">{graph_summary.get('cyclic_dependencies', 0)}</div>
                </div>
                <div class="metric-card" data-tooltip="Temporary or temporal tables detected in the migration scope. These may require special handling during migration">
                    <div class="metric-label">
                        Temporal Tables
                    </div>
                    <div class="metric-value">{temporal_table_count}</div>
                </div>
            </div>

'''

    # Build Dependency Statistics Section HTML (add right after metric cards)
    dependency_stats_html = '''
        <details open style="margin: 16px 0; background: #F8FBFC; border: 1px solid #B6D5F3; border-radius: 8px; padding: 4px 12px;" id="dependency-impact-details">
            <summary id="dependency-stats" style="cursor: pointer; font-weight: 700; color: #102E46; font-size: 1em; padding: 8px 0;">
                Top Objects by Dependency Impact
            </summary>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 4px; padding-bottom: 12px;">
                <div>
                    <h3 style="font-size: 1em; font-weight: 600; color: #005C8F; margin-top: 0; margin-bottom: 8px;">Top 5 Objects with Most Dependencies</h3>
                    <table style="font-size: 1.05em; width: 100%; table-layout: fixed;">
                        <thead style="background: rgb(16, 46, 70); color: #FFFFFF;">
                            <tr>
                                <th style="width: 72%; background: rgb(16, 46, 70); color: #FFFFFF;">Object Name</th>
                                <th style="width: 14%; text-align: center; background: rgb(16, 46, 70); color: #FFFFFF;">Count</th>
                                <th style="width: 14%; text-align: center; background: rgb(16, 46, 70); color: #FFFFFF;">Wave</th>
                            </tr>
                        </thead>
                        <tbody>
'''

    if top_dependencies:
        for obj_name, count, wave in top_dependencies:
            obj_name_attr = str(obj_name).replace('&', '&amp;').replace('"', '&quot;').replace("'", '&#39;').replace('<', '&lt;').replace('>', '&gt;')
            dependency_stats_html += f'''
                            <tr class="top-impact-row" data-object-name="{obj_name_attr}" style="cursor: pointer;">
                                <td><span class="top-impact-object" data-tooltip="{obj_name_attr}" style="display: block; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 1em; color: #111827; font-family: inherit;">{obj_name}</span></td>
                                <td style="text-align: center;"><strong>{count}</strong></td>
                                <td style="text-align: center;">{wave}</td>
                            </tr>
'''
    else:
        dependency_stats_html += '''
                            <tr>
                                <td colspan="3" style="text-align: center; color: #999; font-style: italic;">No dependency data available</td>
                            </tr>
'''

    dependency_stats_html += '''
                        </tbody>
                    </table>
                </div>

                <div>
                    <h3 style="font-size: 1em; font-weight: 600; color: #005C8F; margin-top: 0; margin-bottom: 8px;">Top 5 Objects with Most Dependents</h3>
                    <table style="font-size: 1.05em; width: 100%; table-layout: fixed;">
                        <thead style="background: rgb(16, 46, 70); color: #FFFFFF;">
                            <tr>
                                <th style="width: 72%; background: rgb(16, 46, 70); color: #FFFFFF;">Object Name</th>
                                <th style="width: 14%; text-align: center; background: rgb(16, 46, 70); color: #FFFFFF;">Count</th>
                                <th style="width: 14%; text-align: center; background: rgb(16, 46, 70); color: #FFFFFF;">Wave</th>
                            </tr>
                        </thead>
                        <tbody>
'''

    if top_dependents:
        # A Missing row shows SCHEMA.NAME, like the dashboard; the raw name stays the lookup key.
        display_names = {row['name']: row['display_name'] for row in all_objects_data if row.get('display_name')}
        for obj_name, count, wave in top_dependents:
            obj_name_attr = str(obj_name).replace('&', '&amp;').replace('"', '&quot;').replace("'", '&#39;').replace('<', '&lt;').replace('>', '&gt;')
            shown_name = str(display_names.get(obj_name, obj_name)).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            dependency_stats_html += f'''
                            <tr class="top-impact-row" data-object-name="{obj_name_attr}" style="cursor: pointer;">
                                <td><span class="top-impact-object" data-tooltip="{obj_name_attr}" style="display: block; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 1em; color: #111827; font-family: inherit;">{shown_name}</span></td>
                                <td style="text-align: center;"><strong>{count}</strong></td>
                                <td style="text-align: center;">{wave}</td>
                            </tr>
'''
    else:
        dependency_stats_html += '''
                            <tr>
                                <td colspan="3" style="text-align: center; color: #999; font-style: italic;">No dependency data available</td>
                            </tr>
'''

    dependency_stats_html += '''
                        </tbody>
                    </table>
                </div>
            </div>
        </details>
    '''

    html += dependency_stats_html

    # Circular Dependencies warning — above Dependency Information
    cycle_count = len(cycles) if cycles else 0
    if cycle_count > 0:
        html += f'''
            <details style="margin: 16px 0; background: #FFF8E1; border: 1px solid #FFD54F; border-radius: 6px; padding: 4px 12px;">
                <summary style="cursor: pointer; font-weight: 600; color: #856404; font-size: 0.95em; padding: 8px 0;">&#9888; {cycle_count} Circular {"Dependency" if cycle_count == 1 else "Dependencies"} Detected</summary>
                <div style="margin-top: 8px; padding-bottom: 8px;">
'''
        for cycle in cycles:
            nodes_list = '<ul style="margin-top: 4px; margin-bottom: 4px;">'
            for node in cycle['nodes']:
                nodes_list += f'<li>{node}</li>'
            nodes_list += '</ul>'
            html += f'''
                    <div class="cycle-item">
                        <h4>Cycle {cycle['cycle_num']}: {cycle['node_count']} objects</h4>
                        <div class="cycle-nodes">{nodes_list}</div>
                    </div>
'''
        html += '''
                </div>
            </details>
'''


    # Add Top Undefined Referenced Objects as collapsed section
    top_undefined = excluded_edges.get('top_undefined_referenced', [])
    if top_undefined:
        html += '''
            <details style="margin: 16px 0; background: #F8FBFC; border: 1px solid #B6D5F3; border-radius: 8px; padding: 4px 12px;">
                <summary style="cursor: pointer; font-weight: 700; color: #102E46; font-size: 1em; padding: 8px 0;">Top Frequently Referenced External Objects</summary>
                <div style="margin-top: 10px;">
                    <p style="margin-bottom: 12px; color: #666; font-size: 0.9em;">Objects frequently referenced in the code but not defined in the migration scope. These may include temporary tables (temp, #temp, ##temp), staging tables, or dynamically generated objects.</p>
                    <table style="width: 100%; table-layout: fixed;">
                        <thead style="background: rgb(16, 46, 70); color: #FFFFFF;">
                            <tr>
                                <th style="width: 78%; background: rgb(16, 46, 70); color: #FFFFFF;">Object Name</th>
                                <th style="width: 22%; background: rgb(16, 46, 70); color: #FFFFFF;">Reference Count</th>
                            </tr>
                        </thead>
                        <tbody>
'''
        for obj in top_undefined:
            obj_name_attr = str(obj['object']).replace('&', '&amp;').replace('"', '&quot;').replace("'", '&#39;').replace('<', '&lt;').replace('>', '&gt;')
            html += f'''
                            <tr>
                                <td><span class="copyable-top-object" data-tooltip="{obj_name_attr}" style="display: block; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 1em; color: #111827; font-family: inherit; cursor: copy;">{obj['object']}</span></td>
                                <td>{obj['count']}</td>
                            </tr>
'''
        html += '''
                        </tbody>
                    </table>
                </div>
            </details>
'''

    unique_waves = sorted([w for w in set(obj['wave'] for obj in all_objects_data) if w != '-'])
    unique_types = sorted(set(obj['type'] for obj in all_objects_data))

    html += f'''
        {print_note(f"The PDF leaves out the All Objects table ({len(all_objects_data):,} objects). The full table, with its filters and CSV export, is in the HTML report's Dependencies tab.")}
        <div class="print-omit">
        <h2 id="all-objects" style="font-size: 1.5rem; font-weight: 700; color: #102E46; margin-bottom: 20px; margin-top: 32px;">All Objects</h2>

        <div style="margin-bottom: 14px; background: #F8FBFC; border: 1px solid #D5E6F7; border-left: 4px solid #29B5E8; border-radius: 6px; padding: 10px 12px;">
            <p style="margin: 0 0 6px 0; color: #2A3342; font-size: 0.86rem; line-height: 1.45;">
                <strong>Summary:</strong> This table lists all migration objects with their type, source file, assigned wave, dependency counts, conversion status, and missing-dependency flag.
            </p>
            <p style="margin: 0; color: #5C6775; font-size: 0.82rem; line-height: 1.45;">
                <strong>Quick guide:</strong> Use the search and filters to narrow results, click column headers to sort, hover object/file names for full values, and use checkboxes to select rows for export.
            </p>
        </div>

        <div class="filters" style="background-color: #F9FAFB; border-radius: 6px; padding: 12px; margin: 20px 0; border: 1px solid #E5E7EB;">
            <div style="display: flex; flex-wrap: wrap; gap: 8px; align-items: flex-end; margin-bottom: 10px;">
                <div style="display: flex; flex-direction: column; min-width: 200px; flex: 1;">
                    <label for="searchObjectTable" style="font-size: 0.75em; font-weight: 600; color: #374151; margin-bottom: 4px;">Search:</label>
                    <input type="text" id="searchObjectTable" placeholder="Search by name..." onkeyup="filterObjectsTable()" style="padding: 6px 10px; border: 1px solid #D1D5DB; border-radius: 4px; font-size: 0.8125em; background-color: #FFFFFF;">
                </div>

                <div style="display: flex; flex-direction: column; min-width: 120px;">
                    <label style="font-size: 0.75em; font-weight: 600; color: #374151; margin-bottom: 4px;">Type:</label>
                    <button type="button" id="filterTypeBtn" class="objects-filter-trigger" onclick="openObjectsFilterPopover('type', this)" style="padding: 6px 10px; border: 1px solid #D1D5DB; border-radius: 4px; font-size: 0.8125em; background-color: #FFFFFF; color: #374151; text-align: left; cursor: pointer;">
                        Type
                    </button>
                </div>

                <div style="display: flex; flex-direction: column; min-width: 100px;">
                    <label style="font-size: 0.75em; font-weight: 600; color: #374151; margin-bottom: 4px;">Wave:</label>
                    <button type="button" id="filterWaveBtn" class="objects-filter-trigger" onclick="openObjectsFilterPopover('wave', this)" style="padding: 6px 10px; border: 1px solid #D1D5DB; border-radius: 4px; font-size: 0.8125em; background-color: #FFFFFF; color: #374151; text-align: left; cursor: pointer;">
                        Wave
                    </button>
                </div>

                <div style="display: flex; flex-direction: column; min-width: 110px;">
                    <label style="font-size: 0.75em; font-weight: 600; color: #374151; margin-bottom: 4px;">Status:</label>
                    <button type="button" id="filterStatusBtn" class="objects-filter-trigger" onclick="openObjectsFilterPopover('status', this)" style="padding: 6px 10px; border: 1px solid #D1D5DB; border-radius: 4px; font-size: 0.8125em; background-color: #FFFFFF; color: #374151; text-align: left; cursor: pointer;">
                        Status
                    </button>
                </div>

                <div style="display: flex; flex-direction: column; min-width: 130px;">
                    <label for="filterMissingDeps" style="font-size: 0.75em; font-weight: 600; color: #374151; margin-bottom: 4px;">Missing Deps:</label>
                    <select id="filterMissingDeps" onchange="filterObjectsTable()" style="padding: 6px 10px; border: 1px solid #D1D5DB; border-radius: 4px; font-size: 0.8125em; background-color: #FFFFFF;">
                        <option value="">All</option>
                        <option value="yes">Yes</option>
                        <option value="no">No</option>
                    </select>
                </div>

                <button type="button" onclick="clearAllFilters()" style="padding: 6px 12px; background-color: #6B7280; color: white; border: none; border-radius: 4px; font-size: 0.8125em; cursor: pointer; transition: background-color 0.2s; white-space: nowrap;">Clear</button>
            </div>

            <div style="display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding-top: 8px; border-top: 1px solid #E5E7EB;">
                <button onclick="selectAllVisibleObjects()" style="padding: 6px 12px; background-color: #005C8F; color: white; border: none; border-radius: 4px; font-size: 0.8125em; cursor: pointer; transition: background-color 0.2s;">Select All Visible</button>
                <button onclick="clearObjectSelection()" style="padding: 6px 12px; background-color: #6B7280; color: white; border: none; border-radius: 4px; font-size: 0.8125em; cursor: pointer; transition: background-color 0.2s;">Clear Selection</button>

                <div style="position: relative; display: inline-block;">
                    <button onclick="toggleExportMenu()" id="exportBtn" style="padding: 6px 12px; background-color: #059669; color: white; border: none; border-radius: 4px; font-size: 0.8125em; cursor: pointer; transition: background-color 0.2s; display: flex; align-items: center; gap: 6px;">
                        Export to CSV
                        <span style="font-size: 0.7em;">▼</span>
                    </button>
                    <div id="exportMenu" style="display: none; position: absolute; top: 100%; left: 0; margin-top: 4px; background: white; border: 1px solid #D1D5DB; border-radius: 4px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); z-index: 1000; min-width: 150px;">
                        <button onclick="downloadObjectsCSV('all')" style="width: 100%; padding: 8px 12px; background: none; border: none; text-align: left; font-size: 0.8125em; cursor: pointer; color: #374151;">Export All</button>
                        <button onclick="downloadObjectsCSV('selected')" style="width: 100%; padding: 8px 12px; background: none; border: none; text-align: left; font-size: 0.8125em; cursor: pointer; color: #374151; border-top: 1px solid #E5E7EB;">Export Selected</button>
                    </div>
                </div>

                <span id="selectedCountTable" style="margin-left: auto; font-size: 0.8125em; color: #374151; font-weight: 600;">0 selected</span>
            </div>
        </div>

        <div style="margin: 8px 0; font-size: 0.8rem; color: #6B7280; display: flex; align-items: center; gap: 8px;">
            <span id="visibleCountTable" style="font-weight: 600;">Showing {len(all_objects_data)} of {len(all_objects_data)} objects</span>
            <button onclick="clearFiltersAndSorts()" title="Clear all filters and sorting" style="background: none; border: none; cursor: pointer; padding: 4px; display: inline-flex; align-items: center; color: #6B7280; transition: color 0.2s;">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display: block;">
                    <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2"/>
                </svg>
            </button>
        </div>

        <div class="table-container" style="margin-bottom: 20px; border: 1px solid #E5E7EB; border-radius: 6px; box-shadow: 0 1px 2px rgba(0,0,0,0.04); background: #FFFFFF;">
            <table class="object-table" id="objectsTable" style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr>
                        <th class="col-checkbox"><input type="checkbox" id="selectAllCheckbox" onchange="toggleSelectAll()" style="cursor: pointer; width: 14px; height: 14px;"></th>
                        <th class="col-object-name sortable" onclick="sortObjectsTable('name', event)" style="cursor: pointer;">
                            <span>Object Name</span><span class="sort-arrow"></span>
                            <div class="column-resizer" data-col="0"></div>
                        </th>
                        <th class="col-type sortable" onclick="sortObjectsTable('type', event)" style="cursor: pointer;">
                            <span>Type</span><span class="sort-arrow"></span>
                            <div class="column-resizer" data-col="1"></div>
                        </th>
                        <th class="col-file sortable" onclick="sortObjectsTable('file', event)" style="cursor: pointer;">
                            <span>File</span><span class="sort-arrow"></span>
                            <div class="column-resizer" data-col="2"></div>
                        </th>
                        <th class="col-wave sortable" onclick="sortObjectsTable('wave', event)" style="cursor: pointer;">
                            <span>Wave</span><span class="sort-arrow"></span>
                            <div class="column-resizer" data-col="3"></div>
                        </th>
                        <th class="col-deps sortable" onclick="sortObjectsTable('dependencies', event)" style="cursor: pointer;">
                            <span>Dependencies</span><span class="sort-arrow"></span>
                            <div class="column-resizer" data-col="4"></div>
                        </th>
                        <th class="col-dependents sortable" onclick="sortObjectsTable('dependents', event)" style="cursor: pointer;">
                            <span>Dependents</span><span class="sort-arrow"></span>
                            <div class="column-resizer" data-col="5"></div>
                        </th>
                        <th class="col-status sortable" onclick="sortObjectsTable('conversion_status', event)" style="cursor: pointer;">
                            <span>Status</span><span class="sort-arrow"></span>
                            <div class="column-resizer" data-col="6"></div>
                        </th>
                        <th class="col-missing sortable" onclick="sortObjectsTable('has_missing_deps', event)" style="cursor: pointer;">
                            <span>Missing Deps</span><span class="sort-arrow"></span>
                            <div class="column-resizer" data-col="7"></div>
                        </th>
                    </tr>
                </thead>
                <tbody id="objectsTableBody">
                    <!-- Rows will be populated by JavaScript -->
                </tbody>
            </table>
        </div>
        </div>
        <div id="objectDetailsModal" style="display: none; position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); z-index: 12000; align-items: center; justify-content: center; padding: 20px;" onclick="closeObjectDetailsModal(event)">
            <div style="width: min(1400px, 98vw); max-height: 94vh; overflow: auto; background: #FFFFFF; border-radius: 14px; box-shadow: 0 18px 48px rgba(15, 23, 42, 0.35); border: 1px solid #E2E8F0;" onclick="event.stopPropagation()">
                <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding: 16px 18px; border-bottom: 1px solid #E2E8F0; background: #F8FAFC;">
                    <div style="min-width:0; flex:1;">
                        <div style="font-size: 0.75rem; letter-spacing: 0.05em; text-transform: uppercase; color: #64748B; font-weight: 600;">Object Details</div>
                        <div id="objectDetailsModalName" style="font-size: 1.02rem; font-weight: 700; color: #0F172A; margin-top: 2px; word-break: break-word;"></div>
                    </div>
                    <div style="display:flex; align-items:center; gap:8px; flex-shrink:0;">
                        <button id="modalCopyIconBtn" type="button" onclick="copyModalObjectName()" title="Copy object name" aria-label="Copy object name" style="width:30px; height:30px; border: 1px solid #CBD5E1; background: #FFFFFF; color: #1E293B; border-radius: 8px; font-size: 0.9rem; font-weight: 700; cursor: pointer; display:flex; align-items:center; justify-content:center; padding:0;">⧉</button>
                        <button type="button" onclick="closeObjectDetailsModal()" style="padding: 7px 10px; border: 1px solid #CBD5E1; background: #FFFFFF; color: #1E293B; border-radius: 8px; font-size: 0.8rem; font-weight: 600; cursor: pointer;">Close</button>
                    </div>
                </div>
                <div style="padding: 16px 18px;">
                    <div id="objectDetailsModalMeta" style="display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 26px; row-gap: 12px; margin-bottom: 14px;"></div>
                    <div style="border: 1px solid #E2E8F0; border-radius: 10px; padding: 12px; background: #FFFFFF;">
                        <div style="display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap; margin-bottom:10px;">
                            <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
                                <button id="objectDetailsTabIssuesBtn" type="button" onclick="setObjectDetailsTab('issues')" style="padding:6px 10px; border: 1px solid #CBD5E1; border-radius: 999px; background:#FFFFFF; color:#475569; font-size:0.78rem; font-weight:700; cursor:pointer;">Issues (0)</button>
                                <button id="objectDetailsTabDepsBtn" type="button" onclick="setObjectDetailsTab('dependencies')" style="padding:6px 10px; border: 1px solid #0C7AA6; border-radius: 999px; background:#E6F4FB; color:#0F3A57; font-size:0.78rem; font-weight:700; cursor:pointer;">Direct Dependencies</button>
                                <button id="objectDetailsTabDependentsBtn" type="button" onclick="setObjectDetailsTab('dependents')" style="padding:6px 10px; border: 1px solid #CBD5E1; border-radius: 999px; background:#FFFFFF; color:#475569; font-size:0.78rem; font-weight:700; cursor:pointer;">Direct Dependants</button>
                                <button id="objectDetailsTabMissingBtn" type="button" onclick="setObjectDetailsTab('missing')" style="padding:6px 10px; border: 1px solid #CBD5E1; border-radius: 999px; background:#FFFFFF; color:#475569; font-size:0.78rem; font-weight:700; cursor:pointer;">Missing Dependencies</button>
                            </div>
                            <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                                <div data-modal-filter-wrap="type" style="position:relative;">
                                    <button id="modalTypeFilterBtn" type="button" onclick="toggleModalFilterMenu('type')" style="padding:6px 10px; border:1px solid #CBD5E1; border-radius:8px; background:#FFFFFF; color:#1E293B; font-size:0.78rem; font-weight:600; cursor:pointer; min-width:140px; text-align:left;">Type: All</button>
                                    <div id="modalTypeFilterMenu" style="display:none; position:absolute; top:calc(100% + 4px); right:0; z-index:1001; background:#FFFFFF; border:1px solid #D1D5DB; border-radius:8px; box-shadow:0 8px 22px rgba(15,23,42,0.16); min-width:220px; max-height:260px; overflow:auto; padding:8px;"></div>
                                </div>
                                <div data-modal-filter-wrap="status" style="position:relative;">
                                    <button id="modalStatusFilterBtn" type="button" onclick="toggleModalFilterMenu('status')" style="padding:6px 10px; border:1px solid #CBD5E1; border-radius:8px; background:#FFFFFF; color:#1E293B; font-size:0.78rem; font-weight:600; cursor:pointer; min-width:160px; text-align:left;">Status: All</button>
                                    <div id="modalStatusFilterMenu" style="display:none; position:absolute; top:calc(100% + 4px); right:0; z-index:1001; background:#FFFFFF; border:1px solid #D1D5DB; border-radius:8px; box-shadow:0 8px 22px rgba(15,23,42,0.16); min-width:260px; max-height:260px; overflow:auto; padding:8px;"></div>
                                </div>
                            </div>
                        </div>
                        <div id="objectDetailsRelationsBody"></div>
                    </div>
                </div>
            </div>
        </div>
    '''

    html += '''
        <script>
        const objectReferences = [
'''
    ref_parts = []
    for ref in object_references:
        caller = ref['caller'].replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
        referenced = ref['referenced'].replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
        ref_parts.append(f'''            {{caller: "{caller}", referenced: "{referenced}"}},
''')
    html += ''.join(ref_parts)
    html += '''
        ];
        </script>
'''

    # Close the container div
    html += "\n    </div>\n"

    # Prepare data for All Objects table JavaScript
    all_objects_json = json.dumps(all_objects_data)
    missing_dependents_json = json.dumps(missing_obj_refs.get('dependents', {}))

    html += f'''
    <script>
        // All Objects Table Data
        let allObjectsData = {all_objects_json};
        let missingObjectDependentsMap = {missing_dependents_json};
        // Note: objectReferences is already declared above
        let visibleObjectsData = [...allObjectsData];
        let selectedObjects = new Set();
        let modalObjectNameValue = '';
        let modalObjectMissingDependencies = [];
        let modalObjectIssues = [];
        let objectDetailsCurrentTab = 'dependencies';
        let modalDependencyExpanded = new Set();
        let modalDependencyTypeFilters = new Set();
        let modalDependencyStatusFilters = new Set();
        let modalActiveFilterMenu = '';
        let missingDependentsByMissing = new Map();
        let missingDepsByCaller = new Map();

        function getObjectSelectionKey(obj) {{
            return `${{String(obj?.name || '')}}||${{String(obj?.file || '')}}||${{String(obj?.type || '')}}||${{String(obj?.wave || '')}}`;
        }}

        function escapeHtmlText(text) {{
            const div = document.createElement('div');
            div.textContent = text == null ? '' : String(text);
            return div.innerHTML;
        }}

{ISSUE_DOCUMENTATION_URL_JS}
        function normalizeObjectNameForMatch(name) {{
            return String(name || '')
                .replace(/[\\[\\]"]/g, '')
                .trim()
                .toUpperCase();
        }}

        function normalizeObjectNameNoSignature(name) {{
            return normalizeObjectNameForMatch(String(name || '').replace(/\\([^()]*\\)\\s*$/, ''));
        }}

        function getObjectNameLookupKeys(name) {{
            const full = normalizeObjectNameForMatch(name);
            const noSig = normalizeObjectNameNoSignature(name);
            return Array.from(new Set([full, noSig].filter(Boolean)));
        }}

        function extractMissingDependencyName(entry) {{
            if (entry == null) return '';
            if (typeof entry === 'string') return entry.trim();
            if (typeof entry === 'object') {{
                const candidate = entry.missing_object || entry.referenced || entry.referenced_full_name || entry.name || '';
                return String(candidate || '').trim();
            }}
            return String(entry || '').trim();
        }}

        function normalizeFilterValue(value) {{
            return String(value || '').trim().toUpperCase();
        }}

        function addToMapSet(mapObj, key, value) {{
            if (!key || !value) return;
            if (!mapObj.has(key)) mapObj.set(key, new Set());
            mapObj.get(key).add(value);
        }}

        function initializeMissingReferenceIndexes() {{
            missingDependentsByMissing = new Map();
            missingDepsByCaller = new Map();
            Object.entries(missingObjectDependentsMap || {{}}).forEach(([missingObj, dependents]) => {{
                const missingName = String(missingObj || '').trim();
                const missingKeys = getObjectNameLookupKeys(missingName);
                if (!missingName || !missingKeys.length) return;
                (Array.isArray(dependents) ? dependents : []).forEach(dep => {{
                    const callerName = String((dep && typeof dep === 'object') ? (dep.caller || dep.dependent || '') : dep || '').trim();
                    const callerKeys = getObjectNameLookupKeys(callerName);
                    if (!callerName || !callerKeys.length) return;
                    missingKeys.forEach(key => addToMapSet(missingDependentsByMissing, key, callerName));
                    callerKeys.forEach(key => addToMapSet(missingDepsByCaller, key, missingName));
                }});
            }});
        }}

        function getDirectDependencyNames(objectName) {{
            const objectKeys = getObjectNameLookupKeys(objectName);
            const deps = new Set();
            (objectReferences || []).forEach(ref => {{
                const refCallerKeys = getObjectNameLookupKeys(ref?.caller || '');
                if (!refCallerKeys.some(key => objectKeys.includes(key))) return;
                const target = String(ref?.referenced || '').trim();
                if (target) deps.add(target);
            }});
            return Array.from(deps).sort((a, b) => a.localeCompare(b));
        }}

        function getDirectDependentNames(objectName) {{
            const objectKeys = getObjectNameLookupKeys(objectName);
            const dependents = new Set();
            (objectReferences || []).forEach(ref => {{
                const refTargetKeys = getObjectNameLookupKeys(ref?.referenced || '');
                if (!refTargetKeys.some(key => objectKeys.includes(key))) return;
                const source = String(ref?.caller || '').trim();
                if (source) dependents.add(source);
            }});
            objectKeys.forEach(key => (missingDependentsByMissing.get(key) || new Set()).forEach(dep => dependents.add(dep)));
            return Array.from(dependents).sort((a, b) => a.localeCompare(b));
        }}

        function getDirectMissingDependencyNames(objectName) {{
            const objectKeys = getObjectNameLookupKeys(objectName);
            const missingDeps = new Set();
            objectKeys.forEach(key => (missingDepsByCaller.get(key) || new Set()).forEach(dep => missingDeps.add(dep)));
            (modalObjectMissingDependencies || []).forEach(depName => {{
                const name = extractMissingDependencyName(depName);
                if (name) missingDeps.add(name);
            }});
            // Keep Missing Dependencies tab consistent with what appears as MISSING
            // in the Dependencies explorer for the same root object.
            getDirectDependencyNames(objectName).forEach(depName => {{
                const depMeta = getObjectMetaByName(depName);
                const depType = normalizeFilterValue(depMeta?.type || '');
                const depStatus = normalizeFilterValue(depMeta?.conversion_status || '');
                if (depType === 'MISSING' || depStatus === 'MISSING') missingDeps.add(depName);
            }});
            return Array.from(missingDeps).sort((a, b) => a.localeCompare(b));
        }}

        function renderMissingDependenciesList(items) {{
            if (!items || items.length === 0) {{
                return '<div style="font-size: 0.82rem; color: #64748B;">No missing dependencies</div>';
            }}
            return `
                <div style="display:flex; flex-direction:column; gap:8px;">
                    ${{items.map(rawItem => {{
                        const name = extractMissingDependencyName(rawItem);
                        if (!name) return '';
                        return `
                        <div style="display:flex; align-items:flex-start; gap:8px; padding:4px 0;">
                            <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#CBD5E1; margin-top:8px;"></span>
                            <div style="min-width:0; flex:1;">
                                <div style="font-size:0.84rem; font-weight:600; color:#0F172A; white-space:normal; word-break:break-word;">${{escapeHtmlText(name)}}</div>
                            </div>
                        </div>
                        `;
                    }}).join('')}}
                </div>
            `;
        }}

        function getObjectMetaByName(name) {{
            const objectName = String(name || '');
            const lookupKeys = getObjectNameLookupKeys(objectName);
            const found = (allObjectsData || []).find(obj => {{
                const candidateKeys = getObjectNameLookupKeys(String(obj?.name || ''));
                return candidateKeys.some(key => lookupKeys.includes(key));
            }});
            if (found) return found;
            return {{
                name: objectName,
                type: 'MISSING',
                wave: '-',
                conversion_status: 'Missing',
                file: '-',
                has_missing_deps: true,
            }};
        }}

        function getStatusTone(status) {{
            const normalized = normalizeFilterValue(status);
            if (!normalized) return 'neutral';
            if (normalized.includes('MISSING')) return 'missing';
            if (normalized.includes('PARTIAL') || normalized.includes('REQUIRE ATTENTION')) return 'partial';
            if (normalized.includes('NOT SUPPORTED') || normalized.includes('UNSUPPORTED')) return 'unsupported';
            if (normalized.includes('SUCCESS') || normalized.includes('SUPPORTED') || normalized.includes('CONVERTED')) return 'success';
            return 'neutral';
        }}

        function getStatusBadgeStyle(status) {{
            const tone = getStatusTone(status);
            if (tone === 'success') return 'color:#166534; background:#ECFDF5; border:1px solid #BBF7D0;';
            if (tone === 'partial') return 'color:#854D0E; background:#FEFCE8; border:1px solid #FDE68A;';
            if (tone === 'unsupported') return 'color:#991B1B; background:#FEF2F2; border:1px solid #FECACA;';
            if (tone === 'missing') return 'color:#991B1B; background:#FEF2F2; border:1px solid #FECACA;';
            return 'color:#334155; background:#F1F5F9; border:1px solid #E2E8F0;';
        }}

        function getModalDependencyTypeOptions() {{
            const set = new Set((allObjectsData || []).map(obj => String(obj?.type || '').trim()).filter(Boolean));
            set.add('MISSING');
            return Array.from(set).sort((a, b) => a.localeCompare(b));
        }}

        function getModalDependencyStatusOptions() {{
            const set = new Set((allObjectsData || []).map(obj => String(obj?.conversion_status || '').trim()).filter(Boolean));
            set.add('Missing');
            return Array.from(set).sort((a, b) => a.localeCompare(b));
        }}

        function getModalFilterSummary(prefix, selectedSet) {{
            const count = selectedSet.size;
            if (!count) return `${{prefix}}: All`;
            if (count === 1) return `${{prefix}}: ${{Array.from(selectedSet)[0]}}`;
            return `${{prefix}}: ${{count}} selected`;
        }}

        function updateModalFilterButtons() {{
            const typeBtn = document.getElementById('modalTypeFilterBtn');
            const statusBtn = document.getElementById('modalStatusFilterBtn');
            if (typeBtn) typeBtn.textContent = getModalFilterSummary('Type', modalDependencyTypeFilters);
            if (statusBtn) statusBtn.textContent = getModalFilterSummary('Status', modalDependencyStatusFilters);
        }}

        function renderModalFilterMenu(kind) {{
            const isType = kind === 'type';
            const menuEl = document.getElementById(isType ? 'modalTypeFilterMenu' : 'modalStatusFilterMenu');
            if (!menuEl) return;
            const options = isType ? getModalDependencyTypeOptions() : getModalDependencyStatusOptions();
            const selectedSet = isType ? modalDependencyTypeFilters : modalDependencyStatusFilters;
            const rows = options.map(value => {{
                const norm = normalizeFilterValue(value);
                const checked = selectedSet.has(norm) ? 'checked' : '';
                return `
                    <label style="display:flex; align-items:center; gap:8px; padding:6px 4px; font-size:0.8rem; color:#1F2937; cursor:pointer;">
                        <input type="checkbox" onchange="toggleModalFilterOption('${{kind}}', '${{encodeURIComponent(value)}}')" ${{checked}} style="cursor:pointer;">
                        <span>${{escapeHtmlText(value)}}</span>
                    </label>
                `;
            }}).join('');
            menuEl.innerHTML = `
                <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:6px; padding:2px 4px;">
                    <span style="font-size:0.7rem; color:#64748B; text-transform:uppercase; letter-spacing:0.03em; font-weight:700;">${{isType ? 'Type' : 'Status'}} Filter</span>
                    <button type="button" onclick="clearModalFilter('${{kind}}')" style="border:none; background:none; color:#2563EB; font-size:0.74rem; font-weight:600; cursor:pointer; padding:0;">Clear</button>
                </div>
                <div style="border-top:1px solid #E5E7EB; margin:0 -8px 0 -8px; padding:6px 8px 0 8px;">
                    ${{rows || '<div style="font-size:0.78rem; color:#64748B; padding:6px 4px;">No values</div>'}}
                </div>
            `;
        }}

        function closeModalFilterMenus() {{
            const typeMenu = document.getElementById('modalTypeFilterMenu');
            const statusMenu = document.getElementById('modalStatusFilterMenu');
            if (typeMenu) typeMenu.style.display = 'none';
            if (statusMenu) statusMenu.style.display = 'none';
            modalActiveFilterMenu = '';
        }}

        function toggleModalFilterMenu(kind) {{
            const typeMenu = document.getElementById('modalTypeFilterMenu');
            const statusMenu = document.getElementById('modalStatusFilterMenu');
            if (!typeMenu || !statusMenu) return;
            if (modalActiveFilterMenu === kind) {{
                closeModalFilterMenus();
                return;
            }}
            closeModalFilterMenus();
            renderModalFilterMenu(kind);
            const targetMenu = kind === 'type' ? typeMenu : statusMenu;
            targetMenu.style.display = 'block';
            modalActiveFilterMenu = kind;
        }}

        function clearModalFilter(kind) {{
            if (kind === 'type') modalDependencyTypeFilters = new Set();
            else modalDependencyStatusFilters = new Set();
            renderModalFilterMenu(kind);
            updateModalFilterButtons();
            modalDependencyExpanded = new Set();
            renderObjectDetailsTabContent();
        }}

        function toggleModalFilterOption(kind, encodedValue) {{
            const decodedValue = decodeURIComponent(String(encodedValue || ''));
            if (!decodedValue) return;
            const normalized = normalizeFilterValue(decodedValue);
            const targetSet = kind === 'type' ? modalDependencyTypeFilters : modalDependencyStatusFilters;
            if (targetSet.has(normalized)) targetSet.delete(normalized);
            else targetSet.add(normalized);
            renderModalFilterMenu(kind);
            updateModalFilterButtons();
            modalDependencyExpanded = new Set();
            renderObjectDetailsTabContent();
        }}

        function matchesModalExplorerFilters(meta) {{
            const typeMatch = !modalDependencyTypeFilters.size || modalDependencyTypeFilters.has(normalizeFilterValue(meta?.type || ''));
            const statusMatch = !modalDependencyStatusFilters.size || modalDependencyStatusFilters.has(normalizeFilterValue(meta?.conversion_status || ''));
            return typeMatch && statusMatch;
        }}

        function renderModalList(items, emptyText) {{
            if (!items || items.length === 0) {{
                return `<div style="font-size: 0.82rem; color: #64748B;">${{escapeHtmlText(emptyText)}}</div>`;
            }}
            return `
                <div style="display:flex; flex-wrap:wrap; gap:6px;">
                    ${{items.map(item => `<span style="display:inline-block; max-width:100%; padding:4px 8px; border-radius:999px; background:#F1F5F9; color:#334155; font-size:0.78rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${{escapeHtmlText(item)}}">${{escapeHtmlText(item)}}</span>`).join('')}}
                </div>
            `;
        }}

        function renderDependencyFlowNode(objectName, depth = 0, ancestors = new Set(), mode = 'dependencies') {{
            const safeName = String(objectName || '');
            const meta = getObjectMetaByName(safeName);
            if (!matchesModalExplorerFilters(meta)) return '';
            const childNames = (
                mode === 'dependents'
                    ? getDirectDependentNames(safeName)
                    : getDirectDependencyNames(safeName)
            ).filter(name => !ancestors.has(name));
            const hasChildren = childNames.length > 0;
            const isExpanded = modalDependencyExpanded.has(safeName);
            const nodeKey = encodeURIComponent(safeName);
            const indentPx = depth * 22;

            let html = `
                <div style="margin-left:${{indentPx}}px;">
                    <div style="display:flex; align-items:flex-start; gap:8px; padding:6px 0;">
                        <div style="width:18px; flex:0 0 18px; display:flex; justify-content:center; padding-top:2px;">
                            ${{
                                hasChildren
                                    ? `<button type="button" onclick="toggleDependencyExplorerNode('${{nodeKey}}')" title="${{isExpanded ? 'Collapse' : 'Expand'}}" style="width:16px; height:16px; border: 1px solid #CBD5E1; border-radius: 4px; background:#FFFFFF; color:#475569; font-size:11px; line-height:1; cursor:pointer; padding:0;">${{isExpanded ? '−' : '+'}}</button>`
                                    : `<span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#CBD5E1; margin-top:4px;"></span>`
                            }}
                        </div>
                        <div style="min-width:0; flex:1;">
                            <div style="font-size:0.84rem; font-weight:600; color:#0F172A; white-space:normal; word-break:break-word;">${{escapeHtmlText(safeName)}}</div>
                            <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:3px;">
                                <span style="font-size:0.72rem; color:#334155; background:#EEF2FF; border:1px solid #DCE3FF; border-radius:999px; padding:2px 8px;">${{escapeHtmlText(meta.type || 'Unknown')}}</span>
                                <span style="font-size:0.72rem; color:#334155; background:#F1F5F9; border:1px solid #E2E8F0; border-radius:999px; padding:2px 8px;">Wave ${{escapeHtmlText(meta.wave || '-')}}</span>
                                <span style="font-size:0.72rem; border-radius:999px; padding:2px 8px; ${{getStatusBadgeStyle(meta.conversion_status)}}">${{escapeHtmlText(meta.conversion_status || 'Unknown')}}</span>
                            </div>
                        </div>
                    </div>
                </div>
            `;

            if (hasChildren && isExpanded) {{
                const nextAncestors = new Set(ancestors);
                nextAncestors.add(safeName);
                html += `
                    <div style="margin-left:${{indentPx + 9}}px; border-left:1px dashed #D1D9E6; padding-left:10px;">
                        ${{childNames.map(child => renderDependencyFlowNode(child, depth + 1, nextAncestors, mode)).join('')}}
                    </div>
                `;
            }}
            return html;
        }}

        function toggleDependencyExplorerNode(encodedName) {{
            const name = decodeURIComponent(String(encodedName || ''));
            if (!name) return;
            if (modalDependencyExpanded.has(name)) modalDependencyExpanded.delete(name);
            else modalDependencyExpanded.add(name);
            renderObjectDetailsTabContent();
        }}

        function updateObjectDetailsTabStyles() {{
            const issuesBtn = document.getElementById('objectDetailsTabIssuesBtn');
            const depsBtn = document.getElementById('objectDetailsTabDepsBtn');
            const dependentsBtn = document.getElementById('objectDetailsTabDependentsBtn');
            const missingBtn = document.getElementById('objectDetailsTabMissingBtn');

            const applyState = (btn, isActive) => {{
                if (!btn) return;
                btn.style.borderColor = isActive ? '#0C7AA6' : '#CBD5E1';
                btn.style.background = isActive ? '#E6F4FB' : '#FFFFFF';
                btn.style.color = isActive ? '#0F3A57' : '#475569';
            }};

            applyState(issuesBtn, objectDetailsCurrentTab === 'issues');
            applyState(depsBtn, objectDetailsCurrentTab === 'dependencies');
            applyState(dependentsBtn, objectDetailsCurrentTab === 'dependents');
            applyState(missingBtn, objectDetailsCurrentTab === 'missing');
            document.querySelectorAll('[data-modal-filter-wrap]').forEach(wrap => {{
                wrap.style.display = objectDetailsCurrentTab === 'issues' ? 'none' : '';
            }});
        }}

        function updateObjectDetailsTabLabels() {{
            const issuesBtn = document.getElementById('objectDetailsTabIssuesBtn');
            const depsBtn = document.getElementById('objectDetailsTabDepsBtn');
            const dependentsBtn = document.getElementById('objectDetailsTabDependentsBtn');
            const missingBtn = document.getElementById('objectDetailsTabMissingBtn');
            const issueCount = Array.isArray(modalObjectIssues) ? modalObjectIssues.length : 0;
            const depsCount = getDirectDependencyNames(modalObjectNameValue).length;
            const dependentsCount = getDirectDependentNames(modalObjectNameValue).length;
            const missingCount = getDirectMissingDependencyNames(modalObjectNameValue).length;
            if (issuesBtn) issuesBtn.textContent = `Issues (${{issueCount}})`;
            if (depsBtn) depsBtn.textContent = `Direct Dependencies (${{depsCount}})`;
            if (dependentsBtn) dependentsBtn.textContent = `Direct Dependants (${{dependentsCount}})`;
            if (missingBtn) missingBtn.textContent = `Missing Dependencies (${{missingCount}})`;
        }}

        function renderObjectDetailsTabContent() {{
            const body = document.getElementById('objectDetailsRelationsBody');
            if (!body) return;

            if (objectDetailsCurrentTab === 'issues') {{
                const issues = Array.isArray(modalObjectIssues) ? modalObjectIssues : [];
                const rows = issues.map(issue => {{
                    const code = issue.code || '';
                    const docUrl = issueDocumentationUrl(code);
                    const codeHtml = docUrl
                        ? `<a href="${{escapeHtmlText(docUrl)}}" target="_blank" rel="noopener noreferrer" style="color:#0C7AA6; text-decoration:none;">${{escapeHtmlText(code)}}</a>`
                        : escapeHtmlText(code);
                    return `
                    <div style="display:grid; grid-template-columns: 4.5rem 1fr 4rem; gap: 8px; padding: 6px 0; border-bottom: 1px solid #E2E8F0; font-size: 0.84rem;">
                        <span style="font-weight:700; color:#334155;">${{escapeHtmlText(issue.family || '')}}</span>
                        <span style="font-family: ui-monospace, monospace; color:#0F172A;">${{codeHtml}}</span>
                        <span style="text-align:right; color:#0F172A;">${{escapeHtmlText(issue.count ?? '')}}</span>
                    </div>
                `;
                }}).join('');
                body.innerHTML = `
                    <div style="font-size: 0.78rem; font-weight: 700; color: #334155; text-transform: uppercase; letter-spacing: 0.03em; margin-bottom: 8px;">Issues</div>
                    <div style="background:#FBFDFF; border: 1px solid #E2E8F0; border-radius: 10px; padding: 10px;">
                        ${{rows || '<div style="font-size: 0.82rem; color: #64748B;">No conversion issues.</div>'}}
                    </div>
                `;
                return;
            }}

            if (objectDetailsCurrentTab === 'dependents') {{
                const dependents = getDirectDependentNames(modalObjectNameValue);
                const rootAncestors = new Set([modalObjectNameValue]);
                const explorerHtml = dependents.map(dep => renderDependencyFlowNode(dep, 0, rootAncestors, 'dependents')).join('');
                body.innerHTML = `
                    <div style="font-size: 0.78rem; font-weight: 700; color: #334155; text-transform: uppercase; letter-spacing: 0.03em; margin-bottom: 8px;">Direct Dependants</div>
                    <div style="background:#FBFDFF; border: 1px solid #E2E8F0; border-radius: 10px; padding: 10px;">
                        ${{explorerHtml || '<div style="font-size: 0.82rem; color: #64748B;">No direct dependants</div>'}}
                    </div>
                `;
                return;
            }}

            if (objectDetailsCurrentTab === 'missing') {{
                // Missing Dependencies tab should always show all missing refs for this object,
                // regardless of Type/Status explorer filters.
                const missingDeps = getDirectMissingDependencyNames(modalObjectNameValue);
                body.innerHTML = `
                    <div style="font-size: 0.78rem; font-weight: 700; color: #334155; text-transform: uppercase; letter-spacing: 0.03em; margin-bottom: 8px;">Missing Dependencies</div>
                    <div style="background:#FBFDFF; border: 1px solid #E2E8F0; border-radius: 10px; padding: 10px;">
                        ${{renderMissingDependenciesList(missingDeps)}}
                    </div>
                `;
                return;
            }}

            const dependencies = getDirectDependencyNames(modalObjectNameValue);
            const rootAncestors = new Set([modalObjectNameValue]);
            const explorerHtml = dependencies.map(dep => renderDependencyFlowNode(dep, 0, rootAncestors, 'dependencies')).join('');
            body.innerHTML = `
                <div style="font-size: 0.78rem; font-weight: 700; color: #334155; text-transform: uppercase; letter-spacing: 0.03em; margin-bottom: 8px;">Direct Dependencies</div>
                <div style="background:#FBFDFF; border: 1px solid #E2E8F0; border-radius: 10px; padding: 10px;">
                    ${{explorerHtml || '<div style="font-size: 0.82rem; color: #64748B;">No direct dependencies</div>'}}
                </div>
            `;
        }}

        function setObjectDetailsTab(tabKey) {{
            const allowed = ['issues', 'dependencies', 'dependents', 'missing'];
            objectDetailsCurrentTab = allowed.includes(tabKey) ? tabKey : 'dependencies';
            modalDependencyExpanded = new Set();
            updateObjectDetailsTabStyles();
            renderObjectDetailsTabContent();
        }}

        function openObjectDetailsModal(obj) {{
            if (!obj) return;
            modalObjectNameValue = String(obj.name || '');
            modalObjectMissingDependencies = Array.from(new Set((Array.isArray(obj.missing_dependencies) ? obj.missing_dependencies : [])
                .map(value => extractMissingDependencyName(value))
                .filter(Boolean)));
            modalObjectIssues = Array.isArray(obj.issues) ? obj.issues : [];
            modalDependencyTypeFilters = new Set();
            modalDependencyStatusFilters = new Set();
            modalActiveFilterMenu = '';
            const modal = document.getElementById('objectDetailsModal');
            const nameEl = document.getElementById('objectDetailsModalName');
            const metaEl = document.getElementById('objectDetailsModalMeta');
            if (!modal || !nameEl || !metaEl) return;

            nameEl.textContent = String(obj.display_name || modalObjectNameValue || '-');
            metaEl.innerHTML = `
                <div>
                    <div style="font-size:0.72rem; color:#64748B; text-transform:uppercase; letter-spacing:0.03em; margin-bottom:2px;">Type</div>
                    <div style="font-size:0.9rem; font-weight:600; color:#0F172A; white-space:normal; word-break:break-word;">${{escapeHtmlText(obj.type || '-')}}</div>
                </div>
                <div>
                    <div style="font-size:0.72rem; color:#64748B; text-transform:uppercase; letter-spacing:0.03em; margin-bottom:2px;">Wave</div>
                    <div style="font-size:0.9rem; font-weight:600; color:#0F172A; white-space:normal; word-break:break-word;">${{escapeHtmlText(obj.wave || '-')}}</div>
                </div>
                <div>
                    <div style="font-size:0.72rem; color:#64748B; text-transform:uppercase; letter-spacing:0.03em; margin-bottom:2px;">Status</div>
                    <div style="font-size:0.9rem; font-weight:600; color:#0F172A; white-space:normal; word-break:break-word;">${{escapeHtmlText(obj.conversion_status || '-')}}</div>
                </div>
                <div>
                    <div style="font-size:0.72rem; color:#64748B; text-transform:uppercase; letter-spacing:0.03em; margin-bottom:2px;">Missing Deps</div>
                    <div style="font-size:0.9rem; font-weight:600; color:#0F172A; white-space:normal; word-break:break-word;">${{obj.has_missing_deps ? 'Yes' : 'No'}}</div>
                </div>
                <div>
                    <div style="font-size:0.72rem; color:#64748B; text-transform:uppercase; letter-spacing:0.03em; margin-bottom:2px;">Dependencies</div>
                    <div style="font-size:0.9rem; font-weight:600; color:#0F172A; white-space:normal; word-break:break-word;">${{escapeHtmlText(obj.dependencies ?? 0)}} <span style="font-size:0.74rem; font-weight:500; color:#64748B;">(direct + transitive)</span></div>
                </div>
                <div>
                    <div style="font-size:0.72rem; color:#64748B; text-transform:uppercase; letter-spacing:0.03em; margin-bottom:2px;">Dependants</div>
                    <div style="font-size:0.9rem; font-weight:600; color:#0F172A; white-space:normal; word-break:break-word;">${{escapeHtmlText(obj.dependents ?? 0)}} <span style="font-size:0.74rem; font-weight:500; color:#64748B;">(direct + transitive)</span></div>
                </div>
                <div style="grid-column: 1 / -1;">
                    <div style="font-size:0.72rem; color:#64748B; text-transform:uppercase; letter-spacing:0.03em; margin-bottom:2px;">Filename</div>
                    <div style="font-size:0.86rem; font-weight:500; color:#0F172A; white-space:normal; word-break:break-word;">${{escapeHtmlText(obj.file || '-')}}</div>
                </div>
            `;
            objectDetailsCurrentTab = modalObjectIssues.length ? 'issues' : 'dependencies';
            modalDependencyExpanded = new Set();
            renderModalFilterMenu('type');
            renderModalFilterMenu('status');
            updateModalFilterButtons();
            updateObjectDetailsTabLabels();
            updateObjectDetailsTabStyles();
            renderObjectDetailsTabContent();

            modal.style.display = 'flex';
            document.body.style.overflow = 'hidden';
        }}

        function closeObjectDetailsModal(event) {{
            if (event && event.target && event.target.id && event.target.id !== 'objectDetailsModal') return;
            const modal = document.getElementById('objectDetailsModal');
            if (!modal) return;
            closeModalFilterMenus();
            modal.style.display = 'none';
            document.body.style.overflow = '';
        }}

        function copyModalObjectName() {{
            if (!modalObjectNameValue) return;
            const triggerEl = document.getElementById('modalCopyIconBtn');
            copyObjectNameToClipboard(modalObjectNameValue, triggerEl || document.body);
        }}

        document.addEventListener('click', function(event) {{
            const target = event.target;
            if (!target || typeof target.closest !== 'function') return;
            if (target.closest('[data-modal-filter-wrap]')) return;
            closeModalFilterMenus();
        }});

        initializeMissingReferenceIndexes();

        // Single-column sorting state
        let sortColumn = null;
        let sortDirection = null; // null (unsorted), 'asc', or 'desc'

        // Header-chip filters state (multi-select)
        window.objectsFilters = {{
            wave: new Set(),
            type: new Set(),
            status: new Set(),
            missing: new Set(), // 'yes' | 'no'
        }};

        function buildObjectsFilterOptions() {{
            const waves = Array.from(new Set(allObjectsData.map(o => String(o.wave)))).sort((a,b) => Number(a) - Number(b));
            const types = Array.from(new Set(allObjectsData.map(o => o.type).filter(Boolean))).sort((a,b) => a.localeCompare(b));
            const statuses = Array.from(new Set(allObjectsData.map(o => o.conversion_status).filter(Boolean))).sort((a,b) => a.localeCompare(b));
            const missing = ['yes','no'];
            return {{ waves, types, statuses, missing }};
        }}

        function openObjectsFilterPopover(key, anchorEl) {{
            closeObjectsFilterPopover();

            const opts = buildObjectsFilterOptions();
            const values = (
                key === 'wave' ? opts.waves :
                key === 'type' ? opts.types :
                key === 'status' ? opts.statuses :
                opts.missing
            );

            const popover = document.createElement('div');
            popover.id = 'objectsFilterPopover';
            popover.style.position = 'absolute';
            popover.style.zIndex = '2000';
            popover.style.background = '#FFFFFF';
            popover.style.border = '1px solid #D5DAE4';
            popover.style.borderRadius = '8px';
            popover.style.boxShadow = '0 10px 30px rgba(0,0,0,0.12)';
            popover.style.padding = '10px';
            popover.style.minWidth = '240px';
            popover.style.maxWidth = '320px';

            const titleMap = {{ wave: 'Wave', type: 'Type', status: 'Status', missing: 'Missing Deps' }};
            const title = document.createElement('div');
            title.textContent = titleMap[key] || 'Filter';
            title.style.fontSize = '12px';
            title.style.fontWeight = '700';
            title.style.color = '#102E46';
            title.style.textTransform = 'uppercase';
            title.style.letterSpacing = '0.6px';
            title.style.marginBottom = '8px';
            popover.appendChild(title);

            const list = document.createElement('div');
            list.style.maxHeight = '240px';
            list.style.overflow = 'auto';
            list.style.paddingRight = '4px';

            values.forEach(v => {{
                const id = `objflt_${{key}}_${{String(v).replace(/\\W+/g,'_')}}`;
                const row = document.createElement('label');
                row.setAttribute('for', id);
                row.style.display = 'flex';
                row.style.alignItems = 'center';
                row.style.gap = '8px';
                row.style.padding = '6px 8px';
                row.style.borderRadius = '6px';
                row.style.cursor = 'pointer';
                row.onmouseenter = () => row.style.background = '#F3F4F6';
                row.onmouseleave = () => row.style.background = 'transparent';

                const cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.id = id;
                cb.checked = window.objectsFilters[key].has(String(v));
                cb.style.cursor = 'pointer';
                cb.onchange = () => {{
                    if (cb.checked) window.objectsFilters[key].add(String(v));
                    else window.objectsFilters[key].delete(String(v));
                    filterObjectsTable();
                }};

                const text = document.createElement('div');
                text.style.display = 'flex';
                text.style.flex = '1';
                text.style.minWidth = '0';
                text.style.fontSize = '13px';
                text.style.color = '#2A3342';
                text.style.whiteSpace = 'nowrap';
                text.style.overflow = 'hidden';
                text.style.textOverflow = 'ellipsis';
                text.textContent = (key === 'wave') ? `Wave ${{v}}` : (key === 'missing' ? (v === 'yes' ? 'Yes' : 'No') : String(v));
                text.title = text.textContent;

                row.appendChild(cb);
                row.appendChild(text);
                list.appendChild(row);
            }});

            popover.appendChild(list);

            const footer = document.createElement('div');
            footer.style.display = 'flex';
            footer.style.gap = '8px';
            footer.style.marginTop = '10px';

            const clearBtn = document.createElement('button');
            clearBtn.type = 'button';
            clearBtn.textContent = 'Clear';
            clearBtn.className = 'filter-btn secondary';
            clearBtn.style.padding = '6px 10px';
            clearBtn.style.fontSize = '12px';
            clearBtn.onclick = () => {{
                window.objectsFilters[key].clear();
                filterObjectsTable();
                openObjectsFilterPopover(key, anchorEl);
            }};

            const closeBtn = document.createElement('button');
            closeBtn.type = 'button';
            closeBtn.textContent = 'Done';
            closeBtn.className = 'filter-btn';
            closeBtn.style.padding = '6px 10px';
            closeBtn.style.fontSize = '12px';
            closeBtn.onclick = () => closeObjectsFilterPopover();

            footer.appendChild(clearBtn);
            footer.appendChild(closeBtn);
            popover.appendChild(footer);

            document.body.appendChild(popover);

            const rect = anchorEl.getBoundingClientRect();
            const top = rect.bottom + window.scrollY + 8;
            const left = Math.min(rect.left + window.scrollX, window.scrollX + window.innerWidth - popover.offsetWidth - 12);
            popover.style.top = `${{top}}px`;
            popover.style.left = `${{Math.max(12, left)}}px`;

            setTimeout(() => {{
                document.addEventListener('click', onObjectsFilterOutsideClick, true);
                document.addEventListener('keydown', onObjectsFilterKeyDown, true);
            }}, 0);
        }}

        function closeObjectsFilterPopover() {{
            const existing = document.getElementById('objectsFilterPopover');
            if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
            document.removeEventListener('click', onObjectsFilterOutsideClick, true);
            document.removeEventListener('keydown', onObjectsFilterKeyDown, true);
            updateFilterableColumnsState();
        }}

        function onObjectsFilterOutsideClick(e) {{
            const pop = document.getElementById('objectsFilterPopover');
            if (!pop) return;
            if (pop.contains(e.target)) return;
            if (e.target && (e.target.closest && e.target.closest('.objects-filter-trigger'))) return;
            closeObjectsFilterPopover();
        }}

        function onObjectsFilterKeyDown(e) {{
            if (e.key === 'Escape') closeObjectsFilterPopover();
        }}

        function clearAllObjectsFilters() {{
            window.objectsFilters.wave.clear();
            window.objectsFilters.type.clear();
            window.objectsFilters.status.clear();
            window.objectsFilters.missing.clear();
            filterObjectsTable();
            updateFilterableColumnsState();
            updateObjectsFilterButtonLabels();
        }}

        function updateObjectsFilterButtonLabels() {{
            const setButtonLabel = (id, label, count) => {{
                const btn = document.getElementById(id);
                if (!btn) return;
                btn.textContent = count > 0 ? `${{label}} (${{count}})` : label;
            }};
            setButtonLabel('filterTypeBtn', 'Type', window.objectsFilters.type.size);
            setButtonLabel('filterWaveBtn', 'Wave', window.objectsFilters.wave.size);
            setButtonLabel('filterStatusBtn', 'Status', window.objectsFilters.status.size);
        }}

        function renderObjectsFilterChips() {{
            const container = document.getElementById('objectsFilterChips');
            if (!container) return;

            const mkChip = (key, label, value) => {{
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'objects-filter-chip';
                btn.style.display = 'inline-flex';
                btn.style.alignItems = 'center';
                btn.style.gap = '6px';
                btn.style.padding = '6px 10px';
                btn.style.border = '1px solid #D5DAE4';
                btn.style.borderRadius = '999px';
                btn.style.background = '#FFFFFF';
                btn.style.color = '#2A3342';
                btn.style.fontSize = '12px';
                btn.style.cursor = 'pointer';
                btn.onmouseenter = () => btn.style.background = '#F3F4F6';
                btn.onmouseleave = () => btn.style.background = '#FFFFFF';

                const text = document.createElement('span');
                text.style.whiteSpace = 'nowrap';
                text.textContent = `${{label}}: ${{value}}`;

                const x = document.createElement('span');
                x.textContent = '×';
                x.style.fontWeight = '700';

                btn.appendChild(text);
                btn.appendChild(x);
                btn.onclick = () => {{
                    window.objectsFilters[key].delete(String(value));
                    filterObjectsTable();
                }};
                return btn;
            }};

            container.innerHTML = '';

            Array.from(window.objectsFilters.wave).sort((a,b)=>Number(a)-Number(b)).forEach(v => container.appendChild(mkChip('wave','Wave', v)));
            Array.from(window.objectsFilters.type).sort().forEach(v => container.appendChild(mkChip('type','Type', v)));
            Array.from(window.objectsFilters.status).sort().forEach(v => container.appendChild(mkChip('status','Status', v)));
            Array.from(window.objectsFilters.missing).sort().forEach(v => container.appendChild(mkChip('missing','Missing', v === 'yes' ? 'Yes' : 'No')));

            if (container.childNodes.length === 0) {{
                const empty = document.createElement('span');
                empty.textContent = 'None';
                empty.style.fontSize = '12px';
                empty.style.color = '#64748B';
                container.appendChild(empty);
            }}

            // Update active state of filterable columns
            updateFilterableColumnsState();
        }}

        function updateFilterableColumnsState() {{
            const columns = ['type', 'wave', 'status', 'missing'];
            columns.forEach(key => {{
                const th = document.querySelector(`.col-${{key}}`);
                if (th && th._updateActiveState) {{
                    th._updateActiveState();
                }}
            }});
        }}

        function initObjectsHeaderFilterTriggers() {{
            const map = [
                {{ key: 'type', selector: 'th.col-type' }},
                {{ key: 'wave', selector: 'th.col-wave' }},
                {{ key: 'status', selector: 'th.col-status' }},
                {{ key: 'missing', selector: 'th.col-missing' }},
            ];

            map.forEach(({{ key, selector }}) => {{
                const th = document.querySelector(selector);
                if (!th) return;

                th.classList.add('objects-filter-trigger', 'filterable-column');
                th.style.position = 'relative';
                th.style.userSelect = 'none';

                // Get the text content
                const textContent = th.firstChild?.textContent?.trim() || '';

                // Clear the th content except column-resizer
                const resizer = th.querySelector('.column-resizer');
                th.innerHTML = '';

                // Create dropdown-style wrapper
                const wrapper = document.createElement('div');
                wrapper.className = 'filter-dropdown-wrapper';

                // Add text
                const textSpan = document.createElement('span');
                textSpan.textContent = textContent;
                wrapper.appendChild(textSpan);

                // Add dropdown arrow
                const arrow = document.createElement('span');
                arrow.className = 'filter-dropdown-arrow';
                arrow.innerHTML = '▼';
                wrapper.appendChild(arrow);

                th.appendChild(wrapper);

                // Re-add the column resizer if it existed
                if (resizer) {{
                    th.appendChild(resizer);
                }}

                // Mark column as active when filters are applied
                const updateActiveState = () => {{
                    const hasActiveFilters = window.objectsFilters[key]?.size > 0;
                    if (hasActiveFilters) {{
                        th.classList.add('filter-active');
                    }} else {{
                        th.classList.remove('filter-active');
                    }}
                }};

                // Store update function for later use
                th._updateActiveState = updateActiveState;

                th.addEventListener('click', (e) => {{
                    if (e.target && e.target.classList && e.target.classList.contains('column-resizer')) return;
                    e.preventDefault();
                    e.stopPropagation();
                    openObjectsFilterPopover(key, th);
                }}, true);
            }});
        }}

        // Expose for inline handlers
        window.clearAllObjectsFilters = clearAllObjectsFilters;

        // Filter objects table
        function filterObjectsTable() {{
            const searchTerm = document.getElementById('searchObjectTable').value.toLowerCase();
            const filterMissingDeps = document.getElementById('filterMissingDeps')?.value || '';
            const typeFilters = window.objectsFilters.type || new Set();
            const waveFilters = window.objectsFilters.wave || new Set();
            const statusFilters = window.objectsFilters.status || new Set();

            visibleObjectsData = allObjectsData.filter(obj => {{
                const shownName = String(obj.display_name || obj.name || '');
                const matchesSearch = (searchTerm === '' || shownName.toLowerCase().includes(searchTerm) || String(obj.name || '').toLowerCase().includes(searchTerm));
                const matchesType = (typeFilters.size === 0 || typeFilters.has(String(obj.type || '')));
                const matchesWave = (waveFilters.size === 0 || waveFilters.has(String(obj.wave || '')));
                const matchesStatus = (statusFilters.size === 0 || statusFilters.has(String(obj.conversion_status || '')));

                const objMissing = obj.has_missing_deps === true;
                const matchesMissing = (filterMissingDeps === '') ||
                    (filterMissingDeps === 'yes' && objMissing) ||
                    (filterMissingDeps === 'no' && !objMissing);

                return matchesSearch && matchesType && matchesWave && matchesStatus && matchesMissing;
            }});

            updateObjectsFilterButtonLabels();
            renderObjectsTable();
            updateVisibleCount();
        }}

        function clearAllFilters() {{
            document.getElementById('searchObjectTable').value = '';
            document.getElementById('filterMissingDeps').value = '';
            window.objectsFilters.type.clear();
            window.objectsFilters.wave.clear();
            window.objectsFilters.status.clear();
            closeObjectsFilterPopover();
            updateObjectsFilterButtonLabels();
            filterObjectsTable();
        }}

        function clearFiltersAndSorts() {{
            // Clear filters
            document.getElementById('searchObjectTable').value = '';
            document.getElementById('filterMissingDeps').value = '';
            window.objectsFilters.type.clear();
            window.objectsFilters.wave.clear();
            window.objectsFilters.status.clear();

            // Clear sorting
            sortColumn = null;
            sortDirection = null;

            // Reset to original data
            visibleObjectsData = [...allObjectsData];

            // Update UI
            closeObjectsFilterPopover();
            updateObjectsFilterButtonLabels();
            updateSortIndicators();
            renderObjectsTable();
            updateVisibleCount();
        }}

        function toggleExportMenu() {{
            const menu = document.getElementById('exportMenu');
            if (menu.style.display === 'none' || menu.style.display === '') {{
                menu.style.display = 'block';
            }} else {{
                menu.style.display = 'none';
            }}
        }}

        // Close export menu when clicking outside
        document.addEventListener('click', function(event) {{
            const exportBtn = document.getElementById('exportBtn');
            const exportMenu = document.getElementById('exportMenu');
            if (exportBtn && exportMenu && !exportBtn.contains(event.target) && !exportMenu.contains(event.target)) {{
                exportMenu.style.display = 'none';
            }}
        }});

        // Sort objects table with 3-state sorting (unsorted -> asc -> desc -> unsorted)
        function sortObjectsTable(column, event) {{
            if (sortColumn === column) {{
                // Cycle through: asc -> desc -> unsorted
                if (sortDirection === 'asc') {{
                    sortDirection = 'desc';
                }} else if (sortDirection === 'desc') {{
                    sortColumn = null;
                    sortDirection = null;
                }}
            }} else {{
                // New column - start with asc
                sortColumn = column;
                sortDirection = 'asc';
            }}

            // Apply sorting
            if (sortColumn && sortDirection) {{
                visibleObjectsData.sort((a, b) => {{
                    let aVal = a[sortColumn];
                    let bVal = b[sortColumn];

                    let compareResult = 0;
                    if (typeof aVal === 'number' && typeof bVal === 'number') {{
                        compareResult = aVal - bVal;
                    }} else {{
                        const aStr = String(aVal || '').toLowerCase();
                        const bStr = String(bVal || '').toLowerCase();
                        compareResult = aStr.localeCompare(bStr);
                    }}

                    return sortDirection === 'asc' ? compareResult : -compareResult;
                }});
            }} else {{
                // No sort - restore original order
                visibleObjectsData = allObjectsData.filter(obj => visibleObjectsData.some(v => v.name === obj.name));
            }}

            updateSortIndicators();
            renderObjectsTable();
        }}

        function updateSortIndicators() {{
            // Map column names to selectors
            const columnMap = {{
                'name': 'th.col-object-name',
                'type': 'th.col-type',
                'file': 'th.col-file',
                'wave': 'th.col-wave',
                'dependencies': 'th.col-deps',
                'dependents': 'th.col-dependents',
                'conversion_status': 'th.col-status',
                'has_missing_deps': 'th.col-missing'
            }};

            // Update all column headers
            Object.entries(columnMap).forEach(([column, selector]) => {{
                const th = document.querySelector(selector);
                if (!th) return;

                const arrow = th.querySelector('.sort-arrow');
                if (!arrow) return;

                // Clear existing content
                arrow.innerHTML = '';

                if (sortColumn === column && sortDirection) {{
                    // Column is sorted - show arrow
                    th.classList.add('sorted');
                    if (sortDirection === 'asc') {{
                        arrow.innerHTML = `▲`;
                        arrow.style.color = '#FFFFFF';
                    }} else {{
                        arrow.innerHTML = `▼`;
                        arrow.style.color = '#FFFFFF';
                    }}
                }} else {{
                    // Column is unsorted - show default sort icon (light gray)
                    th.classList.remove('sorted');
                    arrow.innerHTML = `<svg viewBox="0 0 320 512" width="10" height="10" style="display: inline-block; vertical-align: middle; fill: currentColor;"><path d="M137.4 41.4c12.5-12.5 32.8-12.5 45.3 0l128 128c9.2 9.2 11.9 22.9 6.9 34.9s-16.6 19.8-29.6 19.8H32c-12.9 0-24.6-7.8-29.6-19.8s-2.2-25.7 6.9-34.9l128-128zm0 429.3l-128-128c-9.2-9.2-11.9-22.9-6.9-34.9s16.6-19.8 29.6-19.8H288c12.9 0 24.6 7.8 29.6 19.8s2.2 25.7-6.9 34.9l-128 128c-12.5 12.5-32.8 12.5-45.3 0z"/></svg>`;
                    arrow.style.color = 'rgba(255, 255, 255, 0.8)';
                }}
            }});
        }}

        // Render objects table
        function renderObjectsTable() {{
            const tbody = document.getElementById('objectsTableBody');
            if (!tbody) {{
                console.warn('objectsTableBody not found');
                return;
            }}
            tbody.innerHTML = '';

            visibleObjectsData.forEach(obj => {{
                const selectionKey = getObjectSelectionKey(obj);
                const isSelected = selectedObjects.has(selectionKey);
                const statusBgColor = obj.conversion_status === 'Success' ? '#E6F4EA' : '#FEF7E0';
                const statusTextColor = obj.conversion_status === 'Success' ? '#1E7E34' : '#7A6520';

                // HTML escape function
                const escapeHtml = (str) => {{
                    const div = document.createElement('div');
                    div.textContent = str || '';
                    return div.innerHTML;
                }}
                const escapeAttr = (str) => String(str || '')
                    .replace(/&/g, '&amp;')
                    .replace(/"/g, '&quot;')
                    .replace(/'/g, '&#39;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;');

                const row = document.createElement('tr');
                row.className = 'object-row';
                row.dataset.name = obj.name;
                row.dataset.type = obj.type;
                row.dataset.wave = obj.wave;
                row.dataset.status = obj.conversion_status;
                row.dataset.hasMissing = obj.has_missing_deps;

                // Create cells with tooltips for truncated content
                const missingDepsBgColor = obj.has_missing_deps ? '#FEE2E2' : '#F0FDF4';
                const missingDepsTextColor = obj.has_missing_deps ? '#991B1B' : '#166534';
                const missingDepsText = obj.has_missing_deps ? 'Yes' : 'No';

                const cells = [
                    `<input type="checkbox" class="row-checkbox" ${{isSelected ? 'checked' : ''}} data-key="${{escapeAttr(selectionKey)}}" style="cursor: pointer; width: 14px; height: 14px;">`,
                    `<div class="object-name-cell" data-tooltip="${{escapeAttr(obj.display_name || obj.name)}}" style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"><span style="color: #111827; font-weight: 500; font-size: 0.8rem;">${{escapeHtml(obj.display_name || obj.name)}}</span></div>`,
                    `<span style="background-color: #F3F4F6; color: #374151; padding: 2px 6px; border-radius: 3px; font-size: 0.7rem; font-weight: 500; white-space: nowrap;">${{escapeHtml(obj.type)}}</span>`,
                    `<div data-tooltip="${{escapeAttr(obj.file)}}" style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #6B7280; font-size: 0.75rem;"><span>${{escapeHtml(obj.file)}}</span></div>`,
                    `<span style="font-weight: 500; color: #374151; font-size: 0.8rem;">${{obj.wave}}</span>`,
                    `<span style="color: #6B7280; font-size: 0.8rem;">${{obj.dependencies}}</span>`,
                    `<span style="color: #6B7280; font-size: 0.8rem;">${{obj.dependents}}</span>`,
                    `<span style="background-color: ${{statusBgColor}}; color: ${{statusTextColor}}; padding: 2px 6px; border-radius: 3px; font-size: 0.7rem; font-weight: 500; white-space: nowrap;">${{escapeHtml(obj.conversion_status)}}</span>`,
                    `<span style="background-color: ${{missingDepsBgColor}}; color: ${{missingDepsTextColor}}; padding: 2px 6px; border-radius: 3px; font-size: 0.7rem; font-weight: 500; white-space: nowrap;">${{missingDepsText}}</span>`
                ];

                row.innerHTML = cells.map((cell, idx) => {{
                    const align = [4, 5, 6, 8].includes(idx) ? 'center' : 'left';
                    return `<td style="text-align: ${{align}};">${{cell}}</td>`;
                }}).join('');

                // Add checkbox event listener
                const checkbox = row.querySelector('.row-checkbox');
                if (checkbox) {{
                    checkbox.addEventListener('change', function() {{
                        if (this.checked) {{
                            selectedObjects.add(selectionKey);
                        }} else {{
                            selectedObjects.delete(selectionKey);
                        }}
                        updateSelectedCount();
                        syncSelectAllCheckboxState();
                    }});
                }}

                row.style.cursor = 'pointer';
                row.addEventListener('click', function(e) {{
                    if (e.target && e.target.closest && e.target.closest('input, button, a')) return;
                    openObjectDetailsModal(obj);
                }});

                tbody.appendChild(row);
            }});

            syncSelectAllCheckboxState();
        }}

        function syncSelectAllCheckboxState() {{
            const selectAllCheckbox = document.getElementById('selectAllCheckbox');
            if (!selectAllCheckbox) return;
            const checkboxes = document.querySelectorAll('.row-checkbox');
            const total = checkboxes.length;
            const checked = Array.from(checkboxes).filter(cb => cb.checked).length;

            if (total === 0) {{
                selectAllCheckbox.checked = false;
                selectAllCheckbox.indeterminate = false;
                return;
            }}

            selectAllCheckbox.checked = checked === total;
            selectAllCheckbox.indeterminate = checked > 0 && checked < total;
        }}

        function copyObjectNameToClipboard(text, anchorEl) {{
            const copyText = String(text || '');
            const onSuccess = () => showCopiedSvgBadge(anchorEl);
            const onError = () => showCopiedSvgBadge(anchorEl);
            if (navigator.clipboard && navigator.clipboard.writeText) {{
                navigator.clipboard.writeText(copyText).then(onSuccess).catch(() => fallbackCopyObjectName(copyText, onSuccess, onError));
            }} else {{
                fallbackCopyObjectName(copyText, onSuccess, onError);
            }}
        }}

        function fallbackCopyObjectName(text, onSuccess, onError) {{
            try {{
                const textArea = document.createElement('textarea');
                textArea.value = text;
                textArea.style.position = 'fixed';
                textArea.style.left = '-9999px';
                document.body.appendChild(textArea);
                textArea.select();
                const ok = document.execCommand('copy');
                document.body.removeChild(textArea);
                if (ok) onSuccess();
                else onError();
            }} catch (err) {{
                onError();
            }}
        }}

        function showCopiedSvgBadge(anchorEl) {{
            if (!anchorEl) return;
            const badge = document.createElement('div');
            badge.innerHTML = `
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path d="M20 6L9 17l-5-5" stroke="#059669" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <span style="font-size: 11px; color: #065F46; font-weight: 600; margin-left: 4px;">Copied</span>
            `;
            Object.assign(badge.style, {{
                position: 'fixed',
                display: 'inline-flex',
                alignItems: 'center',
                background: 'rgba(240, 253, 244, 0.96)',
                border: '1px solid rgba(16, 185, 129, 0.35)',
                borderRadius: '999px',
                padding: '3px 8px',
                zIndex: '12000',
                boxShadow: '0 6px 16px rgba(6, 95, 70, 0.18)',
                pointerEvents: 'none',
                opacity: '0',
                transform: 'translateY(-4px)',
                transition: 'opacity 120ms ease, transform 120ms ease'
            }});
            document.body.appendChild(badge);
            const r = anchorEl.getBoundingClientRect();
            badge.style.left = `${{Math.max(8, r.left + 8)}}px`;
            badge.style.top = `${{Math.max(8, r.top - 24)}}px`;
            requestAnimationFrame(() => {{
                badge.style.opacity = '1';
                badge.style.transform = 'translateY(0)';
            }});
            setTimeout(() => {{
                badge.style.opacity = '0';
                badge.style.transform = 'translateY(-4px)';
                setTimeout(() => badge.remove(), 140);
            }}, 900);
        }}

        // Click-to-copy for compact object names in the other summary tables.
        document.addEventListener('click', function(e) {{
            const topObj = e.target.closest('.copyable-top-object');
            if (!topObj) return;
            e.preventDefault();
            e.stopPropagation();
            const valueToCopy = (topObj.textContent || '').trim();
            if (!valueToCopy) return;
            copyObjectNameToClipboard(valueToCopy, topObj);
        }});

        // The two Top 5 tables open the same object-details window as All Objects.
        document.addEventListener('click', function(e) {{
            const row = e.target.closest('.top-impact-row');
            if (!row || (e.target.closest && e.target.closest('input, button, a'))) return;
            const name = row.getAttribute('data-object-name') || '';
            const obj = (Array.isArray(allObjectsData) ? allObjectsData : []).find(function(item) {{
                return item && item.name === name;
            }});
            if (obj) openObjectDetailsModal(obj);
        }});

        // Toggle select all
        function toggleSelectAll() {{
            const selectAllCheckbox = document.getElementById('selectAllCheckbox');
            if (!selectAllCheckbox) return;

            const checkboxes = document.querySelectorAll('.row-checkbox');

            if (selectAllCheckbox.checked) {{
                checkboxes.forEach(cb => {{
                    cb.checked = true;
                    const objectKey = cb.dataset.key;
                    if (objectKey) selectedObjects.add(objectKey);
                }});
            }} else {{
                checkboxes.forEach(cb => {{
                    cb.checked = false;
                }});
                selectedObjects.clear();
            }}

            updateSelectedCount();
            syncSelectAllCheckboxState();
        }}

        // Select all visible objects
        function selectAllVisibleObjects() {{
            visibleObjectsData.forEach(obj => {{
                selectedObjects.add(getObjectSelectionKey(obj));
            }});
            renderObjectsTable();
            updateSelectedCount();
        }}

        // Clear object selection
        function clearObjectSelection() {{
            selectedObjects.clear();
            renderObjectsTable();
            updateSelectedCount();
            syncSelectAllCheckboxState();
        }}

        // Update selected count
        function updateSelectedCount() {{
            const count = selectedObjects.size;
            document.getElementById('selectedCountTable').textContent = `${{count}} selected`;
        }}

        // Update visible count
        function updateVisibleCount() {{
            const count = visibleObjectsData.length;
            const total = allObjectsData.length;
            document.getElementById('visibleCountTable').textContent = `Showing ${{count}} of ${{total}} objects`;
        }}

        // Download objects CSV
        function downloadObjectsCSV(mode = 'all') {{
            // Close the export menu
            document.getElementById('exportMenu').style.display = 'none';

            const headers = ['Object Name', 'Type', 'File', 'Wave', 'Dependencies', 'Dependents', 'Conversion Status', 'Has Missing Deps'];
            const rows = [headers];

            let dataToExport = [];
            if (mode === 'selected') {{
                // Export only selected objects
                dataToExport = allObjectsData.filter(obj => selectedObjects.has(getObjectSelectionKey(obj)));

                // If no objects selected, export empty CSV with just headers
                if (dataToExport.length === 0) {{
                    alert('No objects selected. Export will contain only headers.');
                }}
            }} else {{
                // Export full dataset (ignore current filters)
                dataToExport = allObjectsData;
            }}

            dataToExport.forEach(obj => {{
                rows.push([
                    obj.display_name || obj.name,
                    obj.type,
                    obj.file,
                    obj.wave,
                    obj.dependencies,
                    obj.dependents,
                    obj.conversion_status,
                    obj.has_missing_deps ? 'Yes' : 'No'
                ]);
            }});

            const csvContent = rows.map(r => r.map(cell => {{
                if (cell == null) return '';
                const str = String(cell);
                if (str.includes(',') || str.includes('"') || str.includes('\\n')) {{
                    return '"' + str.replace(/"/g, '""') + '"';
                }}
                return str;
            }}).join(',')).join('\\n');

            const blob = new Blob([csvContent], {{ type: 'text/csv;charset=utf-8;' }});
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = mode === 'selected' ? 'objects_selected.csv' : 'objects_all.csv';
            link.click();
        }}

        // Column resizing functionality
        function initColumnResizing() {{
            const table = document.getElementById('objectsTable');
            if (!table) return;

            const resizers = table.querySelectorAll('.column-resizer');
            let isResizing = false;
            let currentResizer = null;
            let startX = 0;
            let startWidth = 0;

            resizers.forEach(resizer => {{
                resizer.addEventListener('mousedown', function(e) {{
                    isResizing = true;
                    currentResizer = e.target;
                    const th = currentResizer.closest('th');
                    startX = e.pageX;
                    startWidth = th.offsetWidth;

                    document.body.style.cursor = 'col-resize';
                    document.body.style.userSelect = 'none';
                    e.preventDefault();
                }});
            }});

            document.addEventListener('mousemove', function(e) {{
                if (!isResizing) return;

                const th = currentResizer.closest('th');
                const diff = e.pageX - startX;

                // Get the minimum width from the column's CSS or use default
                const computedStyle = window.getComputedStyle(th);
                const minWidth = parseInt(computedStyle.minWidth) || 50;

                const newWidth = Math.max(minWidth, startWidth + diff);
                th.style.width = newWidth + 'px';
            }});

            document.addEventListener('mouseup', function() {{
                if (isResizing) {{
                    isResizing = false;
                    currentResizer = null;
                    document.body.style.cursor = '';
                    document.body.style.userSelect = '';
                }}
            }});
        }}

        // Initialize table on page load
        document.addEventListener('DOMContentLoaded', function() {{
            renderObjectsTable();
            updateVisibleCount();
            updateObjectsFilterButtonLabels();
            // Filters are now handled by dropdown selects, not column headers
            // initObjectsHeaderFilterTriggers();
            // renderObjectsFilterChips();
            // updateFilterableColumnsState();
            initColumnResizing();
            updateSortIndicators();
            document.addEventListener('keydown', function(e) {{
                if (e.key === 'Escape') closeObjectDetailsModal();
            }});
        }});

        // Explicitly expose functions to global scope for inline event handlers
        window.filterObjectsTable = filterObjectsTable;
        window.sortObjectsTable = sortObjectsTable;
        window.toggleSelectAll = toggleSelectAll;
        window.selectAllVisibleObjects = selectAllVisibleObjects;
        window.clearObjectSelection = clearObjectSelection;
        window.downloadObjectsCSV = downloadObjectsCSV;
        window.closeObjectDetailsModal = closeObjectDetailsModal;
        window.copyModalObjectName = copyModalObjectName;

        // Info-icon tooltips — appended to <body> so they escape any overflow/transform
        (function() {{
            let tip = null;
            document.addEventListener('mouseover', function(e) {{
                const icon = e.target.closest('.info-icon[data-info]');
                if (!icon) return;
                if (tip) tip.remove();
                tip = document.createElement('div');
                tip.className = 'info-tooltip';
                tip.textContent = icon.getAttribute('data-info');
                document.body.appendChild(tip);
                const rect = icon.getBoundingClientRect();
                const tipW = tip.offsetWidth;
                const tipH = tip.offsetHeight;
                let left = rect.left + rect.width / 2 - tipW / 2;
                left = Math.max(8, Math.min(left, window.innerWidth - tipW - 8));
                tip.style.left = left + 'px';
                tip.style.top = (rect.top - tipH - 10) + 'px';
            }});
            document.addEventListener('mouseout', function(e) {{
                const icon = e.target.closest('.info-icon[data-info]');
                if (!icon) return;
                if (tip) {{ tip.remove(); tip = null; }}
            }});
        }})();

        // Metric-card tooltips — follow cursor for natural positioning
        (function() {{
            let tip = null;
            const OFFSET_X = 14;
            const OFFSET_Y = 14;

            function placeTip(evt) {{
                if (!tip) return;
                const tipW = tip.offsetWidth || 0;
                const tipH = tip.offsetHeight || 0;
                const maxX = window.innerWidth - tipW - 8;
                const maxY = window.innerHeight - tipH - 8;
                const x = Math.max(8, Math.min(evt.clientX + OFFSET_X, maxX));
                const y = Math.max(8, Math.min(evt.clientY + OFFSET_Y, maxY));
                tip.style.left = x + 'px';
                tip.style.top = y + 'px';
            }}

            document.addEventListener('mouseover', function(e) {{
                const card = e.target.closest('.metric-card[data-tooltip]');
                if (!card) return;
                if (tip) tip.remove();
                tip = document.createElement('div');
                tip.className = 'metric-tooltip-cursor';
                tip.textContent = card.getAttribute('data-tooltip') || '';
                document.body.appendChild(tip);
            }});

            document.addEventListener('mousemove', function(e) {{
                if (!tip) return;
                placeTip(e);
            }});

            document.addEventListener('mouseout', function(e) {{
                const card = e.target.closest('.metric-card[data-tooltip]');
                if (!card) return;
                if (tip) {{
                    tip.remove();
                    tip = null;
                }}
            }});
        }})();

        // Object/File name tooltips in All Objects table — follow cursor
        (function() {{
            let tip = null;
            const OFFSET_X = 12;
            const OFFSET_Y = 12;

            function removeTip() {{
                if (tip) {{
                    tip.remove();
                    tip = null;
                }}
            }}

            function placeTip(evt) {{
                if (!tip) return;
                const tipW = tip.offsetWidth || 0;
                const tipH = tip.offsetHeight || 0;
                const maxX = window.innerWidth - tipW - 8;
                const maxY = window.innerHeight - tipH - 8;
                const x = Math.max(8, Math.min(evt.clientX + OFFSET_X, maxX));
                const y = Math.max(8, Math.min(evt.clientY + OFFSET_Y, maxY));
                tip.style.left = x + 'px';
                tip.style.top = y + 'px';
            }}

            document.addEventListener('mouseover', function(e) {{
                const cell = e.target.closest('.object-table [data-tooltip], .copyable-top-object[data-tooltip], .top-impact-object[data-tooltip]');
                if (!cell) return;
                removeTip();
                tip = document.createElement('div');
                tip.textContent = cell.getAttribute('data-tooltip') || '';
                Object.assign(tip.style, {{
                    position: 'fixed',
                    background: 'rgba(255, 255, 255, 0.9)',
                    color: '#102E46',
                    border: '1px solid rgba(16, 46, 70, 0.12)',
                    borderRadius: '6px',
                    padding: '6px 10px',
                    fontSize: '0.8rem',
                    lineHeight: '1.35',
                    maxWidth: '420px',
                    zIndex: '10000',
                    boxShadow: '0 8px 24px rgba(16, 46, 70, 0.14)',
                    pointerEvents: 'none',
                    backdropFilter: 'blur(2px)'
                }});
                document.body.appendChild(tip);
            }});

            document.addEventListener('mousemove', function(e) {{
                if (!tip) return;
                placeTip(e);
            }});

            document.addEventListener('mouseout', function(e) {{
                const cell = e.target.closest('.object-table [data-tooltip], .copyable-top-object[data-tooltip], .top-impact-object[data-tooltip]');
                if (!cell) return;
                removeTip();
            }});
        }})();
    </script>
    '''

    html += '''
</body>
</html>
'''

    return html

def main():
    parser = argparse.ArgumentParser(description='Generate HTML wave migration report')
    parser.add_argument('--waves-json', '-a', required=True,
                       help='Path to waves.json produced by the dependency analyzer')
    parser.add_argument('--output', '-o', required=False,
                       help='Output HTML file path (optional)')
    parser.add_argument('--reports-dir', '-r', required=False,
                       help='Path to Reports directory containing TopLevelCodeUnits CSV (optional)')
    parser.add_argument('--registry-dir', required=False,
                       help='Path to registry directory. When provided, missing objects are loaded from registry entries with isMissing=true.')

    args = parser.parse_args()

    generate_html_report(args.waves_json, args.output, args.reports_dir, args.registry_dir)


if __name__ == '__main__':
    main()