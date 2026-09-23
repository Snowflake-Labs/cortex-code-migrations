# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0

"""Render Teradata DBQL workload-insights HTML. SQL Server stays in
sqlserver_workload_insights.py so Teradata layout changes cannot alter that dialect."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from workload_insights_common import (
    _BUCKET_COLORS,
    _chart,
    _classification_section,
    _esc,
    _fmt_day,
    _fmt_duration,
    _fmt_int,
    _fmt_number,
    _fmt_pct,
    _kpi_value,
    _kpis,
    _num,
    _section,
    _table,
    _text,
    workload_insights_css,
)

_TERADATA_FALLBACK_SQL = """LOCKING ROW FOR ACCESS
SELECT
    CAST(QueryID AS BIGINT) AS QueryID,
    CAST(CollectTimeStamp AS DATE FORMAT 'YYYY-MM-DD') AS LogDate,
    CAST(CollectTimeStamp AS VARCHAR(30)) AS CollectTimeStamp,
    CAST(ProcID AS BIGINT) AS ProcID,
    CAST(SessionID AS INTEGER) AS SessionID,
    COALESCE(CAST(AppID AS VARCHAR(128)), '') AS AppID,
    CAST(StartTime AS VARCHAR(30)) AS StartTime,
    CAST(FirstStepTime AS VARCHAR(30)) AS FirstStepTime,
    CAST(FirstRespTime AS VARCHAR(30)) AS FirstRespTime,
    COALESCE(CAST(StatementType AS VARCHAR(30)), '') AS StatementType,
    COALESCE(DefaultDatabase, '') AS DefaultDatabase,
    COALESCE(StatementGroup, '') AS StatementGroup,
    CAST(ErrorCode AS INTEGER) AS ErrorCode,
    COALESCE(CAST(NumResultRows AS BIGINT), 0) AS NumResultRows,
    COALESCE(CAST(TotalIOCount AS BIGINT), 0) AS TotalIOCount,
    COALESCE(CAST(AMPCPUTime AS FLOAT), 0) AS AMPCPUTime,
    COALESCE(UserName, '') AS UserName
FROM DBC.DBQLogTbl
WHERE CollectTimeStamp BETWEEN TIMESTAMP 'YYYY-MM-DD HH:MM:SS'
                           AND TIMESTAMP 'YYYY-MM-DD HH:MM:SS';"""

_TERADATA_PROBE_SQL = """-- Run these one at a time, top to bottom. Keep the first statement that
-- succeeds and reports a row; that table is your source for the export.
-- Error 3807 means the table does not exist on this system and 3523 means
-- you lack rights on it — in both cases move to the next statement.

LOCKING ROW FOR ACCESS
SELECT TOP 1 'PDCRINFO.DBQLogTbl_Hst' AS SourceTable,
             QueryID,
             CollectTimeStamp
FROM PDCRINFO.DBQLogTbl_Hst;

LOCKING ROW FOR ACCESS
SELECT TOP 1 'PDCRINFO.DBQLogTbl' AS SourceTable,
             QueryID,
             CollectTimeStamp
FROM PDCRINFO.DBQLogTbl;

LOCKING ROW FOR ACCESS
SELECT TOP 1 'DBC.DBQLogTblV' AS SourceTable,
             QueryID,
             CollectTimeStamp
FROM DBC.DBQLogTblV;

LOCKING ROW FOR ACCESS
SELECT TOP 1 'DBC.DBQLogTbl' AS SourceTable,
             QueryID,
             CollectTimeStamp
FROM DBC.DBQLogTbl;"""


def _header() -> str:
    return """
<header class="wi-header">
  <h1>Discovery</h1>
  <p class="wi-notice"><strong>Disclaimer:</strong> This report uses metadata only;
  no SQL text shown or stored. No query text, parameters, query identifiers, or
  error messages appear in the assessment artifact or this report.</p>
  <p class="wi-blurb">Insights from the Teradata <strong>DBQL metrics</strong>
  extract provided for this project. Each row is one request.</p>
</header>"""


def _summary(payload: Mapping[str, Any]) -> str:
    summary = payload["summary"]
    databases = ", ".join(_esc(item) for item in summary.get("databases", []))
    day_count = len(payload["daily"])
    day_word = "day" if day_count == 1 else "days"
    system = ""
    if summary.get("server") or summary.get("engine"):
        system = (
            "<div><strong>Server &middot; engine</strong><br>"
            f"{_esc(summary.get('server')) or 'Not available'} &middot; "
            f"{_esc(summary.get('engine')) or 'Not available'}</div>"
        )
    return f"""
<div class="wi-summary">
  {system}
  <div><strong>Database</strong><br>{databases or "Not available"}</div>
  <div><strong>Capture window</strong><br>{_fmt_day(summary.get("first_seen"))}
    &ndash; {_fmt_day(summary.get("last_seen"))} &middot; {day_count} {day_word}</div>
  <div><strong>Capture filters</strong><br>{_text(summary.get("capture_filters"))}</div>
</div>"""


def _duration_section(payload: Mapping[str, Any]) -> str:
    histogram = payload["duration_histogram"]
    insights = []
    for index, row in enumerate(histogram):
        count = _num(row.get("executions"))
        color = _BUCKET_COLORS[index % len(_BUCKET_COLORS)]
        insights.append(
            '<div class="wi-insight">'
            f'<div class="wi-insight-value" style="color:{color}">'
            f"{_fmt_pct(row.get('pct'))}</div>"
            f'<div class="wi-insight-label">{_esc(row.get("bucket"))}</div>'
            f'<div class="wi-insight-sub">{_fmt_int(count)} executions</div></div>'
        )
    percentile_rows = [
        [_esc(row.get("label")), f"<strong>{_fmt_duration(row.get('duration_ms'))}</strong>"]
        for row in payload["percentiles"].get("rows", [])
    ]
    chart_card = (
        '<div class="wi-card"><h3>Duration bucket distribution (log scale)</h3>'
        f'{_chart("wi-chart-histogram")}</div>'
    )
    percentile_card = (
        '<div class="wi-card"><h3>Duration percentiles</h3>'
        + _table(["Percentile", "Duration"], percentile_rows)
        + "</div>"
    )
    empty = (
        '<p class="wi-empty-notice">No duration buckets were recorded.</p>'
        if not histogram
        else ""
    )
    body = f"""
{empty}
<div class="wi-insights">{"".join(insights)}</div>
<div class="wi-grid-2">{chart_card}{percentile_card}</div>"""
    return _section("Query performance histogram &mdash; duration buckets", body)


def _timeline_section(payload: Mapping[str, Any]) -> str:
    daily = payload["daily"]
    peak = max(daily, key=lambda row: row.get("executions", 0), default={})
    quiet = min(daily, key=lambda row: row.get("executions", 0), default={})
    executions = _num(_kpi_value(payload, "total_requests"))
    average = executions / len(daily) if daily else 0
    empty = (
        '<p class="wi-empty-notice">No capture days were recorded.</p>'
        if not daily
        else ""
    )
    body = f"""
{empty}
<div class="wi-card"><h3>Executions per day &mdash; stacked by duration bucket</h3>
  {_chart("wi-chart-daily", tall=True)}
</div>
<div class="wi-stat-grid">
  <div class="wi-stat"><span>Peak day</span><strong>{_fmt_int(peak.get("executions", 0))}</strong>
    <small>{_esc(peak.get("day"))}</small></div>
  <div class="wi-stat"><span>Quietest day</span><strong>{_fmt_int(quiet.get("executions", 0))}</strong>
    <small>{_esc(quiet.get("day"))}</small></div>
  <div class="wi-stat"><span>Average per day</span><strong>{_fmt_number(average)}</strong>
    <small>{_fmt_int(executions)} executions / {len(daily)} days</small></div>
</div>
<div class="wi-card"><h3>Executions and errors across the window</h3>
  {_chart("wi-chart-timeline")}
</div>"""
    return _section("Query execution timeline", body)


def _connections_section(payload: Mapping[str, Any]) -> str:
    rows = [
        [
            f"<strong>{_esc(row.get('user'))}</strong>",
            f'<span class="wi-mono">{_esc(row.get("app"))}</span>',
            _fmt_int(row.get("executions")),
            _fmt_pct(row.get("pct")),
        ]
        for row in payload["connection_context"]
    ]
    body = f"""
<div class="wi-grid-2">
  <div class="wi-card"><h3>Top applications (AppID)</h3>
    {_chart("wi-chart-apps")}</div>
  <div class="wi-card"><h3>Top users (UserName)</h3>
    {_chart("wi-chart-users")}</div>
</div>
<div class="wi-card"><h3>User and connection context</h3>
  {_table(["User", "Application", "Requests", "% share"], rows)}
</div>"""
    return _section("Applications &amp; users", body)


def _long_running_section(payload: Mapping[str, Any]) -> str:
    long_running = payload["long_running"]
    total = long_running.get("total", 0)
    rows = [
        [
            _fmt_int(row.get("rank")),
            f"<strong>{_fmt_duration(row.get('duration_ms'))}</strong>",
            _esc(row.get("statement_type")),
            _esc(row.get("user")) or "Not available",
            _esc(row.get("database")) or "Not available",
            _fmt_number(row.get("amp_cpu_ms")) if row.get("amp_cpu_ms") is not None else "",
            _fmt_int(row.get("io_count")) if row.get("io_count") is not None else "",
        ]
        for row in long_running.get("top", [])
    ]
    headers = [
        "#", "Duration", "Statement", "User", "Database",
        "AMP CPU ms", "I/O count",
    ]
    bands = [
        (
            _esc(row.get("bucket")),
            row.get("executions"),
            _BUCKET_COLORS[(index + 2) % len(_BUCKET_COLORS)],
            (
                f" &middot; max is {_fmt_duration(long_running.get('max_duration_ms'))}"
                if index == len(long_running.get("bands", [])) - 1
                else ""
            ),
        )
        for index, row in enumerate(long_running.get("bands", []))
    ]
    band_total = sum(_num(count) for _, count, _, _ in bands)
    band_tiles = "".join(
        f'<div class="wi-stat"><span>{label}</span>'
        f'<strong style="color:{color}">{_fmt_int(count)}</strong>'
        f"<small>{_fmt_pct(100 * _num(count) / band_total if band_total else 0)}"
        f" of long-runners{suffix}</small></div>"
        for label, count, color, suffix in bands
    )
    threshold = _esc(long_running.get("threshold_label")) or "the configured threshold"
    body = f"""
<p class="wi-danger-callout"><strong>{_fmt_int(total)} executions</strong> ran longer
than {threshold.removeprefix('&gt; ').lower()} &mdash; {_fmt_pct(long_running.get("pct_of_executions"))} of the
captured workload.</p>
<div class="wi-stat-grid">{band_tiles}</div>
<div class="wi-card"><h3>Long executions ({threshold}) by statement type</h3>
  {_chart("wi-chart-long")}</div>
<div class="wi-card"><h3>Longest captured executions &mdash; top 10 of
{_fmt_int(total)} past {threshold.removeprefix('&gt; ').lower()}</h3>
  <div class="wi-long-table">
    {_table(headers, rows)}
  </div>
</div>"""
    return _section(f"Long-running query analysis ({threshold})", body)


def _schema_correlation_section(payload: Mapping[str, Any]) -> str:
    rows = [
        [
            f"<strong>{_esc(row.get('user'))}</strong>",
            f'<span class="wi-mono">{_esc(row.get("app"))}</span>',
            _fmt_int(row.get("executions")),
            _fmt_pct(row.get("pct")),
            ", ".join(_esc(database) for database in row.get("databases", []))
            or "None recorded",
        ]
        for row in payload["schema_correlation"]
    ]
    return _section(
        "Schema &harr; workload correlation",
        '<div class="wi-card"><h3>Databases seen per user and application (DefaultDatabase)</h3>'
        + _table(
            ["User", "Application", "Requests", "% share", "Databases used"],
            rows,
        )
        + "</div>",
    )


def _errors_section(payload: Mapping[str, Any]) -> str:
    errors = payload["errors"]
    body = f"""
<div class="wi-grid-2">
  <div class="wi-card"><h3>Error and abort counts</h3>
    <div class="wi-tiles">
      <div class="wi-tile"><div class="wi-tile-value" style="color:#D9534F">{_fmt_int(errors.get("count"))}</div>
        <div class="wi-tile-label">Non-zero ErrorCode requests</div>
        <div class="wi-tile-sub">{_fmt_pct(errors.get("pct_of_executions"))} of requests</div></div>
      <div class="wi-tile"><div class="wi-tile-value" style="color:#F0B429">{_fmt_int(errors.get("abort_count"))}</div>
        <div class="wi-tile-label">Abort records</div>
        <div class="wi-tile-sub">{_fmt_pct(errors.get("abort_pct_of_errors"))} of errors</div></div>
    </div>
  </div>
  <div class="wi-card"><h3>Request outcome mix</h3>
    {_chart("wi-chart-event-mix")}</div>
</div>"""
    return _section("Errors &amp; aborts", body)


def _how_to() -> str:
    return f"""
<p class="wi-empty-notice"><strong>No DBQL workload extract in this project yet.</strong>
This phase is optional; the rest of the assessment does not depend on it.</p>
<p>If DBQL logging is on, Teradata already recorded this history &mdash; nothing
has to be installed, started, or waited for, and the export below reads what is
already stored.</p>
<h2 class="wi-how-to-title">How to get a DBQL extract</h2>
<div class="journey-grid wi-how-to">
  <div class="journey-card wi-step"><div class="journey-badge">1</div>
    <div class="journey-card-body"><h3>Find the query log you can read</h3>
      <p>Run these statements one at a time, top to bottom. Keep the first one
      that succeeds and reports rows.</p>
      <div class="wi-script-actions"><button type="button" class="wi-copy-btn"
        data-wi-copy="wi-teradata-probe-sql">Copy</button></div>
      <pre id="wi-teradata-probe-sql">{_esc(_TERADATA_PROBE_SQL)}</pre>
      <p>Zero rows with no error means DBQL logging was not enabled or retained
      for that table. One returned row is enough &mdash; this check does not
      count the whole log.</p></div></div>
  <div class="journey-card wi-step"><div class="journey-badge">2</div>
    <div class="journey-card-body"><h3>Export the request metrics</h3>
      <p>Point the <code>FROM</code> at the table you kept in step 1 and replace both
      <code>YYYY-MM-DD HH:MM:SS</code> bounds with the window you want covered
      &mdash; about 30 days gives a representative picture.</p>
      <p class="wi-dba-note"><strong>Have a DBA review this before you run it.</strong>
      Reading the query log over that window uses CPU, I/O, and spool on the server.
      Run it off-peak, and start with a shorter window if the log is large. A DBA
      with Teradata Tools and Utilities can run this same <code>SELECT</code>
      through FastExport or TPT Export instead of a SQL client. That moves the
      rows faster and avoids a client that chokes on millions of them; it
      does not make the query cheaper on the server, and it takes one of the
      system's load-utility slots.</p>
      <div class="wi-script-actions"><button type="button" class="wi-copy-btn"
        data-wi-copy="wi-teradata-fallback-sql">Copy</button></div>
      <pre id="wi-teradata-fallback-sql">{_esc(_TERADATA_FALLBACK_SQL)}</pre>
      <p>Export the result to CSV with column headers.</p></div></div>
  <div class="journey-card wi-step"><div class="journey-badge">3</div>
    <div class="journey-card-body"><h3>Re-run the assessment, then regenerate this report</h3>
      <pre>scai assessment workload-insights --input /path/to/querylogs.csv</pre>
      <p>Repeat <code>--input</code> to merge split exports.</p></div></div>
</div>
<h2 class="wi-how-to-title">What an extract adds to this report</h2>
<ul class="wi-unlocks">
  <li>Window, databases, request counts, duration mix, long-runners, and errors versus aborts</li>
</ul>"""


def render_teradata_workload_insights_tab_html(
    payload: Optional[Mapping[str, Any]],
) -> str:
    """Render inner Teradata Workload Insights HTML from artifact values."""
    if not payload or not payload.get("found"):
        return f'<div id="workload-insights-report" v-pre>{_header()}{_how_to()}</div>'
    return f"""<div id="workload-insights-report" v-pre>
{_header()}
{_summary(payload)}
{_kpis(payload)}
{_duration_section(payload)}
{_timeline_section(payload)}
{_classification_section(payload)}
{_connections_section(payload)}
{_long_running_section(payload)}
{_schema_correlation_section(payload)}
{_errors_section(payload)}
</div>"""


def teradata_workload_insights_css() -> str:
    """SQL Server styles plus the seven-KPI strip Teradata needs."""
    return (
        workload_insights_css()
        + """
#workload-insights-report .wi-kpis {
  display: grid; grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr);
  border: 1px solid #E2E8F0; border-radius: 12px; overflow: hidden;
}
#workload-insights-report .wi-kpi { min-width: 0; }
@media (max-width: 1000px) {
  #workload-insights-report .wi-kpis {
    grid-auto-flow: row; grid-template-columns: repeat(2, 1fr);
  }
}
"""
    )
