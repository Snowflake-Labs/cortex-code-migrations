# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0

"""Render Amazon Redshift SYS_QUERY_HISTORY workload-insights HTML.

Redshift records no application name, so the artifact's `apps` rows carry per-database
counts and the shared `wi-chart-apps` series plots databases for this dialect.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from teradata_workload_insights import (
    _duration_section,
    _timeline_section,
    teradata_workload_insights_css,
)
from workload_insights_common import (
    _BUCKET_COLORS,
    _chart,
    _classification_section,
    _esc,
    _fmt_day,
    _fmt_duration,
    _fmt_int,
    _fmt_pct,
    _kpis,
    _num,
    _section,
    _table,
    _text,
    render_empty_analysis_pane,
    render_extract_pane,
)

_REDSHIFT_EXTRACT_SQL = """UNLOAD (
'SELECT
    query_id,
    username,
    database_name,
    query_type,
    status,
    start_time,
    end_time,
    elapsed_time,
    returned_rows
 FROM sys_query_history
 WHERE user_id > 1'
)
TO 's3://<bucket>/snowconvert/redshift_telemetry_'
IAM_ROLE '<role-arn>'
CSV
HEADER
PARALLEL OFF;
"""


def _header() -> str:
    return """
<header class="wi-header">
  <h1>Query Logs Analysis</h1>
  <p class="wi-notice"><strong>Disclaimer:</strong> This report uses metadata only;
  no SQL text or error messages are read, stored, or shown. The extract contains
  no query_text, error_message, or user_query_hash.</p>
  <p class="wi-blurb">Insights from the Amazon Redshift query logs extract
  provided for this project.</p>
</header>"""


def _summary(payload: Mapping[str, Any]) -> str:
    summary = payload["summary"]
    databases = ", ".join(_esc(item) for item in summary.get("databases", []))
    day_count = len(payload["daily"])
    day_word = "day" if day_count == 1 else "days"
    return f"""
<div class="wi-summary">
  <div><strong>Database</strong><br>{databases or "Not available"}</div>
  <div><strong>Capture window</strong><br>{_fmt_day(summary.get("first_seen"))}
    &ndash; {_fmt_day(summary.get("last_seen"))} &middot; {day_count} {day_word}</div>
  <div><strong>Capture filters</strong><br>{_text(summary.get("capture_filters"))}</div>
</div>"""


def _users_section(payload: Mapping[str, Any]) -> str:
    rows = [
        [
            f"<strong>{_esc(row.get('user'))}</strong>",
            _fmt_int(row.get("executions")),
            _fmt_pct(row.get("pct")),
        ]
        for row in payload["users"]
    ]
    body = f"""
<div class="wi-grid-2">
  <div class="wi-card"><h3>Top databases (database_name)</h3>
    {_chart("wi-chart-apps")}</div>
  <div class="wi-card"><h3>Top users (username)</h3>
    {_chart("wi-chart-users")}</div>
</div>
<div class="wi-card"><h3>User context</h3>
  {_table(["User", "Requests", "% share"], rows)}
</div>"""
    return _section("Users", body)


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
            _fmt_int(row.get("rows")) if row.get("rows") is not None else "",
        ]
        for row in long_running.get("top", [])
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
than {threshold.removeprefix("&gt; ").lower()} &mdash; {_fmt_pct(long_running.get("pct_of_executions"))} of the
captured workload.</p>
<div class="wi-stat-grid">{band_tiles}</div>
<div class="wi-card"><h3>Long executions ({threshold}) by statement type</h3>
  {_chart("wi-chart-long")}</div>
<div class="wi-card"><h3>Longest captured executions &mdash; top 10 of
{_fmt_int(total)} past {threshold.removeprefix("&gt; ").lower()}</h3>
  <div class="wi-long-table">
    {_table(["#", "Duration", "Statement", "User", "Database", "Rows returned"], rows)}
  </div>
</div>"""
    return _section(f"Long-running query analysis ({threshold})", body)


def _schema_correlation_section(payload: Mapping[str, Any]) -> str:
    rows = [
        [
            f"<strong>{_esc(row.get('user'))}</strong>",
            _fmt_int(row.get("executions")),
            _fmt_pct(row.get("pct")),
            ", ".join(_esc(database) for database in row.get("databases", []))
            or "None recorded",
        ]
        for row in payload["schema_correlation"]
    ]
    return _section(
        "Schema &harr; workload correlation",
        '<div class="wi-card"><h3>Databases seen per user (database_name)</h3>'
        + _table(["User", "Requests", "% share", "Databases used"], rows)
        + "</div>",
    )


def _errors_section(payload: Mapping[str, Any]) -> str:
    errors = payload["errors"]
    total = sum(_num(row.get("count")) for row in errors.get("outcome_mix", []))
    completed = next(
        (
            _num(row.get("count"))
            for row in errors.get("outcome_mix", [])
            if str(row.get("outcome", "")).lower() == "success"
        ),
        max(0, total - _num(errors.get("count"))),
    )
    body = f"""
<div class="wi-grid-2">
  <div class="wi-card"><h3>Error counts</h3>
    <div class="wi-tiles">
      <div class="wi-tile"><div class="wi-tile-value" style="color:#D9534F">{_fmt_int(errors.get("count"))}</div>
        <div class="wi-tile-label">Failed executions</div>
        <div class="wi-tile-sub">{_fmt_pct(errors.get("pct_of_executions"))} of requests</div></div>
      <div class="wi-tile"><div class="wi-tile-value" style="color:#2E9E64">{_fmt_int(completed)}</div>
        <div class="wi-tile-label">Completed executions</div></div>
    </div>
  </div>
  <div class="wi-card"><h3>Request outcome mix</h3>
    {_chart("wi-chart-event-mix")}</div>
</div>"""
    return _section("Errors", body)


def _how_to() -> str:
    return f"""
<h2 class="wi-how-to-title">How to get a query logs extract</h2>
<div class="journey-grid wi-how-to">
  <div class="journey-card wi-step"><div class="journey-badge">1</div>
    <div class="journey-card-body"><h3>Export the query history</h3>
      <p>Run this from a SQL client or the Redshift Query Editor. Redshift keeps
      <code>SYS_QUERY_HISTORY</code> for only <strong>7 days</strong>, so one
      export covers at most the last week. For a longer window, schedule the
      same <code>UNLOAD</code> to run at least weekly or enable Redshift's
      AWS-native system-view stream.</p>
      <p class="wi-notice"><strong>Have a DBA review and run this.</strong>
      Redshift system views show only the current user's activity unless the
      account is a SUPERUSER or holds <code>SYSLOG ACCESS UNRESTRICTED</code>,
      so run by anyone else the export succeeds and silently covers one user.
      The <code>UNLOAD</code> also writes to an S3 bucket under an IAM role
      &mdash; both belong to whoever administers the cluster.</p>
      <p>The nine columns below are the whole extract: no query text, no error
      messages, no query hashes. Restrict access to the user and database names
      on disk, and delete the files after ingest.</p>
      <div class="wi-script-actions"><button type="button" class="wi-copy-btn"
        data-wi-copy="wi-redshift-extract-sql">Copy</button></div>
      <pre id="wi-redshift-extract-sql">{_esc(_REDSHIFT_EXTRACT_SQL)}</pre></div></div>
  <div class="journey-card wi-step"><div class="journey-badge">2</div>
    <div class="journey-card-body"><h3>Re-run the assessment, then regenerate this report</h3>
      <pre>scai assessment workload-insights --input /path/to/querylogs.csv</pre>
      <p>Repeat <code>--input</code> to merge split exports.</p></div></div>
</div>
<h2 class="wi-how-to-title">What an extract adds to this report</h2>
<ul class="wi-unlocks">
  <li>Window, databases, execution counts, duration mix, statement types, users,
  long-runners, and failures</li>
</ul>"""


def render_redshift_workload_insights_extract_html() -> str:
    """Render Redshift extract instructions for the Extract Log tab."""
    return render_extract_pane(_how_to())


def render_redshift_workload_insights_tab_html(
    payload: Mapping[str, Any] | None,
) -> str:
    """Render inner Redshift Workload Insights HTML from artifact values."""
    if not payload or not payload.get("found"):
        return render_empty_analysis_pane(_header())
    return f"""<div id="workload-insights-report" class="wi-pane" v-pre>
{_header()}
{_summary(payload)}
{_kpis(payload)}
{_duration_section(payload)}
{_timeline_section(payload)}
{_classification_section(payload)}
{_users_section(payload)}
{_long_running_section(payload)}
{_schema_correlation_section(payload)}
{_errors_section(payload)}
</div>"""


def redshift_workload_insights_css() -> str:
    """Return shared Teradata-layout styles for Redshift."""
    return teradata_workload_insights_css()
