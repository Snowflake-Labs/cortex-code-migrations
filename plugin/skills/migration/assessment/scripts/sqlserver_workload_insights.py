# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0

"""Render SQL Server workload-insights HTML."""

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
)

def _header() -> str:
    return """
<header class="wi-header">
  <h1>Discovery</h1>
  <p class="wi-notice"><strong>Disclaimer:</strong> Captured Extended Events data,
  including SQL statement text, is used for <strong>reporting only</strong>.
  Statement text is read only to classify the type of query
  (for example SELECT, Call, or INSERT). It is <strong>not stored</strong> in
  the assessment artifact and is <strong>not shown</strong> in this report
  &mdash; no query text, parameters, or error messages appear here.</p>
  <p class="wi-blurb">Insights from the SQL Server <strong>Extended Events</strong>
  capture provided for this project. Each row in the capture is
  <strong>one statement execution</strong> &mdash; not an aggregate &mdash; so durations
  and counts describe individual runs rather than averaged query shapes.</p>
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
    empty = (
        '<p class="wi-empty-notice">No duration buckets were recorded.</p>'
        if not histogram
        else ""
    )
    body = f"""
{empty}
<div class="wi-insights">{"".join(insights)}</div>
<div class="wi-card wi-card-centered"><h3>Duration bucket distribution (log scale)</h3>
  {_chart("wi-chart-histogram")}
</div>
<p class="wi-callout"><strong>Capture floor:</strong> the session records nothing below
0.5 s, so faster statements are absent by design. Read the sub-second share as a
floor, not a total.</p>"""
    return _section("Query performance histogram &mdash; duration buckets", body)


def _timeline_section(payload: Mapping[str, Any]) -> str:
    daily = payload["daily"]
    peak = max(daily, key=lambda row: row.get("executions", 0), default={})
    quiet = min(daily, key=lambda row: row.get("executions", 0), default={})
    executions = _num(_kpi_value(payload, "user_executions"))
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
            f"<strong>{_esc(row.get('user'))}</strong> &middot; "
            f'<span class="wi-mono">{_esc(row.get("app"))}</span>',
            f"{_fmt_int(row.get('executions'))} ({_fmt_pct(row.get('pct'))})",
        ]
        for row in payload["connection_context"]
    ]
    body = f"""
<div class="wi-grid-2">
  <div class="wi-card"><h3>Top applications (client_app_name)</h3>
    {_chart("wi-chart-apps")}</div>
  <div class="wi-card"><h3>Top users (username)</h3>
    {_chart("wi-chart-users")}</div>
</div>
<div class="wi-card"><h3>User and connection context</h3>
  {_table(["User &middot; application", "Captured executions"], rows)}
</div>"""
    return _section("Applications &amp; users", body)


def _long_running_section(payload: Mapping[str, Any]) -> str:
    long_running = payload["long_running"]
    total = long_running.get("total", 0)
    rows = [
        [
            _fmt_int(row.get("rank")),
            f"<strong>{_fmt_duration(row.get('duration_ms'))}</strong>",
            _fmt_number(row.get("cpu_ms")),
            f"{_num(row.get('cpu_share')) * 100:.0f}%",
            _fmt_int(row.get("reads")),
            _fmt_int(row.get("writes")),
            _fmt_int(row.get("rows")),
            _esc(row.get("statement_type")),
        ]
        for row in long_running.get("top", [])
    ]
    headers = ["#", "Duration", "CPU ms", "CPU share", "Reads", "Writes", "Rows", "Statement"]
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


def _errors_section(payload: Mapping[str, Any]) -> str:
    errors = payload["errors"]
    total_events = _kpi_value(payload, "total_events")
    error_rate = _kpi_value(payload, "error_rate_pct")
    body = f"""
<div class="wi-grid-2">
  <div class="wi-card"><h3>Severity overview</h3>
    <div class="wi-tiles">
      <div class="wi-tile">
        <div class="wi-tile-value" style="color:#D9534F">{_fmt_int(errors.get("count"))}</div>
        <div class="wi-tile-label">Captured error events</div>
        <div class="wi-tile-sub">severity &ge; 11</div>
      </div>
      <div class="wi-tile">
        <div class="wi-tile-value" style="color:#F0B429">{_fmt_pct(error_rate)}</div>
        <div class="wi-tile-label">Trace error ratio</div>
        <div class="wi-tile-sub">{_fmt_int(errors.get("count"))} errors / {_fmt_int(total_events)} events</div>
      </div>
    </div>
  </div>
  <div class="wi-card"><h3>Captured event mix</h3>
    {_chart("wi-chart-event-mix")}</div>
</div>"""
    return _section("Error &amp; exception analysis", body)


_SESSION_SQL = """-- SUGGESTED STARTER SCRIPT — review every value below with your DBA
-- before you run it. These are defaults that fit a typical host, not
-- a guarantee for this instance. This capture uses CPU and disk; it
-- is not free. Needs permission to create a server event session.
--
-- REQUIRED before execute:
--   * Replace YourDatabase in all three database_name predicates with
--     the one database you want to profile.
--   * Replace &lt;dedicated volume&gt; in the target filename with a path on
--     a volume that is not a data or log disk.
--   * If a session named WorkloadReport_XE already exists, change that
--     name in the CREATE statement and in the commented START / STOP
--     statements.
--   * CREATE only defines the session. Uncomment and run START when you
--     want capture to begin.
--
-- Review and change as needed (suggested values):
--   Session name            WorkloadReport_XE
--   Duration threshold      500000 microseconds (0.5 s). Raise to write
--                           less; lowering it costs more CPU and disk.
--   Filters                 one database, is_system = 0, no SSMS /
--                           telemetry, error severity >= 11. Removing
--                           the database predicate traces the instance.
--   filename                path + base name on a dedicated volume, not
--                           data or log disks.
--   max_file_size           200 MB per file
--   max_rollover_files      5  (1 GB cap at the default file size).
--                           Confirm more than that is free.
--   MAX_MEMORY              8192 KB. Keep this from competing with the
--                           buffer pool.
--   MAX_DISPATCH_LATENCY    30 seconds
--   STARTUP_STATE           OFF (session does not return after a
--                           restart; set ON only if you want it to)
--   MEMORY_PARTITION_MODE   Not set, which is right for a typical host.
--                           On a busy many-core server, partitioning
--                           buffers PER_CPU reduces contention when many
--                           queries finish at once. It splits MAX_MEMORY
--                           across cores, so raise MAX_MEMORY (16-32 MB)
--                           if you turn it on — 8192 KB spread over many
--                           cores drops more events.
--
-- Do not change:
--   The three events and their ACTION lists, or this report loses
--   columns. EVENT_RETENTION_MODE = ALLOW_SINGLE_EVENT_LOSS — do not
--   switch to NO_EVENT_LOSS (that can stall user queries).

-- Create the session
CREATE EVENT SESSION [WorkloadReport_XE] ON SERVER

-- Event 1: ad-hoc SQL statements completed
ADD EVENT sqlserver.sql_statement_completed(
    ACTION(
        sqlserver.database_name,
        sqlserver.username,
        sqlserver.client_app_name,
        sqlserver.client_hostname,
        sqlserver.session_id
    )
    WHERE (
        [duration] &gt;= 500000 -- microseconds, so 0.5 s
        AND [sqlserver].[is_system] = 0
        AND [sqlserver].[database_name] = N'YourDatabase'
        AND [sqlserver].[client_app_name] &lt;&gt; N'SQLServerCEIP'
        AND [sqlserver].[username] &lt;&gt; N'NT SERVICE\\SQLTELEMETRY'
        AND [sqlserver].[client_app_name] &lt;&gt; N'Microsoft SQL Server Management Studio'
    )
),

-- Event 2: stored procedure and RPC calls completed
ADD EVENT sqlserver.rpc_completed(
    ACTION(
        sqlserver.database_name,
        sqlserver.username,
        sqlserver.client_app_name,
        sqlserver.client_hostname,
        sqlserver.session_id
    )
    WHERE (
        [duration] &gt;= 500000
        AND [sqlserver].[is_system] = 0
        AND [sqlserver].[database_name] = N'YourDatabase'
        AND [sqlserver].[client_app_name] &lt;&gt; N'SQLServerCEIP'
        AND [sqlserver].[username] &lt;&gt; N'NT SERVICE\\SQLTELEMETRY'
        AND [sqlserver].[client_app_name] &lt;&gt; N'Microsoft SQL Server Management Studio'
    )
),

-- Event 3: application and query errors
ADD EVENT sqlserver.error_reported(
    ACTION(
        sqlserver.database_name,
        sqlserver.username,
        sqlserver.client_app_name,
        sqlserver.session_id,
        sqlserver.sql_text
    )
    WHERE (
        [severity] &gt;= 11
        AND [sqlserver].[is_system] = 0
        AND [sqlserver].[database_name] = N'YourDatabase'
        AND [sqlserver].[client_app_name] &lt;&gt; N'Microsoft SQL Server Management Studio'
    )
)

-- Target: binary rollover files on disk. Point this at a volume that is
-- not a data or log disk; SQL Server appends its own suffix and .xel.
ADD TARGET package0.event_file(
    SET filename = N'&lt;dedicated volume&gt;\\XETraces\\WorkloadReport_XE',
    max_file_size = (200),   -- MB per file
    max_rollover_files = (5) -- 1 GB total at the default size
)
WITH (
    MAX_MEMORY = 8192 KB,                          -- session RAM cap
    EVENT_RETENTION_MODE = ALLOW_SINGLE_EVENT_LOSS, -- do not change to NO_EVENT_LOSS
    MAX_DISPATCH_LATENCY = 30 SECONDS,             -- flush cadence
    STARTUP_STATE = OFF                            -- does not return after restart
    -- On a busy many-core host, add the line below and raise MAX_MEMORY
    -- to 16-32 MB first:
    -- , MEMORY_PARTITION_MODE = PER_CPU
);
GO

-- CREATE leaves the session stopped. Uncomment and run this to start
-- capture. Nothing is recorded until you do.
--
-- ALTER EVENT SESSION [WorkloadReport_XE] ON SERVER STATE = START;
-- GO

-- After you have collected data for the time you need, copy every .xel
-- file off the server, then run the statement below to stop the session.
-- Leaving it running keeps using CPU and disk. Use the same session name
-- as CREATE / START.
--
-- ALTER EVENT SESSION [WorkloadReport_XE] ON SERVER STATE = STOP;
-- GO"""

_HOW_TO_STEPS = [
    (
        "Start a workload capture on the database",
        "SQL Server keeps no history of past queries, so nothing can be reported "
        "until a capture is running. The script below creates a "
        "<strong>SQL Server Extended Events</strong> session on a single "
        "database; it does not start until you uncomment START. While it runs, "
        "it records each completed user statement and stored-procedure call "
        "that meets the duration filter &mdash; duration, CPU, reads, writes, "
        "rows, application, and user &mdash; plus errors at severity 11 or "
        "higher. Statement text is used only to classify the query type. "
        "Treat it as a starter, not a one-size-fits-all run: change the "
        "settings that do not fit this host. "
        "The three events and their <code>ACTION</code> lists must stay, "
        "or this report loses columns.",
        "",
    ),
    (
        "Let it run while the database handles real traffic",
        "The capture only records what happens after it starts, so leave it on "
        "long enough to be representative &mdash; around 30 days is a good "
        "target, though a shorter window still works. It writes a series of "
        "<code>.xel</code> files; copy all of them off the server when you are "
        "done, <strong>then stop the session</strong> (the stop statement is "
        "at the end of the script, commented out so it does not run with the "
        "start).",
        "",
    ),
    (
        "Re-run the assessment, then regenerate this report",
        "Re-run the assessment and give it the folder or files when the Discovery "
        "step asks for them, or run the command yourself:",
        "scai assessment workload-insights --input /path/to/capture.xel",
    ),
]

_HOW_TO_UNLOCKS = [
    "The capture window, the database covered, and the filters the capture used",
    "Total events, user executions, sub-second share, and error rate",
    "How execution times are distributed across duration buckets",
    "Executions and errors per day across the whole window",
    "The mix of statement types and groups making up the workload",
    "Which applications and users drive the captured work",
    "The longest executions, with CPU, reads, writes, and rows",
]


_HOW_TO_CONFIG = """
<p class="wi-dba-note"><strong>A DBA should own this capture.</strong> Have a DBA
set the values, confirm it is safe to run on this instance, and start it. Watch
the server once it is running &mdash; CPU, disk space, and waits &mdash; and stop
the session if anything degrades.</p>
<p class="wi-config-lead">This capture uses CPU and disk. It is reasonable on a
typical host with the defaults below, but it is <strong>not free</strong> and
it can compete with the database if those knobs are set too aggressively. Do
not switch <code>EVENT_RETENTION_MODE</code> to <code>NO_EVENT_LOSS</code>
&mdash; that can stall user queries.</p>
<div class="wi-config">
  <div class="wi-config-card">
    <h4>You can change these to fit the capture</h4>
    <ul>
      <li><strong>Session name</strong> &mdash; default is <code>WorkloadReport_XE</code>.
      Change it if another session already uses that name; keep the same name
      in the create and start statements.</li>
      <li><strong>Duration threshold</strong> &mdash; default is 0.5 s
      (<code>[duration] &gt;= 500000</code>, in microseconds). Raise it to write
      less; lowering it captures more and costs more CPU and disk.</li>
      <li><strong>Filters</strong> &mdash; default is one database, no system
      work, no SSMS / telemetry, and errors at severity &ge; 11. Tighten or
      loosen as needed. Removing the database predicate traces the whole
      instance and is usually too wide.</li>
    </ul>
  </div>
  <div class="wi-config-card wi-config-careful">
    <h4>Set these carefully &mdash; they affect the database</h4>
    <ul>
      <li><strong><code>filename</code></strong> &mdash; replace
      <code>&lt;dedicated volume&gt;</code> with a path on a volume that has
      space and is not a data or log disk. SQL Server appends its own suffix
      and <code>.xel</code>.</li>
      <li><strong><code>max_file_size</code></strong> (200 MB) and
      <strong><code>max_rollover_files</code></strong> (5) &mdash; together they
      cap disk at 1 GB. Confirm more than that is free before starting. Smaller
      caps use less disk; larger caps keep more history.</li>
      <li><strong><code>MAX_MEMORY</code></strong> (8,192 KB) &mdash; how much
      RAM the session may hold. Raising it buffers more events; leaving it low
      keeps it from competing with the buffer pool.</li>
      <li><strong><code>MAX_DISPATCH_LATENCY</code></strong> (30 seconds) &mdash;
      how soon events flush to disk. Lower it to write sooner; higher it to
      batch more.</li>
      <li><strong><code>STARTUP_STATE</code></strong> (OFF) &mdash; the session
      does not come back after a service restart. Set <code>ON</code> only if
      you want it to resume automatically, and still stop it when the capture
      window ends.</li>
      <li><strong><code>MEMORY_PARTITION_MODE</code></strong> &mdash; not set,
      which is right for a typical host. On a busy many-core server, set
      <code>PER_CPU</code> (commented in the script) to reduce contention when
      many queries finish at once, and raise <code>MAX_MEMORY</code> to
      16&ndash;32 MB first. Leaving 8,192 KB with <code>PER_CPU</code> drops
      more events.</li>
    </ul>
  </div>
</div>"""


def _how_to() -> str:
    session_sql = (
        '<details class="wi-howto-sql"><summary>Show the capture script</summary>'
        '<div class="wi-script-actions">'
        '<button type="button" class="wi-copy-btn" data-wi-copy="wi-session-sql">'
        "Copy</button></div>"
        f'<pre id="wi-session-sql">{_SESSION_SQL}</pre></details>'
    )
    steps = "".join(
        f'<div class="journey-card wi-step"><div class="journey-badge">{number}</div>'
        f'<div class="journey-card-body"><h3>{title}</h3><p>{copy}</p>'
        + (f"<pre>{command}</pre>" if command else "")
        + ((_HOW_TO_CONFIG + session_sql) if number == 1 else "")
        + "</div></div>"
        for number, (title, copy, command) in enumerate(_HOW_TO_STEPS, start=1)
    )
    unlocks = "".join(f"<li>{item}</li>" for item in _HOW_TO_UNLOCKS)
    return f"""
<p class="wi-empty-notice"><strong>No workload capture in this project yet.</strong>
This phase is <strong>optional</strong> &mdash; the rest of the assessment does not
depend on it.</p>
<h2 class="wi-how-to-title">How to capture workload data</h2>
<div class="journey-grid wi-how-to">{steps}</div>
<h2 class="wi-how-to-title">What a capture adds to this report</h2>
<ul class="wi-unlocks">{unlocks}</ul>"""


def render_workload_insights_tab_html(
    payload: Optional[Mapping[str, Any]],
    source_dialect: str = "",
) -> str:
    """Render inner SQL Server Workload Insights HTML from artifact values."""
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
{_errors_section(payload)}
</div>"""

__all__ = ("render_workload_insights_tab_html",)
