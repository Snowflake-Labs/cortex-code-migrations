#!/usr/bin/env python3
"""
Generate Multi-Tab HTML Report for Migration Assessment

Creates an interactive HTML report with 4 tabs:
1. Dependencies Report (dependency analysis and object inventory)
2. Exclusion Report (object exclusion detection analysis)
3. Dynamic SQL Report (dynamic SQL pattern analysis)
4. SSIS Report (ETL assessment analysis)

Uses Vue.js 3, Chart.js, and Tailwind CSS following Snowflake styling.
"""

import argparse
import base64
import csv
import json
import os
import re
import sys
import tempfile
import traceback
import html as html_escape_module
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# Waves-generator modules (optional)
try:
    _waves_scripts = str(Path(__file__).parent.parent / 'waves-generator' / 'scripts')
    if _waves_scripts not in sys.path:
        sys.path.insert(0, _waves_scripts)
    from load_data_html_report import (
        load_issues_estimation,
        load_toplevel_code_units,
        load_partition_membership,
        parse_graph_summary,
        parse_cycles,
        parse_excluded_edges,
        load_toplevel_objects_estimation,
        find_estimation_reports,
        load_estimation_grand_totals,
        estimate_hours_for_object,
        load_missing_object_references,
        load_missing_refs,
    )
    from generate_html_report import generate_html_report as generate_full_waves_report
    from snowconvert_reports import load_registry_entries
    WAVES_SUPPORT = True
except ImportError as e:
    print(f"Warning: Waves generator modules not available: {e}", file=sys.stderr)
    WAVES_SUPPORT = False

# SSIS report generator (optional)
try:
    from ssis_report import generate_ssis_html_content
    SSIS_SUPPORT = True
except ImportError as e:
    print(f"Warning: SSIS report generator not available: {e}", file=sys.stderr)
    SSIS_SUPPORT = False


def generate_ai_summary(summary: Dict, temp_staging: List, deprecated: List, testing: List) -> str:
    """Generate AI summary of the exclusion analysis"""
    total = summary.get('total_objects_found', 0)
    temp_count = len(temp_staging)
    deprec_count = len(deprecated)
    testing_count = len(testing)
    
    temp_pct = (temp_count / total * 100) if total > 0 else 0
    deprec_pct = (deprec_count / total * 100) if total > 0 else 0
    testing_pct = (testing_count / total * 100) if total > 0 else 0
    
    return f"""
    <p><strong>Analysis Overview:</strong></p>
    <p>This analysis examined <strong>{summary.get('total_files_analyzed', 0)} SQL files</strong> containing <strong>{total} database objects</strong>. 
    The analysis identified three key categories of objects that may require special attention during migration planning.</p>
    
    <p><strong>Temporary/Staging Objects ({temp_count} objects, {temp_pct:.1f}%):</strong></p>
    <p>Found <strong>{temp_count} temporary or staging objects</strong> that may not require migration. 
    These objects should be reviewed to determine if they can be excluded from the migration scope, potentially reducing migration effort.</p>
    
    <p><strong>Deprecated/Legacy Objects ({deprec_count} objects, {deprec_pct:.1f}%):</strong></p>
    <p>Identified <strong>{deprec_count} deprecated or legacy objects</strong> that should be considered for removal rather than migration. 
    These objects represent technical debt and should be prioritized for deprecation planning.</p>
    
    <p><strong>Testing Objects ({testing_count} objects, {testing_pct:.1f}%):</strong></p>
    <p>Detected <strong>{testing_count} objects</strong> with testing-related naming patterns (test, fake, mock, demo, sample). 
    These objects require manual review to determine their purpose and whether they should be included in the migration.</p>
    
    <p><strong>Recommendations:</strong></p>
    <ul style="margin-left: 20px; margin-top: 10px;">
        <li>Review temporary/staging objects to confirm they can be excluded from migration</li>
        <li>Plan deprecation strategy for deprecated/legacy objects before migration</li>
        <li>Investigate testing objects to determine their purpose and migration necessity</li>
        <li>Consider consolidating or removing duplicate objects with version numbers</li>
    </ul>
    """


def generate_type_filter_options(temp_staging: List, deprecated: List, testing: List) -> str:
    """Generate options for the type filter dropdown"""
    all_types = set()
    
    for obj in temp_staging + deprecated + testing:
        obj_type = obj.get('type', 'Unknown')
        if obj_type:
            all_types.add(obj_type)
    
    sorted_types = sorted(all_types)
    options = []
    for t in sorted_types:
        escaped_type = html_escape_module.escape(str(t))
        options.append(f'<option value="{escaped_type}">{escaped_type}</option>')
    
    return ''.join(options)


def generate_reason_filter_options(temp_staging: List, deprecated: List, testing: List) -> str:
    """Generate options for the reason filter dropdown"""
    all_reasons = set()
    
    for obj in temp_staging + deprecated + testing:
        matched_patterns = obj.get('matched_patterns', [])
        if matched_patterns:
            all_reasons.add(matched_patterns[0])  # Primary pattern
    
    # Add duplicate files as a reason
    all_reasons.add('duplicate files')
    
    sorted_reasons = sorted(all_reasons)
    options = []
    for r in sorted_reasons:
        escaped_reason = html_escape_module.escape(str(r))
        options.append(f'<option value="{escaped_reason}">{escaped_reason}</option>')
    
    return ''.join(options)


def generate_schema_filter_options(temp_staging: List, deprecated: List, testing: List) -> str:
    """Generate options for the schema filter dropdown"""
    all_schemas = set()
    
    for obj in temp_staging + deprecated + testing:
        schema = obj.get('schema', 'Unknown')
        if schema:
            all_schemas.add(schema)
    
    sorted_schemas = sorted(all_schemas)
    options = []
    for s in sorted_schemas:
        escaped_schema = html_escape_module.escape(str(s))
        options.append(f'<option value="{escaped_schema}">{escaped_schema}</option>')
    
    return ''.join(options)


def generate_exclusion_table_rows(temp_staging: List, deprecated: List, testing: List, version_analysis: Dict = None, duplicate_objects: List = None) -> str:
    """Generate table rows for exclusion objects"""
    
    # Build version lookup from version_analysis
    version_lookup = {}
    if version_analysis:
        for group in version_analysis.get('objects_with_versions', []):
            prod_name = group.get('production_full_name', '')
            prod_file = group.get('production_file', '')
            version_lookup[prod_name] = {
                'is_production': True,
                'total_versions': group.get('total_versions', 0),
                'production_file': prod_file,
                'deprecated_versions': group.get('deprecated_versions', [])
            }
            for dep_obj in group.get('deprecated_versions', []):
                dep_name = dep_obj.get('full_name', '')
                version_lookup[dep_name] = {
                    'is_production': False,
                    'production_version': prod_name,
                    'production_file': prod_file,
                    'total_versions': group.get('total_versions', 0)
            }
    
    # Deduplicate objects across categories and combine reasons
    objects_by_name = {}
    
    # Process temp/staging objects
    for obj in temp_staging:
        full_name = obj.get('full_name', 'Unknown')
        if full_name not in objects_by_name:
            objects_by_name[full_name] = {
                'full_name': full_name,
                'schema': obj.get('schema', 'Unknown'),
                'type': obj.get('type', 'Unknown'),
                'file': obj.get('file', 'Unknown'),
                'classifications': [],
                'matched_patterns': [],
                'raw': obj
            }
        objects_by_name[full_name]['classifications'].append('temp')
        objects_by_name[full_name]['matched_patterns'].extend(obj.get('matched_patterns', []))
    
    # Process deprecated objects
    for obj in deprecated:
        full_name = obj.get('full_name', 'Unknown')
        if full_name not in objects_by_name:
            objects_by_name[full_name] = {
                'full_name': full_name,
                'schema': obj.get('schema', 'Unknown'),
                'type': obj.get('type', 'Unknown'),
                'file': obj.get('file', 'Unknown'),
                'classifications': [],
                'matched_patterns': [],
                'raw': obj
            }
        objects_by_name[full_name]['classifications'].append('deprecated')
        objects_by_name[full_name]['matched_patterns'].extend(obj.get('matched_patterns', []))
        # Keep deprecated raw for version lookup
        if 'deprecated' in objects_by_name[full_name]['classifications']:
            objects_by_name[full_name]['raw'] = obj
    
    # Process testing objects
    for obj in testing:
        full_name = obj.get('full_name', 'Unknown')
        if full_name not in objects_by_name:
            objects_by_name[full_name] = {
                'full_name': full_name,
                'schema': obj.get('schema', 'Unknown'),
                'type': obj.get('type', 'Unknown'),
                'file': obj.get('file', 'Unknown'),
                'classifications': [],
                'matched_patterns': [],
                'raw': obj
            }
        objects_by_name[full_name]['classifications'].append('testing')
        objects_by_name[full_name]['matched_patterns'].extend(obj.get('matched_patterns', []))
    
    # Build all_objects list from deduplicated data
    all_objects = []
    classification_labels = {'temp': 'Temp/Staging', 'deprecated': 'Deprecated', 'testing': 'Testing'}
    classification_priority = {'deprecated': 0, 'temp': 1, 'testing': 2}  # Priority for primary classification
    
    for full_name, data in objects_by_name.items():
        # Sort classifications by priority and pick primary
        sorted_classifications = sorted(data['classifications'], key=lambda c: classification_priority.get(c, 99))
        primary_classification = sorted_classifications[0]
        
        # Combine classification labels
        combined_labels = ', '.join([classification_labels[c] for c in sorted_classifications])
        
        # Deduplicate matched patterns while preserving order
        seen_patterns = set()
        unique_patterns = []
        for p in data['matched_patterns']:
            if p not in seen_patterns:
                seen_patterns.add(p)
                unique_patterns.append(p)
        
        all_objects.append({
            'full_name': full_name,
            'schema': data['schema'],
            'type': data['type'],
            'file': data['file'],
            'classification': primary_classification,
            'classifications': sorted_classifications,  # All classifications for filtering
            'classification_label': combined_labels,
            'matched_patterns': unique_patterns,
            'raw': data['raw']
        })
    
    # Add duplicate objects - grouped by full_name (one row per unique object)
    if duplicate_objects:
        # Group duplicates by full_name
        duplicates_by_name = {}
        for obj in duplicate_objects:
            full_name = obj.get('full_name', 'Unknown')
            if full_name not in duplicates_by_name:
                duplicates_by_name[full_name] = []
            duplicates_by_name[full_name].append(obj)
        
        # Create one combined entry per unique object
        for full_name, dup_list in duplicates_by_name.items():
            # Use the first duplicate as the base - it already has all the data we need:
            # - all_files_for_object: list of all files
            # - primary_file: recommended file
            # - depended_by: dependency info (on each duplicate)
            base_obj = dup_list[0]
            all_files = base_obj.get('all_files_for_object', [])
            
            # Collect all dependents and dependencies from all duplicates
            all_dependents = set()
            all_dependencies = set()
            for dup in dup_list:
                all_dependents.update(dup.get('depended_by', []))
                all_dependencies.update(dup.get('depends_on', []))
            
            # Create combined entry using existing data
            combined_obj = base_obj.copy()
            combined_obj['all_dependents'] = list(all_dependents)
            combined_obj['all_dependencies'] = list(all_dependencies)
            
            all_objects.append({
                'full_name': full_name,
                'schema': base_obj.get('schema', 'Unknown'),
                'type': base_obj.get('type', 'Unknown'),
                'file': f"{len(all_files)} files",
                'classification': 'duplicate',
                'classification_label': 'Duplicate',
                'raw': combined_obj
            })
    
    # Sort by classification, then by name
    all_objects.sort(key=lambda x: (x['classification'], x['full_name'].lower()))
    
    rows = []
    row_id = 0
    
    for obj in all_objects:
        full_name = html_escape_module.escape(str(obj['full_name']))
        schema = html_escape_module.escape(str(obj['schema']))
        obj_type = html_escape_module.escape(str(obj['type']))
        file_name = html_escape_module.escape(str(obj['file']))
        classification = obj['classification']
        classification_label = obj['classification_label']
        raw = obj['raw']
        
        # Get reason from matched patterns (use combined patterns if available, else from raw)
        matched_patterns = obj.get('matched_patterns') or raw.get('matched_patterns', [])
        if classification == 'duplicate':
            reason = 'duplicate files'
        elif matched_patterns:
            reason = ', '.join(matched_patterns)  # Combine all matched patterns
        else:
            reason = 'other'
        reason_display = html_escape_module.escape(str(reason))
        
        # Classification badge colors
        badge_class = f'classification-{classification}'
        
        # Build details content
        details_items = []
        
        # Version suggestion (from version analysis) - only for deprecated objects
        if classification == 'deprecated':
            obj_full_name = raw.get('full_name', '')
            if obj_full_name in version_lookup:
                ver_info = version_lookup[obj_full_name]
                if not ver_info['is_production']:
                    prod_version = html_escape_module.escape(ver_info['production_version'])
                    prod_file = html_escape_module.escape(ver_info.get('production_file', ''))
                    version_html = '<div class="refs-list">'
                    version_html += f'<div class="refs-item"><code>{prod_version}</code></div>'
                    if prod_file:
                        version_html += f'<div class="refs-item" style="font-size: 0.8rem; color: #64748B;">File: {prod_file}</div>'
                    version_html += '</div>'
                    details_items.append(f'''<div class="detail-item">
                        <span class="detail-label">Suggested Version:</span>
                        {version_html}
                    </div>''')
        
        # Duplicate-specific information (Source Files)
        if classification == 'duplicate':
            # Use data already computed by analyze_duplicate_objects()
            all_files = raw.get('all_files_for_object', [])
            primary_file = raw.get('primary_file', '')
            
            # Show all files - simple list with recommended marked
            if all_files:
                files_html = '<div class="duplicate-files-list">'
                for file_path in all_files:
                    escaped_path = html_escape_module.escape(str(file_path))
                    is_recommended = (file_path == primary_file)
                    recommended_tag = '<span class="file-recommended-tag">✓ Recommended</span>' if is_recommended else ''
                    
                    files_html += f'''<div class="duplicate-file-item">
                        <code class="file-path">{escaped_path}</code>
                        {recommended_tag}
                    </div>'''
                
                files_html += '</div>'
                details_items.append(f'''<div class="detail-item">
                    <span class="detail-label">Source Files:</span>
                    {files_html}
                </div>''')
        
        # References info - what this object depends on (unified for all categories)
        deps = raw.get('all_dependencies') or raw.get('depends_on', [])
        if deps:
            deps_html = '<div class="refs-list">'
            for dep_name in deps[:10]:  # Show up to 10 items
                escaped_dep = html_escape_module.escape(str(dep_name))
                deps_html += f'<div class="refs-item"><code>{escaped_dep}</code></div>'
            if len(deps) > 10:
                deps_html += f'<div class="refs-item refs-more">... and {len(deps) - 10} more</div>'
            deps_html += '</div>'
            details_items.append(f'''<div class="detail-item">
                <span class="detail-label">References:</span>
                {deps_html}
            </div>''')
        
        # Referenced by info - what depends on this object (unified for all categories)
        refs = raw.get('all_dependents') or raw.get('depended_by', [])
        if refs:
            refs_html = '<div class="refs-list">'
            for ref_name in refs[:10]:  # Show up to 10 items
                escaped_ref = html_escape_module.escape(str(ref_name))
                refs_html += f'<div class="refs-item"><code>{escaped_ref}</code></div>'
            if len(refs) > 10:
                refs_html += f'<div class="refs-item refs-more">... and {len(refs) - 10} more</div>'
            refs_html += '</div>'
            details_items.append(f'''<div class="detail-item">
                <span class="detail-label">Referenced By:</span>
                {refs_html}
            </div>''')
        
        # Only build details HTML if there are items to show
        has_details = len(details_items) > 0
        details_html = ''
        if has_details:
            details_content = ''.join(details_items)
            details_html = f'''
            <tr class="details-row" id="details-{row_id}" style="display: none;" data-classification="{classification}" data-type="{obj_type}">
                <td colspan="5" class="details-cell">{details_content}</td>
            </tr>'''
        
        # Show expand icon only if there are details
        expand_icon = '<span class="expand-icon">+</span>' if has_details else ''
        row_class = 'expandable' if has_details else ''
        onclick_attr = f'onclick="toggleDetails({row_id}, this)"' if has_details else ''
        
        # Get all classifications for filtering (comma-separated)
        all_classifications = obj.get('classifications', [classification])
        classifications_attr = ','.join(all_classifications)
        
        rows.append(f'''
            <tr data-classification="{classifications_attr}" data-type="{obj_type}" data-schema="{schema}" data-reason="{reason_display}" class="{row_class}" {onclick_attr}>
                <td class="name-cell">
                    <div class="object-name"><code>{full_name}</code> {expand_icon}</div>
                    <div class="object-file">{file_name}</div>
                </td>
                <td>{schema}</td>
                <td>{obj_type}</td>
                <td>{reason_display}</td>
                <td><span class="classification-badge {badge_class}">{classification_label}</span></td>
            </tr>
            {details_html}
        ''')
        row_id += 1
    
    return ''.join(rows)


def load_json_data(json_file: Path) -> Dict:
    """Load and parse JSON file"""
    if not json_file.exists():
        raise FileNotFoundError(f"JSON file not found: {json_file}")
    
    with open(json_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def flatten_dynamic_sql_json(data: Dict) -> List[Dict]:
    """Convert dynamic SQL nested JSON structure into flat array"""
    flattened = []
    code_units = data.get('code_units', {})
    
    for code_unit_id, cu_data in code_units.items():
        metadata = cu_data.get('metadata', {})
        occurrences = cu_data.get('occurrences', [])
        procedure_source = metadata.get('procedure', '') or ''
        
        for occ in occurrences:
            category_data = occ.get('category', [])
            if isinstance(category_data, str):
                category = [c.strip() for c in category_data.split('|') if c.strip()] if category_data else []
            else:
                category = category_data if category_data else []
            
            flattened.append({
                'id': occ.get('id'),
                'name': metadata.get('procedure_name', ''),
                'filename': metadata.get('filename', ''),
                'line': occ.get('line'),
                'procedure_name': metadata.get('procedure_name', ''),
                'procedure_source': procedure_source,
                'code_unit_id': code_unit_id,
                'code_unit_start_line': metadata.get('code_unit_start_line', 0),
                'lines_of_code': metadata.get('lines_of_code', 0),
                'status': occ.get('status', 'PENDING'),
                'category': category,
                'complexity': occ.get('complexity', ''),
                'notes': occ.get('notes', ''),
                'generated_sql': occ.get('generated_sql', ''),
                'sql_classification': occ.get('sql_classification', '')
            })
    
    return flattened


def load_waves_data(analysis_dir: Path, reports_dir: Path = None, issues_json_path: Path = None, registry_dir: Path = None):
    """Load waves/dependency analysis data and generate HTML content for the waves report tab."""
    if not WAVES_SUPPORT:
        return None
    
    try:
        # Generate the full waves HTML report to a temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as tmp:
            tmp_path = Path(tmp.name)
        
        # Find issues-estimation.json if not provided
        if not issues_json_path:
            search_dirs = [analysis_dir, analysis_dir.parent.parent.parent]
            if reports_dir:
                search_dirs.insert(0, Path(reports_dir))
                # Also check SnowConvert subdirectory
                snowconvert_dir = Path(reports_dir) / 'SnowConvert'
                if snowconvert_dir.exists():
                    search_dirs.insert(0, snowconvert_dir)
            
            for search_dir in search_dirs:
                if search_dir.exists():
                    issue_matches = list(search_dir.glob('**/issues-estimation.json'))
                    if issue_matches:
                        issues_json_path = issue_matches[0]
                        break
            
            # Use a dummy path if not found
            if not issues_json_path:
                # Create a minimal issues JSON
                issues_json_path = Path(tempfile.mktemp(suffix='.json'))
                with open(issues_json_path, 'w') as f:
                    json.dump({"Issues": [], "Severities": []}, f)
        
        # Determine the correct reports_dir to pass (should include SnowConvert if it exists)
        reports_dir_to_use = reports_dir
        if reports_dir:
            snowconvert_dir = Path(reports_dir) / 'SnowConvert'
            if snowconvert_dir.exists():
                reports_dir_to_use = snowconvert_dir
        
        # Generate the full waves report
        print(f"Generating waves HTML content...")
        report_path = generate_full_waves_report(
            analysis_dir=str(analysis_dir),
            issues_json_path=str(issues_json_path),
            output_path=str(tmp_path),
            reports_dir=str(reports_dir_to_use) if reports_dir_to_use else None,
            registry_dir=str(registry_dir) if registry_dir else None,
        )
        
        if not report_path or not Path(report_path).exists():
            print(f"Error: Failed to generate waves report")
            return None
        
        # Read the generated HTML and extract the main content
        with open(report_path, 'r', encoding='utf-8') as f:
            full_html = f.read()
        
        # Extract content: everything from container div to its closing tag (before final script tags)
        # Pattern: <div class="container">...(everything)...</div> (before the last <script>)
        match = re.search(r'<div class="container">(.*)</div>\s*<script>', full_html, re.DOTALL)
        if match:
            waves_html_content = match.group(1)  # Get everything inside container
        else:
            # Fallback: try to find container without requiring script after
            match = re.search(r'<div class="container">(.*)</div>', full_html, re.DOTALL)
            if match:
                waves_html_content = match.group(1)
            else:
                waves_html_content = "<p>Error: Could not extract waves content</p>"

        # Remove all <script> tags from HTML content (JavaScript will be added separately)
        waves_html_content = re.sub(r'<script>.*?</script>', '', waves_html_content, flags=re.DOTALL)

        # Extract sidebar navigation for in-page links
        sidebar_match = re.search(r'<nav class="side-nav"[^>]*>(.*?)</nav>', full_html, re.DOTALL)
        waves_sidebar_html = sidebar_match.group(1) if sidebar_match else ""
        
        # Extract ALL JavaScript sections for interactivity (there are multiple script blocks)
        js_matches = re.findall(r'<script>(.*?)</script>', full_html, re.DOTALL)
        raw_waves_js = '\n\n'.join(js_matches) if js_matches else ""
        
        # Add null checks for DOM element access to prevent errors in tabbed context
        # Replace getElementById and addEventListener calls with safe versions
        waves_js = raw_waves_js
        
        # Add safe getElementById wrapper
        waves_js = """
        // Safe DOM access helpers for tabbed context
        const safeGetElementById = (id) => {
            const el = document.getElementById(id);
            if (!el) console.warn(`Element with id '${id}' not found`);
            return el;
        };
        const safeAddEventListener = (elementId, event, handler) => {
            const el = document.getElementById(elementId);
            if (el) {
                el.addEventListener(event, handler);
            } else {
                console.warn(`Cannot add ${event} listener: element '${elementId}' not found`);
            }
        };
        
        """ + raw_waves_js
        
        # Replace problematic getElementById calls with safe version
        waves_js = waves_js.replace(
            "document.getElementById('pipelineView').addEventListener(",
            "safeAddEventListener('pipelineView', "
        ).replace(
            "document.getElementById('pipelineView').addEventListener",
            "safeAddEventListener('pipelineView'"
        )
        
        # Clean up temp files
        # TEMPORARILY DISABLED FOR DEBUGGING
        # try:
        #     tmp_path.unlink()
        # except:
        #     pass
        print(f"DEBUG: Temp waves HTML saved at: {tmp_path}", file=sys.stderr)
        
        return {
            'html_content': waves_html_content,
            'sidebar_html': waves_sidebar_html,
            'javascript': waves_js,
            'has_content': True
        }
    
    except Exception as e:
        print(f"Error loading waves data: {e}", file=sys.stderr)
        traceback.print_exc()
        return None


def generate_waves_html_content(waves_info: Dict) -> tuple:
    """Generate HTML content, sidebar, and JavaScript for waves report tab.

    Returns: (html_content, sidebar_html, javascript)
    """
    if not waves_info or not waves_info.get('has_content'):
        return ("", "", "")

    return (waves_info['html_content'], waves_info.get('sidebar_html', ''), waves_info['javascript'])


def _shared_refs_to_overview(shared_result: Dict) -> Dict:
    """Convert the shared missing-refs loader contract into the Overview UI contract."""
    missing_set = shared_result.get('missing_objects', set()) or set()
    dependents_map = shared_result.get('dependents', {}) or {}
    details = shared_result.get('details', []) or []
    data_source = shared_result.get('data_source', 'none')
    warning_msg = shared_result.get('warning') or ''

    if not missing_set and not details:
        return {
            'missing_objects': [],
            'summary': {},
            'error': warning_msg or None,
            'source': data_source,
        }

    missing_objects = []
    for missing_name in sorted(missing_set, key=lambda x: str(x).lower()):
        dependent_rows = dependents_map.get(missing_name, [])
        callers = sorted({
            str(item.get('caller', '')).strip()
            for item in dependent_rows
            if str(item.get('caller', '')).strip()
        })
        missing_objects.append({
            'referenced': missing_name,
            'callers': callers,
            'dependants_count': len(callers),
            'reference_count': len(dependent_rows),
        })

    return {
        'missing_objects': missing_objects,
        'summary': {
            'total_missing': len(missing_objects),
            'total_references': len(details),
        },
        'source': data_source,
    }


def load_missing_objects_for_overview(
    waves_analysis_dir: Path = None,
    snowconvert_reports_dir: Path = None,
    registry_dir: Path = None,
) -> Dict:
    """Load missing objects for the Overview tab.

    Delegates to :func:`load_missing_refs` (registry-first, CSV fallback)
    and converts the result into the Overview UI contract.
    """
    shared_result = load_missing_refs(
        registry_dir=registry_dir,
        reports_dir=snowconvert_reports_dir,
    )
    overview = _shared_refs_to_overview(shared_result)

    data_source = overview.get('source', 'none')
    count = len(overview.get('missing_objects', []))
    if count:
        print(f"  Found {count} missing objects (source={data_source})")
    elif overview.get('error'):
        print(f"Warning: {overview['error']}", file=sys.stderr)

    return overview


def load_overview_stats(
    waves_analysis_dir: Path,
    partition_membership_path: Path = None,
    snowconvert_reports_dir: Path = None,
    registry_dir: Path = None,
) -> Dict:
    """Load overview statistics from waves analysis.

    Returns dict with object counts by type, total waves, external tables count, source dialect, etc.
    """
    stats = {
        'total_objects': 0,
        'total_waves': 0,
        'objects_by_type': {},
        'conversion_stats': {'Success': 0, 'Partial': 0, 'NotSupported': 0},
        'external_tables_count': 0,
        'source_dialect': ''
    }

    if not waves_analysis_dir:
        return stats

    # Load from partition_membership.csv
    pm_path = partition_membership_path or (waves_analysis_dir / 'partition_membership.csv')
    if pm_path.exists():
        try:
            with open(pm_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                waves_set = set()
                for row in reader:
                    stats['total_objects'] += 1

                    # Track object types
                    category = row.get('category', 'Unknown')
                    stats['objects_by_type'][category] = stats['objects_by_type'].get(category, 0) + 1

                    # Track waves
                    partition = row.get('partition_number', '')
                    if partition:
                        waves_set.add(partition)

                    # Track conversion status
                    conv_status = row.get('conversion_status', '')
                    if conv_status in stats['conversion_stats']:
                        stats['conversion_stats'][conv_status] += 1

                stats['total_waves'] = len(waves_set)
        except Exception as e:
            print(f"Warning: Could not load partition membership: {e}", file=sys.stderr)

    # Load deployment partitions for more details
    dp_path = waves_analysis_dir / 'deployment_partitions.json'
    if dp_path.exists():
        try:
            with open(dp_path, 'r', encoding='utf-8') as f:
                dp_data = json.load(f)
                metadata = dp_data.get('metadata', {})
                stats['total_waves'] = metadata.get('total_partitions', stats['total_waves'])
                stats['total_objects'] = metadata.get('total_objects', stats['total_objects'])
        except Exception as e:
            print(f"Warning: Could not load deployment partitions: {e}", file=sys.stderr)

    # Count temporal tables (SQL Server #/## temp tables) from partition membership
    temporal_count = 0
    if pm_path.exists():
        try:
            with open(pm_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    obj_name = row.get('object_name', '')
                    bare = obj_name.replace('[', '').replace(']', '').rsplit('.', 1)[-1]
                    if bare.startswith('#'):
                        temporal_count += 1
        except Exception:
            pass
    stats['temporal_tables_count'] = temporal_count

    # Load external tables count from registry when available.
    if registry_dir:
        try:
            _entries = load_registry_entries(Path(registry_dir))
            external_count = sum(
                1 for e in _entries
                if e.get("inScope", False)
                and not e.get("isMissing", False)
                and e.get("source", {}).get("objectType", "").upper() == "EXTERNAL TABLE"
            )
            stats['external_tables_count'] = external_count
            if external_count > 0:
                print(f"  - External tables: {external_count} found (from registry)")
        except Exception as e:
            print(f"Warning: Could not load external tables from registry: {e}", file=sys.stderr)

    # Always read source dialect (and external tables if not from registry)
    # from TopLevelCodeUnits CSV — it contains SourceLanguage which the
    # registry does not provide.
    if snowconvert_reports_dir:
        toplevel_csv = _find_toplevel_code_units_csv(snowconvert_reports_dir)
        if toplevel_csv:
            try:
                csv_external_count = 0
                dialect = ''
                with open(toplevel_csv, 'r', encoding='utf-8-sig') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        category = row.get('Category', '').strip()
                        if category == 'EXTERNAL TABLE':
                            csv_external_count += 1
                        if not dialect:
                            dialect = row.get('SourceLanguage', '').strip()
                if not registry_dir:
                    stats['external_tables_count'] = csv_external_count
                stats['source_dialect'] = dialect
                if dialect:
                    print(f"  - Source dialect: {dialect}")
            except Exception as e:
                print(f"Warning: Could not load TopLevelCodeUnits: {e}", file=sys.stderr)

    return stats


def _find_toplevel_code_units_csv(snowconvert_reports_dir: Path) -> Path:
    """Find the TopLevelCodeUnits CSV in the SnowConvert reports directory."""
    reports_dir = Path(snowconvert_reports_dir)
    dirs_to_try = [reports_dir]
    snowconvert_subdir = reports_dir / 'SnowConvert'
    if snowconvert_subdir.exists():
        dirs_to_try.append(snowconvert_subdir)

    for search_dir in dirs_to_try:
        for pattern in ['TopLevelCodeUnits.NA.csv', 'TopLevelCodeUnits.*.csv']:
            matches = list(search_dir.glob(pattern))
            if matches:
                return matches[0]
    return None


def generate_multi_report(
    output_file: Path,
    exclusion_json: Path = None,
    dynamic_sql_json: Path = None,
    waves_analysis_dir: Path = None,
    snowconvert_reports_dir: Path = None,
    registry_dir: Path = None,
    ssis_json: Path = None
) -> None:
    """Generate multi-tab HTML report"""
    
    # Load data
    exclusion_data = None
    dynamic_sql_data = None
    waves_info = None
    default_tab = 'exclusion'
    
    if exclusion_json:
        print(f"Loading exclusion data from {exclusion_json}...")
        exclusion_data = load_json_data(exclusion_json)
        default_tab = 'exclusion'
    
    if dynamic_sql_json:
        print(f"Loading dynamic SQL data from {dynamic_sql_json}...")
        dynamic_sql_data = load_json_data(dynamic_sql_json)
        if not exclusion_json:
            default_tab = 'dynamic-sql'
    
    if waves_analysis_dir:
        print(f"Loading waves data from {waves_analysis_dir}...")
        waves_info = load_waves_data(waves_analysis_dir, snowconvert_reports_dir, registry_dir=registry_dir)
        if waves_info and not exclusion_json and not dynamic_sql_json:
            default_tab = 'waves'
    
    # Load SSIS data
    ssis_data = None
    has_ssis = False
    if ssis_json and SSIS_SUPPORT:
        print(f"Loading SSIS data from {ssis_json}...")
        try:
            ssis_data = load_json_data(ssis_json)
            has_ssis = True
            if not exclusion_json and not dynamic_sql_json and not waves_info:
                default_tab = 'ssis'
        except Exception as e:
            print(f"Warning: Could not load SSIS data: {e}", file=sys.stderr)
    
    if not exclusion_data and not dynamic_sql_data and not waves_info and not ssis_data:
        raise ValueError("At least one data source (exclusion, dynamic SQL, waves, or SSIS) must be provided")
    
    # Process exclusion data
    exclusion_summary = exclusion_data.get('summary', {}) if exclusion_data else {}
    temp_staging = exclusion_data.get('temporary_staging_objects', []) if exclusion_data else []
    deprecated = exclusion_data.get('deprecated_legacy_objects', []) if exclusion_data else []
    testing = exclusion_data.get('testing_objects', []) if exclusion_data else []
    duplicate_objects = exclusion_data.get('duplicate_objects', []) if exclusion_data else []
    version_analysis = exclusion_data.get('version_analysis', {}) if exclusion_data else {}
    
    # Adaptive mode flag
    is_adaptive = bool(exclusion_data and ('discovered_patterns' in exclusion_data or 'analysis_mode' in exclusion_data))
    
    total_objects_excl = exclusion_summary.get('total_objects_found', 0)
    temp_count = len(temp_staging)
    deprec_count = len(deprecated)
    testing_count = len(testing)
    
    # Use pre-computed unique count from summary (number of unique objects with duplicates)
    duplicate_count = exclusion_summary.get('unique_duplicate_objects_count', 0)
    
    flagged_count = temp_count + deprec_count + testing_count + duplicate_count
    
    temp_pct = (temp_count / flagged_count * 100) if flagged_count > 0 else 0
    deprec_pct = (deprec_count / flagged_count * 100) if flagged_count > 0 else 0
    testing_pct = (testing_count / flagged_count * 100) if flagged_count > 0 else 0
    duplicate_pct = (duplicate_count / flagged_count * 100) if flagged_count > 0 else 0
    
    ai_summary = generate_ai_summary(exclusion_summary, temp_staging, deprecated, testing) if exclusion_data else ""
    
    # Prepare exclusion export data (tag each object with its category)
    def tag_objects_for_export(objects: List, category: str) -> List:
        """Tag objects with category for CSV export"""
        result = []
        for obj in objects:
            obj_copy = obj.copy()
            obj_copy['category'] = category
            if 'customer_decision' not in obj_copy:
                obj_copy['customer_decision'] = 'Pending Review'
            result.append(obj_copy)
        return result
    
    all_objects_for_export = (
        tag_objects_for_export(temp_staging, 'Temporary/Staging') +
        tag_objects_for_export(deprecated, 'Deprecated/Legacy') +
        tag_objects_for_export(testing, 'Testing') +
        tag_objects_for_export(duplicate_objects, 'Duplicate')
    )
    
    # Process dynamic SQL data
    flattened_dynamic_sql = flatten_dynamic_sql_json(dynamic_sql_data) if dynamic_sql_data else []
    dynamic_sql_meta = dynamic_sql_data.get('metadata', {}) if dynamic_sql_data else {}
    
    # Load overview and missing objects data
    overview_stats = None
    missing_objects_data = None
    if waves_analysis_dir:
        print(f"Loading overview statistics from {waves_analysis_dir}...")
        overview_stats = load_overview_stats(
            waves_analysis_dir,
            snowconvert_reports_dir=snowconvert_reports_dir,
            registry_dir=registry_dir,
        )
    
    # Load missing objects from SnowConvert reports or waves analysis
    if waves_analysis_dir or snowconvert_reports_dir or registry_dir:
        print(f"Loading missing objects data...")
        missing_objects_data = load_missing_objects_for_overview(
            waves_analysis_dir,
            snowconvert_reports_dir,
            registry_dir=registry_dir,
        )
        print(f"  - Missing objects: {len(missing_objects_data.get('missing_objects', []))} references found")
    
    if overview_stats:
        print(f"  - Overview: {overview_stats.get('total_objects', 0)} objects in {overview_stats.get('total_waves', 0)} waves")

    # If no source_dialect in overview but have dynamic SQL with source_language, use that
    if overview_stats and not overview_stats.get('source_dialect') and dynamic_sql_meta.get('source_language'):
        overview_stats['source_dialect'] = dynamic_sql_meta.get('source_language')
        print(f"  - Using source dialect from SQL Dynamic: {overview_stats['source_dialect']}")
    
    # Set default tab to overview if available
    if waves_analysis_dir:
        default_tab = 'overview'
    
    print(f"Processed data:")
    if exclusion_data:
        print(f"  - Exclusion: {len(all_objects_for_export)} objects from {len(exclusion_data.get('summary', {}).get('objects_by_schema', []))} schemas")
    if dynamic_sql_data:
        print(f"  - Dynamic SQL: {len(flattened_dynamic_sql)} occurrences from {len(dynamic_sql_data.get('code_units', {}))} code units")
    if waves_info:
        print(f"  - Waves: HTML content generated successfully")
    
    # Generate HTML
    json_data_dynamic_str = json.dumps(flattened_dynamic_sql, ensure_ascii=False)
    json_data_exclusion_str = json.dumps(all_objects_for_export, ensure_ascii=False)
    
    html_content = generate_html_template(
        default_tab=default_tab,
        has_exclusion=exclusion_data is not None,
        has_dynamic_sql=dynamic_sql_data is not None,
        has_waves=waves_info is not None,
        waves_info=waves_info,
        has_ssis=has_ssis,
        ssis_json=ssis_json if has_ssis else None,
        output_file=output_file,
        dynamic_sql_meta=dynamic_sql_meta,
        exclusion_summary=exclusion_summary,
        is_adaptive=is_adaptive,
        temp_count=temp_count,
        deprec_count=deprec_count,
        testing_count=testing_count,
        duplicate_count=duplicate_count,
        flagged_count=flagged_count,
        temp_pct=temp_pct,
        deprec_pct=deprec_pct,
        testing_pct=testing_pct,
        duplicate_pct=duplicate_pct,
        total_objects_excl=total_objects_excl,
        version_analysis=version_analysis,
        temp_staging=temp_staging,
        deprecated=deprecated,
        testing=testing,
        duplicate_objects=duplicate_objects,
        json_data_exclusion=json_data_exclusion_str,
        json_data_dynamic=json_data_dynamic_str,
        overview_stats=overview_stats,
        missing_objects_data=missing_objects_data
    )
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"\n✓ Multi-tab HTML report generated successfully!")
    print(f"  Output: {output_file}")
    print(f"  Size: {output_file.stat().st_size:,} bytes")
    print(f"\nOpen the report in your browser:")
    print(f"  open {output_file}")


def generate_html_template(
    default_tab: str,
    has_exclusion: bool,
    has_dynamic_sql: bool,
    has_waves: bool,
    waves_info: Dict,
    has_ssis: bool,
    ssis_json: Path,
    output_file: Path,
    dynamic_sql_meta: Dict,
    exclusion_summary: Dict,
    is_adaptive: bool,
    temp_count: int,
    deprec_count: int,
    testing_count: int,
    duplicate_count: int,
    flagged_count: int,
    temp_pct: float,
    deprec_pct: float,
    testing_pct: float,
    duplicate_pct: float,
    total_objects_excl: int,
    version_analysis: Dict,
    temp_staging: List,
    deprecated: List,
    testing: List,
    duplicate_objects: List,
    json_data_exclusion: str,
    json_data_dynamic: str,
    overview_stats: Dict = None,
    missing_objects_data: Dict = None
) -> str:
    """Generate the complete HTML template"""
    dynamic_sql_meta_json = json.dumps(dynamic_sql_meta or {}, ensure_ascii=False)
    
    logo_base64 = ""
    resources_dir = Path(__file__).parent.parent / "resources"
    logo_name = "snowflake_logo_sidebar"
    # Search order: SVG preferred, PNG fallback
    logo_candidates = [
        (resources_dir / "svg" / f"{logo_name}.svg", "image/svg+xml"),
        (resources_dir / "images" / f"{logo_name}.png", "image/png"),
    ]
    for logo_path, mime_type in logo_candidates:
        if logo_path.exists():
            try:
                with open(logo_path, 'rb') as f:
                    logo_base64 = f"data:{mime_type};base64,{base64.b64encode(f.read()).decode()}"
                break
            except Exception as e:
                pass

    # Load SVG logos as text
    snowflake_logo_svg = ""
    snowconvert_ai_logo_svg = ""

    snowflake_logo_path = resources_dir / "svg" / "snowflake-logo.svg"
    snowconvert_ai_logo_path = resources_dir / "svg" / "snowconvert-ai-logo.svg"

    try:
        if snowflake_logo_path.exists():
            with open(snowflake_logo_path, 'r', encoding='utf-8') as f:
                snowflake_logo_svg = f.read()
    except Exception as e:
        print(f"Warning: Could not load snowflake-logo.svg: {e}", file=sys.stderr)

    try:
        if snowconvert_ai_logo_path.exists():
            with open(snowconvert_ai_logo_path, 'r', encoding='utf-8') as f:
                snowconvert_ai_logo_svg = f.read()
    except Exception as e:
        print(f"Warning: Could not load snowconvert-ai-logo.svg: {e}", file=sys.stderr)
    
    # Default overview stats if not provided
    if overview_stats is None:
        overview_stats = {
            'total_objects': total_objects_excl,
            'total_waves': 0,
            'objects_by_type': {},
            'conversion_stats': {}
        }
    
    if missing_objects_data is None:
        missing_objects_data = {'missing_objects': [], 'summary': {}}
    
    # Serialize missing objects for JavaScript
    missing_objects_json = json.dumps(missing_objects_data.get('missing_objects', [])[:5000], ensure_ascii=False)  # Limit to 5000 for performance
    missing_objects_count = len(missing_objects_data.get('missing_objects', []))
    missing_objects_error = missing_objects_data.get('error', '')

    # Prepare top missing references table (Overview Section C)
    missing_objects_list = missing_objects_data.get('missing_objects', []) if isinstance(missing_objects_data, dict) else []

    def _callers_count(item: Dict[str, Any]) -> int:
        return int(item.get('dependants_count') or len(item.get('callers') or []))

    top_missing_objects = sorted(
        missing_objects_list,
        key=lambda item: (-_callers_count(item), str(item.get('referenced', '')).lower())
    )[:10]

    missing_top10_rows = []
    if top_missing_objects:
        for item in top_missing_objects:
            referenced = html_escape_module.escape(str(item.get('referenced', '')))
            dependants_count = int(item.get('dependants_count') or len(item.get('callers') or []))
            reference_count = int(item.get('reference_count') or dependants_count)
            missing_top10_rows.append(f'''
                            <tr>
                                <td><span class="copyable-top-object" data-tooltip="{referenced}" style="display: block; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 1em; color: #111827; font-family: inherit; cursor: copy;">{referenced}</span></td>
                                <td style="text-align: center;"><strong>{reference_count}</strong></td>
                                <td style="text-align: center;"><strong>{dependants_count}</strong></td>
                            </tr>
''')
    else:
        missing_top10_rows.append('''
                            <tr>
                                <td colspan="3" style="text-align: center; color: #999; font-style: italic;">No missing object references found</td>
                            </tr>
''')

    missing_top10_rows_html = ''.join(missing_top10_rows)

    if missing_objects_error:
        missing_objects_section_html = f'''
            <div style="background: linear-gradient(135deg, #FEE2E2 0%, #FECACA 100%); border: 1px solid #EF4444; border-radius: 12px; padding: 24px; margin-bottom: 24px;">
                <div style="display: flex; align-items: center; gap: 16px;">
                    <div style="font-size: 2.5rem;">❌</div>
                    <div>
                        <h3 style="margin: 0; color: #991B1B; font-size: 1.25rem;">Missing Objects Data Not Available</h3>
                        <p style="margin: 4px 0 0 0; color: #B91C1C; font-size: 0.9rem;">{html_escape_module.escape(str(missing_objects_error))}</p>
                    </div>
                </div>
            </div>
        '''
    else:
        missing_objects_section_html = f'''
            <div style="background: linear-gradient(135deg, #FEF3C7 0%, #FDE68A 100%); border: 1px solid #F59E0B; border-radius: 12px; padding: 18px 20px; margin-bottom: 16px;">
                <div style="display: flex; align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap;">
                    <div style="display: flex; align-items: center; gap: 14px;">
                        <div style="font-size: 1.9rem;">⚠️</div>
                        <div>
                            <h3 style="margin: 0; color: #92400E; font-size: 1.1rem;">{missing_objects_count:,} Missing Object References Found</h3>
                            <p style="margin: 4px 0 0 0; color: #B45309; font-size: 0.86rem;">
                                These objects are referenced but not defined in the source workload.
                            </p>
                        </div>
                    </div>
                    <div style="position: relative; display: inline-block;">
                        <button onclick="toggleMissingExportMenu()" id="missingExportBtn" style="padding: 6px 12px; background-color: rgb(5, 150, 105); color: white; border: none; border-radius: 4px; font-size: 0.8125em; cursor: pointer; transition: background-color 0.2s; display: flex; align-items: center; gap: 6px;">
                            Export Missing Objects
                            <span style="font-size: 0.7em;">▼</span>
                        </button>
                        <div id="missingExportMenu" style="display: none; position: absolute; top: 100%; right: 0; margin-top: 4px; background: white; border: 1px solid #D1D5DB; border-radius: 4px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); z-index: 1000; min-width: 190px;">
                            <button onclick="downloadMissingObjectsCSV()" style="width: 100%; padding: 8px 12px; background: none; border: none; text-align: left; font-size: 0.8125em; cursor: pointer; color: #374151;">Export CSV</button>
                            <button onclick="downloadMissingObjectsExcel()" style="width: 100%; padding: 8px 12px; background: none; border: none; text-align: left; font-size: 0.8125em; cursor: pointer; color: #374151; border-top: 1px solid #E5E7EB;">Export Excel</button>
                        </div>
                    </div>
                </div>
            </div>
            <div style="margin: 0 0 12px 0; background: #F8FBFC; border: 1px solid #B6D5F3; border-left: 4px solid #29B5E8; border-radius: 8px; padding: 10px 12px; color: #2A3342; font-size: 0.85rem; display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;">
                <div>
                    To fully <strong>analyze and download all missing objects</strong>, open
                    <a href="#all-objects" onclick="document.querySelector('.nav-link[data-tab=\\'waves\\']').click(); setTimeout(function(){{ window.location.hash = 'all-objects'; }}, 0);" style="color: #005C8F; font-weight: 700; text-decoration: underline;">Dependencies Report (All Objects)</a>
                    and filter by <strong>Status = Missing</strong>.
                </div>
            </div>
            <div style="background: white; border: 1px solid #B6D5F3; border-radius: 8px; padding: 12px;">
                <h3 style="font-size: 1rem; font-weight: 700; color: #102E46; margin: 0 0 10px 0;">Top 10 Missing Object References</h3>
                <table style="font-size: 1.05em; width: 100%; table-layout: fixed;">
                    <thead style="background: rgb(16, 46, 70); color: #FFFFFF;">
                        <tr>
                            <th style="width: 52%; background: rgb(16, 46, 70); color: #FFFFFF;">Missing Object</th>
                            <th style="width: 14%; text-align: center; background: rgb(16, 46, 70); color: #FFFFFF;">Count</th>
                            <th style="width: 14%; text-align: center; background: rgb(16, 46, 70); color: #FFFFFF;">Dependants</th>
                        </tr>
                    </thead>
                    <tbody>
                        {missing_top10_rows_html}
                    </tbody>
                </table>
            </div>
        '''
    
    # Temporal tables (SQL Server #/## temp tables) — count from membership + missing objects
    temporal_tables_count = overview_stats.get('temporal_tables_count', 0) if overview_stats else 0
    if missing_objects_data:
        for item in missing_objects_data.get('missing_objects', []):
            ref_name = item.get('referenced', '') if isinstance(item, dict) else str(item)
            bare = ref_name.replace('[', '').replace(']', '').rsplit('.', 1)[-1]
            if bare.startswith('#'):
                temporal_tables_count += 1

    temporal_tables_card_html = ''
    if temporal_tables_count > 0:
        temporal_tables_card_html = f'''
                <div style="background: white; padding: 20px; border-radius: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border-top: 4px solid #F59E0B;">
                    <div style="color: #64748B; font-size: 0.85rem; font-weight: 600; text-transform: uppercase;">Temporal Tables</div>
                    <div style="font-size: 2rem; font-weight: 800; color: #102E46; margin-top: 4px;">{temporal_tables_count}</div>
                </div>
        '''

    # External tables (only render if present)
    external_tables_count = overview_stats.get('external_tables_count', 0) if overview_stats else 0
    source_dialect = (overview_stats.get('source_dialect', '') if overview_stats else '') or ''
    safe_source_dialect = html_escape_module.escape(str(source_dialect)) if source_dialect else 'Unknown'

    external_tables_card_html = ''
    objects_by_type = overview_stats.get('objects_by_type', {}) if overview_stats else {}
    if external_tables_count > 0 and 'EXTERNAL TABLE' not in objects_by_type:
        external_tables_card_html = f'''
                <div style="background: white; padding: 20px; border-radius: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border-top: 4px solid #E85D29;">
                    <div style="color: #64748B; font-size: 0.85rem; font-weight: 600; text-transform: uppercase;">External Tables</div>
                    <div style="font-size: 2rem; font-weight: 800; color: #102E46; margin-top: 4px;">{external_tables_count}</div>
                </div>
        '''

    # Overview tab HTML
    overview_html = f"""
        <!-- Overview Tab -->
        <div class="tab-content" :class="{{active: activeTab === 'overview'}}">
            <div style="margin-bottom: 32px;">
                <h1 style="font-size: 1.875rem; font-weight: 800; color: #102E46; margin-bottom: 12px;">
                    Migration Assessment Overview
                </h1>
                <p style="color: #64748B; font-size: 1.1rem;">
                    This assessment analyzes the workload for migration to Snowflake. It breaks down the code inventory, 
                    estimates conversion effort, and identifies dependencies for a wave-based deployment.
                </p>
                <div style="margin-top: 12px; background: #F3F4F6; border: 1px solid #D1D5DB; border-left: 4px solid #9CA3AF; border-radius: 6px; padding: 10px 12px;">
                    <p style="margin: 0; color: #374151; font-size: 0.78rem; line-height: 1.45;">
                        <strong>Disclaimer:</strong> Parts of this report were AI-generated. Please use your discretion while using the results.
                    </p>
                </div>
                <div style="display: flex; flex-wrap: wrap; gap: 10px; margin-top: 12px;">
                    <span style="background: #F1F5F9; color: #334155; padding: 6px 10px; border-radius: 999px; font-size: 0.85rem; font-weight: 600;">
                        Source dialect: {safe_source_dialect}
                    </span>
                </div>
            </div>

            <h2 id="workload-inventory" style="font-size: 1.5rem; font-weight: 700; color: #102E46; margin-bottom: 20px; display: flex; align-items: center; gap: 10px;">
                <span style="background: #E0F2FE; color: #0284C7; padding: 4px 10px; border-radius: 6px; font-size: 0.9rem;">Section A</span>
                Workload Inventory
            </h2>
            
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 20px; margin-bottom: 40px;">
                <div style="background: #102E46; padding: 20px; border-radius: 12px; color: white;">
                    <div style="font-size: 0.85rem; font-weight: 600; opacity: 0.8; text-transform: uppercase;">Total Objects</div>
                    <div style="font-size: 2.5rem; font-weight: 800; margin-top: 4px;">{overview_stats.get('total_objects', total_objects_excl)}</div>
                    <div style="font-size: 0.8rem; opacity: 0.8; margin-top: 4px;">In {overview_stats.get('total_waves', 'N/A')} Waves</div>
                </div>
                
                {''.join([f'''
                <div style="background: white; padding: 20px; border-radius: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border-top: 4px solid {'#29B5E8' if i == 0 else '#7D44CF' if i == 1 else '#FF9F36' if i == 2 else '#64748B'};">
                    <div style="color: #64748B; font-size: 0.85rem; font-weight: 600; text-transform: uppercase;">{obj_type}s</div>
                    <div style="font-size: 2rem; font-weight: 800; color: #102E46; margin-top: 4px;">{count}</div>
                </div>
                ''' + (external_tables_card_html + temporal_tables_card_html if obj_type.upper() == 'TABLE' else '') for i, (obj_type, count) in enumerate(list(overview_stats.get('objects_by_type', {}).items())[:5])])}
            </div>

            <h2 id="how-to-use" style="font-size: 1.5rem; font-weight: 700; color: #102E46; margin-bottom: 20px; display: flex; align-items: center; gap: 10px;">
                <span style="background: #E0F2FE; color: #0284C7; padding: 4px 10px; border-radius: 6px; font-size: 0.9rem;">Section B</span>
                How to Use This Report
            </h2>

            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 24px; margin-bottom: 40px;">
                
                <div style="background: white; padding: 24px; border-radius: 12px; border: 1px solid #E2E8F0; transition: transform 0.2s; cursor: pointer;" 
                     onclick="document.querySelector('.nav-link[data-tab=\\'waves\\']').click()"
                     onmouseover="this.style.borderColor='#29B5E8'; this.style.transform='translateY(-2px)'" 
                     onmouseout="this.style.borderColor='#E2E8F0'; this.style.transform='translateY(0)'">
                    <div style="width: 40px; height: 40px; background: #F0F9FF; border-radius: 8px; display: flex; align-items: center; justify-content: center; margin-bottom: 16px; font-size: 1.25rem;">
                        1
                    </div>
                    <h3 style="margin: 0 0 8px 0; color: #102E46; font-size: 1.1rem;">Dependencies Report</h3>
                    <p style="color: #64748B; font-size: 0.9rem; line-height: 1.5; margin-bottom: 16px;">
                        <strong>Goal:</strong> Understand dependencies and plan deployment. <br>
                        View comprehensive object inventory, dependency statistics, and migration wave planning.
                    </p>
                    <div style="background: #F8FAFC; padding: 10px; border-radius: 6px; font-size: 0.85rem; color: #475569;">
                        <strong>Key Insight:</strong> {overview_stats.get('total_waves', 'N/A')} waves identified for deployment.
                    </div>
                </div>

                <div style="background: white; padding: 24px; border-radius: 12px; border: 1px solid #E2E8F0; transition: transform 0.2s; cursor: pointer;" 
                     onclick="document.querySelector('.nav-link[data-tab=\\'exclusion\\']').click()"
                     onmouseover="this.style.borderColor='#29B5E8'; this.style.transform='translateY(-2px)'" 
                     onmouseout="this.style.borderColor='#E2E8F0'; this.style.transform='translateY(0)'">
                    <div style="width: 40px; height: 40px; background: #F0F9FF; border-radius: 8px; display: flex; align-items: center; justify-content: center; margin-bottom: 16px; font-size: 1.25rem;">
                        2
                    </div>
                    <h3 style="margin: 0 0 8px 0; color: #102E46; font-size: 1.1rem;">Exclusion Report</h3>
                    <p style="color: #64748B; font-size: 0.9rem; line-height: 1.5; margin-bottom: 16px;">
                        <strong>Goal:</strong> Reduce scope. <br>
                        Identify objects that may not need to be migrated, such as temporary, deprecated, testing, and duplicate objects.
                    </p>
                    <div style="background: #F8FAFC; padding: 10px; border-radius: 6px; font-size: 0.85rem; color: #475569;">
                        <strong>Key Insight:</strong> {temp_count} objects ({temp_pct:.1f}%) are marked as Temporary/Staging.
                    </div>
                </div>

                <div style="background: white; padding: 24px; border-radius: 12px; border: 1px solid #E2E8F0; transition: transform 0.2s; cursor: pointer;" 
                     onclick="document.querySelector('.nav-link[data-tab=\\'dynamic-sql\\']').click()"
                     onmouseover="this.style.borderColor='#29B5E8'; this.style.transform='translateY(-2px)'" 
                     onmouseout="this.style.borderColor='#E2E8F0'; this.style.transform='translateY(0)'">
                    <div style="width: 40px; height: 40px; background: #F0F9FF; border-radius: 8px; display: flex; align-items: center; justify-content: center; margin-bottom: 16px; font-size: 1.25rem;">
                        3
                    </div>
                    <h3 style="margin: 0 0 8px 0; color: #102E46; font-size: 1.1rem;">Dynamic SQL Report</h3>
                    <p style="color: #64748B; font-size: 0.9rem; line-height: 1.5; margin-bottom: 16px;">
                        <strong>Goal:</strong> Fix runtime issues. <br>
                        Deep dive into complex code patterns (Dynamic SQL, Linked Servers) that SnowConvert cannot statically analyze.
                    </p>
                    <div style="background: #F8FAFC; padding: 10px; border-radius: 6px; font-size: 0.85rem; color: #475569;">
                        <strong>Key Insight:</strong> Review dynamic SQL patterns that require manual attention.
                    </div>
                </div>

                <div style="background: white; padding: 24px; border-radius: 12px; border: 1px solid #E2E8F0; transition: transform 0.2s; cursor: pointer;" 
                     onclick="document.querySelector('.nav-link[data-tab=\\'ssis\\']').click()"
                     onmouseover="this.style.borderColor='#29B5E8'; this.style.transform='translateY(-2px)'" 
                     onmouseout="this.style.borderColor='#E2E8F0'; this.style.transform='translateY(0)'">
                    <div style="width: 40px; height: 40px; background: #F0F9FF; border-radius: 8px; display: flex; align-items: center; justify-content: center; margin-bottom: 16px; font-size: 1.25rem;">
                        4
                    </div>
                    <h3 style="margin: 0 0 8px 0; color: #102E46; font-size: 1.1rem;">SSIS Report</h3>
                    <p style="color: #64748B; font-size: 0.9rem; line-height: 1.5; margin-bottom: 16px;">
                        <strong>Goal:</strong> Assess ETL pipelines. <br>
                        Analyze SSIS packages to understand data flow complexity, identify unsupported components, and plan ETL migration.
                    </p>
                    <div style="background: #F8FAFC; padding: 10px; border-radius: 6px; font-size: 0.85rem; color: #475569;">
                        <strong>Key Insight:</strong> Review SSIS packages for migration readiness.
                    </div>
                </div>

            </div>

            <!-- Missing Objects Section -->
            <h2 id="missing-objects" style="font-size: 1.5rem; font-weight: 700; color: #102E46; margin-bottom: 20px; display: flex; align-items: center; gap: 10px;">
                <span style="background: #FEF3C7; color: #D97706; padding: 4px 10px; border-radius: 6px; font-size: 0.9rem;">Section C</span>
                Missing Objects Analysis
            </h2>
            
            {missing_objects_section_html}
        </div>
    """
    
    # Generate waves HTML content
    waves_html = ""
    waves_js = ""
    if has_waves and waves_info:
        waves_content, _, waves_js = generate_waves_html_content(waves_info)
        waves_html = f"""
            <!-- Dependencies Report Tab -->
            <div class=\"tab-content dependencies-tab\" :class=\"{{active: activeTab === 'waves'}}\">
                <!-- Main Content -->
                <div style="padding: 20px; min-width: 0;">
                    {waves_content}
                </div>
            </div>
        """
    else:
        waves_html = """
            <!-- Dependencies Report Tab -->
            <div class=\"tab-content dependencies-tab\" :class=\"{active: activeTab === 'waves'}\">
                <div class=\"empty-state\">
                    <h3>No Data Available</h3>
                    <p>Waves/dependency analysis data was not provided. Please ask to the agent to include it.</p>
                    <p>Try a prompt like "Please include the waves/dependency analysis data in the report."</p>
                </div>
            </div>
        """
    
    # Generate SSIS HTML content
    ssis_html = ""
    ssis_js = ""
    ssis_css = ""
    if has_ssis and SSIS_SUPPORT and ssis_json:
        # Pass output_file so package pages can be generated in packages/ folder alongside it
        ssis_content, ssis_js, ssis_css = generate_ssis_html_content(ssis_json, output_html_path=output_file)
        ssis_html = f"""
            <!-- SSIS Report Tab -->
            <div class="tab-content" :class="{{active: activeTab === 'ssis'}}">
                {ssis_content}
            </div>
        """
    else:
        ssis_html = """
            <div class="tab-content" :class="{active: activeTab === 'ssis'}">
                <div style="margin-bottom: 32px;">
                    <h1 style="font-size: 1.875rem; font-weight: 800; color: #102E46; margin-bottom: 12px;">
                        SSIS Assessment Report
                    </h1>
                    <p style="color: #64748B; font-size: 1.1rem;">
                        Comprehensive analysis of SSIS packages identified for migration including component analysis and conversion readiness metrics.
                    </p>
                </div>
                <div class="empty-state">
                    <h3>No Data Available</h3>
                    <p>SSIS assessment data was not provided. Please provide the SSIS JSON file using --ssis-json parameter.</p>
                </div>
            </div>
        """
    
    exclusion_html = ""
    if has_exclusion:
        exclusion_html = f"""
            <!-- Exclusion Report Tab -->
            <div class="tab-content" :class="{{active: activeTab === 'exclusion'}}">
                <!-- Executive Summary -->
                <section id="executive-summary" style="margin-bottom: 48px;">
                    <div style="margin-bottom: 32px;">
                        <h1 style="font-size: 1.875rem; font-weight: 800; color: #102E46; margin-bottom: 12px;">
                            Object Exclusion Analysis
                        </h1>
                        <p style="color: #64748B; font-size: 1.1rem;">
                            Identify objects that do not need to be migrated, such as temporary tables, backups, or deprecated code.
                        </p>
                    </div>
                
                    <h2 style="font-size: 1.25rem; font-weight: 600; color: #102E46; margin-top: 28px; margin-bottom: 16px;">Overview Statistics</h2>
                    <div class="metric-grid">
                        <div class="metric-card" style="cursor: pointer;" onclick="navigateToCategory('all')">
                            <div class="metric-label">Total in Database</div>
                            <div class="metric-value">{total_objects_excl}</div>
                            <div class="metric-description">Objects found in source project</div>
                        </div>
                        <div class="metric-card" style="cursor: pointer;" onclick="navigateToCategory('all')">
                            <div class="metric-label">Total Flagged</div>
                            <div class="metric-value">{flagged_count}</div>
                            <div class="metric-description">Objects to review</div>
                        </div>
                        <div class="metric-card" style="cursor: pointer;" onclick="navigateToCategory('temp')">
                            <div class="metric-label">Temporary/Staging</div>
                            <div class="metric-value">{temp_count}</div>
                            <div class="metric-description">{temp_pct:.1f}% of flagged objects</div>
                        </div>
                        <div class="metric-card" style="cursor: pointer;" onclick="navigateToCategory('deprecated')">
                            <div class="metric-label">Deprecated/Legacy</div>
                            <div class="metric-value">{deprec_count}</div>
                            <div class="metric-description">{deprec_pct:.1f}% of flagged objects</div>
                        </div>
                        <div class="metric-card" style="cursor: pointer;" onclick="navigateToCategory('testing')">
                            <div class="metric-label">Testing Objects</div>
                            <div class="metric-value">{testing_count}</div>
                            <div class="metric-description">{testing_pct:.1f}% of flagged objects</div>
                        </div>
                        <div class="metric-card" style="cursor: pointer;" onclick="navigateToCategory('duplicate')">
                            <div class="metric-label">Duplicate Objects</div>
                            <div class="metric-value">{duplicate_count}</div>
                            <div class="metric-description">{duplicate_pct:.1f}% of flagged objects</div>
                        </div>
                    </div>
                </section>
                
                <!-- Flagged Objects Section -->
                <section id="objects" style="margin-bottom: 48px;">
                    <h2 style="font-size: 1.25rem; font-weight: 600; color: #102E46; margin-bottom: 16px;">
                        Flagged Objects for Review
                    </h2>
                    <p style="color: #64748B; margin-bottom: 1rem;">Showing {flagged_count} objects that match naming patterns for temporary, deprecated, testing, or duplicate categories. These objects require review before migration.</p>
                    <div class="export-buttons" style="margin-bottom: 1.5rem;">
                        <button class="export-btn-compact" onclick="downloadCSV('all')">Download All (CSV)</button>
                        <button class="export-btn-compact" onclick="downloadExcel('all')">Download All (Excel)</button>
                        <button class="export-btn-compact" onclick="downloadCSV('temp')">Temporary/Staging (CSV)</button>
                        <button class="export-btn-compact" onclick="downloadCSV('deprecated')">Deprecated (CSV)</button>
                        <button class="export-btn-compact" onclick="downloadCSV('testing')">Testing (CSV)</button>
                        <button class="export-btn-compact" onclick="downloadCSV('duplicate')">Duplicate (CSV)</button>
                    </div>
                    
                    <!-- Search and Count -->
                    <div style="display: flex; gap: 1rem; margin-bottom: 1rem; align-items: center; flex-wrap: wrap;">
                        <div style="display: flex; align-items: center; gap: 0.5rem;">
                            <input type="text" id="search-objects" placeholder="Search by name, schema, file..." onkeyup="filterExclusionTable()" style="padding: 0.5rem 1rem; border: 1px solid #E2E8F0; border-radius: 6px; font-size: 0.875rem; width: 280px;">
                        </div>
                        <span id="table-count" style="font-size: 0.875rem; color: #64748B;"></span>
                        <button onclick="clearExclusionFilters()" class="export-btn-compact" style="margin-left: auto;">Clear Filters</button>
                    </div>
                    
                    <!-- Objects Table -->
                    <div>
                        <table class="exclusion-table" id="exclusion-objects-table">
                            <thead>
                                <tr>
                                    <th class="col-name">Object Name</th>
                                    <th class="col-schema">
                                        <div class="th-content">
                                            <span>Schema</span>
                                            <select id="schema-filter" onchange="filterExclusionTable()" class="column-filter">
                                                <option value="all">All</option>
                                                {generate_schema_filter_options(temp_staging, deprecated, testing)}
                                            </select>
                                        </div>
                                    </th>
                                    <th class="col-type">
                                        <div class="th-content">
                                            <span>Type</span>
                                            <select id="type-filter" onchange="filterExclusionTable()" class="column-filter">
                                                <option value="all">All</option>
                                                {generate_type_filter_options(temp_staging, deprecated, testing)}
                                            </select>
                                        </div>
                                    </th>
                                    <th class="col-reason">
                                        <div class="th-content">
                                            <span>Reason</span>
                                            <select id="reason-filter" onchange="filterExclusionTable()" class="column-filter">
                                                <option value="all">All</option>
                                                {generate_reason_filter_options(temp_staging, deprecated, testing)}
                                            </select>
                                        </div>
                                    </th>
                                    <th class="col-classification">
                                        <div class="th-content">
                                            <span>Classification</span>
                                            <select id="classification-filter" onchange="filterExclusionTable()" class="column-filter">
                                                <option value="all">All</option>
                                                <option value="temp">Temp/Staging</option>
                                                <option value="deprecated">Deprecated</option>
                                                <option value="testing">Testing</option>
                                                <option value="duplicate">Duplicate</option>
                                            </select>
                                        </div>
                                    </th>
                                </tr>
                            </thead>
                            <tbody>
                                {generate_exclusion_table_rows(temp_staging, deprecated, testing, version_analysis, duplicate_objects)}
                            </tbody>
                        </table>
                    </div>
                </section>
            </div>
        """
    else:
        exclusion_html = """
            <div class="tab-content" :class="{active: activeTab === 'exclusion'}">
                <h2 class="text-3xl font-bold text-sf-dark-blue mb-6 border-b-2 border-sf-blue pb-2">
                    Exclusion Report
                </h2>
                <div class="empty-state">
                    <h3>No Data Available</h3>
                    <p>Exclusion report data was not provided.</p>
                </div>
            </div>
        """
    
    dynamic_sql_html = ""
    if has_dynamic_sql:
        dynamic_sql_html = """
            <!-- Dynamic SQL Report Tab -->
            <div class="tab-content" :class="{active: activeTab === 'dynamic-sql'}">
                <!-- Executive Summary -->
                <section id="executive-summary" style="margin-bottom: 48px;">
                    <div style="margin-bottom: 32px;">
                        <h1 style="font-size: 1.875rem; font-weight: 800; color: #102E46; margin-bottom: 12px;">
                            Dynamic SQL Analysis
                        </h1>
                        <p style="color: #64748B; font-size: 1.1rem;">
                            Deep dive into code patterns that require special attention during migration to Snowflake.
                        </p>
                    </div>
                    <div class="metrics-row">
                        <div class="metric-item">
                            <div class="metric-label">Total occurrences</div>
                            <div class="metric-value">{{ totalOccurrences }}</div>
                            <div class="metric-sub">Dynamic SQL instances detected</div>
                        </div>
                        <div class="metric-item">
                            <div class="metric-label">Analyzed</div>
                            <div class="metric-value">{{ analyzedOccurrencesCount }}</div>
                            <div class="metric-sub">Reviewed occurrences</div>
                        </div>
                        <div class="metric-item" v-if="pendingOccurrencesCount > 0">
                            <div class="metric-label">Pending</div>
                            <div class="metric-value metric-value-warn">{{ pendingOccurrencesCount }}</div>
                            <div class="metric-sub">Excluded from code units</div>
                        </div>
                        <div class="metric-item">
                            <div class="metric-label">Code units</div>
                            <div class="metric-value">{{ uniqueCodeUnits }}</div>
                            <div class="metric-sub">With reviewed occurrences</div>
                        </div>
                        <div class="metric-item">
                            <div class="metric-label">High priority</div>
                            <div class="metric-value metric-value-warn">{{ highPriority }}</div>
                            <div class="metric-sub">Critical + High (reviewed)</div>
                        </div>
                    </div>

                    <h3 class="text-xl font-semibold text-sf-dark-blue mb-4">Pattern Categories</h3>
                    <table class="w-full border-collapse" style="border: 1px solid #8A999E;">
                        <thead class="bg-sf-blue text-white">
                            <tr>
                                <th class="p-3 text-left">Category</th>
                                <th class="p-3 text-center">Occurrences</th>
                                <th class="p-3 text-center">Code Units</th>
                                <th class="p-3 text-center">Percentage</th>
                            </tr>
                        </thead>
                        <tbody class="text-sm">
                            <tr v-for="(pattern, index) in sortedPatterns" :key="index" 
                                class="border-b border-sf-gray hover:bg-blue-50"
                                :style="index % 2 === 0 ? 'background: #FFFFFF' : 'background: #F9FAFB'">
                                <td class="p-3 font-semibold">{{ pattern.name }}</td>
                                <td class="p-3 text-center">{{ pattern.count }}</td>
                                <td class="p-3 text-center">{{ pattern.codeUnitCount }}</td>
                                <td class="p-3 text-center">{{ pattern.percentage }}%</td>
                            </tr>
                        </tbody>
                    </table>

                    <h3 class="text-xl font-semibold text-sf-dark-blue mb-4" style="margin-top: 28px;">SQL Classification</h3>
                    <table class="w-full border-collapse" style="border: 1px solid #8A999E;">
                        <thead class="bg-sf-blue text-white">
                            <tr>
                                <th class="p-3 text-left">Type</th>
                                <th class="p-3 text-center">Occurrences</th>
                                <th class="p-3 text-center">Code Units</th>
                                <th class="p-3 text-center">Percentage</th>
                            </tr>
                        </thead>
                        <tbody class="text-sm">
                            <tr v-for="(entry, index) in sortedSqlClassifications" :key="entry.name + '_' + index"
                                class="border-b border-sf-gray hover:bg-blue-50"
                                :style="index % 2 === 0 ? 'background: #FFFFFF' : 'background: #F9FAFB'">
                                <td class="p-3 font-semibold">{{ entry.name }}</td>
                                <td class="p-3 text-center">{{ entry.count }}</td>
                                <td class="p-3 text-center">{{ entry.codeUnitCount }}</td>
                                <td class="p-3 text-center">{{ entry.percentage }}%</td>
                            </tr>
                        </tbody>
                    </table>
                </section>

                <section id="key-findings" style="margin-bottom: 48px;">
                    <h2 class="text-3xl font-bold text-sf-dark-blue mb-6 border-b-2 border-sf-blue pb-2">Key Findings</h2>
                    <div style="background: #F8FAFC; padding: 24px; border-radius: 8px; border-left: 4px solid #29B5E8;">
                        <ul style="list-style: disc; margin-left: 24px; line-height: 1.8;">
                            <li v-for="(finding, index) in keyFindings" :key="index" v-html="finding"></li>
                        </ul>
                    </div>
                </section>

                <section id="code-units" style="margin-bottom: 48px;">
                    <h2 class="text-3xl font-bold text-sf-dark-blue mb-6 border-b-2 border-sf-blue pb-2">Code Units</h2>

                    <div class="dsq-layout">
                        <!-- Left: searchable list -->
                        <div class="dsq-panel dsq-table">
                            <div class="dsq-toolbar">
                                <div class="dsq-search">
                                    <input v-model="searchQuery" type="text" placeholder="Search name, file path..." class="filter-input"/>
                                </div>
                                <select v-model="complexityFilter" class="filter-select">
                                    <option value="all">All complexities</option>
                                    <option value="critical">Critical</option>
                                    <option value="high">High</option>
                                    <option value="medium">Medium</option>
                                    <option value="low">Low</option>
                                </select>
                                <select v-model="categoryFilter" class="filter-select">
                                    <option value="all">All categories</option>
                                    <option v-for="category in allCategories" :key="category" :value="category">{{ category }}</option>
                                </select>
                                <select v-model="sqlClassificationFilter" class="filter-select">
                                    <option value="all">All SQL types</option>
                                    <option v-for="cls in allSqlClassifications" :key="cls" :value="cls">{{ cls }}</option>
                                </select>
                                <button @click="clearFilters" class="btn-primary">Reset</button>
                                <span class="text-sm text-sf-gray dsq-count">
                                    Showing {{ filteredCodeUnits.length }} of {{ uniqueCodeUnits }} code units
                                </span>
                                <span v-if="pendingOccurrencesCount > 0" class="text-xs dsq-count-note">
                                    {{ pendingOccurrencesCount }} pending occurrence{{ pendingOccurrencesCount === 1 ? '' : 's' }} hidden
                                </span>
                            </div>

                            <div class="dsq-thead" role="row">
                                <div class="dsq-cell">Name</div>
                                <div class="dsq-cell">Complexity</div>
                                <div class="dsq-cell">Occurrences</div>
                                <div class="dsq-cell">File</div>
                            </div>

                            <div class="dsq-tbody" role="rowgroup">
                                <div v-if="filteredCodeUnits.length === 0" class="empty-state">
                                    <h3>No results</h3>
                                    <p>Try adjusting filters or search terms.</p>
                                </div>
                                <button
                                    v-for="unit in filteredCodeUnits"
                                    :key="unit.code_unit_id"
                                    class="dsq-row"
                                    role="row"
                                    type="button"
                                    :aria-selected="String(selectedCodeUnitId === unit.code_unit_id)"
                                    @click="selectCodeUnit(unit.code_unit_id)"
                                >
                                    <div class="dsq-cell dsq-name">
                                        <div class="dsq-name-strong dsq-truncate" :title="unit.name">{{ unit.name }}</div>
                                        <div class="dsq-subtext">
                                            <span v-if="unit.pendingCount > 0" class="dsq-pending-tag">+{{ unit.pendingCount }} pending</span>
                                        </div>
                                    </div>
                                    <div class="dsq-cell dsq-complexity" :title="unit.maxComplexity" :data-level="unit.maxComplexity">
                                        {{ unit.maxComplexity }}
                                    </div>
                                    <div class="dsq-cell dsq-mono">{{ unit.occurrenceCount }}</div>
                                    <div class="dsq-cell dsq-mono dsq-truncate" :title="unit.filename">{{ unit.filename }}</div>
                                </button>
                            </div>
                        </div>

                        <!-- Right: detail panel -->
                        <aside v-if="!isModalMode" class="dsq-panel dsq-detail" aria-label="Details panel">
                            <div v-if="!selectedCodeUnit" class="empty-state" style="height: 100%;">
                                <h3>Select a code unit</h3>
                                <p>Pick an item from the list to review occurrences and migration notes.</p>
                            </div>

                            <div v-else class="dsq-detail-inner">
                                <div class="dsq-detail-head">
                                    <div class="dsq-detail-title">
                                        <div class="dsq-detail-title-left">
                                            <div class="dsq-detail-name">{{ selectedCodeUnit.name }}</div>
                                        </div>
                                    </div>

                                    <div class="dsq-codeunit-grid">
                                        <div class="dsq-kvs dsq-kvs-compact">
                                            <div class="dsq-k">Complexity</div><div class="dsq-v">{{ selectedCodeUnit.maxComplexity }}</div>
                                            <div class="dsq-k">Analyzed occurrences</div><div class="dsq-v">{{ selectedCodeUnit.occurrenceCount }}</div>
                                            <div v-if="selectedCodeUnit.pendingCount > 0" class="dsq-k">Pending occurrences</div>
                                            <div v-if="selectedCodeUnit.pendingCount > 0" class="dsq-v">{{ selectedCodeUnit.pendingCount }}</div>
                                            <div class="dsq-k">Filename</div>
                                            <div class="dsq-v dsq-vpath" :title="selectedCodeUnit.filename">{{ selectedCodeUnit.filename }}</div>
                                        </div>

                                        <div class="dsq-codeunit-patterns">
                                            <div class="dsq-k" style="margin-bottom: 6px;">Patterns</div>
                                            <div class="dsq-patterns-wrap">
                                                <div class="dsq-patterns-text" :title="(selectedCodeUnit.categories || []).join(', ')">
                                                    {{ formatPatternList(selectedCodeUnit.categories, showAllPatterns ? 999 : 6) }}
                                                </div>
                                                <button
                                                    v-if="selectedCodeUnit.categories.length > 6"
                                                    type="button"
                                                    class="dsq-link"
                                                    @click="showAllPatterns = !showAllPatterns"
                                                >
                                                    {{ showAllPatterns ? 'Show less' : `+${selectedCodeUnit.categories.length - 6} more` }}
                                                </button>
                                            </div>
                                        </div>
                                    </div>

                                </div>

                                <div class="dsq-detail-body">
                                    <details v-for="(occ, idx) in selectedCodeUnit.occurrences" :key="occ.id" class="dsq-occ" :open="idx === 0">
                                        <summary class="dsq-occ-summary">
                                            <div class="dsq-occ-title">
                                                <div class="dsq-occ-top">Occurrence {{ idx + 1 }}</div>
                                                <div class="dsq-occ-meta">
                                                    Line {{ occ.line }} · {{ Array.isArray(occ.category) ? occ.category.join(', ') : '' }}
                                                    <span v-if="isPendingStatus(occ.status)" class="dsq-occ-status" data-status="pending">Pending</span>
                                                </div>
                                            </div>
                                        </summary>

                                        <div class="dsq-occ-body">
                                            <div class="dsq-occ-tabs" role="tablist" aria-label="Occurrence tabs">
                                                <button
                                                    class="dsq-occ-tab"
                                                    type="button"
                                                    role="tab"
                                                    :aria-selected="getOccurrenceTab(occ.id) === 'sql'"
                                                    @click="setOccurrenceTab(occ.id, 'sql')"
                                                >SQL</button>
                                                <button
                                                    class="dsq-occ-tab"
                                                    type="button"
                                                    role="tab"
                                                    :aria-selected="getOccurrenceTab(occ.id) === 'analysis'"
                                                    @click="setOccurrenceTab(occ.id, 'analysis')"
                                                >Analysis</button>
                                                <button
                                                    class="dsq-occ-tab"
                                                    type="button"
                                                    role="tab"
                                                    :aria-selected="getOccurrenceTab(occ.id) === 'complexity'"
                                                    @click="setOccurrenceTab(occ.id, 'complexity')"
                                                >Complexity</button>
                                                <button
                                                    class="dsq-occ-tab"
                                                    type="button"
                                                    role="tab"
                                                    :aria-selected="getOccurrenceTab(occ.id) === 'migration'"
                                                    @click="setOccurrenceTab(occ.id, 'migration')"
                                                >Migration</button>
                                            </div>

                                            <!-- SQL tab -->
                                            <div v-if="getOccurrenceTab(occ.id) === 'sql'" class="dsq-occ-pane">
                                                <div class="dsq-sql-stack">
                                            <div class="dsq-sql-block">
                                                <div class="dsq-sql-meta">
                                                    <span class="dsq-sql-label">SQL classification</span>
                                                    <span class="dsq-sql-value">{{ occ.sql_classification || 'Unknown' }}</span>
                                                </div>
                                                        <div class="section-title">Generated SQL</div>
                                                        <div class="dsq-hint">Best-effort example of the SQL this code builds at runtime (may not match exact runtime values).</div>
                                                        <pre class="dsq-code">{{ occ.generated_sql || 'No generated SQL available.' }}</pre>
                                                    </div>
                                                    <div class="dsq-sql-block">
                                                        <div class="section-title">Original SQL (procedure)</div>
                                                        <pre class="dsq-code">{{ occ.procedure_source || 'No source code available.' }}</pre>
                                                    </div>
                                                </div>
                                            </div>

                                            <!-- Analysis tab -->
                                            <div v-else-if="getOccurrenceTab(occ.id) === 'analysis'" class="dsq-occ-pane">
                                                <div class="text-block">{{ occ.parsedNotes.justification || occ.notes || 'No analysis available.' }}</div>
                                            </div>

                                            <!-- Complexity tab -->
                                            <div v-else-if="getOccurrenceTab(occ.id) === 'complexity'" class="dsq-occ-pane">
                                                <pre class="dsq-code">{{ occ.parsedNotes.complexity || (occ.complexity || '').toUpperCase() || 'No complexity details available.' }}</pre>
                                            </div>

                                            <!-- Migration tab -->
                                            <div v-else class="dsq-occ-pane">
                                                <pre class="dsq-code">{{ occ.parsedNotes.migration_considerations || 'No migration considerations provided.' }}</pre>
                                            </div>
                                        </div>
                                    </details>
                                </div>
                            </div>
                        </aside>

                        <!-- Modal details (used when the split view would be cramped) -->
                        <div
                            v-if="isModalMode && isDetailModalOpen"
                            class="dsq-modal-overlay"
                            role="dialog"
                            aria-modal="true"
                            @click="closeDetailModal"
                        >
                            <div class="dsq-modal" @click.stop>
                                <div class="dsq-modal-bar">
                                    <div class="dsq-modal-title">
                                        {{ selectedCodeUnit ? selectedCodeUnit.name : 'Code Unit Details' }}
                                    </div>
                                    <button type="button" class="dsq-modal-close" @click="closeDetailModal">Close</button>
                                </div>

                                <div class="dsq-modal-body">
                                    <div v-if="!selectedCodeUnit" class="empty-state">
                                        <h3>Select a code unit</h3>
                                        <p>Pick an item from the list to review occurrences and migration notes.</p>
                                    </div>

                                    <div v-else class="dsq-detail-inner">
                                        <div class="dsq-detail-head">
                                            <div class="dsq-detail-title">
                                                <div class="dsq-detail-title-left">
                                                    <div class="dsq-detail-name">{{ selectedCodeUnit.name }}</div>
                                                </div>
                                            </div>

                                            <div class="dsq-codeunit-grid">
                                                <div class="dsq-kvs dsq-kvs-compact">
                                            <div class="dsq-k">Complexity</div><div class="dsq-v">{{ selectedCodeUnit.maxComplexity }}</div>
                                            <div class="dsq-k">Analyzed occurrences</div><div class="dsq-v">{{ selectedCodeUnit.occurrenceCount }}</div>
                                            <div v-if="selectedCodeUnit.pendingCount > 0" class="dsq-k">Pending occurrences</div>
                                            <div v-if="selectedCodeUnit.pendingCount > 0" class="dsq-v">{{ selectedCodeUnit.pendingCount }}</div>
                                                    <div class="dsq-k">Filename</div>
                                                    <div class="dsq-v dsq-vpath" :title="selectedCodeUnit.filename">{{ selectedCodeUnit.filename }}</div>
                                                </div>

                                                <div class="dsq-codeunit-patterns">
                                                    <div class="dsq-k" style="margin-bottom: 6px;">Patterns</div>
                                                    <div class="dsq-patterns-wrap">
                                                        <div class="dsq-patterns-text" :title="(selectedCodeUnit.categories || []).join(', ')">
                                                            {{ formatPatternList(selectedCodeUnit.categories, showAllPatterns ? 999 : 6) }}
                                                        </div>
                                                        <button
                                                            v-if="selectedCodeUnit.categories.length > 6"
                                                            type="button"
                                                            class="dsq-link"
                                                            @click="showAllPatterns = !showAllPatterns"
                                                        >
                                                            {{ showAllPatterns ? 'Show less' : `+${selectedCodeUnit.categories.length - 6} more` }}
                                                        </button>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>

                                        <div class="dsq-detail-body">
                                            <details v-for="(occ, idx) in selectedCodeUnit.occurrences" :key="occ.id" class="dsq-occ" :open="idx === 0">
                                                <summary class="dsq-occ-summary">
                                                    <div class="dsq-occ-title">
                                                        <div class="dsq-occ-top">Occurrence {{ idx + 1 }}</div>
                                                        <div class="dsq-occ-meta">
                                                            Line {{ occ.line }} · {{ Array.isArray(occ.category) ? occ.category.join(', ') : '' }}
                                                            <span v-if="isPendingStatus(occ.status)" class="dsq-occ-status" data-status="pending">Pending</span>
                                                        </div>
                                                    </div>
                                                </summary>

                                                <div class="dsq-occ-body">
                                                    <div class="dsq-occ-tabs" role="tablist" aria-label="Occurrence tabs">
                                                        <button class="dsq-occ-tab" type="button" role="tab" :aria-selected="getOccurrenceTab(occ.id) === 'sql'" @click="setOccurrenceTab(occ.id, 'sql')">SQL</button>
                                                        <button class="dsq-occ-tab" type="button" role="tab" :aria-selected="getOccurrenceTab(occ.id) === 'analysis'" @click="setOccurrenceTab(occ.id, 'analysis')">Analysis</button>
                                                        <button class="dsq-occ-tab" type="button" role="tab" :aria-selected="getOccurrenceTab(occ.id) === 'complexity'" @click="setOccurrenceTab(occ.id, 'complexity')">Complexity</button>
                                                        <button class="dsq-occ-tab" type="button" role="tab" :aria-selected="getOccurrenceTab(occ.id) === 'migration'" @click="setOccurrenceTab(occ.id, 'migration')">Migration</button>
                                                    </div>

                                                    <div v-if="getOccurrenceTab(occ.id) === 'sql'" class="dsq-occ-pane">
                                                        <div class="dsq-sql-stack">
                                                            <div class="dsq-sql-block">
                                                                <div class="dsq-sql-meta">
                                                                    <span class="dsq-sql-label">SQL classification</span>
                                                                    <span class="dsq-sql-value">{{ occ.sql_classification || 'Unknown' }}</span>
                                                                </div>
                                                                <div class="section-title">Generated SQL</div>
                                                                <div class="dsq-hint">Best-effort example of the SQL this code builds at runtime (may not match exact runtime values).</div>
                                                                <pre class="dsq-code">{{ occ.generated_sql || 'No generated SQL available.' }}</pre>
                                                            </div>
                                                            <div class="dsq-sql-block">
                                                                <div class="section-title">Original SQL (procedure)</div>
                                                                <pre class="dsq-code">{{ occ.procedure_source || 'No source code available.' }}</pre>
                                                            </div>
                                                        </div>
                                                    </div>

                                                    <div v-else-if="getOccurrenceTab(occ.id) === 'analysis'" class="dsq-occ-pane">
                                                        <div class="text-block">{{ occ.parsedNotes.justification || occ.notes || 'No analysis available.' }}</div>
                                                    </div>

                                                    <div v-else-if="getOccurrenceTab(occ.id) === 'complexity'" class="dsq-occ-pane">
                                                        <pre class="dsq-code">{{ occ.parsedNotes.complexity || (occ.complexity || '').toUpperCase() || 'No complexity details available.' }}</pre>
                                                    </div>

                                                    <div v-else class="dsq-occ-pane">
                                                        <pre class="dsq-code">{{ occ.parsedNotes.migration_considerations || 'No migration considerations provided.' }}</pre>
                                                    </div>
                                                </div>
                                            </details>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </section>
            </div>
        """
    else:
        dynamic_sql_html = """
            <div class="tab-content" :class="{active: activeTab === 'dynamic-sql'}">
                <h2 class="text-3xl font-bold text-sf-dark-blue mb-6 border-b-2 border-sf-blue pb-2">
                    Dynamic SQL Report
                </h2>
                <div class="empty-state">
                    <h3>No Data Available</h3>
                    <p>Dynamic SQL report data was not provided.</p>
                </div>
            </div>
        """
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Migration Assessment Report</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/vue@3/dist/vue.global.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0"></script>
    <script src="https://cdn.sheetjs.com/xlsx-0.20.1/package/dist/xlsx.full.min.js"></script>
    <script>
      tailwind.config = {{
        theme: {{
          extend: {{
            colors: {{
              'sf-blue': '#29B5E8',
              'sf-dark-blue': '#11567F',
              'sf-deep-blue': '#003545',
              'sf-navy': '#102E46',
              'sf-orange': '#FF9F36',
              'sf-cyan': '#71D3DC',
              'sf-purple': '#7D44CF',
              'sf-pink': '#D45B90',
              'sf-gray': '#8A999E',
              'sf-dark-gray': '#24323D'
            }}
          }}
        }}
      }}
    </script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        :root {{
            /* Snowflake color palette - aligned with waves-generator */
            --sf-blue: #29B5E8;
            --sf-dark-blue: #11567F;
            --sf-deep-blue: #003545;
            --sf-navy: #102E46;
            --sf-orange: #FF9F36;
            --sf-cyan: #71D3DC;
            --sf-purple: #7D44CF;
            --sf-pink: #D45B90;
            --sf-gray: #8A999E;
            --sf-dark-gray: #24323D;
            
            /* Semantic colors */
            --primary-color: var(--sf-blue);
            --secondary-color: var(--sf-dark-blue);
            --success-color: #10b981;
            --warning-color: var(--sf-orange);
            --danger-color: #ef4444;
            --info-color: var(--sf-cyan);
            --bg-color: #f8fafc;
            --card-bg: #ffffff;
            --text-primary: #000000;
            --text-secondary: var(--sf-gray);
            --border-color: #e2e8f0;
            --nav-bg: var(--sf-navy);
            --nav-hover: var(--sf-blue);
        }}
        
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            margin: 0;
            padding: 0;
            background: #FFFFFF;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }}
        .sidebar {{
            width: 248px;
            position: fixed;
            height: 100vh;
            background: #F7F7F7;
            color: #2A3342;
            overflow-y: auto;
            border-right: 1px solid #D5DAE4;
        }}
        .content {{
            margin-left: 248px;
            padding: 2rem;
            background: #FFFFFF;
        }}
        .nav-link {{
            display: flex;
            align-items: center;
            gap: 12px;
            height: 30px;
            padding: 0 16px;
            margin: 0 16px;
            border-radius: 4px;
            color: #2A3342;
            text-decoration: none;
            transition: background 0.2s;
            cursor: pointer;
            font-size: 14px;
            font-weight: 400;
        }}
        .nav-link:hover {{
            background: #D5DAE4;
        }}
        .nav-link.active {{
            background: #D6E6FF;
            color: #1A6CE7;
        }}
        .nav-sublist {{
            padding: 4px 0 8px 0;
        }}
        .nav-sublink {{
            display: block;
            min-height: 30px;
            padding: 6px 16px 6px 24px;
            line-height: 1.25;
            white-space: normal;
            margin: 0 16px;
            border-radius: 4px;
            color: #5C6775;
            font-size: 13px;
            text-decoration: none;
            cursor: pointer;
            font-weight: 400;
        }}
        .nav-sublink:hover {{
            color: #2A3342;
            background: #D5DAE4;
        }}
        
        /* Exclusion Report Styles */
        .header {{
            background: #FFFFFF;
            color: #102E46;
            padding: 1.5rem 1.5rem;
            border-radius: 12px;
            margin-bottom: 2rem;
            border: 1px solid #D5DAE4;
            box-shadow: 0 1px 3px rgba(0,0,0,0.06);
        }}
        .header h1 {{
            font-size: 1.625rem;
            font-weight: 800;
            margin-bottom: 0.5rem;
            color: #102E46;
        }}
        .header p {{
            font-size: 1rem;
            opacity: 1;
            color: #64748B;
        }}
        .section {{
            background: var(--card-bg);
            border-radius: 12px;
            padding: 2rem;
            margin-bottom: 2rem;
            box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1);
        }}
        .section-title {{
            font-size: 1.875rem;
            font-weight: 700;
            color: var(--sf-dark-blue);
            margin-bottom: 1.5rem;
            padding-bottom: 0.5rem;
            border-bottom: 2px solid var(--sf-blue);
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1.25rem;
            margin: 1.5rem 0;
        }}
        .stat-card {{
            background: white;
            border: 1px solid var(--sf-gray);
            border-radius: 8px;
            padding: 1.5rem;
            text-align: center;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
            transition: all 0.2s;
        }}
        .stat-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.15);
        }}
        .stat-card h3 {{
            font-size: 2.5rem;
            font-weight: 700;
            color: var(--sf-blue);
            margin-bottom: 0.5rem;
        }}
        .stat-card p {{
            font-size: 0.875rem;
            color: var(--sf-gray);
            font-weight: 500;
            margin-top: 0.5rem;
        }}
        .stat-card.primary h3 {{ color: var(--sf-blue); }}
        .stat-card.warning h3 {{ color: var(--sf-orange); }}
        .stat-card.danger h3 {{ color: var(--danger-color); }}
        .stat-card.success h3 {{ color: var(--success-color); }}
        .stat-card.info h3 {{ color: var(--sf-cyan); }}
        .summary-box {{
            background: #f8fafc;
            padding: 1.5rem;
            border-radius: 10px;
            margin: 1.5rem 0;
            line-height: 1.8;
            font-size: 0.9375rem;
            color: var(--text-primary);
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
            border-left: 4px solid var(--primary-color);
        }}
        .summary-box strong {{
            color: var(--primary-color);
            font-weight: 600;
        }}
        .pattern-badge {{
            display: inline-block;
            background: var(--primary-color);
            color: white;
            padding: 0.25rem 0.65rem;
            border-radius: 12px;
            font-size: 0.8rem;
            margin: 0.15rem;
            font-weight: 600;
        }}
        .testing-reason {{
            color: var(--info-color);
            font-weight: 600;
            margin-top: 0.5rem;
            padding: 0.5rem;
            background: #e0f2fe;
            border-radius: 6px;
            font-size: 0.9rem;
        }}
        .production-version-info {{
            color: var(--success-color);
            font-weight: 600;
            margin-top: 0.5rem;
            padding: 0.5rem;
            background: #d1fae5;
            border-radius: 6px;
            font-size: 0.9rem;
        }}
        .dependency-warning {{
            color: #b45309;
            font-weight: 600;
            margin-top: 0.5rem;
            padding: 0.75rem;
            background: #fef3c7;
            border-radius: 6px;
            border-left: 4px solid #f59e0b;
            font-size: 0.9rem;
        }}
        .dependency-info {{
            color: #1e40af;
            font-weight: 500;
            margin-top: 0.5rem;
            padding: 0.75rem;
            background: #dbeafe;
            border-radius: 6px;
            border-left: 4px solid #3b82f6;
            font-size: 0.85rem;
        }}
        .dependency-list {{
            margin-top: 0.5rem;
            padding-left: 1rem;
            font-size: 0.85rem;
            color: var(--text-secondary);
        }}
        .dependency-list li {{
            margin: 0.25rem 0;
        }}
        .caller-info {{
            margin-top: 0.75rem;
            padding: 0.75rem;
            background: #f0f9ff;
            border-radius: 6px;
            border-left: 4px solid #0ea5e9;
        }}
        .caller-toggle {{
            background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
            color: white;
            border: none;
            padding: 0.625rem 1.25rem;
            border-radius: 6px;
            font-size: 0.9rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            box-shadow: 0 2px 4px rgba(14, 165, 233, 0.2);
        }}
        .caller-toggle:hover {{
            transform: translateY(-1px);
            box-shadow: 0 4px 8px rgba(14, 165, 233, 0.3);
        }}
        .caller-toggle:active {{
            transform: translateY(0);
        }}
        .caller-toggle .arrow {{
            transition: transform 0.2s;
            font-size: 0.8rem;
        }}
        .caller-toggle.expanded .arrow {{
            transform: rotate(180deg);
        }}
        .caller-list {{
            display: none;
            margin-top: 0.75rem;
            padding: 0;
            list-style: none;
        }}
        .caller-list.show {{
            display: block;
        }}
        .caller-item {{
            padding: 0.75rem;
            margin: 0.5rem 0;
            background: white;
            border-radius: 6px;
            border-left: 3px solid #0ea5e9;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
            transition: all 0.2s;
        }}
        .caller-item:hover {{
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
            transform: translateX(2px);
        }}
        .caller-item.problematic {{
            border-left-color: #ef4444;
            background: #fef2f2;
        }}
        .caller-item-name {{
            font-weight: 600;
            color: var(--text-primary);
            font-size: 0.95rem;
            margin-bottom: 0.25rem;
        }}
        .caller-item-details {{
            font-size: 0.85rem;
            color: var(--text-secondary);
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
        }}
        .caller-badge {{
            display: inline-block;
            background: #fee2e2;
            color: #991b1b;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
        }}
        .production-badge {{
            display: inline-block;
            background: var(--success-color);
            color: white;
            padding: 0.375rem 0.875rem;
            border-radius: 16px;
            font-size: 0.8rem;
            font-weight: 700;
            margin-left: 0.5rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .deprecated-badge {{
            display: inline-block;
            background: var(--warning-color);
            color: white;
            padding: 0.375rem 0.875rem;
            border-radius: 16px;
            font-size: 0.8rem;
            font-weight: 700;
            margin-left: 0.5rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .version-badge {{
            display: inline-block;
            background: var(--info-color);
            color: white;
            padding: 0.25rem 0.65rem;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: 600;
            margin-left: 0.5rem;
        }}
        .no-results {{
            text-align: center;
            padding: 3rem;
            color: var(--text-secondary);
            font-size: 1rem;
            font-style: italic;
        }}
        code {{
            background: #f1f5f9;
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 0.875em;
            color: var(--secondary-color);
            border: 1px solid var(--border-color);
        }}
        @media (max-width: 768px) {{
            .header h1 {{
                font-size: 1.5rem;
            }}
            .section-title {{
                font-size: 1.5rem;
            }}
            .stats-grid {{
                grid-template-columns: 1fr;
            }}
        }}
        .download-section {{
            margin: 1.5rem 0;
            padding: 2rem;
            background: linear-gradient(135deg, var(--primary-color) 0%, var(--secondary-color) 100%);
            border-radius: 12px;
            text-align: center;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }}
        .download-section h3 {{
            color: white;
            margin-bottom: 1.5rem;
            font-size: 1.125rem;
            font-weight: 700;
        }}
        .download-buttons {{
            display: flex;
            gap: 0.75rem;
            justify-content: center;
            flex-wrap: wrap;
        }}
        .download-btn {{
            background: white;
            color: var(--secondary-color);
            border: none;
            padding: 0.75rem 1.5rem;
            border-radius: 8px;
            font-size: 0.875rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
        }}
        .download-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
            background: #f8fafc;
        }}
        .download-btn:active {{
            transform: translateY(0);
        }}
        .download-btn svg {{
            width: 16px;
            height: 16px;
        }}
        .toast {{
            position: fixed;
            bottom: 2rem;
            right: 2rem;
            background: var(--sf-navy);
            color: white;
            padding: 1rem 1.5rem;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
            z-index: 9999;
            opacity: 0;
            transform: translateY(20px);
            transition: all 0.3s;
            font-weight: 600;
        }}
        .toast.show {{
            opacity: 1;
            transform: translateY(0);
        }}
        .toast.success {{
            background: #059669;
        }}
        .toast.error {{
            background: #dc2626;
        }}
        .info-icon {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 20px;
            height: 20px;
            background: rgba(113, 211, 220, 0.15);
            border-radius: 50%;
            font-size: 13px;
            font-weight: 700;
            color: #71D3DC;
            cursor: help;
            position: relative;
            margin-left: 0.5rem;
            vertical-align: middle;
            transition: all 0.2s;
        }}
        .info-icon:hover {{
            background: #71D3DC;
            color: white;
            transform: scale(1.1);
        }}
        .info-icon .tooltip {{
            visibility: hidden;
            opacity: 0;
            position: absolute;
            bottom: 130%;
            left: 50%;
            transform: translateX(-50%);
            background: var(--sf-navy);
            color: white;
            padding: 0.75rem 1rem;
            border-radius: 8px;
            font-size: 0.8rem;
            font-weight: 500;
            width: 280px;
            text-align: left;
            line-height: 1.5;
            z-index: 1000;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
            transition: all 0.2s;
        }}
        .info-icon .tooltip::after {{
            content: '';
            position: absolute;
            top: 100%;
            left: 50%;
            transform: translateX(-50%);
            border: 8px solid transparent;
            border-top-color: var(--sf-navy);
        }}
        .info-icon:hover .tooltip {{
            visibility: visible;
            opacity: 1;
        }}

        /* Dynamic tooltip appended to body via JavaScript */
        .info-tooltip-dynamic {{
            position: fixed;
            background: #102E46;
            color: white;
            padding: 10px 14px;
            border-radius: 6px;
            font-size: 0.875rem;
            white-space: normal;
            max-width: 300px;
            z-index: 10000;
            box-shadow: 0 4px 16px rgba(0,0,0,0.3);
            pointer-events: none;
            line-height: 1.5;
            font-weight: 400;
            text-align: left;
        }}

        .info-tooltip-dynamic::after {{
            content: '';
            position: absolute;
            top: 100%;
            left: 50%;
            transform: translateX(-50%);
            border: 6px solid transparent;
            border-top-color: #102E46;
        }}

        .stat-card.clickable {{
            cursor: pointer;
        }}
        .stat-card.clickable:hover {{
            transform: translateY(-4px);
            box-shadow: 0 8px 16px rgba(0, 0, 0, 0.15);
            border-color: var(--primary-color);
            transform: translateY(0);
        }}
        
        /* Dynamic SQL Report Styles */
        .tags-container {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}
        /* Modern chips (scoped to Dynamic SQL split-view) */
        /* Pattern display (no chips): readable text + subtle count */
        .dsq-patterns-wrap {{
            display: flex;
            align-items: baseline;
            gap: 10px;
            flex-wrap: wrap;
        }}
        .dsq-patterns-text {{
            color: #11567F;
            font-size: 0.86rem;
            font-weight: 650;
            letter-spacing: 0.1px;
        }}
        .dsq-patterns-more {{
            margin-left: 8px;
            font-size: 0.82rem;
            font-weight: 800;
            color: #65757F;
            border: 1px solid rgba(138, 153, 158, 0.35);
            border-radius: 6px;
            padding: 2px 6px;
        }}
        .dsq-link {{
            border: 0;
            background: transparent;
            color: #29B5E8;
            font-weight: 750;
            cursor: pointer;
            padding: 0;
        }}
        .dsq-link:hover {{
            text-decoration: underline;
        }}

        /* Complexity badges removed (use text instead) */
        .occurrences-list {{ list-style: none; padding: 0; }}
        .occurrence-item {{
            padding: 8px 12px;
            background: #F8FAFC;
            border-radius: 4px;
            margin-bottom: 6px;
            font-size: 0.9rem;
        }}
        .analysis-container {{
            background: #F8FAFC;
            padding: 16px;
            border-radius: 6px;
        }}
        .text-block {{
            font-size: 0.9rem;
            line-height: 1.6;
            white-space: pre-wrap;
            color: #24323D;
        }}

        /* Split-view layout inspired by idea.html (light theme, Snowflake-ish) */
        .dsq-layout {{
            display: grid;
            /* Wider detail panel for readability */
            grid-template-columns: minmax(520px, 1fr) minmax(620px, 720px);
            gap: 14px;
            min-height: 0;
        }}
        .dsq-panel {{
            border: 1px solid #E3E8EE;
            border-radius: 12px;
            background: #FFFFFF;
            overflow: hidden;
            min-height: 0;
            box-shadow: 0 2px 6px rgba(0, 92, 143, 0.08);
        }}
        .dsq-toolbar {{
            padding: 12px;
            border-bottom: 1px solid #E3E8EE;
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
            background: linear-gradient(180deg, rgba(0,0,0,0.03), transparent);
        }}
        .dsq-search {{
            flex: 1;
            min-width: 240px;
        }}
        .dsq-count {{
            margin-left: auto;
            white-space: nowrap;
        }}
        .dsq-thead, .dsq-row {{
            display: grid;
            grid-template-columns: 1.6fr 140px 120px 2.2fr;
            gap: 10px;
            align-items: center;
            padding: 10px 12px;
        }}
        .dsq-thead {{
            font-size: 0.85rem;
            color: #8A999E;
            border-bottom: 1px solid #E3E8EE;
            background: #F8FAFC;
            font-weight: 700;
            letter-spacing: 0.2px;
        }}
        .dsq-tbody {{
            overflow: auto;
            max-height: 520px;
        }}
        .dsq-row {{
            width: 100%;
            border: 0;
            background: transparent;
            text-align: left;
            cursor: pointer;
            border-bottom: 1px solid rgba(227, 232, 238, 0.7);
        }}
        .dsq-row:hover {{
            background: rgba(41, 181, 232, 0.06);
        }}
        .dsq-row[aria-selected="true"] {{
            background: rgba(41, 181, 232, 0.10);
            box-shadow: inset 4px 0 0 #29B5E8;
        }}
        .dsq-row:focus {{
            outline: none;
        }}
        .dsq-row:focus-visible {{
            outline: 3px solid rgba(41, 181, 232, 0.35);
            outline-offset: -2px;
        }}
        .dsq-cell {{
            min-width: 0;
        }}
        .dsq-name-strong {{
            font-weight: 700;
            color: #11567F;
            max-width: 100%;
        }}
        .dsq-subtext {{
            font-size: 0.8rem;
            color: #8A999E;
            margin-top: 2px;
            font-variant-numeric: tabular-nums;
        }}
        .dsq-mono {{
            font-family: 'Courier New', monospace;
            font-size: 0.85rem;
            color: #65757F;
            font-variant-numeric: tabular-nums;
        }}
        .dsq-complexity {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            font-size: 0.85rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.2px;
            color: #24323D;
        }}
        .dsq-complexity::before {{
            content: '';
            width: 8px;
            height: 8px;
            border-radius: 999px;
            background: rgba(41, 181, 232, 0.55); /* default: blue */
            flex: 0 0 auto;
        }}
        .dsq-complexity[data-level="low"] {{
            color: #11567F;
        }}
        .dsq-complexity[data-level="low"]::before {{
            background: rgba(41, 181, 232, 0.55);
        }}
        .dsq-complexity[data-level="medium"] {{
            color: #11567F;
        }}
        .dsq-complexity[data-level="medium"]::before {{
            background: rgba(41, 181, 232, 0.70);
        }}
        .dsq-complexity[data-level="high"] {{
            color: #8A4B00;
        }}
        .dsq-complexity[data-level="high"]::before {{
            background: rgba(255, 159, 54, 0.80);
        }}
        .dsq-complexity[data-level="critical"] {{
            color: #991B1B;
        }}
        .dsq-complexity[data-level="critical"]::before {{
            background: rgba(239, 68, 68, 0.85);
        }}
        .dsq-truncate {{
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        /* .dsq-chips removed (patterns column removed) */
        .dsq-detail {{
            display: flex;
            flex-direction: column;
            min-height: 0;
        }}
        .dsq-detail-inner {{
            display: flex;
            flex-direction: column;
            min-height: 0;
            height: 100%;
        }}
        .dsq-detail-head {{
            padding: 14px;
            border-bottom: 1px solid #E3E8EE;
            background: linear-gradient(180deg, rgba(0,0,0,0.03), transparent);
        }}
        .dsq-detail-title {{
            display: flex;
            gap: 10px;
            align-items: flex-start;
            justify-content: space-between;
        }}
        .dsq-detail-name {{
            font-size: 1rem;
            font-weight: 800;
            color: #11567F;
            word-break: break-word;
        }}
        .dsq-detail-badge-row {{
            margin-top: 10px;
            display: flex;
            align-items: center;
            justify-content: flex-start;
        }}
        .dsq-detail-path {{
            margin-top: 6px;
            font-family: 'Courier New', monospace;
            font-size: 0.8rem;
            color: #8A999E;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            max-width: 460px;
        }}
        .dsq-vmono {{
            font-family: 'Courier New', monospace;
            font-variant-numeric: tabular-nums;
            color: #65757F;
        }}
        .dsq-vpath {{
            font-family: 'Courier New', monospace;
            font-size: 0.85rem;
            color: #65757F;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .dsq-kvs-compact {{
            margin-top: 0;
            gap: 6px 10px;
        }}
        .dsq-codeunit-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 14px;
            margin-top: 10px;
            padding: 10px 12px;
            border: 1px solid #E3E8EE;
            border-radius: 12px;
            background: #F8FAFC;
        }}
        .dsq-codeunit-patterns {{
            min-width: 0;
        }}
        .dsq-kvs {{
            display: grid;
            grid-template-columns: 110px 1fr;
            gap: 8px 10px;
            margin-top: 10px;
            font-size: 0.85rem;
            color: #65757F;
        }}
        .dsq-k {{
            color: #8A999E;
            font-weight: 700;
        }}
        .dsq-v {{
            color: #24323D;
            min-width: 0;
        }}
        /* Code-unit-level tabs removed; we use per-occurrence tabs instead */
        .dsq-detail-body {{
            padding: 14px;
            overflow: auto;
            min-height: 0;
            height: 100%;
        }}

        /* Modal for code-unit details (used when split-view would be cramped) */
        .dsq-modal-overlay {{
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.35);
            z-index: 2000;
            display: flex;
            align-items: flex-start;
            justify-content: center;
            padding: 24px;
            overflow: auto;
        }}
        .dsq-modal {{
            width: 100%;
            max-width: 1100px;
            background: #FFFFFF;
            border-radius: 14px;
            border: 1px solid rgba(227, 232, 238, 0.95);
            box-shadow: 0 18px 60px rgba(0, 0, 0, 0.25);
            overflow: hidden;
        }}
        .dsq-modal-bar {{
            height: 56px;
            padding: 0 14px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid #E3E8EE;
            background: #F8FAFC;
        }}
        .dsq-modal-title {{
            font-weight: 800;
            color: #11567F;
            font-size: 0.95rem;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            max-width: 80%;
        }}
        .dsq-modal-close {{
            border: 1px solid #E3E8EE;
            background: #FFFFFF;
            color: #11567F;
            font-weight: 800;
            padding: 8px 12px;
            border-radius: 10px;
            cursor: pointer;
        }}
        .dsq-modal-close:hover {{
            background: rgba(41, 181, 232, 0.06);
            border-color: rgba(41, 181, 232, 0.35);
        }}
        .dsq-modal-body {{
            overflow: auto;
            max-height: calc(90vh - 56px);
        }}
        .dsq-modal-body .dsq-detail-head {{
            border-bottom: 1px solid #E3E8EE;
        }}
        .dsq-modal-body .dsq-detail-body {{
            height: auto;
        }}
        @media (max-width: 720px) {{
            .dsq-codeunit-grid {{
                grid-template-columns: 1fr;
            }}
        }}
        .dsq-occ {{
            border: 1px solid #E3E8EE;
            border-radius: 12px;
            background: #F8FAFC;
            overflow: hidden;
            margin-bottom: 10px;
        }}
        .dsq-occ-summary {{
            list-style: none;
            cursor: pointer;
            padding: 12px;
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 10px;
            user-select: none;
        }}
        .dsq-occ-summary::-webkit-details-marker {{ display: none; }}
        .dsq-occ-top {{
            font-size: 0.95rem;
            font-weight: 800;
            color: #24323D;
        }}
        .dsq-occ-meta {{
            margin-top: 4px;
            font-size: 0.8rem;
            color: #65757F;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            max-width: 440px;
        }}
        .dsq-occ-status {{
            margin-left: 8px;
            padding: 2px 6px;
            border-radius: 10px;
            font-size: 0.7rem;
            font-weight: 700;
            background: rgba(255, 159, 54, 0.15);
            color: #9A5A0D;
        }}
        .dsq-occ-body {{
            border-top: 1px solid #E3E8EE;
            padding: 12px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            background: #FFFFFF;
        }}
        .dsq-occ-tabs {{
            display: flex;
            gap: 14px;
            flex-wrap: wrap;
            border-bottom: 1px solid #E3E8EE;
            padding-bottom: 6px;
        }}
        .dsq-occ-tab {{
            height: 32px;
            padding: 0 4px;
            border: 0;
            border-bottom: 3px solid transparent;
            background: transparent;
            color: #65757F;
            font-size: 0.9rem;
            font-weight: 800;
            cursor: pointer;
        }}
        .dsq-occ-tab[aria-selected="true"] {{
            color: #11567F;
            border-bottom-color: #29B5E8;
        }}
        .dsq-occ-pane {{
            padding-top: 6px;
        }}
        .dsq-sql-stack {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 12px;
        }}
        .dsq-sql-meta {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 6px;
            font-size: 0.78rem;
            color: #65757F;
        }}
        .dsq-sql-label {{
            text-transform: uppercase;
            letter-spacing: 0.04em;
            font-weight: 700;
            color: #8A999E;
        }}
        .dsq-sql-value {{
            padding: 2px 8px;
            border-radius: 10px;
            background: rgba(41, 181, 232, 0.12);
            color: #11567F;
            font-weight: 700;
            font-size: 0.78rem;
        }}
        .dsq-code {{
            margin: 0;
            padding: 12px;
            border-radius: 10px;
            background: #F8FAFC;
            border: 1px solid #E3E8EE;
            color: #24323D;
            font-family: 'Courier New', monospace;
            font-size: 0.85rem;
            line-height: 1.55;
            /* Wrap long lines (no horizontal scrolling), keep vertical scrolling */
            white-space: pre-wrap;
            overflow-wrap: anywhere;
            word-break: break-word;
            overflow-y: auto;
            overflow-x: hidden;
            max-height: 240px;
        }}
        .dsq-hint {{
            font-size: 0.78rem;
            color: #8A999E;
            margin: 2px 0 8px;
            line-height: 1.35;
        }}
        /* Smaller section labels inside occurrence panes (Generated SQL / Original SQL / etc.) */
        .dsq-occ-body .section-title {{
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0.2px;
            color: #65757F;
            margin-bottom: 6px;
            text-transform: uppercase;
        }}

        /* Stack on typical laptop widths; keep side-by-side mainly for large monitors */
        @media (max-width: 1750px) {{
            .dsq-layout {{ grid-template-columns: 1fr; }}
            .dsq-tbody {{ max-height: 420px; }}
        }}
        .badge {{
            padding: 4px 12px;
            border-radius: 16px;
            font-size: 0.8rem;
            font-weight: 600;
            margin-left: 8px;
        }}
        .badge.critical {{ background: #FF9F36; color: white; }}
        .badge.high {{ background: #D45B90; color: white; }}
        .badge.medium {{ background: #29B5E8; color: white; }}
        .badge.low {{ background: #71D3DC; color: white; }}
        .info-tooltip:hover .tooltip-content {{
            display: block !important;
        }}
        .info-tooltip svg {{
            transition: all 0.2s;
        }}
        .info-tooltip:hover svg {{
            transform: scale(1.1);
        }}
        .metrics-row {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
            margin-bottom: 20px;
        }}
        .metric-item {{
            background: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-radius: 8px;
            padding: 10px 14px;
        }}
        .metric-label {{
            font-size: 0.78rem;
            color: #64748B;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}
        .metric-value {{
            font-size: 1.5rem;
            font-weight: 700;
            color: #11567F;
            margin-top: 2px;
        }}
        .metric-value-warn {{
            color: #FF9F36;
        }}
        .metric-sub {{
            font-size: 0.78rem;
            color: #8A999E;
            margin-top: 2px;
        }}
        .metric-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
            margin: 1rem 0;
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

        .metric-tooltip-cursor-dynamic {{
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
        .export-buttons {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.75rem;
            margin: 1rem 0;
        }}
        .export-btn-compact {{
            background: white;
            border: 1px solid #E2E8F0;
            border-radius: 6px;
            padding: 0.5rem 1rem;
            font-size: 0.875rem;
            font-weight: 500;
            color: #102E46;
            cursor: pointer;
            transition: all 0.15s;
        }}
        .export-btn-compact:hover {{
            border-color: #29B5E8;
            color: #29B5E8;
            background: #F8FAFC;
        }}
        .exclusion-table {{
            width: 100%;
            table-layout: fixed;
            border-collapse: collapse;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .exclusion-table thead {{
            background: #29B5E8;
            color: white;
        }}
        .exclusion-table th {{
            padding: 0.75rem 0.75rem;
            text-align: left;
            font-weight: 600;
            font-size: 0.85rem;
            vertical-align: middle;
        }}
        .exclusion-table th .th-content {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        .exclusion-table td {{
            padding: 0.75rem 0.75rem;
            border-bottom: 1px solid #E2E8F0;
            font-size: 0.85rem;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .exclusion-table td code {{
            display: inline-block;
            max-width: 100%;
            overflow: hidden;
            text-overflow: ellipsis;
            vertical-align: bottom;
        }}
        /* Column widths - total 100% (5 columns) */
        .exclusion-table .col-name {{ width: 40%; }}
        .exclusion-table .col-schema {{ width: 12%; }}
        .exclusion-table .col-type {{ width: 12%; }}
        .exclusion-table .col-reason {{ width: 18%; }}
        .exclusion-table .col-classification {{ width: 18%; }}
        /* Name cell with file path underneath */
        .exclusion-table .name-cell {{
            white-space: normal;
        }}
        .exclusion-table .object-name {{
            display: flex;
            align-items: center;
            gap: 0.25rem;
        }}
        .exclusion-table .object-name code {{
            word-break: break-all;
        }}
        .exclusion-table .object-file {{
            font-size: 0.75rem;
            color: #64748B;
            margin-top: 2px;
            word-break: break-all;
        }}
        .exclusion-table tbody tr:not(.details-row) {{
            background: #FFFFFF;
        }}
        .exclusion-table tbody tr:hover:not(.details-row) {{
            background: #F1F5F9;
        }}
        .exclusion-table tbody tr:last-child td {{
            border-bottom: none;
        }}
        .classification-badge {{
            display: inline-block;
            padding: 0.3rem 0.75rem;
            border-radius: 4px;
            font-size: 0.875rem;
            font-weight: 500;
            white-space: nowrap;
        }}
        .classification-temp {{
            background: #FEF3C7;
            color: #92400E;
        }}
        .classification-deprecated {{
            background: #FEE2E2;
            color: #991B1B;
        }}
        .classification-testing {{
            background: #E0F2FE;
            color: #0369A1;
        }}
        .classification-duplicate {{
            background: #F3E8FF;
            color: #7C3AED;
        }}
        /* Duplicate files list styles */
        .duplicate-files-list {{
            margin-top: 8px;
            display: flex;
            flex-direction: column;
            gap: 6px;
        }}
        .duplicate-file-item {{
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 10px;
            padding: 6px 12px;
            background: #F8FAFC;
            border-radius: 4px;
        }}
        .duplicate-file-item .file-path {{
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            font-size: 0.85rem;
            color: #334155;
            word-break: break-all;
        }}
        /* Referenced by list styles */
        .refs-list {{
            margin-top: 8px;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}
        .refs-item {{
            padding: 4px 12px;
            background: #F8FAFC;
            border-radius: 4px;
        }}
        .refs-item code {{
            font-family: 'SF Mono', Monaco, 'Courier New', monospace;
            font-size: 0.85rem;
            color: #334155;
            word-break: break-all;
        }}
        .refs-item.refs-more {{
            color: #64748B;
            font-style: italic;
            font-size: 0.85rem;
        }}
        .file-recommended-tag {{
            font-size: 0.75rem;
            color: #166534;
            font-weight: 500;
        }}
        .column-filter {{
            padding: 0.35rem 0.6rem;
            border: 1px solid rgba(255,255,255,0.4);
            border-radius: 4px;
            font-size: 0.85rem;
            font-weight: 400;
            background: rgba(255,255,255,0.2);
            color: white;
            cursor: pointer;
            min-width: 100px;
        }}
        .column-filter:focus {{
            outline: none;
            background: rgba(255,255,255,0.3);
        }}
        .column-filter option {{
            color: #102E46;
            background: white;
        }}
        .exclusion-table tr.expandable {{
            cursor: pointer;
        }}
        .exclusion-table tr.expandable:hover td:first-child {{
            color: #29B5E8;
        }}
        .expand-icon {{
            display: inline-block;
            width: 18px;
            height: 18px;
            line-height: 16px;
            text-align: center;
            background: #E2E8F0;
            border-radius: 4px;
            font-size: 0.85rem;
            font-weight: 600;
            color: #64748B;
            margin-left: 0.5rem;
            vertical-align: middle;
        }}
        .exclusion-table tr.expanded .expand-icon {{
            background: #29B5E8;
            color: white;
        }}
        .details-row {{
            background: #F8FAFC !important;
        }}
        .details-row:hover {{
            background: #F8FAFC !important;
        }}
        .details-cell {{
            padding: 1rem 1.25rem 1rem 2.5rem !important;
            border-bottom: 2px solid #E2E8F0 !important;
        }}
        .detail-item {{
            margin-bottom: 0.75rem;
            font-size: 0.95rem;
        }}
        .detail-item:last-child {{
            margin-bottom: 0;
        }}
        .detail-label {{
            font-weight: 600;
            color: #102E46;
        }}
        .detail-sub {{
            display: block;
            margin-top: 0.25rem;
            font-size: 0.875rem;
            color: #64748B;
            padding-left: 1rem;
        }}
        .detail-replacement {{
            background: rgba(16, 185, 129, 0.1);
            padding: 0.75rem;
            border-radius: 6px;
            border-left: 3px solid #10B981;
        }}
        .detail-warning {{
            background: rgba(245, 158, 11, 0.1);
            padding: 0.75rem;
            border-radius: 6px;
            border-left: 3px solid #F59E0B;
        }}
        .detail-info {{
            background: rgba(59, 130, 246, 0.1);
            padding: 0.75rem;
            border-radius: 6px;
            border-left: 3px solid #3B82F6;
        }}
        .dsq-count-note {{
            padding-left: 8px;
            color: #8A999E;
        }}
        .dsq-pending-tag {{
            display: inline-flex;
            align-items: center;
            margin-left: 8px;
            padding: 2px 6px;
            border-radius: 10px;
            background: rgba(255, 159, 54, 0.15);
            color: #9A5A0D;
            font-size: 0.7rem;
            font-weight: 600;
        }}
        .filter-input {{
            padding: 8px 12px;
            border: 1px solid #8A999E;
            border-radius: 6px;
            width: 100%;
            max-width: 300px;
        }}
        .filter-select {{
            padding: 8px 12px;
            border: 1px solid #8A999E;
            border-radius: 6px;
            background: white;
        }}
        .btn-primary {{
            background: #29B5E8;
            color: white;
            padding: 8px 16px;
            border-radius: 6px;
            border: none;
            cursor: pointer;
            transition: background 0.2s;
        }}
        .btn-primary:hover {{ background: #11567F; }}
        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}
        
        /* SSIS report styles (scoped to #ssis-report) */
{ssis_css}
        .empty-state {{
            text-align: center;
            padding: 60px 20px;
            color: #8A999E;
        }}
        .empty-state h3 {{
            font-size: 1.5rem;
            font-weight: 600;
            color: #11567F;
            margin-bottom: 12px;
        }}
        
        /* Dependencies Report Styles */
        /* NOTE: these styles are intentionally scoped to the Dependencies tab to avoid leaking
           into other tabs and causing header styling/height issues. */
        .tab-content.dependencies-tab .container {{
            max-width: 1600px;
            margin: 0 auto;
            background-color: #FCFFFE;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            padding: 40px;
        }}
        
        .tab-content.dependencies-tab html {{
            scroll-behavior: smooth;
            scroll-padding-top: 20px;
        }}
        
        .tab-content.dependencies-tab h1 {{
            color: #005C8F;
            font-size: 2.2em;
            margin-bottom: 10px;
            border-bottom: 3px solid #B6D5F3;
            padding-bottom: 15px;
        }}
        
        .tab-content.dependencies-tab h2 {{
            color: #005C8F;
            font-size: 1.6em;
            margin-top: 40px;
            margin-bottom: 20px;
            border-left: 4px solid #B6D5F3;
            padding-left: 15px;
            scroll-margin-top: 20px;
        }}
        
        .tab-content.dependencies-tab h3 {{
            color: #005C8F;
            font-size: 1.2em;
            margin-top: 25px;
            margin-bottom: 15px;
        }}
        
        .tab-content.dependencies-tab .timestamp {{
            color: #666;
            font-size: 0.95em;
            margin-bottom: 30px;
        }}
        
        .tab-content.dependencies-tab .analysis-info {{
            background: linear-gradient(135deg, #EEF6F7 0%, #CFECEF 100%);
            border-left: 4px solid #005C8F;
            padding: 20px;
            margin: 25px 0;
            border-radius: 6px;
        }}
        
        .tab-content.dependencies-tab .analysis-info p {{
            margin: 8px 0;
            font-size: 0.95em;
        }}
        
        .tab-content.dependencies-tab .analysis-info strong {{
            color: #005C8F;
            font-weight: 600;
        }}
        
        .tab-content.dependencies-tab .stat-label {{
            font-size: 0.9em;
            color: #005C8F;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 10px;
        }}
        
        .tab-content.dependencies-tab .stat-value {{
            font-size: 2.2em;
            font-weight: 700;
            color: #005C8F;
        }}
        
        .tab-content.dependencies-tab .stat-value.large {{
            font-size: 2.8em;
        }}
        
        .tab-content.dependencies-tab .filters {{
            background-color: #EEF6F7;
            border-radius: 8px;
            padding: 15px;
            margin: 20px 0;
            border: 1px solid #CFECEF;
        }}
        
        .tab-content.dependencies-tab .filter-group {{
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            align-items: flex-start;
        }}
        
        .tab-content.dependencies-tab .filter-item {{
            display: flex;
            flex-direction: column;
            gap: 5px;
            min-width: 180px;
        }}
        
        .tab-content.dependencies-tab .filter-item-input-wrapper {{
            display: flex;
            flex-direction: column;
            gap: 6px;
        }}
        
        .tab-content.dependencies-tab .filter-item label {{
            font-size: 0.85em;
            font-weight: 600;
            color: #005C8F;
        }}
        
        .tab-content.dependencies-tab .filter-item input,
        .tab-content.dependencies-tab .filter-item select {{
            padding: 8px 12px;
            border: 1px solid #B6D5F3;
            border-radius: 4px;
            font-size: 0.9em;
            background-color: #FCFFFE;
            transition: border-color 0.2s;
        }}
        
        .tab-content.dependencies-tab .filter-item input:focus,
        .tab-content.dependencies-tab .filter-item select:focus {{
            outline: none;
            border-color: #005C8F;
        }}
        
        .tab-content.dependencies-tab table {{
            width: 100%;
            border-collapse: collapse;
            margin: 25px 0;
            background-color: #FCFFFE;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        /* All Objects (waves generator) table: cap columns so long names don't stretch layout */
        .tab-content.dependencies-tab #objectsTable {{
            table-layout: fixed;
        }}

        .tab-content.dependencies-tab #objectsTable th,
        .tab-content.dependencies-tab #objectsTable td {{
            overflow: hidden;
            text-overflow: ellipsis;
        }}

        .tab-content.dependencies-tab #objectsTable th.col-checkbox {{ width: 40px; min-width: 40px; max-width: 40px; text-align: center; }}
        .tab-content.dependencies-tab #objectsTable th.col-object-name {{ width: 260px; min-width: 220px; text-align: left; }}
        .tab-content.dependencies-tab #objectsTable th.col-type {{ width: 80px; min-width: 70px; }}
        .tab-content.dependencies-tab #objectsTable th.col-file {{ width: 240px; min-width: 200px; text-align: left; }}
        .tab-content.dependencies-tab #objectsTable th.col-wave {{ width: 60px; min-width: 55px; text-align: center; }}
        .tab-content.dependencies-tab #objectsTable th.col-deps {{ width: 88px; min-width: 70px; text-align: center; }}
        .tab-content.dependencies-tab #objectsTable th.col-dependents {{ width: 88px; min-width: 70px; text-align: center; }}
        .tab-content.dependencies-tab #objectsTable th.col-status {{ width: 96px; min-width: 80px; }}
        .tab-content.dependencies-tab #objectsTable th.col-missing {{ width: 96px; min-width: 80px; text-align: center; }}

        .tab-content.dependencies-tab #objectsTable td:nth-child(1) {{ width: 40px; min-width: 40px; max-width: 40px; text-align: center; }}
        .tab-content.dependencies-tab #objectsTable td:nth-child(2) {{ width: 260px; min-width: 220px; text-align: left; }}
        .tab-content.dependencies-tab #objectsTable td:nth-child(3) {{ width: 80px; min-width: 70px; text-align: left; }}
        .tab-content.dependencies-tab #objectsTable td:nth-child(4) {{ width: 240px; min-width: 200px; text-align: left; }}
        .tab-content.dependencies-tab #objectsTable td:nth-child(5) {{ width: 60px; min-width: 55px; text-align: center; }}
        .tab-content.dependencies-tab #objectsTable td:nth-child(6) {{ width: 88px; min-width: 70px; text-align: center; }}
        .tab-content.dependencies-tab #objectsTable td:nth-child(7) {{ width: 88px; min-width: 70px; text-align: center; }}
        .tab-content.dependencies-tab #objectsTable td:nth-child(8) {{ width: 96px; min-width: 80px; text-align: left; }}
        .tab-content.dependencies-tab #objectsTable td:nth-child(9) {{ width: 96px; min-width: 80px; text-align: center; }}

        /* Column resizer for dependencies table */
        .tab-content.dependencies-tab .column-resizer {{
            position: absolute;
            top: 0;
            right: 0;
            width: 8px;
            height: 100%;
            cursor: col-resize;
            user-select: none;
            z-index: 100;
        }}

        .tab-content.dependencies-tab .column-resizer:hover {{
            background-color: rgba(41, 181, 232, 0.3);
            border-right: 2px solid #29B5E8;
        }}

        .tab-content.dependencies-tab #objectsTable thead th {{
            position: sticky;
            top: 0;
            z-index: 110;
        }}

        .tab-content.dependencies-tab thead {{
            background-color: rgb(16, 46, 70);
            color: #FFFFFF;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        /* Table container with scrolling */
        .tab-content.dependencies-tab .table-container {{
            max-height: none;
            overflow: visible;
        }}

        .tab-content.dependencies-tab #objectsTable thead,
        .tab-content.dependencies-tab #objectsTable tbody tr {{
            display: table;
            width: 100%;
            table-layout: fixed;
        }}

        .tab-content.dependencies-tab #objectsTable tbody {{
            display: block;
            max-height: 560px;
            overflow-y: auto;
            overflow-x: hidden;
        }}

        .tab-content.dependencies-tab th {{
            padding: 6px 8px;
            text-align: left;
            font-weight: 600;
            font-size: 0.6875em;
            cursor: pointer;
            user-select: none;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            border-bottom: 1px solid #E5E7EB;
            position: sticky;
            top: 0;
            z-index: 100;
            background-color: rgb(16, 46, 70);
            color: #FFFFFF;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        .tab-content.dependencies-tab th:hover {{
            background-color: rgb(14, 40, 61);
        }}

        .tab-content.dependencies-tab td {{
            padding: 6px 8px;
            border-bottom: 1px solid #F3F4F6;
            font-size: 0.75em;
        }}

        .tab-content.dependencies-tab #objectsTable th.col-checkbox,
        .tab-content.dependencies-tab #objectsTable td:nth-child(1) {{
            padding-left: 0 !important;
            padding-right: 0 !important;
        }}

        .tab-content.dependencies-tab #objectsTable #selectAllCheckbox,
        .tab-content.dependencies-tab #objectsTable .row-checkbox {{
            display: block;
            margin: 0 auto;
        }}

        .tab-content.dependencies-tab tbody tr:hover {{
            background-color: #F9FAFB;
        }}
        
        tbody tr:last-child td {{
            border-bottom: none;
        }}
        
        .object-row {{
            cursor: pointer;
            transition: background-color 0.2s;
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
        
        .badge-success {{
            background-color: #D4EDDA;
            color: #155724;
        }}
        
        .badge-warning {{
            background-color: #FFF3CD;
            color: #856404;
        }}
        
        .badge-danger {{
            background-color: #F8D7DA;
            color: #721C24;
        }}
        
        .badge-info {{
            background-color: #D1ECF1;
            color: #0C5460;
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
            margin-top: 15px;
        }}
        
        .object-table th {{
            background-color: #F9FAFB;
            color: #374151;
            font-size: 0.6875em;
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
        
        .scrollable-waves-container {{
            max-height: 600px;
            overflow-y: auto;
            border: 1px solid #B6D5F3;
            border-radius: 6px;
            padding: 10px;
            margin: 20px 0;
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

        /* All Objects tooltips are rendered by JS near cursor */
        .tab-content.dependencies-tab .object-table [data-tooltip] {{
            position: relative;
            cursor: default;
        }}

        .tab-content.dependencies-tab .object-table [data-tooltip]:hover::after,
        .tab-content.dependencies-tab .object-table [data-tooltip]:hover::before {{
            content: none;
        }}

        .tab-content.dependencies-tab .sort-arrow {{
            margin-left: 2px;
            padding-left: 2px;
        }}
    </style>
</head>
<body>
    <div id="app">
        <div class="sidebar">
            <div style="padding: 24px 24px 16px 24px;">
                <div style="margin-bottom: 8px;">
                    {snowflake_logo_svg}
                </div>
                <div style="margin-bottom: 8px;">
                    {snowconvert_ai_logo_svg}
                </div>
                <div style="border-bottom: 1px solid #D5DAE4; padding-bottom: 0.75rem; margin-bottom: 0.75rem;">
                </div>
                <p style="font-size: 1rem; color: #5D6A85; margin: 0; font-weight: 500;">AI Assessment</p>
            </div>
            <nav style="padding: 16px 0;">
                <a @click="activeTab = 'overview'" class="nav-link" data-tab="overview" :class="{{active: activeTab === 'overview'}}">
                    Overview
                </a>
                <div v-if="activeTab === 'overview'" class="nav-sublist">
                    <a @click="scrollToSection('#workload-inventory', 'overview')" class="nav-sublink">Workload Inventory</a>
                    <a @click="scrollToSection('#how-to-use', 'overview')" class="nav-sublink">How to Use This Report</a>
                    <a @click="scrollToSection('#missing-objects', 'overview')" class="nav-sublink">Missing Objects Analysis</a>
                </div>
                <a @click="activeTab = 'waves'" class="nav-link" data-tab="waves" :class="{{active: activeTab === 'waves'}}">
                    Dependencies Report
                </a>
                <div v-if="activeTab === 'waves'" class="nav-sublist">
                    <a @click="scrollToSection('#overview', 'waves')" class="nav-sublink">Overview</a>
                    <a @click="scrollToSection('#all-objects', 'waves')" class="nav-sublink">All Objects</a>
                    <a @click="scrollToSection('#wave-recommendations', 'waves')" class="nav-sublink">Migration Waves</a>
                </div>
                <a @click="activeTab = 'exclusion'" class="nav-link" data-tab="exclusion" :class="{{active: activeTab === 'exclusion'}}">
                    Exclusion Report
                </a>
                <a @click="activeTab = 'dynamic-sql'" class="nav-link" data-tab="dynamic-sql" :class="{{active: activeTab === 'dynamic-sql'}}">
                    Dynamic SQL Report
                </a>
                <a @click="activeTab = 'ssis'" class="nav-link" data-tab="ssis" :class="{{active: activeTab === 'ssis'}}">
                    SSIS Report
                </a>
                <div v-if="activeTab === 'ssis'" class="nav-sublist">
                    <a @click="scrollToSection('#executive-summary')" class="nav-sublink">AI Summary</a>
                    <a @click="scrollToSection('#metrics')" class="nav-sublink">Key Metrics</a>
                    <a @click="scrollToSection('#package-summary')" class="nav-sublink">Package Classification</a>
                    <a @click="scrollToSection('#not-supported')" class="nav-sublink">Component Breakdown</a>
                </div>
            </nav>
        </div>

        <div class="content">
            {overview_html}
            {exclusion_html}
            {dynamic_sql_html}
            {waves_html}
            {ssis_html}
        </div>
    </div>

    <script>
        /**
         * @typedef {{Object}} DynamicSqlOccurrence
         * @property {{number}} id - Unique occurrence ID
         * @property {{string}} name - Procedure/function name
         * @property {{string}} filename - Source file path
         * @property {{number}} line - Line number in source file
         * @property {{string}} procedure_name - Full procedure name
         * @property {{string}} code_unit_id - Unique code unit identifier
         * @property {{number}} code_unit_start_line - Starting line of code unit
         * @property {{number}} lines_of_code - Total lines in code unit
         * @property {{string}} status - Review status (e.g., REVIEWED, PENDING)
         * @property {{string[]}} category - Pattern categories
         * @property {{string}} complexity - Complexity level (critical/high/medium/low)
         * @property {{string}} notes - Analysis notes
         * @property {{string}} generated_sql - Generated SQL (if any)
         * @property {{string}} sql_classification - SQL type classification
         */

        /**
         * @typedef {{Object}} CodeUnitCard
         * @property {{string}} code_unit_id - Unique identifier
         * @property {{string}} name - Code unit name
         * @property {{string}} filename - Source file
         * @property {{number}} code_unit_start_line - Start line
         * @property {{number}} lines_of_code - LOC count
         * @property {{string}} maxComplexity - Highest complexity (critical/high/medium/low)
         * @property {{number}} occurrenceCount - Number of analyzed occurrences
         * @property {{number}} pendingCount - Pending occurrences excluded from display
         * @property {{string[]}} categories - Pattern categories
         * @property {{DynamicSqlOccurrence[]}} occurrences - Analyzed occurrences
         */

        /**
         * Validates and normalizes a Dynamic SQL occurrence object
         * @param {{any}} occ - Raw occurrence data
         * @returns {{DynamicSqlOccurrence}} Validated occurrence
         */
        function validateOccurrence(occ) {{
            if (!occ || typeof occ !== 'object') {{
                console.error('Invalid occurrence data:', occ);
                return createDefaultOccurrence();
            }}
            
            return {{
                id: Number(occ.id) || 0,
                name: String(occ.name || occ.procedure_name || 'Unknown'),
                filename: String(occ.filename || 'Unknown'),
                line: Number(occ.line) || 0,
                procedure_name: String(occ.procedure_name || occ.name || 'Unknown'),
                procedure_source: String(occ.procedure_source || ''),
                code_unit_id: String(occ.code_unit_id || 'unknown'),
                code_unit_start_line: Number(occ.code_unit_start_line) || 0,
                lines_of_code: Number(occ.lines_of_code) || 0,
                status: String(occ.status || 'PENDING'),
                category: Array.isArray(occ.category) ? occ.category : [],
                complexity: String(occ.complexity || 'low'),
                notes: String(occ.notes || ''),
                generated_sql: String(occ.generated_sql || ''),
                sql_classification: String(occ.sql_classification || '')
            }};
        }}

        /**
         * Creates a default occurrence object for error cases
         * @returns {{DynamicSqlOccurrence}}
         */
        function createDefaultOccurrence() {{
            return {{
                id: 0,
                name: 'Unknown',
                filename: 'Unknown',
                line: 0,
                procedure_name: 'Unknown',
                procedure_source: '',
                code_unit_id: 'unknown',
                code_unit_start_line: 0,
                lines_of_code: 0,
                status: 'UNKNOWN',
                category: [],
                complexity: 'low',
                notes: 'No data available',
                generated_sql: '',
                sql_classification: ''
            }};
        }}

        /**
         * Determines whether a status should be treated as pending.
         * @param {{any}} status
         * @returns {{boolean}}
         */
        function isPendingStatus(status) {{
            const normalized = String(status || '').trim().toUpperCase();
            return normalized === '' || normalized === 'PENDING';
        }}

        // Load and validate data
        const exportData = {json_data_exclusion};
        const isAdaptive = {str(is_adaptive).lower()};
        const rawDynamicSqlData = {json_data_dynamic};
        const dynamicSqlMeta = {dynamic_sql_meta_json};
        const hasExclusion = {str(has_exclusion).lower()};
        const hasDynamicSql = {str(has_dynamic_sql).lower()};
        const hasWaves = {str(has_waves).lower()};
        // Validate and normalize dynamic SQL data
        const dynamicSqlData = Array.isArray(rawDynamicSqlData) 
            ? rawDynamicSqlData.map(validateOccurrence)
            : [];

        if (dynamicSqlData.length === 0 && hasDynamicSql) {{
            console.warn('Dynamic SQL data is empty or invalid');
        }}

        const {{ createApp }} = Vue;

        createApp({{
            data() {{
                return {{
                    activeTab: '{default_tab}',
                    jsonData: dynamicSqlData,
                    searchQuery: '',
                    complexityFilter: 'all',
                    categoryFilter: 'all',
                    sqlClassificationFilter: 'all',
                    selectedCodeUnitId: null,
                    showAllPatterns: false,
                    occurrenceTabs: {{}},
                    windowWidth: (typeof window !== 'undefined' ? window.innerWidth : 9999),
                    isDetailModalOpen: false
                }}
            }},
            computed: {{
                hasDynamicSqlMeta() {{
                    return dynamicSqlMeta && typeof dynamicSqlMeta === 'object' && Object.keys(dynamicSqlMeta).length > 0;
                }},
                dynamicSqlFiles() {{
                    // Backwards compatible: prefer metadata.files, fallback to metadata.source
                    const files = (dynamicSqlMeta && dynamicSqlMeta.files) ? dynamicSqlMeta.files : (dynamicSqlMeta && dynamicSqlMeta.source) ? dynamicSqlMeta.source : {{}};
                    return files || {{}};
                }},
                formattedDynamicSqlGeneratedAt() {{
                    const raw = dynamicSqlMeta && dynamicSqlMeta.generated_at ? String(dynamicSqlMeta.generated_at) : '';
                    if (!raw) return 'Unknown';
                    const d = new Date(raw);
                    if (Number.isNaN(d.getTime())) return raw;
                    return d.toLocaleString(undefined, {{
                        year: 'numeric',
                        month: 'short',
                        day: '2-digit',
                        hour: '2-digit',
                        minute: '2-digit'
                    }});
                }},
                groupedByCodeUnit() {{
                    const groups = {{}};
                    if (!Array.isArray(this.jsonData)) {{
                        console.error('jsonData is not an array');
                        return groups;
                    }}
                    
                    this.jsonData.forEach(row => {{
                        const codeUnitId = row.code_unit_id || 'unknown';
                        if (!groups[codeUnitId]) groups[codeUnitId] = [];
                        groups[codeUnitId].push(row);
                    }});
                    return groups;
                }},
                analyzedOccurrences() {{
                    if (!Array.isArray(this.jsonData)) return [];
                    return this.jsonData.filter(row => !isPendingStatus(row && row.status));
                }},
                analyzedOccurrencesCount() {{
                    return Array.isArray(this.analyzedOccurrences) ? this.analyzedOccurrences.length : 0;
                }},
                pendingOccurrencesCount() {{
                    if (!Array.isArray(this.jsonData)) return 0;
                    return this.jsonData.filter(row => isPendingStatus(row && row.status)).length;
                }},
                codeUnitCards() {{
                    try {{
                        return Object.keys(this.groupedByCodeUnit).map(code_unit_id => {{
                            const allOccurrences = this.groupedByCodeUnit[code_unit_id];
                            
                            if (!Array.isArray(allOccurrences) || allOccurrences.length === 0) {{
                                console.warn(`No occurrences for code unit: ${{code_unit_id}}`);
                                return null;
                            }}
                            
                            const analyzedOccurrences = allOccurrences.filter(occ => !isPendingStatus(occ && occ.status));
                            const pendingCount = allOccurrences.length - analyzedOccurrences.length;
                            if (analyzedOccurrences.length === 0) {{
                                return null;
                            }}
                            
                            const categories = new Set();
                            analyzedOccurrences.forEach(occ => {{
                                if (Array.isArray(occ.category)) {{
                                    occ.category.forEach(cat => {{
                                        if (cat && typeof cat === 'string') {{
                                            categories.add(cat.trim());
                                        }}
                                    }});
                                }}
                            }});
                            
                            const firstOcc = analyzedOccurrences[0] || allOccurrences[0] || {{}};
                            
                            return {{
                                code_unit_id,
                                name: firstOcc.name || 'Unknown',
                                filename: firstOcc.filename || 'Unknown',
                                code_unit_start_line: firstOcc.code_unit_start_line || 0,
                                lines_of_code: firstOcc.lines_of_code || 0,
                                maxComplexity: this.getMaxComplexity(analyzedOccurrences),
                                occurrenceCount: analyzedOccurrences.length,
                                pendingCount,
                                categories: Array.from(categories),
                                occurrences: allOccurrences.map(occ => ({{
                                    ...occ,
                                    parsedNotes: this.parseNotes(occ.notes)
                                }}))
                            }};
                        }}).filter(card => card !== null).sort((a, b) => {{
                            const complexityOrder = {{ critical: 0, high: 1, medium: 2, low: 3 }};
                            const aComplexity = a.maxComplexity || 'low';
                            const bComplexity = b.maxComplexity || 'low';
                            const complexityDiff = (complexityOrder[aComplexity] || 3) - (complexityOrder[bComplexity] || 3);
                            if (complexityDiff !== 0) return complexityDiff;
                            return b.occurrenceCount - a.occurrenceCount;
                        }});
                    }} catch (error) {{
                        console.error('Error in codeUnitCards:', error);
                        return [];
                    }}
                }},
                filteredCodeUnits() {{
                    try {{
                        return this.codeUnitCards.filter(unit => {{
                            if (!unit) return false;
                            
                            const searchLower = (this.searchQuery || '').toLowerCase();
                            const matchesSearch = searchLower === '' ||
                                (unit.name || '').toLowerCase().includes(searchLower) ||
                                (unit.filename || '').toLowerCase().includes(searchLower) ||
                                (Array.isArray(unit.categories) && unit.categories.join(' ').toLowerCase().includes(searchLower)) ||
                                (Array.isArray(unit.occurrences) && unit.occurrences.some(o => String((o && o.generated_sql) || '').toLowerCase().includes(searchLower)));
                            
                            const matchesComplexity = this.complexityFilter === 'all' || 
                                unit.maxComplexity === this.complexityFilter;
                            
                            const matchesCategory = this.categoryFilter === 'all' || 
                                (Array.isArray(unit.categories) && unit.categories.includes(this.categoryFilter));

                            const matchesSqlClass = this.sqlClassificationFilter === 'all' ||
                                (Array.isArray(unit.occurrences) && unit.occurrences.some(o => {{
                                    const cls = String((o && o.sql_classification) || 'UNKNOWN').trim().toUpperCase();
                                    return cls === this.sqlClassificationFilter;
                                }}));
                            
                            return matchesSearch && matchesComplexity && matchesCategory && matchesSqlClass;
                        }});
                    }} catch (error) {{
                        console.error('Error in filteredCodeUnits:', error);
                        return [];
                    }}
                }},
                selectedCodeUnit() {{
                    if (!this.selectedCodeUnitId) return null;
                    const all = Array.isArray(this.codeUnitCards) ? this.codeUnitCards : [];
                    return all.find(u => u && u.code_unit_id === this.selectedCodeUnitId) || null;
                }},
                isModalMode() {{
                    // Keep in sync with the CSS breakpoint used to switch to single-column list
                    return (this.windowWidth || 0) < 1750;
                }},
                totalOccurrences() {{ 
                    return Array.isArray(this.jsonData) ? this.jsonData.length : 0;
                }},
                uniqueCodeUnits() {{ 
                    return Array.isArray(this.codeUnitCards) ? this.codeUnitCards.length : 0;
                }},
                highPriority() {{ 
                    if (!Array.isArray(this.analyzedOccurrences)) return 0;
                    return this.analyzedOccurrences.filter(r => {{
                        const complexity = ((r && r.complexity) || 'low').toLowerCase();
                        return complexity === 'critical' || complexity === 'high';
                    }}).length;
                }},
                sortedPatterns() {{
                    /**
                     * Category summary should reflect:
                     * - occurrences: how many times a category appears across all occurrences
                     * - code units: how many distinct code units contain at least one occurrence of the category
                     */
                    const totalsByCategory = {{}};
                    const codeUnitsByCategory = {{}};
                    const patterns = [];
                    const total = this.analyzedOccurrencesCount || 1; // Avoid division by zero

                    if (Array.isArray(this.analyzedOccurrences)) {{
                        this.analyzedOccurrences.forEach(row => {{
                            const codeUnitId = (row && row.code_unit_id) ? String(row.code_unit_id) : 'unknown';
                            if (row && Array.isArray(row.category)) {{
                                row.category.forEach(cat => {{
                                    if (cat && typeof cat === 'string') {{
                                        const category = cat.trim();
                                        if (!category) return;
                                        totalsByCategory[category] = (totalsByCategory[category] || 0) + 1;
                                        if (!codeUnitsByCategory[category]) codeUnitsByCategory[category] = new Set();
                                        codeUnitsByCategory[category].add(codeUnitId);
                                    }}
                                }});
                            }}
                        }});
                    }}

                    for (const [name, count] of Object.entries(totalsByCategory)) {{
                        const cuSet = codeUnitsByCategory[name];
                        const codeUnitCount = cuSet && typeof cuSet.size === 'number' ? cuSet.size : 0;
                        patterns.push({{
                            name,
                            count,
                            codeUnitCount,
                            percentage: ((count / total) * 100).toFixed(1)
                        }});
                    }}

                    return patterns.sort((a, b) => {{
                        if (b.count !== a.count) return b.count - a.count;
                        return b.codeUnitCount - a.codeUnitCount;
                    }});
                }},
                sortedSqlClassifications() {{
                    const totalsByClass = {{}};
                    const codeUnitsByClass = {{}};
                    const entries = [];
                    const total = this.analyzedOccurrencesCount || 1;

                    if (Array.isArray(this.analyzedOccurrences)) {{
                        this.analyzedOccurrences.forEach(row => {{
                            const codeUnitId = (row && row.code_unit_id) ? String(row.code_unit_id) : 'unknown';
                            const cls = String((row && row.sql_classification) || 'UNKNOWN').trim().toUpperCase();
                            totalsByClass[cls] = (totalsByClass[cls] || 0) + 1;
                            if (!codeUnitsByClass[cls]) codeUnitsByClass[cls] = new Set();
                            codeUnitsByClass[cls].add(codeUnitId);
                        }});
                    }}

                    for (const [name, count] of Object.entries(totalsByClass)) {{
                        const cuSet = codeUnitsByClass[name];
                        const codeUnitCount = cuSet && typeof cuSet.size === 'number' ? cuSet.size : 0;
                        entries.push({{
                            name,
                            count,
                            codeUnitCount,
                            percentage: ((count / total) * 100).toFixed(1)
                        }});
                    }}

                    return entries.sort((a, b) => b.count - a.count);
                }},
                allCategories() {{ 
                    const patterns = Array.isArray(this.sortedPatterns) ? this.sortedPatterns : [];
                    return patterns.map(p => p.name).filter(Boolean).sort();
                }},
                allSqlClassifications() {{
                    const entries = Array.isArray(this.sortedSqlClassifications) ? this.sortedSqlClassifications : [];
                    return entries.map(e => e.name).filter(Boolean).sort();
                }},
                keyFindings() {{
                    const findings = [];
                    const sortedPatterns = Array.isArray(this.sortedPatterns) ? this.sortedPatterns : [];
                    
                    if (sortedPatterns.length > 0) {{
                        const top = sortedPatterns[0];
                        if (top && top.name && top.count !== undefined) {{
                            findings.push(`<strong>${{top.name}}</strong> is the most common pattern (${{top.count}} occurrences).`);
                        }}
                    }}
                    
                    if (!Array.isArray(this.analyzedOccurrences)) {{
                        return findings;
                    }}
                    
                    const complexityCounts = {{
                        critical: this.analyzedOccurrences.filter(r => r && (r.complexity || '').toLowerCase() === 'critical').length,
                        high: this.analyzedOccurrences.filter(r => r && (r.complexity || '').toLowerCase() === 'high').length
                    }};
                    
                    if (complexityCounts.critical > 0 || complexityCounts.high > 0) {{
                        findings.push(`<strong>${{complexityCounts.critical + complexityCounts.high}} high-priority items</strong> require immediate attention.`);
                    }}

                    if (this.pendingOccurrencesCount > 0) {{
                        findings.push(`<strong>${{this.pendingOccurrencesCount}}</strong> occurrence${{this.pendingOccurrencesCount === 1 ? '' : 's'}} pending review and excluded from code units.`);
                    }}
                    
                    return findings;
                }}
            }},
            watch: {{
                filteredCodeUnits(newList) {{
                    // Keep a valid selection as filters/search change
                    if (!Array.isArray(newList) || newList.length === 0) {{
                        this.selectedCodeUnitId = null;
                        this.isDetailModalOpen = false;
                        return;
                    }}
                    const stillVisible = newList.some(u => u && u.code_unit_id === this.selectedCodeUnitId);
                    if (!this.selectedCodeUnitId || !stillVisible) {{
                        this.selectedCodeUnitId = newList[0].code_unit_id;
                        this.showAllPatterns = false;
                    }}
                }},
                isModalMode(newVal) {{
                    // If we leave modal mode (wide screen), ensure modal is closed
                    if (!newVal) {{
                        this.isDetailModalOpen = false;
                        try {{ document.body.style.overflow = ''; }} catch (e) {{}}
                    }}
                }}
            }},
            methods: {{
                isPendingStatus(status) {{
                    return isPendingStatus(status);
                }},
                getMaxComplexity(occurrences) {{
                    const complexityOrder = {{ critical: 0, high: 1, medium: 2, low: 3 }};
                    let max = 'low';
                    occurrences.forEach(occ => {{
                        const complexity = (occ.complexity || 'low').toLowerCase();
                        if (complexityOrder[complexity] !== undefined && complexityOrder[complexity] < complexityOrder[max]) {{
                            max = complexity;
                        }}
                    }});
                    return max;
                }},
                parseNotes(notesString) {{
                    // If notes is already an object, return structured data
                    if (typeof notesString === 'object') {{
                        return {{
                            justification: notesString.justification || notesString.notes || '',
                            complexity: notesString.complexity || '',
                            migration_considerations: notesString.migration_considerations || ''
                        }};
                    }}
                    
                    // Try to parse as JSON first
                    try {{
                        const notes = JSON.parse(notesString);
                        return {{
                            justification: notes.justification || notes.notes || '',
                            complexity: notes.complexity || '',
                            migration_considerations: notes.migration_considerations || ''
                        }};
                    }} catch (e) {{
                        // If not JSON, treat as plain text - put it all in justification
                        return {{ 
                            justification: notesString || 'No notes available',
                            complexity: '',
                            migration_considerations: ''
                        }};
                    }}
                }},
                selectCodeUnit(codeUnitId) {{
                    this.selectedCodeUnitId = codeUnitId;
                    this.showAllPatterns = false;
                    if (this.isModalMode) {{
                        this.openDetailModal();
                    }}
                }},
                openDetailModal() {{
                    this.isDetailModalOpen = true;
                    try {{ document.body.style.overflow = 'hidden'; }} catch (e) {{}}
                }},
                closeDetailModal() {{
                    this.isDetailModalOpen = false;
                    try {{ document.body.style.overflow = ''; }} catch (e) {{}}
                }},
                getOccurrenceTab(occId) {{
                    const id = String(occId);
                    return (this.occurrenceTabs && this.occurrenceTabs[id]) ? this.occurrenceTabs[id] : 'sql';
                }},
                setOccurrenceTab(occId, tab) {{
                    const id = String(occId);
                    if (!this.occurrenceTabs) this.occurrenceTabs = {{}};
                    this.occurrenceTabs[id] = tab;
                }},
                formatPatternList(patterns, limit) {{
                    const list = Array.isArray(patterns) ? patterns.filter(Boolean) : [];
                    const n = Number(limit) || list.length;
                    return list.slice(0, n).join(', ');
                }},
                clearFilters() {{
                    this.searchQuery = '';
                    this.complexityFilter = 'all';
                    this.categoryFilter = 'all';
                    this.sqlClassificationFilter = 'all';
                    // Selection will be set by watcher once filtered list updates
                }},
                scrollToSection(selector, tab = 'ssis') {{
                    // Ensure the correct tab is active, then scroll to the section
                    this.activeTab = tab;
                    this.$nextTick(() => {{
                        try {{
                            const el = document.querySelector(selector);
                            if (el) {{
                                el.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
                            }}
                        }} catch (e) {{}}
                    }});
                }},
                getSqlClassificationColor(classification) {{
                    const colors = {{
                        'DQL': 'low', 'DML': 'medium', 'DDL': 'high',
                        'DCL': 'medium', 'TCL': 'medium', 'UNKNOWN': 'low'
                    }};
                    return colors[classification] || 'low';
                }}
            }},
            mounted() {{
                // Initialize selection (first visible code unit) for a better default UX
                if (Array.isArray(this.filteredCodeUnits) && this.filteredCodeUnits.length > 0) {{
                    this.selectedCodeUnitId = this.filteredCodeUnits[0].code_unit_id;
                }}

                // Track viewport width to decide when to use modal vs side-by-side
                const onResize = () => {{
                    this.windowWidth = window.innerWidth;
                }};
                window.addEventListener('resize', onResize);

                // Close modal on ESC
                const onKeyDown = (e) => {{
                    if (e && e.key === 'Escape' && this.isDetailModalOpen) {{
                        this.closeDetailModal();
                    }}
                }};
                window.addEventListener('keydown', onKeyDown);
            }}
        }}).mount('#app');
        
        function toggleCallers(objId, event) {{
            const callerList = document.getElementById('callers-' + objId);
            const button = event.currentTarget;
            
            if (callerList.classList.contains('show')) {{
                callerList.classList.remove('show');
                button.classList.remove('expanded');
            }} else {{
                callerList.classList.add('show');
                button.classList.add('expanded');
            }}
        }}
        
        // Exclusion table filter functionality
        function filterExclusionTable() {{
            const classificationFilter = document.getElementById('classification-filter');
            const typeFilter = document.getElementById('type-filter');
            const schemaFilter = document.getElementById('schema-filter');
            const reasonFilter = document.getElementById('reason-filter');
            const searchInput = document.getElementById('search-objects');
            const table = document.getElementById('exclusion-objects-table');
            const countSpan = document.getElementById('table-count');
            
            if (!table) return;
            
            const classification = classificationFilter ? classificationFilter.value : 'all';
            const objType = typeFilter ? typeFilter.value : 'all';
            const schema = schemaFilter ? schemaFilter.value : 'all';
            const reason = reasonFilter ? reasonFilter.value : 'all';
            const searchText = searchInput ? searchInput.value.toLowerCase() : '';
            
            // Get data rows (not details rows)
            const rows = table.querySelectorAll('tbody tr:not(.details-row)');
            
            let visibleCount = 0;
            let totalCount = rows.length;
            
            rows.forEach(row => {{
                const rowClassification = row.getAttribute('data-classification');
                const rowType = row.getAttribute('data-type');
                const rowSchema = row.getAttribute('data-schema');
                const rowReason = row.getAttribute('data-reason');
                const rowText = row.textContent.toLowerCase();
                
                const matchesClassification = classification === 'all' || (rowClassification && rowClassification.includes(classification));
                const matchesType = objType === 'all' || rowType === objType;
                const matchesSchema = schema === 'all' || rowSchema === schema;
                const matchesReason = reason === 'all' || (rowReason && rowReason.includes(reason));
                const matchesSearch = searchText === '' || rowText.includes(searchText);
                
                if (matchesClassification && matchesType && matchesSchema && matchesReason && matchesSearch) {{
                    row.style.display = '';
                    visibleCount++;
                }} else {{
                    row.style.display = 'none';
                    row.classList.remove('expanded');
                    const icon = row.querySelector('.expand-icon');
                    if (icon) icon.textContent = '+';
                }}
            }});
            
            // Hide all details rows when filtering
            table.querySelectorAll('.details-row').forEach(detailRow => {{
                detailRow.style.display = 'none';
            }});
            
            // Reset expanded state
            table.querySelectorAll('tr.expanded').forEach(row => {{
                row.classList.remove('expanded');
                const icon = row.querySelector('.expand-icon');
                if (icon) icon.textContent = '+';
            }});
            
            if (countSpan) {{
                countSpan.textContent = `Showing ${{visibleCount}} of ${{totalCount}} objects`;
            }}
        }}
        
        // Clear all filters
        function clearExclusionFilters() {{
            const classificationFilter = document.getElementById('classification-filter');
            const typeFilter = document.getElementById('type-filter');
            const schemaFilter = document.getElementById('schema-filter');
            const reasonFilter = document.getElementById('reason-filter');
            const searchInput = document.getElementById('search-objects');
            
            if (classificationFilter) classificationFilter.value = 'all';
            if (typeFilter) typeFilter.value = 'all';
            if (schemaFilter) schemaFilter.value = 'all';
            if (reasonFilter) reasonFilter.value = 'all';
            if (searchInput) searchInput.value = '';
            
            filterExclusionTable();
        }}
        
        // Toggle details row
        function toggleDetails(rowId, rowElement) {{
            const detailsRow = document.getElementById('details-' + rowId);
            if (!detailsRow) return;
            
            if (detailsRow.style.display === 'none') {{
                detailsRow.style.display = '';
                rowElement.classList.add('expanded');
                const icon = rowElement.querySelector('.expand-icon');
                if (icon) icon.textContent = '−';
            }} else {{
                detailsRow.style.display = 'none';
                rowElement.classList.remove('expanded');
                const icon = rowElement.querySelector('.expand-icon');
                if (icon) icon.textContent = '+';
            }}
        }}
        
        // Initialize table count on load
        document.addEventListener('DOMContentLoaded', function() {{
            filterExclusionTable();
        }});
        
        // Navigate to table and optionally set filter
        function navigateToCategory(category) {{
            // Scroll to flagged objects table
            const tableSection = document.getElementById('objects');
            if (tableSection) {{
                const offset = 20;
                const elementPosition = tableSection.getBoundingClientRect().top;
                const offsetPosition = elementPosition + window.pageYOffset - offset;
                
                window.scrollTo({{
                    top: offsetPosition,
                    behavior: 'smooth'
                }});
            }}
            
            // Set classification filter based on category
            const classificationFilter = document.getElementById('classification-filter');
            if (classificationFilter) {{
                if (category === 'temp') {{
                    classificationFilter.value = 'temp';
                }} else if (category === 'deprecated') {{
                    classificationFilter.value = 'deprecated';
                }} else if (category === 'testing') {{
                    classificationFilter.value = 'testing';
                }} else if (category === 'duplicate') {{
                    classificationFilter.value = 'duplicate';
                }} else {{
                    classificationFilter.value = 'all';
                }}
                filterExclusionTable();
            }}
        }}
        
        // ============================================
        // Missing Objects Table Functionality
        // ============================================
        const missingObjectsData = {missing_objects_json};
        let filteredMissingObjects = [...missingObjectsData];
        let missingCurrentPage = 1;
        const missingPageSize = 50;
        
        function initMissingObjectsTable() {{
            filterMissingObjects();
        }}
        
        function filterMissingObjects() {{
            const searchTerm = (document.getElementById('missing-search')?.value || '').toLowerCase();
            
            filteredMissingObjects = missingObjectsData.filter(obj => {{
                if (!searchTerm) return true;
                // Search in referenced name
                if (obj.referenced.toLowerCase().includes(searchTerm)) return true;
                // Search in callers array
                if (obj.callers && obj.callers.some(c => c.toLowerCase().includes(searchTerm))) return true;
                return false;
            }});
            
            missingCurrentPage = 1;
            renderMissingObjectsTable();
        }}
        
        function renderMissingObjectsTable() {{
            const tbody = document.getElementById('missing-objects-tbody');
            if (!tbody) return;
            
            const start = (missingCurrentPage - 1) * missingPageSize;
            const end = start + missingPageSize;
            const pageData = filteredMissingObjects.slice(start, end);
            
            if (pageData.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="2" style="padding: 40px; text-align: center; color: #64748B;">No missing objects found matching your criteria.</td></tr>';
            }} else {{
                tbody.innerHTML = pageData.map((obj, idx) => {{
                    const callersList = (obj.callers || []).map(c => escapeHtml(c)).join('<br>');
                    const callersCount = (obj.callers || []).length;
                    return `
                    <tr style="background: ${{idx % 2 === 0 ? '#FFFFFF' : '#F9FAFB'}}; border-bottom: 1px solid #E2E8F0;">
                        <td style="padding: 12px 16px;">
                            <div style="font-weight: 600; color: #102E46; word-break: break-all;">${{escapeHtml(obj.referenced)}}</div>
                        </td>
                        <td style="padding: 12px 16px;">
                            <div style="color: #64748B; font-size: 0.8rem; margin-bottom: 4px;">Referenced by ${{callersCount}} object${{callersCount !== 1 ? 's' : ''}}:</div>
                            <div style="color: #475569; font-size: 0.85rem; word-break: break-all; line-height: 1.6;">${{callersList}}</div>
                        </td>
                    </tr>`;
                }}).join('');
            }}
            
            // Update pagination info
            const totalPages = Math.ceil(filteredMissingObjects.length / missingPageSize);
            const pageInfo = document.getElementById('missing-page-info');
            const countDisplay = document.getElementById('missing-count-display');
            const prevBtn = document.getElementById('missing-prev-btn');
            const nextBtn = document.getElementById('missing-next-btn');
            
            if (pageInfo) {{
                pageInfo.textContent = `Page ${{missingCurrentPage}} of ${{totalPages || 1}}`;
            }}
            if (countDisplay) {{
                countDisplay.textContent = `Showing ${{filteredMissingObjects.length}} of ${{missingObjectsData.length}} objects`;
            }}
            if (prevBtn) {{
                prevBtn.disabled = missingCurrentPage <= 1;
                prevBtn.style.opacity = prevBtn.disabled ? '0.5' : '1';
            }}
            if (nextBtn) {{
                nextBtn.disabled = missingCurrentPage >= totalPages;
                nextBtn.style.opacity = nextBtn.disabled ? '0.5' : '1';
            }}
        }}
        
        function changeMissingPage(delta) {{
            const totalPages = Math.ceil(filteredMissingObjects.length / missingPageSize);
            const newPage = missingCurrentPage + delta;
            if (newPage >= 1 && newPage <= totalPages) {{
                missingCurrentPage = newPage;
                renderMissingObjectsTable();
            }}
        }}
        
        function escapeHtml(text) {{
            const div = document.createElement('div');
            div.textContent = text || '';
            return div.innerHTML;
        }}
        
        function downloadMissingObjectsCSV() {{
            const exportRows = getMissingObjectsExportRows();
            if (exportRows.length === 0) {{
                alert('No missing objects to export.');
                return;
            }}

            const headers = ['Object Name', 'File', 'Dependents', 'Conversion Status'];
            let csvContent = headers.join(',') + '\\n';

            exportRows.forEach(row => {{
                const csvRow = [
                    escapeCSV(row.object_name),
                    escapeCSV(row.file),
                    row.dependents,
                    escapeCSV(row.conversion_status)
                ];
                csvContent += csvRow.join(',') + '\\n';
            }});
            
            const blob = new Blob([csvContent], {{ type: 'text/csv;charset=utf-8;' }});
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = 'missing_objects.csv';
            link.click();
        }}
        
        function downloadMissingObjectsExcel() {{
            const exportRows = getMissingObjectsExportRows();
            if (exportRows.length === 0) {{
                alert('No missing objects to export.');
                return;
            }}

            if (typeof XLSX === 'undefined') {{
                alert('Excel export requires the XLSX library. Please use CSV export instead.');
                return;
            }}
            
            const headers = ['Object Name', 'File', 'Dependents', 'Conversion Status'];
            const data = exportRows.map(row => {{
                return [
                    row.object_name,
                    row.file,
                    row.dependents,
                    row.conversion_status
                ];
            }});
            
            const ws = XLSX.utils.aoa_to_sheet([headers, ...data]);
            ws['!cols'] = [{{ wch: 52 }}, {{ wch: 70 }}, {{ wch: 14 }}, {{ wch: 18 }}];
            
            const wb = XLSX.utils.book_new();
            XLSX.utils.book_append_sheet(wb, ws, 'Missing Objects');
            XLSX.writeFile(wb, 'missing_objects.xlsx');
        }}

        function getMissingObjectsExportRows() {{
            // Preferred source: Dependencies "All Objects" table data for exact column parity.
            if (typeof allObjectsData !== 'undefined' && Array.isArray(allObjectsData) && allObjectsData.length > 0) {{
                return allObjectsData
                    .filter(obj => String(obj?.conversion_status || '').toLowerCase() === 'missing')
                    .map(obj => ({{
                        object_name: String(obj?.name || ''),
                        file: String(obj?.file || '-'),
                        dependents: Number(obj?.dependents || 0),
                        conversion_status: String(obj?.conversion_status || 'Missing'),
                    }}));
            }}

            // Fallback: derived from overview missing-object data if dependencies payload is unavailable.
            return (filteredMissingObjects || []).map(obj => ({{
                object_name: String(obj?.referenced || ''),
                file: '-',
                dependents: Array.isArray(obj?.callers) ? obj.callers.length : Number(obj?.dependants_count || 0),
                conversion_status: 'Missing',
            }}));
        }}

        function toggleMissingExportMenu() {{
            const menu = document.getElementById('missingExportMenu');
            if (!menu) return;
            if (menu.style.display === 'none' || menu.style.display === '') {{
                menu.style.display = 'block';
            }} else {{
                menu.style.display = 'none';
            }}
        }}
        
        // Initialize on page load
        window.addEventListener('DOMContentLoaded', function() {{
            initMissingObjectsTable();
            document.addEventListener('click', function(event) {{
                const exportBtn = document.getElementById('missingExportBtn');
                const exportMenu = document.getElementById('missingExportMenu');
                if (exportBtn && exportMenu && !exportBtn.contains(event.target) && !exportMenu.contains(event.target)) {{
                    exportMenu.style.display = 'none';
                }}
            }});
        }});
        
        // CSV Export Function
        function downloadCSV(category) {{
            let dataToExport = exportData;
            let filename = 'naming_convention_analysis';
            
            if (category === 'temp') {{
                dataToExport = exportData.filter(obj => obj.category === 'Temporary/Staging');
                filename = 'temporary_staging_objects';
            }} else if (category === 'deprecated') {{
                dataToExport = exportData.filter(obj => obj.category === 'Deprecated/Legacy');
                filename = 'deprecated_legacy_objects';
            }} else if (category === 'testing') {{
                dataToExport = exportData.filter(obj => obj.category === 'Testing');
                filename = 'testing_objects';
            }} else if (category === 'duplicate') {{
                dataToExport = exportData.filter(obj => obj.category === 'Duplicate');
                filename = 'duplicate_objects';
            }}
            
            if (dataToExport.length === 0) {{
                alert('No objects to export in this category.');
                return;
            }}
            
            let headers = ['Category', 'Object Name', 'Full Name', 'Schema', 'Type', 'File', 'Production Version', 'Customer Decision', 'Testing Reason'];
            if (isAdaptive) {{
                headers.push('Confidence', 'Top Signals');
            }}
            let csvContent = headers.join(',') + '\\n';
            
            dataToExport.forEach(obj => {{
                const reason = obj.testing_reason || obj.questionable_reason || '';
                const productionVersion = obj.production_version || '';
                const decision = obj.customer_decision || 'Pending Review';
                const row = [
                    escapeCSV(obj.category || ''),
                    escapeCSV(obj.name || ''),
                    escapeCSV(obj.full_name || ''),
                    escapeCSV(obj.schema || ''),
                    escapeCSV(obj.type || ''),
                    escapeCSV(obj.file || ''),
                    escapeCSV(productionVersion),
                    escapeCSV(decision),
                    escapeCSV(reason)
                ];
                if (isAdaptive) {{
                    row.push(escapeCSV((obj.confidence || 0).toString()));
                    const signals = (obj.signals || []).slice(0, 3).join('; ');
                    row.push(escapeCSV(signals));
                }}
                csvContent += row.join(',') + '\\n';
            }});
            
            const blob = new Blob([csvContent], {{ type: 'text/csv;charset=utf-8;' }});
            const link = document.createElement('a');
            const url = URL.createObjectURL(blob);
            link.setAttribute('href', url);
            link.setAttribute('download', filename + '.csv');
            link.style.visibility = 'hidden';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        }}
        
        // Excel Export Function
        function downloadExcel(category) {{
            let dataToExport = exportData;
            let filename = 'naming_convention_analysis';
            
            if (category === 'temp') {{
                dataToExport = exportData.filter(obj => obj.category === 'Temporary/Staging');
                filename = 'temporary_staging_objects';
            }} else if (category === 'deprecated') {{
                dataToExport = exportData.filter(obj => obj.category === 'Deprecated/Legacy');
                filename = 'deprecated_legacy_objects';
            }} else if (category === 'testing') {{
                dataToExport = exportData.filter(obj => obj.category === 'Testing');
                filename = 'testing_objects';
            }} else if (category === 'duplicate') {{
                dataToExport = exportData.filter(obj => obj.category === 'Duplicate');
                filename = 'duplicate_objects';
            }}
            
            if (dataToExport.length === 0) {{
                alert('No objects to export in this category.');
                return;
            }}
            
            let excelHeaders = ['Category', 'Object Name', 'Full Name', 'Schema', 'Type', 'File', 'Production Version', 'Customer Decision', 'Testing Reason'];
            if (isAdaptive) {{
                excelHeaders.push('Confidence', 'Top Signals');
            }}
            const worksheetData = [excelHeaders];
            
            dataToExport.forEach(obj => {{
                const reason = obj.testing_reason || obj.questionable_reason || '';
                const productionVersion = obj.production_version || '';
                const decision = obj.customer_decision || 'Pending Review';
                const row = [
                    obj.category || '',
                    obj.name || '',
                    obj.full_name || '',
                    obj.schema || '',
                    obj.type || '',
                    obj.file || '',
                    productionVersion,
                    decision,
                    reason
                ];
                if (isAdaptive) {{
                    row.push((obj.confidence || 0).toString());
                    const signals = (obj.signals || []).slice(0, 3).join('; ');
                    row.push(signals);
                }}
                worksheetData.push(row);
            }});
            
            const wb = XLSX.utils.book_new();
            const ws = XLSX.utils.aoa_to_sheet(worksheetData);
            
            const colWidths = [
                {{ wch: 20 }},
                {{ wch: 30 }},
                {{ wch: 40 }},
                {{ wch: 15 }},
                {{ wch: 15 }},
                {{ wch: 50 }},
                {{ wch: 40 }},
                {{ wch: 18 }},
                {{ wch: 40 }}
            ];
            if (isAdaptive) {{
                colWidths.push({{ wch: 12 }});
                colWidths.push({{ wch: 50 }});
            }}
            ws['!cols'] = colWidths;
            
            XLSX.utils.book_append_sheet(wb, ws, 'Objects');
            XLSX.writeFile(wb, filename + '.xlsx');
        }}
        
        function escapeCSV(field) {{
            if (field === null || field === undefined) {{
                return '';
            }}
            field = String(field);
            if (field.includes(',') || field.includes('"') || field.includes('\\n')) {{
                field = '"' + field.replace(/"/g, '""') + '"';
            }}
            return field;
        }}
        
        // Show toast notification
        function showToast(message, type) {{
            document.querySelectorAll('.toast').forEach(t => t.remove());
            
            const toast = document.createElement('div');
            toast.className = 'toast ' + (type || '');
            toast.textContent = message;
            document.body.appendChild(toast);
            
            setTimeout(() => toast.classList.add('show'), 10);
            
            setTimeout(() => {{
                toast.classList.remove('show');
                setTimeout(() => toast.remove(), 300);
            }}, 3000);
        }}
    </script>
    
    <!-- SSIS Report JavaScript (package filters) -->
    <script>
        {ssis_js}
    </script>

    <!-- Dependencies Report JavaScript (separate script block for global scope) -->
    <script>
        {waves_js}
        console.log("typeof openWaveModal:", typeof openWaveModal);
        console.log("typeof waveNames:", typeof waveNames);
    </script>

    <!-- Info-icon tooltip handler -->
    <script>
        // Info-icon tooltips — appended to <body> so they escape any overflow/transform
        (function() {{
            let tip = null;
            document.addEventListener('mouseover', function(e) {{
                const icon = e.target.closest('.info-icon[data-info]');
                if (!icon) return;
                if (tip) tip.remove();
                tip = document.createElement('div');
                tip.className = 'info-tooltip-dynamic';
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
    </script>
    <script>
        // Dependencies metric-card tooltips — follow cursor
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
                const card = e.target.closest('.tab-content.dependencies-tab .metric-card[data-tooltip]');
                if (!card) return;
                if (tip) tip.remove();
                tip = document.createElement('div');
                tip.className = 'metric-tooltip-cursor-dynamic';
                tip.textContent = card.getAttribute('data-tooltip') || '';
                document.body.appendChild(tip);
            }});

            document.addEventListener('mousemove', function(e) {{
                if (!tip) return;
                placeTip(e);
            }});

            document.addEventListener('mouseout', function(e) {{
                const card = e.target.closest('.tab-content.dependencies-tab .metric-card[data-tooltip]');
                if (!card) return;
                if (tip) {{
                    tip.remove();
                    tip = null;
                }}
            }});
        }})();
    </script>
</body>
</html>
"""


def print_usage():
    """Print usage information"""
    print("Generate Multi-Tab HTML Report for Migration Assessment")
    print("\nUsage:")
    print("  python generate_multi_report.py [OPTIONS]")
    print("\nOptions:")
    print("  --exclusion-json PATH           Path to object exclusion JSON file")
    print("  --dynamic-sql-json PATH         Path to dynamic SQL analysis JSON file")
    print("  --waves-analysis-dir PATH       Path to waves dependency analysis directory")
    print("  --snowconvert-reports-dir PATH  Path to SnowConvert reports directory (optional, for waves data)")
    print("  --output PATH                   Output path for HTML report (required)")
    print("\nExamples:")
    print("  # Generate report with all three data sources")
    print("  python generate_multi_report.py \\")
    print("      --exclusion-json data/object_exclusion.json \\")
    print("      --dynamic-sql-json data/sql_dynamic_analysis.json \\")
    print("      --waves-analysis-dir data/waves/dependency_analysis_20241204_162225 \\")
    print("      --output report.html")
    print("\n  # Generate report with only waves data")
    print("  python generate_multi_report.py \\")
    print("      --waves-analysis-dir data/waves/dependency_analysis_20241204_162225 \\")
    print("      --output report.html")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Generate Multi-Tab HTML Report for Migration Assessment',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--exclusion-json',
        type=Path,
        help='Path to object exclusion JSON file'
    )
    
    parser.add_argument(
        '--dynamic-sql-json',
        type=Path,
        help='Path to dynamic SQL analysis JSON file'
    )
    
    parser.add_argument(
        '--waves-analysis-dir',
        type=Path,
        help='Path to waves dependency analysis directory'
    )
    
    parser.add_argument(
        '--snowconvert-reports-dir',
        type=Path,
        help='Path to SnowConvert reports directory (optional, for waves data)'
    )
    
    parser.add_argument(
        '--ssis-json',
        type=Path,
        help='Path to SSIS assessment JSON file'
    )

    parser.add_argument(
        '--registry-dir',
        type=Path,
        help='Path to SnowConvert registry directory (JSON files, preferred over CSV)'
    )

    parser.add_argument(
        '--output',
        type=Path,
        required=True,
        help='Output path for HTML report'
    )
    
    args = parser.parse_args()
    
    if not args.exclusion_json and not args.dynamic_sql_json and not args.waves_analysis_dir and not args.ssis_json:
        print("Error: At least one data source (--exclusion-json, --dynamic-sql-json, --waves-analysis-dir, or --ssis-json) must be provided", file=sys.stderr)
        print_usage()
        sys.exit(1)
    
    if args.exclusion_json and not args.exclusion_json.exists():
        print(f"Error: Exclusion JSON file not found: {args.exclusion_json}", file=sys.stderr)
        sys.exit(1)
    
    if args.dynamic_sql_json and not args.dynamic_sql_json.exists():
        print(f"Error: Dynamic SQL JSON file not found: {args.dynamic_sql_json}", file=sys.stderr)
        sys.exit(1)
    
    if args.waves_analysis_dir and not args.waves_analysis_dir.exists():
        print(f"Error: Waves analysis directory not found: {args.waves_analysis_dir}", file=sys.stderr)
        sys.exit(1)
    
    if args.ssis_json and not args.ssis_json.exists():
        print(f"Error: SSIS JSON file not found: {args.ssis_json}", file=sys.stderr)
        sys.exit(1)
    
    try:
            generate_multi_report(
                output_file=args.output,
                exclusion_json=args.exclusion_json,
                dynamic_sql_json=args.dynamic_sql_json,
                waves_analysis_dir=args.waves_analysis_dir,
                snowconvert_reports_dir=args.snowconvert_reports_dir,
                registry_dir=args.registry_dir,
                ssis_json=args.ssis_json
            )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()