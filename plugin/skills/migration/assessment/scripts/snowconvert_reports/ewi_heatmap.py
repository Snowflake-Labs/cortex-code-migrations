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

"""EWI heatmap for the SSIS Package Distribution section.

Rows are the busiest EWI codes, columns are the busiest packages, and each
code links to its AIM conversion-issues page. The letters between ``SSC-EWI-``
and the number choose that page.
"""

from __future__ import annotations

import html
import re
from collections import Counter, defaultdict
from typing import Callable, Mapping

TOP_CODES = 15
TOP_PACKAGES = 30
RED_AT = 50

_DOCS_BASE = (
    "https://docs.snowflake.com/en/migrations/aim-for-datawarehouses"
    "/code-conversion/issues-and-troubleshooting/conversion-issues"
)
# Infix → docs page. Only pages confirmed against docs.snowflake.com.
_PAGE_BY_INFIX = {
    "": "generalEWI",
    "SSIS": "ssisEWI",
    "TS": "sqlServerEWI",
}
_CODE_RE = re.compile(r"SSC-EWI-([A-Z]*)(\d+)\Z")
_SEVERITIES = ("Critical", "High", "Medium", "Low")
_BADGE = {
    "Critical": ("#fee2e2", "#b91c1c"),
    "High": ("#ffedd5", "#c2410c"),
    "Medium": ("#fef3c7", "#b45309"),
    "Low": ("#e0f2fe", "#0369a1"),
    "Unknown": ("#f1f5f9", "#475569"),
}


def ewi_doc_url(code: str) -> str | None:
    """AIM docs URL for an EWI code, or None when its page is not mapped."""
    match = _CODE_RE.fullmatch((code or "").upper())
    if not match:
        return None
    page = _PAGE_BY_INFIX.get(match.group(1))
    if not page:
        return None
    return f"{_DOCS_BASE}/{page}#{code.lower()}"


def _is_ewi(issue: dict) -> bool:
    code = str(issue.get("code") or "")
    kind = str(issue.get("type") or "").upper()
    if kind == "EWI":
        return bool(code)
    if kind in {"FDM", "PRF", "OOS"}:
        return False
    return "-EWI-" in code.upper()


def _occurrence_count(issue: dict) -> int:
    raw = issue.get("count")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 1
    if raw <= 0:
        return 1
    return int(raw)


def _iter_issues(package: dict):
    for component in package.get("control_flow_components") or []:
        if isinstance(component, dict):
            yield from component.get("issues") or []
    for flow in package.get("data_flows") or []:
        if not isinstance(flow, dict):
            continue
        yield from flow.get("issues") or []
        for component in flow.get("components") or []:
            if isinstance(component, dict):
                yield from component.get("issues") or []
    for manager in package.get("connection_managers") or []:
        if isinstance(manager, dict):
            yield from manager.get("issues") or []
    yield from package.get("issues") or []


def _package_stem(package: dict) -> str:
    name = str(package.get("name") or package.get("path") or "Package")
    stem = re.sub(r"\.dtsx\Z", "", name, flags=re.IGNORECASE)
    return stem or name


def _package_labels(packages: list[dict]) -> list[str]:
    """One column label per package. Same file names in different folders stay apart."""
    stems = [_package_stem(package) for package in packages]
    collisions = {stem for stem, count in Counter(stems).items() if count > 1}
    labels: list[str] = []
    seen: Counter[str] = Counter()
    for package, stem in zip(packages, stems):
        label = stem
        if stem in collisions:
            path = str(package.get("path") or stem).replace("\\", "/").strip("/")
            parent = path.rsplit("/", 2)[-2] if "/" in path else ""
            label = f"{parent}/{stem}" if parent else stem
        seen[label] += 1
        if seen[label] > 1:
            label = f"{label} ({seen[label]})"
        labels.append(label)
    return labels


def _severity(code: str, issue_severity: str, lookup: Callable[[str], str] | None) -> str:
    if lookup is not None:
        catalogued = lookup(code)
        if catalogued in _SEVERITIES:
            return catalogued
    if issue_severity in _SEVERITIES:
        return issue_severity
    return "Unknown"


def build_ewi_heatmap(
    packages: list[dict],
    severity_of: Callable[[str], str] | None = None,
) -> dict | None:
    """Top codes by top packages. None when the packages carry no EWIs."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    severities: dict[str, str] = {}
    for package, label in zip(packages, _package_labels(packages)):
        for issue in _iter_issues(package):
            if not isinstance(issue, dict) or not _is_ewi(issue):
                continue
            code = str(issue["code"])
            counts[label][code] += _occurrence_count(issue)
            severities.setdefault(code, _severity(code, str(issue.get("severity") or ""), severity_of))
    return build_matrix(counts, severities)


def counts_from_informatica_units(
    units: list[dict],
    severity_of: Callable[[str], str] | None = None,
) -> tuple[dict[str, dict[str, int]], dict[str, str]]:
    """Per-mapping EWI counts from Informatica registry units.

    Only mapping units carry EWIs in the registry. Each unit is one column,
    labelled by its source name. Same-named mappings get a ``(n)`` suffix.
    """
    counts: dict[str, dict[str, int]] = {}
    severities: dict[str, str] = {}
    for unit in units:
        if not isinstance(unit, dict) or unit.get("kind") != "etl":
            continue
        source = unit.get("source") or {}
        if str(source.get("platform") or "").lower() != "informatica":
            continue
        issues = [
            issue
            for part in unit.get("parts") or []
            if isinstance(part, dict)
            for issue in part.get("issues") or []
            if isinstance(issue, dict) and _is_ewi(issue)
        ]
        if not issues:
            continue
        label = _unique_label(str(source.get("name") or unit.get("id") or "Mapping"), counts)
        bucket = counts.setdefault(label, {})
        for issue in issues:
            code = str(issue["code"])
            bucket[code] = bucket.get(code, 0) + _occurrence_count(issue)
            severity = str(issue.get("severity") or "").capitalize()
            severities.setdefault(code, _severity(code, severity, severity_of))
    return counts, severities


def _unique_label(label: str, taken: dict) -> str:
    if label not in taken:
        return label
    n = 2
    while f"{label} ({n})" in taken:
        n += 1
    return f"{label} ({n})"


def build_matrix(
    counts: Mapping[str, Mapping[str, int]],
    severities: Mapping[str, str],
) -> dict | None:
    """Top codes by top units from per-unit EWI counts. None when there are none."""
    if not counts:
        return None

    package_order = sorted(
        counts,
        key=lambda name: (-sum(counts[name].values()), name.lower()),
    )[:TOP_PACKAGES]
    code_totals: dict[str, int] = defaultdict(int)
    for name in package_order:
        for code, count in counts[name].items():
            code_totals[code] += count
    code_order = sorted(code_totals, key=lambda code: (-code_totals[code], code))[:TOP_CODES]

    cells = {
        (code, name): counts[name].get(code, 0)
        for code in code_order
        for name in package_order
    }
    package_counts = {
        code: sum(1 for name in package_order if counts[name].get(code, 0) > 0)
        for code in code_order
    }
    return {
        "codes": code_order,
        "packages": package_order,
        "cells": cells,
        "package_counts": package_counts,
        "severities": {code: severities.get(code, "Unknown") for code in code_order},
    }


def cell_color(count: int) -> str:
    """White at 0. Any occurrence starts light green and reaches red at RED_AT."""
    if count <= 0:
        return "#ffffff"
    t = min(count, RED_AT) / RED_AT
    green = round(252 + (38 - 252) * t)
    blue = round(231 + (38 - 231) * t)
    return f"#{220:02x}{green:02x}{blue:02x}"


def _cell_text_color(count: int) -> str:
    if count <= 0:
        return "#111827"
    t = min(count, RED_AT) / RED_AT
    return "#ffffff" if t >= 0.55 else "#111827"


# Table, header, and cell metrics shared by every heatmap. The multi-report puts
# this in the page <head> stylesheet: a <style> inside a report section is not
# applied reliably (Chrome drops it inside the Informatica section).
EWI_HEATMAP_CSS = """
.ewi-heatmap-title { font-size: 1.5rem; font-weight: 600; }
.ewi-heatmap-scroll { overflow-x: auto; width: 85%; margin: 0 auto; }
@media (max-width: 1600px) { .ewi-heatmap-scroll { width: 100%; } }
.ewi-heatmap-table { margin: 1.5rem 0; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); background: white; }
.ewi-heatmap-table thead { background: #29B5E8; color: #ffffff; }
.ewi-heatmap-table th { padding: 1rem; text-align: left; font-weight: 600; font-size: 0.875rem; text-transform: uppercase; letter-spacing: 0.05em; }
.ewi-heatmap-table td { padding: 1rem; border-bottom: 1px solid #8A999E; }
.ewi-heatmap-table tbody tr:hover { background: #E5F6FD; }
.ewi-heatmap-table tbody tr:nth-child(even) { background: #F9FAFB; }
.ewi-heatmap-table tbody tr:nth-child(even):hover { background: #E5F6FD; }
"""


def _code_cell(code: str) -> str:
    safe = html.escape(code)
    url = ewi_doc_url(code)
    if not url:
        return safe
    href = html.escape(url, quote=True)
    return (
        f'<a href="{href}" target="_blank" rel="noopener noreferrer" '
        f'style="color: #11567F; font-weight: 600; text-decoration: none;">{safe}</a>'
    )


def render_ewi_heatmap(
    packages: list[dict],
    severity_of: Callable[[str], str] | None = None,
) -> str:
    """Heatmap markup for SSIS Package Distribution. Empty when there are no EWIs."""
    return render_matrix_heatmap(build_ewi_heatmap(packages, severity_of))


def render_matrix_heatmap(
    matrix: dict | None,
    *,
    unit_plural: str = "packages",
    select_id: str = "ewiSeverityFilter",
    row_class: str = "ewi-heatmap-row",
) -> str:
    """Heatmap markup for a built matrix. Empty when there is no matrix.

    ``select_id`` and ``row_class`` name the severity filter, so two heatmaps
    on one page filter independently.
    """
    if matrix is None:
        return ""

    codes = matrix["codes"]
    package_names = matrix["packages"]
    header_cells = []
    for name in package_names:
        safe = html.escape(name)
        header_cells.append(
            "<th style=\"height: 9rem; padding: 0.25rem; vertical-align: bottom; text-align: center; font-weight: 500; overflow: hidden;\">"
            f'<span title="{safe}" style="writing-mode: vertical-rl; transform: rotate(180deg); '
            "display: inline-block; height: 8rem; max-height: 8rem; overflow: hidden; "
            f'text-overflow: ellipsis; white-space: nowrap; font-size: 0.7rem; color: #334155;">{safe}</span></th>'
        )

    body_rows = []
    for code in codes:
        severity = matrix["severities"][code]
        badge_bg, badge_fg = _BADGE.get(severity, _BADGE["Unknown"])
        cells = []
        for name in package_names:
            count = matrix["cells"][(code, name)]
            shown = "" if count <= 0 else str(count)
            cells.append(
                f'<td style="text-align: center; background: {cell_color(count)}; '
                f"color: {_cell_text_color(count)}; font-size: 0.75rem; padding: 0.35rem 0.1rem; "
                f'overflow: hidden;">{shown}</td>'
            )
        body_rows.append(
            f'<tr class="{row_class}" data-severity="{html.escape(severity)}">'
            '<th style="position: sticky; left: 0; min-width: 11rem; width: 11rem; background: #e8f4fb; '
            'z-index: 1; text-align: left; white-space: nowrap; padding: 0.35rem 0.5rem; '
            f'border-right: 1px solid #7fb3d3; box-shadow: 1px 0 0 #b9d7ea;">{_code_cell(code)}</th>'
            '<td style="position: sticky; left: 11rem; min-width: 6.5rem; background: #e8f4fb; z-index: 1; '
            'text-align: center; box-shadow: 1px 0 0 #b9d7ea;">'
            f'<span style="background: {badge_bg}; color: {badge_fg}; border-radius: 999px; '
            f'padding: 0.1rem 0.45rem; font-size: 0.7rem; font-weight: 600;">{html.escape(severity)}</span>'
            "</td>"
            f"{''.join(cells)}"
            '<td style="position: sticky; right: 0; background: #f8fafc; text-align: center; '
            f'font-weight: 600;">{matrix["package_counts"][code]}</td>'
            "</tr>"
        )

    code_count = len(codes)
    package_count = len(package_names)
    return f"""
        <div style="margin-top: 1.5rem;">
            <div style="display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap;">
                <h3 class="ewi-heatmap-title" style="margin: 0; color: #1f2937;">EWI Heatmap</h3>
                <label style="color: #475569; font-size: 0.875rem;">
                    Filter severity:
                    <select id="{select_id}" style="margin-left: 0.35rem; padding: 0.35rem 0.5rem; border: 1px solid #d1d5db; border-radius: 4px;">
                        <option value="">All</option>
                        <option value="Critical">Critical</option>
                        <option value="High">High</option>
                        <option value="Medium">Medium</option>
                        <option value="Low">Low</option>
                    </select>
                </label>
            </div>
            <p style="color: #64748b; font-size: 0.875rem; margin: 0.5rem 0 0.75rem;">
                Top {code_count} EWI codes across {package_count} {unit_plural}.
                Cell colour: white = 0 → red = {RED_AT}+ occurrences.
            </p>
            <div class="ewi-heatmap-scroll">
                <table class="ewi-heatmap-table" style="border-collapse: separate; border-spacing: 0; width: 100%; min-width: 52rem; table-layout: fixed;">
                    <thead>
                        <tr>
                            <th style="position: sticky; left: 0; min-width: 11rem; width: 11rem; background: #11567F; color: #ffffff; z-index: 2; text-align: center; padding: 0.5rem; border-right: 1px solid #0c3d5c; box-shadow: 1px 0 0 #0c3d5c;">EWI code</th>
                            <th style="position: sticky; left: 11rem; width: 6.5rem; background: #11567F; color: #ffffff; z-index: 2; text-align: center; padding: 0.5rem; box-shadow: 1px 0 0 #0c3d5c;">Severity</th>
                            {''.join(header_cells)}
                            <th style="position: sticky; right: 0; width: 6.5rem; background: #11567F; color: #ffffff; z-index: 2; text-align: center; padding: 0.5rem; box-shadow: -1px 0 0 #0c3d5c;">{unit_plural.capitalize()}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(body_rows)}
                    </tbody>
                </table>
            </div>
        </div>
    """
