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

"""Load and render ``scai assessment workload-insights`` artifacts."""

from __future__ import annotations

import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

_SCHEMA_VERSION = 1
_TOP_N = 20
_ENABLE_QUERY_STORE_SQL = """ALTER DATABASE CURRENT SET QUERY_STORE = ON (
    OPERATION_MODE = READ_WRITE,
    QUERY_CAPTURE_MODE = AUTO,
    -- 30 is the suggested window; any positive integer is valid
    CLEANUP_POLICY = ( STALE_QUERY_THRESHOLD_DAYS = 30 )
);"""
_EXTRACT_SQL = """EXEC sys.sp_query_store_flush_db;
GO

DECLARE @Days int = 30;  -- suggested window; any positive integer is valid

WITH s AS (
    SELECT
        p.query_id,
        SUM(rs.count_executions)                   AS executions,
        SUM(rs.avg_duration * rs.count_executions) AS duration_us,
        SUM(rs.avg_cpu_time * rs.count_executions) AS cpu_us,
        MAX(rs.max_duration)                       AS max_duration_us,
        MIN(rs.first_execution_time)               AS first_seen,
        MAX(rs.last_execution_time)                AS last_seen
    FROM sys.query_store_runtime_stats AS rs
    JOIN sys.query_store_plan AS p
        ON p.plan_id = rs.plan_id
    WHERE rs.execution_type = 0
      AND rs.last_execution_time >= DATEADD(DAY, -@Days, SYSDATETIMEOFFSET())
    GROUP BY p.query_id
)
SELECT
    DB_NAME()                       AS database_name,
    s.query_id,
    q.object_id,
    OBJECT_SCHEMA_NAME(q.object_id) AS object_schema,
    OBJECT_NAME(q.object_id)        AS object_name,
    s.executions,
    s.duration_us,
    s.cpu_us,
    s.max_duration_us,
    s.first_seen,
    s.last_seen,
    qt.query_sql_text
FROM s
JOIN sys.query_store_query AS q
    ON q.query_id = s.query_id
   AND q.is_internal_query = 0
JOIN sys.query_store_query_text AS qt
    ON qt.query_text_id = q.query_text_id;"""
_H2_STYLE = (
    'style="font-size:1.35rem;font-weight:700;color:#102E46;'
    'margin:48px 0 16px;"'
)


def is_sql_server(source_dialect: str) -> bool:
    """Return whether the multi-report dialect token is SQL Server."""
    return source_dialect == "Transact"


def load_workload_insights(path: Path) -> Optional[dict[str, Any]]:
    """Load a schema-v1 artifact, returning ``None`` for optional bad input."""
    try:
        with Path(path).open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"Warning: Could not load workload insights data: {exc}", file=sys.stderr)
        return None

    if not isinstance(payload, dict) or payload.get("schema_version") != _SCHEMA_VERSION:
        print(
            "Warning: Could not load workload insights data: unsupported schema",
            file=sys.stderr,
        )
        return None

    dict_fields = ("kpis", "window")
    list_fields = (
        "databases",
        "statement_mix",
        "busiest_modules",
        "top_shapes_by_duration",
        "slow_shapes",
    )
    invalid = any(not isinstance(payload.get(field), dict) for field in dict_fields)
    invalid = invalid or any(
        not isinstance(payload.get(field), list) for field in list_fields
    )
    row_fields = list_fields[1:]
    invalid = invalid or any(
        not isinstance(row, dict)
        for field in row_fields
        for row in (payload.get(field) if isinstance(payload.get(field), list) else [])
    )
    if invalid:
        print(
            "Warning: Could not load workload insights data: invalid schema shape",
            file=sys.stderr,
        )
        return None
    return payload


def _esc(value: Any) -> str:
    return html.escape(str(value)) if value is not None else ""


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return _esc(value)


def _fmt_pct(value: Any) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return _esc(value)


def _fmt_ms(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return _esc(value)


_MS_ABBR = '<span class="wi-ms">ms<span class="tooltip">milliseconds</span></span>'


def _fmt_timestamp(value: Any) -> str:
    if not value:
        return "Not available"
    raw = str(value)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.strftime("%b %d, %Y %H:%M")
        return parsed.astimezone(timezone.utc).strftime("%b %d, %Y %H:%M UTC")
    except ValueError:
        return _esc(raw)


def render_object_cell(row: Mapping[str, Any]) -> str:
    """Render the locked named/ad-hoc/dropped-module object treatments."""
    kind = row.get("object_kind")
    if kind == "AD_HOC":
        return '<span class="wi-muted">Ad-hoc</span>'
    if kind == "MODULE_DROPPED":
        object_id = _esc(row.get("object_id") or "")
        return (
            '<span class="wi-muted">Unnamed module</span> '
            f'<span class="wi-mono">{object_id}</span>'
        )

    schema = str(row.get("object_schema") or "").strip()
    name = str(row.get("object_name") or "").strip()
    schema_html = (
        f'<span class="wi-muted wi-mono">{_esc(schema)}</span>.' if schema else ""
    )
    name_html = f'<strong class="wi-mono">{_esc(name)}</strong>' if name else ""
    rendered = (schema_html + name_html).strip()
    return rendered or '<span class="wi-muted">Unnamed module</span>'


def object_title(row: Mapping[str, Any]) -> str:
    """Return the plain-text object label used as a tooltip when the cell clips."""
    kind = row.get("object_kind")
    if kind == "AD_HOC":
        return "Ad-hoc"
    object_id = str(row.get("object_id") or "").strip()
    if kind == "MODULE_DROPPED":
        return f"Unnamed module {object_id}".strip()

    schema = str(row.get("object_schema") or "").strip()
    name = str(row.get("object_name") or "").strip()
    if schema and name:
        return f"{schema}.{name}"
    return name or "Unnamed module"


def _render_header() -> str:
    return f"""
        <div style="margin-bottom:24px;">
            <h1 style="font-size:1.875rem;font-weight:800;color:#102E46;margin-bottom:8px;">
                Workload Insights
            </h1>
            <p class="wi-notice">
                <strong>Disclaimer:</strong> Query Store data, and everything derived from it
                in this report, is used for reporting purposes only.
            </p>
            <p class="wi-blurb">
                Insights from the SQL Server Query Store extract provided for this project.
                Counts are per <strong>shape</strong>. Module totals are
                <strong>statement executions</strong>, not procedure calls.
            </p>
        </div>
    """


def _render_summary(payload: Mapping[str, Any]) -> str:
    window = payload.get("window") or {}
    databases = payload.get("databases") or []
    database_text = ", ".join(_esc(database) for database in databases) or "Not available"
    return f"""
        <div class="wi-summary">
            <div><strong>Observed window</strong><br>
                {_fmt_timestamp(window.get("first_seen"))} &ndash;
                {_fmt_timestamp(window.get("last_seen"))}
            </div>
            <div><strong>Databases</strong><br>{database_text}</div>
        </div>
    """


def _render_kpis(payload: Mapping[str, Any]) -> str:
    kpis = payload.get("kpis") or {}
    cards = (
        ("Statement executions", _fmt_int(kpis.get("execution_count", 0))),
        ("Distinct shapes", _fmt_int(kpis.get("shape_count", 0))),
        ("Named modules", _fmt_int(kpis.get("module_count", 0))),
        (
            "% executions in modules",
            _fmt_pct(kpis.get("pct_executions_in_modules", 0)),
        ),
    )
    items = "".join(
        '<div class="effort-card">'
        f'<div class="effort-card-num">{value}</div>'
        f'<div class="effort-card-lbl">{label}</div>'
        "</div>"
        for label, value in cards
    )
    return f'<div class="effort-cards wi-kpis">{items}</div>'


def _empty_table_row(columns: int) -> str:
    return (
        f'<tr><td colspan="{columns}" class="wi-table-empty">'
        "No rows were recorded for this section.</td></tr>"
    )


def _render_statement_mix(rows: Sequence[Mapping[str, Any]]) -> str:
    body = "".join(
        "<tr>"
        f'<td><span class="badge info">{_esc(row.get("statement_type"))}</span></td>'
        f'<td class="num">{_fmt_int(row.get("shapes"))}</td>'
        f'<td class="num">{_fmt_int(row.get("executions"))}</td>'
        f'<td class="num">{_fmt_pct(row.get("pct_executions"))}</td>'
        f'<td class="num">{_fmt_ms(row.get("avg_duration_ms"))}</td>'
        "</tr>"
        for row in rows
    ) or _empty_table_row(5)
    return f"""
        <h2 {_H2_STYLE}>Statement mix</h2>
        <p class="wi-section-intro">
            Every observed statement type, ordered as emitted by the assessment artifact.
        </p>
        <div class="effort-table-wrap">
            <table class="effort-table wi-mix-table">
                <thead><tr>
                    <th class="wi-col-label">Type</th>
                    <th class="num wi-col-shapes">Shapes</th>
                    <th class="num wi-col-num">Executions</th>
                    <th class="num wi-col-num">% of executions</th>
                    <th class="num wi-col-num">Weighted avg {_MS_ABBR}</th>
                </tr></thead>
                <tbody>{body}</tbody>
            </table>
        </div>
    """


def _render_busiest_modules(rows: Sequence[Mapping[str, Any]]) -> str:
    body = "".join(
        "<tr>"
        f'<td class="wi-object-cell" title="{_esc(object_title(row))}">'
        f"{render_object_cell(row)}</td>"
        + f'<td class="num">{_fmt_int(row.get("shapes"))}</td>'
        + f'<td class="num">{_fmt_int(row.get("statement_executions"))}</td>'
        + f'<td class="num">{_fmt_ms(row.get("total_duration_ms"))}</td>'
        + f'<td class="num">{_fmt_ms(row.get("avg_ms_per_statement"))}</td>'
        + "</tr>"
        for row in rows[:_TOP_N]
    ) or _empty_table_row(5)
    return f"""
        <h2 {_H2_STYLE}>Busiest modules &mdash; Top 20 by statement executions</h2>
        <p class="wi-section-intro">
            Totals count statements executed inside each module, not procedure calls.
        </p>
        <div class="effort-table-wrap">
            <table class="effort-table wi-mix-table">
                <thead><tr>
                    <th class="wi-col-label">Object</th>
                    <th class="num wi-col-shapes">Statements</th>
                    <th class="num wi-col-num">Statement executions</th>
                    <th class="num wi-col-num">Total {_MS_ABBR}</th>
                    <th class="num wi-col-num">Avg {_MS_ABBR} / statement</th>
                </tr></thead>
                <tbody>{body}</tbody>
            </table>
        </div>
    """


def _render_shape_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    include_total: bool,
) -> str:
    rendered = []
    columns = 7
    for row in rows[:_TOP_N]:
        # Slow has no total duration, so it pads the grid to keep both tables
        # column-for-column aligned instead of widening its own columns.
        duration_cells = (
            f'<td class="num">{_fmt_ms(row.get("total_duration_ms"))}</td>'
            f'<td class="num">{_fmt_ms(row.get("avg_duration_ms"))}</td>'
            f'<td class="num">{_fmt_ms(row.get("max_duration_ms"))}</td>'
            if include_total
            else (
                f'<td class="num">{_fmt_ms(row.get("max_duration_ms"))}</td>'
                f'<td class="num">{_fmt_ms(row.get("avg_duration_ms"))}</td>'
                '<td class="wi-col-spacer" aria-hidden="true"></td>'
            )
        )
        truncated = (
            '<span class="wi-truncated">SQL was truncated in the artifact.</span>'
            if row.get("sql_truncated")
            else ""
        )
        rendered.append(
            '<tr class="wi-shape-row">'
            "<td>"
            '<details class="wi-sql-details">'
            '<summary><span class="expand-icon">&#9656;</span>'
            f'<span class="wi-sql-oneline">{_esc(row.get("display_sql"))}</span>'
            "</summary>"
            f"{truncated}"
            f'<pre class="wi-full-sql">{_esc(row.get("full_sql"))}</pre>'
            "</details>"
            "</td>"
            f'<td><span class="badge info">{_esc(row.get("statement_type"))}</span></td>'
            f'<td class="wi-object-cell" title="{_esc(object_title(row))}">'
            f"{render_object_cell(row)}</td>"
            f'<td class="num">{_fmt_int(row.get("executions"))}</td>'
            f"{duration_cells}"
            "</tr>"
        )
    return "".join(rendered) or _empty_table_row(columns)


def _render_cost(rows: Sequence[Mapping[str, Any]]) -> str:
    return f"""
        <h2 {_H2_STYLE}>Cost &mdash; Top 20 by total duration</h2>
        <p class="wi-section-intro">
            Shapes whose cumulative runtime consumed the most time. Select a row to expand its SQL.
        </p>
        <div class="effort-table-wrap">
            <table class="effort-table wi-shape-table">
                <thead><tr>
                    <th class="wi-col-sql">Shape</th>
                    <th class="wi-col-type">Type</th>
                    <th class="wi-col-obj">Object</th>
                    <th class="num wi-col-num">Executions</th>
                    <th class="num wi-col-num">Total {_MS_ABBR}</th>
                    <th class="num wi-col-num">Avg {_MS_ABBR}</th>
                    <th class="num wi-col-num">Max {_MS_ABBR}</th>
                </tr></thead>
                <tbody>{_render_shape_rows(rows, include_total=True)}</tbody>
            </table>
        </div>
    """


def _render_slow(rows: Sequence[Mapping[str, Any]]) -> str:
    return f"""
        <h2 {_H2_STYLE}>Slow &mdash; Top 20 by worst observed run</h2>
        <p class="wi-section-intro">
            Shapes with the highest recorded maximum. Max is a worst observed run, not a percentile.
        </p>
        <div class="effort-table-wrap">
            <table class="effort-table wi-shape-table">
                <thead><tr>
                    <th class="wi-col-sql">Shape</th>
                    <th class="wi-col-type">Type</th>
                    <th class="wi-col-obj">Object</th>
                    <th class="num wi-col-num">Executions</th>
                    <th class="num wi-col-num">Max {_MS_ABBR}</th>
                    <th class="num wi-col-num">Avg {_MS_ABBR}</th>
                    <th class="num wi-col-num wi-col-spacer" aria-hidden="true"></th>
                </tr></thead>
                <tbody>{_render_shape_rows(rows, include_total=False)}</tbody>
            </table>
        </div>
    """


def _render_step(number: int, title: str, body: str) -> str:
    return f"""
            <div class="journey-card wi-step">
                <div class="journey-badge">{number}</div>
                <div class="journey-card-body">
                    <h3>{title}</h3>
                    {body}
                </div>
            </div>
    """


def _render_sql_disclosure(label: str, sql: str) -> str:
    return f"""
                    <details class="wi-sql-details wi-howto-sql">
                        <summary><span class="expand-icon">&#9656;</span>
                            <span>{label}</span></summary>
                        <pre class="wi-full-sql">{_esc(sql)}</pre>
                    </details>
    """


def _render_how_to() -> str:
    steps = (
        _render_step(
            1,
            "Confirm Query Store is on",
            "<p>Query Store is per database, not per instance. If it is off, turn it on and"
            " give it time to record history under real traffic before extracting. 30 days is"
            " the suggested window — change <code>STALE_QUERY_THRESHOLD_DAYS</code> to a"
            " shorter or longer range.</p>"
            + _render_sql_disclosure("Enable Query Store", _ENABLE_QUERY_STORE_SQL),
        )
        + _render_step(
            2,
            "Export the extract as CSV",
            "<p>Run the extract <strong>inside each user database</strong> you care about"
            " and save the result as CSV <strong>with headers included</strong> — one file"
            " per database, or the files concatenated. 30 days is the suggested"
            " window — change <code>@Days</code> to a shorter or longer range.</p>"
            + _render_sql_disclosure("Query Store extract", _EXTRACT_SQL),
        )
        + _render_step(
            3,
            "Re-run the assessment, then regenerate this report",
            "<p>Re-run the assessment and give it the CSV path when the Workload Insights"
            " step asks for it, or run the command yourself:</p>"
            '<pre class="wi-full-sql">scai assessment workload-insights'
            " --input /path/to/query-store.csv</pre>",
        )
    )
    unlocks = "".join(
        f"<li>{item}</li>"
        for item in (
            "Observed window and the databases the extract covers",
            "Statement executions, distinct shapes, and named modules",
            "Statement mix by type",
            "Busiest modules by statement executions",
            "The most expensive shapes by total duration",
            "Shapes whose worst observed run stands out",
        )
    )
    return f"""
        <p class="wi-disclaimer">
            <strong>No Query Store extract in this project yet.</strong> This phase is
            optional — the rest of the assessment does not depend on it.
        </p>
        <h2 {_H2_STYLE}>How to get the extract</h2>
        <div class="journey-grid">{steps}</div>
        <h2 {_H2_STYLE}>What the extract adds to this report</h2>
        <ul class="wi-unlocks">{unlocks}</ul>
    """


def render_workload_insights_tab_html(
    payload: Optional[Mapping[str, Any]],
) -> str:
    """Render inner Workload Insights HTML from already-computed artifact values."""
    if not payload or not payload.get("found"):
        return f"""
            <div id="workload-insights-report" v-pre>
                {_render_header()}
                {_render_how_to()}
            </div>
        """
    header = _render_header()

    return f"""
        <div id="workload-insights-report" v-pre>
            {header}
            {_render_summary(payload)}
            {_render_kpis(payload)}
            {_render_statement_mix(payload.get("statement_mix") or [])}
            {_render_busiest_modules(payload.get("busiest_modules") or [])}
            {_render_cost(payload.get("top_shapes_by_duration") or [])}
            {_render_slow(payload.get("slow_shapes") or [])}
        </div>
    """


def workload_insights_css() -> str:
    """Return the small, tab-scoped additions not covered by shared report CSS."""
    # Raw string: the disclosure chevrons rely on CSS escapes such as \25B8, which a
    # regular literal would swallow as octal.
    return r"""
/* Same treatment as the Overview tab's report-level disclaimer. */
#workload-insights-report .wi-notice {
    color: #374151; background: #F3F4F6; border: 1px solid #D1D5DB;
    border-left: 4px solid #9CA3AF; border-radius: 6px; padding: 10px 12px;
    font-size: 0.78rem; line-height: 1.45; margin: 0 0 12px;
}
#workload-insights-report .wi-blurb {
    color: #64748B; font-size: 1rem; line-height: 1.6; margin: 0;
}
#workload-insights-report .wi-disclaimer {
    color: #0369A1; background: #F0F9FF; border: 1px solid #BAE6FD;
    border-radius: 8px; padding: 12px 14px; font-size: 0.88rem;
    line-height: 1.5; margin-bottom: 24px;
}
#workload-insights-report .wi-summary {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 16px; margin-bottom: 24px; color: var(--text-secondary);
}
#workload-insights-report .wi-section-intro {
    color: var(--text-secondary); font-size: 0.9rem; margin: -8px 0 12px;
}
#workload-insights-report .wi-muted { color: var(--text-secondary); }
#workload-insights-report .wi-mono {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
/* Native disclosure keeps the SQL inside its own shape cell, so nothing spans the
   row and no script is needed to toggle it. */
#workload-insights-report .wi-sql-details summary {
    cursor: pointer; list-style: none; display: flex; align-items: baseline;
}
#workload-insights-report .wi-sql-details summary::-webkit-details-marker {
    display: none;
}
/* Same chevron as Anti-Patterns; flex: none keeps every box a uniform 18px. */
#workload-insights-report .expand-icon {
    margin-right: 8px; flex: none; transition: transform 0.15s;
    color: var(--sf-dark-blue);
}
#workload-insights-report .wi-sql-details[open] .expand-icon { transform: rotate(90deg); }
/* Every column is pinned so Cost and Slow align end to end; Slow pads its missing
   fourth measure with an empty cell rather than stretching its own columns. */
#workload-insights-report .wi-shape-table { table-layout: fixed; }
#workload-insights-report .wi-col-sql { width: 32%; }
#workload-insights-report .wi-col-type { width: 8%; }
#workload-insights-report .wi-col-obj { width: 24%; }
#workload-insights-report .wi-col-num { width: 9%; }
#workload-insights-report .wi-mix-table { table-layout: fixed; }
#workload-insights-report .wi-col-label { width: 32%; }
#workload-insights-report .wi-col-shapes { width: 14%; }
#workload-insights-report .wi-mix-table .wi-col-num { width: 18%; }
#workload-insights-report .wi-sql-oneline {
    min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
#workload-insights-report .wi-object-cell {
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
#workload-insights-report .wi-truncated {
    display: block; color: var(--text-secondary); font-size: 0.8rem;
}
#workload-insights-report .wi-full-sql {
    white-space: pre-wrap; overflow-wrap: anywhere; font-size: 0.8rem;
    margin: 8px 0 0; padding: 14px; background: #F8FAFC;
    border: 1px solid var(--border-color); border-radius: 8px;
}
#workload-insights-report .wi-table-empty {
    text-align: center; color: var(--text-secondary); font-style: italic;
}
#workload-insights-report .wi-ms {
    position: relative; cursor: help; text-decoration: underline dotted;
    text-underline-offset: 2px;
}
#workload-insights-report .wi-ms .tooltip {
    visibility: hidden; opacity: 0; position: absolute; top: 140%; left: 50%;
    transform: translateX(-50%); background: var(--sf-navy); color: white;
    padding: 6px 10px; border-radius: 8px; font-size: 0.75rem; font-weight: 500;
    white-space: nowrap; z-index: 20; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    pointer-events: none; transition: opacity 0.15s;
}
#workload-insights-report .wi-ms .tooltip::after {
    content: ""; position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%);
    border: 6px solid transparent; border-bottom-color: var(--sf-navy);
}
#workload-insights-report .wi-ms:hover .tooltip { visibility: visible; opacity: 1; }
#workload-insights-report .wi-step { cursor: default; align-items: flex-start; }
#workload-insights-report .wi-step:hover {
    border-color: #E2E8F0; box-shadow: none; transform: none;
}
#workload-insights-report .wi-step .journey-badge { margin-top: 2px; }
#workload-insights-report .wi-howto-sql { margin-top: 10px; }
#workload-insights-report .wi-howto-sql summary {
    font-size: 0.85rem; font-weight: 600; color: var(--sf-dark-blue);
}
#workload-insights-report .wi-unlocks {
    margin: 0; padding-left: 22px; list-style: disc outside;
    color: var(--text-secondary); font-size: 0.9rem; line-height: 1.9;
}
"""
