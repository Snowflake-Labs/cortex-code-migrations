# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Load and render versioned migration effort-estimate artifacts."""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

_HOURS_PER_WORK_DAY = 8.0

# Shares the ``.nav-preview-badge`` CSS class defined in generate_multi_report.py's
# stylesheet (embedded in the same HTML page) so the badge markup is defined once.
EFFORT_PREVIEW_BADGE_HTML = '<span class="nav-preview-badge">Preview</span>'

EFFORT_DISCLAIMER_HTML = (
    '<p style="color: #0369A1; background: #F0F9FF; border: 1px solid #BAE6FD; '
    'border-radius: 8px; padding: 12px 14px; font-size: 0.88rem; line-height: 1.5; '
    'margin-bottom: 20px;">'
    "<strong>Disclaimer:</strong> These estimates are a best-effort recommendation only. "
    "Actual effort may vary based on project scope, team experience, data quality, "
    "and migration complexity."
    "</p>"
)
_DDL_EXCLUDED_DISPLAY_TYPES = frozenset({"Index", "Flow Control"})


@dataclass
class CalculatorRow:
    component: str
    object_type: str
    quantity: Any
    baseline_hours: float
    total_baseline_hours: float
    fde_hours: float
    unweighted_fde_hours: float
    comments: str = ""


def load_effort_assessment(path: Path) -> Optional[Dict[str, Any]]:
    """Load an effort artifact and rehydrate its calculator rows for HTML renderers."""
    try:
        with Path(path).open(encoding="utf-8") as stream:
            assessment = json.load(stream)
        assessment["calculator_rows"] = [
            CalculatorRow(**row) for row in assessment.get("calculator_rows") or []
        ]
        return assessment
    except (OSError, json.JSONDecodeError, TypeError, ValueError, AttributeError) as exc:
        print(f"Warning: Could not load effort estimates data: {exc}", file=sys.stderr)
        return None


def workload_size_label(tier: str, small_max: int, medium_max: int) -> str:
    """Human-readable workload tier label using thresholds from the artifact."""
    labels = {
        "small": f"Small (up to {small_max:,} objects)",
        "medium": f"Medium ({small_max + 1:,}–{medium_max:,} objects)",
        "large": f"Large (more than {medium_max:,} objects)",
    }
    return labels.get(tier, tier.title())


def _esc(text: Any) -> str:
    import html

    return html.escape(str(text)) if text is not None else ""


def _hours_to_rounded_days(hours: float) -> int:
    """Convert effort hours to whole days, rounded up (8h work day)."""
    if hours <= 0:
        return 0
    return int(math.ceil(hours / _HOURS_PER_WORK_DAY))


def _days_label(days: int) -> str:
    return f"{days:,} day" if days == 1 else f"{days:,} days"


def _render_fixed_budget_info_icon(
    fixed_items: Dict[str, Optional[float]],
    workload_tier: str,
    total_objects: int,
    small_max: int,
    medium_max: int,
) -> str:
    """Info icon with hover tooltip listing fixed budget line items."""
    if not fixed_items:
        return ""
    header = (
        f"<div style='margin-bottom:8px;font-weight:600;'>"
        f"{_esc(workload_size_label(workload_tier, small_max, medium_max))} · "
        f"{total_objects:,} objects"
        f"</div>"
    )
    tooltip_lines = header + "".join(
        f"<div style='margin-bottom:4px;'>{_esc(label)}: "
        f"{f'{hours:g} h' if hours is not None else 'N/A'}</div>"
        for label, hours in fixed_items.items()
    )
    return (
        f'<span class="info-icon" style="margin-left:4px;">i'
        f'<span class="tooltip">{tooltip_lines}</span></span>'
    )


def render_overview_section_b_html(assessment: Dict[str, Any]) -> str:
    """Section B on Overview: effort summary for SQL Server DDL + fixed budgets."""
    s = assessment["summary"]
    ddl = s.get("ddl_summary", {})
    ddl_rows = ""
    for obj_type in sorted(ddl.keys()):
        if obj_type in _DDL_EXCLUDED_DISPLAY_TYPES:
            continue
        st = ddl[obj_type]
        pct = f"{st['pct_auto'] * 100:.1f}%"
        ddl_rows += f"""
        <tr>
            <td>{_esc(obj_type)}</td>
            <td class="ctr">{st['total']}</td>
            <td class="ctr">{st['success']}</td>
            <td class="ctr">{st['partial']}</td>
            <td class="ctr">{st['unsupported']}</td>
            <td class="ctr">{pct}</td>
        </tr>"""

    fixed_items = s.get("fixed_budget_items", {})
    workload_tier = s.get("workload_size_tier", "small")
    workload_objects = s.get("workload_object_count", s.get("ddl_objects", 0))
    small_max = s.get("workload_small_max", 500)
    medium_max = s.get("workload_medium_max", 1500)
    fixed_info_icon = _render_fixed_budget_info_icon(
        fixed_items,
        workload_tier,
        workload_objects,
        small_max,
        medium_max,
    )
    workload_subtitle = (
        f"<div style='font-size:0.72rem;color:#64748B;margin-top:4px;'>"
        f"{_esc(workload_size_label(workload_tier, small_max, medium_max))}</div>"
    )

    total_days = _hours_to_rounded_days(s.get("total_fde_hours", 0))

    # One metric among several, so it carries the shared card styling rather than a
    # colour and type size that would read as the section's headline.
    automation_card = ""
    if s.get("conversion_weighted") and s.get("hours_saved_by_automation", 0) > 0:
        auto_pct = s.get("conversion_automated_pct", 0) * 100
        automation_card = f"""
                <div class="effort-card">
                    <div class="effort-card-num">{auto_pct:.0f}%</div>
                    <div class="effort-card-lbl">Automated conversion</div>
                </div>"""

    return f"""
            <h2 id="effort-estimates" style="font-size: 1.5rem; font-weight: 700; color: #102E46; margin-bottom: 8px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                <span style="background: #E0F2FE; color: #0284C7; padding: 4px 10px; border-radius: 6px; font-size: 0.9rem;">Section B</span>
                Estimated effort to migrate
                {EFFORT_PREVIEW_BADGE_HTML}
            </h2>
            {EFFORT_DISCLAIMER_HTML}
            <p style="color: #64748B; font-size: 0.95rem; margin-bottom: 20px; line-height: 1.6;">
                Effort summary using migration assessment formulas (flat phase budgets, LOC-based partials).
                Quantities reflect unique converted objects (session and batch rows excluded).
            </p>

            <div class="effort-cards">
                <div class="effort-card">
                    <div class="effort-card-num">{_esc(_days_label(total_days))}</div>
                    <div class="effort-card-lbl">Total Effort</div>
                </div>
                <div class="effort-card">
                    <div class="effort-card-num">{s.get('ddl_fde_hours', 0):,.1f} h</div>
                    <div class="effort-card-lbl">DDL Effort · {s.get('ddl_objects', 0):,} objects · {s.get('ddl_auto_pct', 0) * 100:.1f}% auto-converted · includes unit testing</div>
                </div>
                {automation_card}
                <div style="background: white; padding: 18px; border-radius: 12px; border-top: 4px solid #FF9F36; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                    <div style="font-size: 0.78rem; color: #64748B; font-weight: 600; text-transform: uppercase; display: flex; align-items: center;">
                        Fixed Budget{fixed_info_icon}
                    </div>
                    <div style="font-size: 1.6rem; font-weight: 800; color: #102E46; margin-top: 4px;">{s.get('fixed_budget_fde_hours', 0):,.1f} h</div>
                    {workload_subtitle}
                </div>
            </div>

            <h3 style="font-size: 1.1rem; font-weight: 700; color: #102E46; margin-bottom: 12px;">DDL conversion breakdown</h3>
            <div class="effort-table-wrap">
                <table class="effort-table">
                    <thead>
                        <tr>
                            <th>Object Type</th>
                            <th class="ctr">Total</th>
                            <th class="ctr">Success</th>
                            <th class="ctr">Partial</th>
                            <th class="ctr">Unsupported</th>
                            <th class="ctr">% Auto-Converted</th>
                        </tr>
                    </thead>
                    <tbody>{ddl_rows}</tbody>
                </table>
            </div>

            <div style="background: #F0F9FF; border: 1px solid #BAE6FD; border-radius: 10px; padding: 16px 20px; margin-bottom: 40px;">
                <p style="margin: 0 0 8px 0; color: #102E46; font-weight: 600;">Need line-item detail?</p>
                <p style="margin: 0 0 12px 0; color: #475569; font-size: 0.9rem; line-height: 1.5;">
                    The Effort Estimates tab shows the full migration calculator — every component, conversion tier quantity, baseline hours, and total time.
                </p>
                <a @click="activeTab = 'effort-estimates'"
                   style="display: inline-block; background: #005C8F; color: white; padding: 10px 18px; border-radius: 8px; font-weight: 600; font-size: 0.9rem; cursor: pointer; text-decoration: none;">
                    Open detailed effort calculator →
                </a>
            </div>
    """


def _new_ddl_row() -> Dict[str, Any]:
    return {
        "total": 0,
        "success": 0,
        "partial": 0,
        "unsupported": 0,
        "lines_of_code": 0,
        "issues_none_info": 0,
        "issues_low": 0,
        "issues_medium": 0,
        "issues_high": 0,
        "issues_critical": 0,
        "effort_hours": 0.0,
        "notes": "",
        "pct_auto": 0.0,
    }


def _render_ddl_assessment_table(
    ddl_summary: Dict[str, Dict[str, Any]],
    testing_fde: float = 0.0,
) -> str:
    rows_html = ""
    totals = _new_ddl_row()
    for obj_type in sorted(ddl_summary.keys()):
        if obj_type in _DDL_EXCLUDED_DISPLAY_TYPES:
            continue
        st = ddl_summary[obj_type]
        for k in totals:
            if k in ("pct_auto", "notes"):
                continue
            if isinstance(totals[k], (int, float)):
                totals[k] += st.get(k, 0)
        pct = f"{st['pct_auto'] * 100:.1f}%"
        effort = f"{st.get('effort_hours', 0):,.1f}" if st.get("effort_hours") else "—"
        rows_html += f"""
        <tr>
            <td>{_esc(obj_type)}</td>
            <td class="ctr">{st['total']:,}</td>
            <td class="ctr">{st['success']:,}</td>
            <td class="ctr">{st['partial']:,}</td>
            <td class="ctr">{st['unsupported']:,}</td>
            <td class="ctr">{pct}</td>
            <td class="num">{st['lines_of_code']:,}</td>
            <td class="ctr">{st['issues_none_info']:,}</td>
            <td class="ctr">{st['issues_low']:,}</td>
            <td class="ctr">{st['issues_medium']:,}</td>
            <td class="ctr">{st['issues_high']:,}</td>
            <td class="ctr">{st['issues_critical']:,}</td>
            <td class="num" style="font-weight:600;">{effort}</td>
            <td style="color:#64748B;font-size:0.8rem;">{_esc(st.get('notes', ''))}</td>
        </tr>"""
    total_pct = f"{(totals['success'] / totals['total'] * 100):.1f}%" if totals["total"] else "—"
    # Always the true sum of the rows displayed above (+ testing) so TOTALS never
    # understates what's visibly listed in this table.
    total_effort = round(totals["effort_hours"] + testing_fde, 1)
    if testing_fde:
        rows_html += f"""
        <tr style="background:#F8FAFC;">
            <td style="padding:8px 12px;">Code Conversion Testing</td>
            <td colspan="11" style="padding:8px 12px;color:#64748B;font-size:0.8rem;">Unit testing for functions and stored procedures</td>
            <td style="padding:8px 12px;text-align:right;font-weight:600;">{testing_fde:,.1f}</td>
            <td style="padding:8px 12px;color:#64748B;font-size:0.8rem;">1h per object (see calculator)</td>
        </tr>"""
    rows_html += f"""
        <tr class="effort-total">
            <td>TOTALS</td>
            <td class="ctr">{totals['total']:,}</td>
            <td class="ctr">{totals['success']:,}</td>
            <td class="ctr">{totals['partial']:,}</td>
            <td class="ctr">{totals['unsupported']:,}</td>
            <td class="ctr">{total_pct}</td>
            <td class="num">{totals['lines_of_code']:,}</td>
            <td class="ctr">{totals['issues_none_info']:,}</td>
            <td class="ctr">{totals['issues_low']:,}</td>
            <td class="ctr">{totals['issues_medium']:,}</td>
            <td class="ctr">{totals['issues_high']:,}</td>
            <td class="ctr">{totals['issues_critical']:,}</td>
            <td class="num">{total_effort:,.1f}</td>
            <td></td>
        </tr>"""
    return rows_html


def _render_calculator_rows(rows: List[CalculatorRow]) -> str:
    """Render the migration effort calculator's line-item rows."""
    calc_body = ""
    for r in rows:
        qty = r.quantity
        qty_disp = _esc(qty) if not isinstance(qty, (int, float)) else f"{int(qty):,}" if qty else "0"
        calc_body += f"""
        <tr>
            <td>{_esc(r.component)}</td>
            <td>{_esc(r.object_type)}</td>
            <td class="num">{qty_disp}</td>
            <td class="num">{r.baseline_hours:g}</td>
            <td class="num" style="font-weight:600;">{r.fde_hours:,.1f}</td>
            <td style="color:#64748B;font-size:0.85rem;">{_esc(r.comments)}</td>
        </tr>"""
    return calc_body


def _render_top_issues_section(top_issues: List[Dict[str, Any]]) -> str:
    """Top DDL issues-by-occurrence section; empty if there are no issues."""
    if not top_issues:
        return ""

    issues_html = ""
    for issue in top_issues:
        issues_html += f"""
        <tr>
            <td>{_esc(issue['code'])}</td>
            <td>{_esc(issue.get('name', ''))}</td>
            <td class="ctr">{_esc(issue.get('severity', '—'))}</td>
            <td class="ctr">{issue['occurrences']:,}</td>
        </tr>"""

    return f"""
        <h2 id="effort-top-issues" style="font-size:1.35rem;font-weight:700;color:#102E46;margin:32px 0 12px;">Top issues (DDL) – by occurrence</h2>
        <p style="color:#64748B;font-size:0.9rem;margin-bottom:12px;">Top conversion issues by occurrence count across DDL objects.</p>
        <div class="effort-table-wrap">
            <table class="effort-table">
                <thead><tr>
                    <th>Issue Code</th>
                    <th>Name</th>
                    <th class="ctr">Severity</th>
                    <th class="ctr">Occurrences</th>
                </tr></thead>
                <tbody>{issues_html}</tbody>
            </table>
        </div>"""


def _render_effort_formulas_legend(summary: Dict[str, Any]) -> str:
    """Collapsible legend explaining how each effort figure is derived."""
    weighting_note = ""
    if summary.get("conversion_weighted"):
        weighting_note = (
            "<p><strong>Automated conversion:</strong> code-conversion effort is charged "
            "only for the share SnowConvert did not convert automatically. Per-object "
            "types (functions, stored procedures) scale by effort × (1 − conversion rate). "
            "Flat-category budgets (tables, views) are all-or-nothing: a category costs 0h "
            "once every object in it auto-converted, and its full budget while any object "
            "still needs manual work. "
            f"On this workload automation avoided ≈ {summary.get('hours_saved_by_automation', 0):,.0f} h "
            "of manual conversion.</p>"
        )
    return f"""
        <details style="margin-bottom:32px;background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;padding:16px;">
            <summary style="font-weight:700;color:#102E46;cursor:pointer;">Effort formulas &amp; legend</summary>
            <div style="margin-top:12px;font-size:0.88rem;color:#475569;line-height:1.6;">
                <p><strong>DDL:</strong> Tables = flat 4h total; Views = flat 4h total; Functions and stored procedures = 1h each for conversion (plus 1h each for unit testing in the calculator).</p>
                {weighting_note}
                <p><strong>Fixed Budget:</strong> Data migration setup plus phase budgets scaled by workload size — Small (≤{summary.get('workload_small_max', 500):,} objects), Medium ({summary.get('workload_small_max', 500) + 1:,}–{summary.get('workload_medium_max', 1500):,}), Large (&gt;{summary.get('workload_medium_max', 1500):,}).</p>
                <p><strong>Sources:</strong> SnowConvert conversion statistics — object conversion rates and issue severity counts.</p>
            </div>
        </details>"""


def render_effort_tab_html(assessment: Dict[str, Any]) -> str:
    """Full effort page aligned with the migration assessment workbook sections."""
    rows = assessment["calculator_rows"]
    summary = assessment["summary"]
    ddl = summary.get("ddl_summary", {})
    top_issues = assessment.get("top_issues", [])

    ddl_effort = summary.get("ddl_fde_hours", 0)

    calc_body = _render_calculator_rows(rows)
    issues_section = _render_top_issues_section(top_issues)
    formulas_legend = _render_effort_formulas_legend(summary)

    return f"""
    <div class="tab-content" :class="{{active: activeTab === 'effort-estimates'}}">
        <div style="margin-bottom: 24px;">
            <h1 style="font-size: 1.875rem; font-weight: 800; color: #102E46; margin-bottom: 8px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                Migration effort estimates
                {EFFORT_PREVIEW_BADGE_HTML}
            </h1>
            {EFFORT_DISCLAIMER_HTML}
            <p style="color: #64748B; font-size: 1rem; line-height: 1.6;">
                Derived from SnowConvert conversion results. Tables and views use a flat 4h conversion budget each;
                data migration setup and phase budgets appear under Fixed Budget on the Overview tab.
            </p>
        </div>

        <div class="effort-cards">
            <div class="effort-card">
                <div class="effort-card-num">{summary.get('ddl_objects', 0):,}</div>
                <div class="effort-card-lbl">Total DDL Objects</div>
            </div>
            <div class="effort-card">
                <div class="effort-card-num">{summary.get('ddl_auto_pct', 0) * 100:.1f}%</div>
                <div class="effort-card-lbl">DDL Auto-Converted</div>
            </div>
            <div class="effort-card">
                <div class="effort-card-num">{summary.get('total_fde_hours', 0):,.1f} h</div>
                <div class="effort-card-lbl">Total Effort</div>
            </div>
            <div class="effort-card">
                <div class="effort-card-num">{ddl_effort:,.1f} h</div>
                <div class="effort-card-lbl">DDL Effort</div>
            </div>
        </div>

        <h2 id="effort-ddl-assessment" style="font-size:1.35rem;font-weight:700;color:#102E46;margin-bottom:12px;">DDL conversion effort</h2>
        <div class="effort-table-wrap" style="margin-bottom:32px;">
            <table class="effort-table compact">
                <thead><tr>
                    <th>Object Type</th>
                    <th class="ctr">Total</th>
                    <th class="ctr">Success</th>
                    <th class="ctr">Partial</th>
                    <th class="ctr">Unsupported</th>
                    <th class="ctr">% Auto-Conv.</th>
                    <th class="num">Lines of Code</th>
                    <th class="ctr">None/Info</th>
                    <th class="ctr">Low</th>
                    <th class="ctr">Medium</th>
                    <th class="ctr">High</th>
                    <th class="ctr">Critical</th>
                    <th class="num">Effort (h)</th>
                    <th>Notes</th>
                </tr></thead>
                <tbody>{_render_ddl_assessment_table(ddl, summary.get("testing_fde_hours", 0))}</tbody>
            </table>
        </div>

        {issues_section}

        <h2 id="effort-calculator" style="font-size:1.35rem;font-weight:700;color:#102E46;margin:32px 0 12px;">Migration effort calculator</h2>
        <p style="color:#64748B;font-size:0.9rem;margin-bottom:12px;">Line-item estimate broken down by migration component; quantities reflect unique conversion tiers per object type.</p>
        <div class="effort-table-wrap">
            <table class="effort-table">
                <thead><tr>
                    <th>Migration Component</th>
                    <th>Object Type</th>
                    <th class="num">Quantity</th>
                    <th class="num">Baseline Hours</th>
                    <th class="num">Total Time</th>
                    <th>Comments</th>
                </tr></thead>
                <tbody>
                    {calc_body}
                    <tr class="effort-total">
                        <td colspan="4">TOTAL</td>
                        <td class="num">{summary.get('total_fde_hours', 0):,.1f}</td>
                        <td></td>
                    </tr>
                </tbody>
            </table>
        </div>

        {formulas_legend}
    </div>
    """
