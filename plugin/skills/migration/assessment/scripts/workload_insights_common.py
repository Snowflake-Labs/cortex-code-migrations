# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0

"""Shared schema-v3 workload-insights loading, formatting, charts, and styles."""

from __future__ import annotations

import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

_SCHEMA_VERSION = 3
_SOURCE_DIALECTS = {
    ("extended_events", "sqlserver"),
    ("dbql", "teradata"),
}
_MAPPING_FIELDS = ("summary", "percentiles", "long_running", "errors")
_SEQUENCE_FIELDS = (
    "kpis",
    "duration_histogram",
    "daily",
    "statement_mix",
    "statement_groups",
    "apps",
    "users",
    "connection_context",
    "schema_correlation",
)
_COLORS = [
    "#5B98FF",
    "#F4BE5D",
    "#E95240",
    "#6FD8B7",
    "#9F88FF",
    "#6FD3FC",
    "#DA8FEB",
]
# Duration buckets read fastest-to-slowest, so the strip runs green to red in the
# same order the histogram lists them. Six entries, because Teradata buckets an
# hour band the SQL Server histogram has no equivalent for; without the sixth the
# index wrapped and painted the slowest bucket the fastest bucket's green. The
# first five are what SQL Server's five buckets keep using.
_BUCKET_COLORS = [
    "#2E9E64",
    "#1E6FD9",
    "#F0B429",
    "#E8843C",
    "#D9534F",
    "#66000E",
]


def is_sql_server(source_dialect: str) -> bool:
    """Return whether the multi-report dialect token is SQL Server."""
    return source_dialect == "Transact"


def is_workload_insights_dialect(source_dialect: str) -> bool:
    """Return whether the multi-report dialect has a renderer."""
    return source_dialect in {"Transact", "Teradata"}


def _is_mapping_sequence(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(row, dict) for row in value)


def load_workload_insights(path: Path) -> Optional[dict[str, Any]]:
    """Load a strict schema-v3 artifact from a supported source/dialect pair."""
    try:
        with Path(path).open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"Warning: Could not load workload insights data: {exc}", file=sys.stderr)
        return None

    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != _SCHEMA_VERSION
        or (payload.get("source"), payload.get("source_dialect"))
        not in _SOURCE_DIALECTS
    ):
        print(
            "Warning: Could not load workload insights data: unsupported schema or source",
            file=sys.stderr,
        )
        return None

    valid = all(isinstance(payload.get(field), dict) for field in _MAPPING_FIELDS)
    valid = valid and all(
        _is_mapping_sequence(payload.get(field)) for field in _SEQUENCE_FIELDS
    )
    percentiles = payload.get("percentiles")
    daily = payload.get("daily")
    schema_correlation = payload.get("schema_correlation")
    long_running = payload.get("long_running")
    errors = payload.get("errors")
    valid = (
        valid
        and isinstance(percentiles, dict)
        and _is_mapping_sequence(percentiles.get("rows"))
        and all(_is_mapping_sequence(row.get("buckets")) for row in daily)
        and all(
            isinstance(row.get("databases"), list)
            and all(isinstance(database, str) for database in row["databases"])
            for row in schema_correlation
        )
        and isinstance(long_running, dict)
        and all(
            _is_mapping_sequence(long_running.get(field))
            for field in ("bands", "by_type", "top")
        )
    )
    valid = (
        valid
        and isinstance(errors, dict)
        and _is_mapping_sequence(errors.get("outcome_mix"))
    )
    if not valid:
        print(
            "Warning: Could not load workload insights data: invalid schema shape",
            file=sys.stderr,
        )
        return None
    return payload


def _esc(value: Any) -> str:
    return html.escape(str(value)) if value is not None else ""


def _text(value: Any) -> str:
    return _esc(value).replace("·", "&middot;")


def _num(value: Any, default: float = 0.0) -> float:
    """Coerce a JSON number; missing, null, or junk becomes default."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return _esc(value)


def _fmt_number(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return _esc(value)


def _fmt_pct(value: Any) -> str:
    return f"{_fmt_number(value)}%"


def _fmt_day(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc)
        return parsed.strftime("%b %d, %Y")
    except (TypeError, ValueError):
        return _esc(value) or "Not available"


def _day_tick(value: Any) -> str:
    """Format a capture day as a short axis tick (month and year live in the title)."""
    day = _parse_day(value)
    return f"{day:%d %b}" if day else (_esc(value) or "")


def _day_axis_title(daily: Sequence[Mapping[str, Any]]) -> str:
    days = [day for day in (_parse_day(row.get("day")) for row in daily) if day]
    if not days:
        return "Day of capture"
    first, last = min(days), max(days)
    if (first.year, first.month) == (last.year, last.month):
        span = f"{first:%B %Y}"
    elif first.year == last.year:
        span = f"{first:%B} – {last:%B} {last.year}"
    else:
        span = f"{first:%B %Y} – {last:%B %Y}"
    return f"Day of capture ({span})"


def _parse_day(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _fmt_duration(value: Any) -> str:
    try:
        milliseconds = float(value)
    except (TypeError, ValueError):
        return _esc(value)
    if milliseconds >= 3_600_000:
        return f"{milliseconds / 3_600_000:.1f} hr"
    if milliseconds >= 60_000:
        return f"{milliseconds / 60_000:.1f} min"
    return f"{milliseconds:,.1f} ms"


def _safe_json(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return (
        serialized.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _kpis(payload: Mapping[str, Any]) -> str:
    def format_value(row: Mapping[str, Any]) -> str:
        value = row.get("value")
        if row.get("format") == "pct":
            return _fmt_pct(value)
        if row.get("format") == "duration_ms":
            return _fmt_duration(value)
        return _fmt_int(value)

    cards = [(_esc(row.get("label")), format_value(row)) for row in payload["kpis"]]
    body = "".join(
        f'<div class="wi-kpi"><span class="wi-kpi-value">{value}</span>'
        f'<span class="wi-kpi-label">{label}</span></div>'
        for label, value in cards
    )
    return f'<div class="wi-kpis">{body}</div>'


def _section(title: str, body: str) -> str:
    return f"""
<section class="wi-section">
  <h2>{title}</h2>
  {body}
</section>"""


def _kpi_value(payload: Mapping[str, Any], key: str) -> Any:
    return next(
        (row.get("value") for row in payload["kpis"] if row.get("key") == key),
        0,
    )


def _chart(chart_id: str, *, tall: bool = False) -> str:
    class_name = "wi-chart-frame wi-chart-frame-tall" if tall else "wi-chart-frame"
    return f'<div class="{class_name}"><canvas id="{chart_id}"></canvas></div>'


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    head = "".join(f"<th>{header}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows
    )
    if not body:
        body = (
            f'<tr><td colspan="{len(headers)}" class="wi-empty-row">'
            "No rows were recorded for this section.</td></tr>"
        )
    return (
        '<div class="wi-table-wrap"><table><thead><tr>'
        f"{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def _classification_section(payload: Mapping[str, Any]) -> str:
    mix = payload["statement_mix"]
    mix_total = sum(_num(row.get("executions")) for row in mix)
    rows = [
        [
            _esc(row.get("statement_type")),
            _fmt_int(row.get("executions")),
            _fmt_pct(row.get("pct")),
        ]
        for row in mix
    ]
    body = f"""
<div class="wi-grid-2">
  <div class="wi-card"><h3>Statement type distribution</h3>
    {_table(["Statement type", "Count", "% share"], rows)}
  </div>
  <div class="wi-card"><h3>Statement types ({_fmt_int(mix_total)} executions)</h3>
    {_chart("wi-chart-types")}
  </div>
</div>"""
    return _section("Query type &amp; workload classification", body)


def _chart_data(payload: Mapping[str, Any]) -> dict[str, Any]:
    histogram = payload["duration_histogram"]
    daily = payload["daily"]
    statement_mix = payload["statement_mix"]
    statement_groups = payload["statement_groups"]
    apps = payload["apps"]
    users = payload["users"]
    long_by_type = payload["long_running"]["by_type"]
    outcome_mix = payload["errors"]["outcome_mix"]
    bucket_labels: list[Any] = []
    for row in daily:
        for bucket in row.get("buckets", []):
            label = bucket.get("bucket")
            if label not in bucket_labels:
                bucket_labels.append(label)
    return {
        "histo": {
            "labels": [row.get("bucket") for row in histogram],
            "values": [row.get("executions") for row in histogram],
        },
        "dayAxis": _day_axis_title(daily),
        "daily": {
            "labels": [row.get("day") for row in daily],
            "ticks": [_day_tick(row.get("day")) for row in daily],
            "bucketLabels": bucket_labels,
            "bucketValues": [
                [
                    next(
                        (
                            bucket.get("executions")
                            for bucket in row.get("buckets", [])
                            if bucket.get("bucket") == label
                        ),
                        0,
                    )
                    for label in bucket_labels
                ]
                for row in daily
            ],
            "executions": [row.get("executions") for row in daily],
            "errors": [row.get("errors") for row in daily],
        },
        "types": {
            "labels": [row.get("statement_type") for row in statement_mix],
            "values": [row.get("executions") for row in statement_mix],
        },
        "groups": {
            "labels": [row.get("group") for row in statement_groups],
            "values": [row.get("executions") for row in statement_groups],
        },
        "apps": {
            "labels": [row.get("app") for row in apps],
            "values": [row.get("executions") for row in apps],
        },
        "users": {
            "labels": [row.get("user") for row in users],
            "values": [row.get("executions") for row in users],
        },
        "longByType": {
            "labels": [row.get("statement_type") for row in long_by_type],
            "values": [row.get("executions") for row in long_by_type],
        },
        "outcomeMix": {
            "labels": [row.get("outcome") for row in outcome_mix],
            "values": [row.get("count") for row in outcome_mix],
        },
    }


def _copy_script_js() -> str:
    """Copy handler for the empty-state capture script, same pattern as DMV SQL."""
    return """
(function() {
document.addEventListener("click", function(event) {
  const button = event.target && event.target.closest && event.target.closest("[data-wi-copy]");
  if (!button) return;
  const source = document.getElementById(button.getAttribute("data-wi-copy"));
  if (!source) return;
  const text = source.innerText || source.textContent || "";
  const original = button.textContent;
  const flash = function() {
    button.textContent = "Copied";
    setTimeout(function() { button.textContent = original; }, 1500);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(flash).catch(function() {
      const area = document.createElement("textarea");
      area.value = text;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      document.body.removeChild(area);
      flash();
    });
  }
});
})();
"""


def workload_insights_chart_js(payload: Optional[Mapping[str, Any]]) -> str:
    """Return chart bootstrap JavaScript for emission after the Vue mount."""
    if not payload or not payload.get("found"):
        return _copy_script_js()
    data = _safe_json(_chart_data(payload))
    colors = _safe_json(_COLORS)
    return f"""
(function() {{
const D={data};
const PAL={colors};
const axes={{color:"#64748B"}};
const barOptions={{indexAxis:"y",responsive:true,maintainAspectRatio:false,
  plugins:{{legend:{{display:false}}}},
  scales:{{x:{{beginAtZero:true,grid:{{color:"#E2E8F0"}},...axes}},
  y:{{grid:{{display:false}}}}}}}};
const histogramDisplay=D.histo.values.map(value => value === 0 ? null : value);
const dayScales=(yTitle,stacked=false) => ({{
  x:{{stacked:stacked,ticks:{{maxRotation:60,font:{{size:9}}}},grid:{{display:false}},
  title:{{display:true,text:D.dayAxis,...axes}}}},
  y:{{stacked:stacked,beginAtZero:true,grid:{{color:"#E2E8F0"}},
  title:{{display:true,text:yTitle,...axes}}}}}});
window.renderWorkloadInsightsCharts=function() {{
const charts=window.__workloadInsightsCharts || {{}};
if(Object.keys(charts).length) {{
  Object.values(charts).forEach(chart => chart.resize());
  return;
}}
const make=(id,config) => {{
  const canvas=document.getElementById(id);
  if(canvas) charts[id]=new Chart(canvas,config);
}};
make("wi-chart-histogram",{{
  type:"bar",data:{{labels:D.histo.labels,datasets:[{{label:"Executions",
  data:histogramDisplay,backgroundColor:PAL,borderRadius:4}}]}},
  options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},
  scales:{{x:{{grid:{{display:false}}}},y:{{type:"logarithmic",min:0.8,
  title:{{display:true,text:"Executions (log scale)",...axes}}}}}}}}}});
make("wi-chart-daily",{{
  type:"bar",data:{{labels:D.daily.ticks,datasets:D.daily.bucketLabels.map(
  (label,index) => ({{label:label,data:D.daily.bucketValues.map(row => row[index] || 0),
  backgroundColor:PAL[index % PAL.length],stack:"s"}}))}},
  options:{{responsive:true,maintainAspectRatio:false,
  plugins:{{legend:{{position:"top",labels:{{boxWidth:12,padding:10}}}}}},
  scales:dayScales("Executions",true)}}}});
make("wi-chart-timeline",{{
  type:"line",data:{{labels:D.daily.ticks,datasets:[
  {{label:"Executions",data:D.daily.executions,borderColor:PAL[0],
  backgroundColor:"rgba(91,152,255,.15)",fill:true,tension:.3}},
  {{label:"Errors",data:D.daily.errors,borderColor:PAL[2],
  backgroundColor:"rgba(233,82,64,.12)",fill:true,tension:.3}}]}},
  options:{{responsive:true,maintainAspectRatio:false,
  plugins:{{legend:{{position:"bottom",labels:{{boxWidth:12,padding:14}}}}}},
  scales:dayScales("Events")}}}});
for(const [id,src] of [["wi-chart-types",D.types],["wi-chart-event-mix",D.outcomeMix]]){{
  const total=src.values.reduce((sum,value) => sum + (value || 0),0);
  const labels=src.labels.map((label,index) => total
    ? `${{label}} (${{(100*(src.values[index] || 0)/total).toFixed(1)}}%)`
    : label);
  make(id,{{type:"doughnut",
  data:{{labels:labels,datasets:[{{data:src.values,backgroundColor:PAL,
  borderColor:"#fff",borderWidth:2}}]}},
  options:{{responsive:true,maintainAspectRatio:false,cutout:"55%",
  plugins:{{legend:{{position:"bottom",
  labels:{{boxWidth:11,padding:9,font:{{size:11}}}}}}}}}}}});
}}
make("wi-chart-apps",{{
  type:"bar",data:{{labels:D.apps.labels,datasets:[{{data:D.apps.values,
  backgroundColor:PAL[0],borderRadius:4}}]}},options:barOptions}});
make("wi-chart-users",{{
  type:"bar",data:{{labels:D.users.labels,datasets:[{{data:D.users.values,
  backgroundColor:PAL[1],borderRadius:4}}]}},options:barOptions}});
make("wi-chart-long",{{
  type:"bar",data:{{labels:D.longByType.labels,datasets:[{{data:D.longByType.values,
  backgroundColor:PAL,borderRadius:4}}]}},
  options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},
  scales:{{x:{{grid:{{display:false}}}},y:{{beginAtZero:true,grid:{{color:"#E2E8F0"}},
  title:{{display:true,text:"Count",...axes}}}}}}}}}});
window.__workloadInsightsCharts=charts;
}};
}})();"""


def workload_insights_css() -> str:
    """Return tab-scoped Workload Insights styles."""
    return """
#workload-insights-report { color: #102E46; }
#workload-insights-report .wi-header h1 {
  margin: 0 0 12px; font-size: 1.875rem; font-weight: 800; color: #102E46;
}
#workload-insights-report .wi-notice {
  color: #374151; background: #F3F4F6; border: 1px solid #D1D5DB;
  border-left: 4px solid #9CA3AF; border-radius: 6px; padding: 10px 12px;
  font-size: 0.78rem; line-height: 1.45; margin: 0 0 12px;
}
#workload-insights-report .wi-blurb { color: #64748B; font-size: 1.1rem; margin: 0; }
#workload-insights-report .wi-summary {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 16px; margin: 24px 0; color: #64748B; font-size: 0.85rem;
}
#workload-insights-report .wi-kpis {
  display: grid; grid-template-columns: repeat(5, 1fr); border: 1px solid #E2E8F0;
  border-radius: 12px; overflow: hidden;
}
#workload-insights-report .wi-kpi {
  display: flex; flex-direction: column; text-align: center; padding: 18px 10px;
  border-right: 1px solid #E2E8F0;
}
#workload-insights-report .wi-kpi:last-child { border-right: 0; }
#workload-insights-report .wi-kpi-value { font-size: 1.35rem; font-weight: 800; }
#workload-insights-report .wi-kpi-label {
  color: #64748B; font-size: 0.68rem; text-transform: uppercase;
}
#workload-insights-report .wi-section { margin: 44px 0; }
#workload-insights-report .wi-section h2 {
  font-size: 1.5rem; font-weight: 700; color: #102E46; margin: 0 0 20px;
}
#workload-insights-report .wi-insights {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 14px; margin-bottom: 20px;
}
#workload-insights-report .wi-insight {
  border: 1px solid #E2E8F0; border-radius: 10px; padding: 18px 16px;
  text-align: center; min-width: 0;
}
#workload-insights-report .wi-insight-value {
  font-size: 1.75rem; font-weight: 900; line-height: 1; margin-bottom: 5px;
}
#workload-insights-report .wi-insight-label {
  color: #64748B; font-size: 0.7rem; text-transform: uppercase;
  letter-spacing: 0.4px;
}
#workload-insights-report .wi-insight-sub {
  color: #64748B; font-size: 0.72rem; margin-top: 4px;
}
#workload-insights-report .wi-tiles {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px;
}
#workload-insights-report .wi-tile {
  background: #F8FAFC; border-radius: 8px; padding: 16px; text-align: center;
  min-width: 0;
}
#workload-insights-report .wi-tile-value { font-size: 1.9rem; font-weight: 800; }
#workload-insights-report .wi-tile-label {
  color: #64748B; font-size: 0.75rem; margin-top: 4px;
}
#workload-insights-report .wi-tile-sub { color: #64748B; font-size: 0.7rem; }
#workload-insights-report .wi-card {
  border: 1px solid #E2E8F0; border-radius: 10px; padding: 20px 22px;
  margin-bottom: 16px; min-width: 0;
}
#workload-insights-report .wi-card-centered {
  max-width: 85%; margin-left: auto; margin-right: auto;
}
#workload-insights-report .wi-card h3 {
  color: #64748B; font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.6px; margin: 0 0 14px;
}
#workload-insights-report .wi-grid-2 {
  display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px;
}
#workload-insights-report .wi-chart-frame { position: relative; height: 290px; }
#workload-insights-report .wi-chart-frame-tall { height: 340px; }
#workload-insights-report .wi-callout,
#workload-insights-report .wi-danger-callout,
#workload-insights-report .wi-empty-notice {
  border-radius: 8px; padding: 13px 17px; margin: 0 0 18px;
  font-size: 0.83rem; line-height: 1.55;
}
#workload-insights-report .wi-callout { background: #FEF9E7; border-left: 4px solid #FF9F36; }
#workload-insights-report .wi-danger-callout { background: #FDEDEC; border-left: 4px solid #D9534F; }
#workload-insights-report .wi-empty-notice { background: #F0F9FF; border: 1px solid #BAE6FD; }
#workload-insights-report .wi-stat-grid {
  display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px;
  margin-bottom: 16px;
}
#workload-insights-report .wi-stat-grid-2 { grid-template-columns: repeat(2, 1fr); }
#workload-insights-report .wi-stat {
  display: flex; flex-direction: column; text-align: center; padding: 18px;
  border: 1px solid #E2E8F0; border-radius: 10px;
}
#workload-insights-report .wi-stat strong { font-size: 1.7rem; }
#workload-insights-report .wi-stat small { color: #64748B; }
#workload-insights-report .wi-table-wrap {
  overflow-x: auto; border: 1px solid #E2E8F0; border-radius: 8px;
}
#workload-insights-report table { width: 100%; border-collapse: collapse; font-size: 0.83rem; }
#workload-insights-report th {
  padding: 10px 13px; text-align: left; background: #F8FAFC; white-space: nowrap;
}
#workload-insights-report td { padding: 9px 13px; border-top: 1px solid #E2E8F0; }
#workload-insights-report td:not(:first-child),
#workload-insights-report th:not(:first-child) { text-align: right; }
#workload-insights-report .wi-long-table th:last-child,
#workload-insights-report .wi-long-table td:last-child { text-align: left; }
#workload-insights-report .wi-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
#workload-insights-report .wi-how-to-title {
  font-size: 1.35rem; font-weight: 700; color: #102E46; margin: 40px 0 16px;
}
#workload-insights-report .wi-how-to { margin: 0; }
#workload-insights-report .wi-step { align-items: flex-start; cursor: default; }
#workload-insights-report .wi-step:hover {
  border-color: #E2E8F0; box-shadow: none; transform: none;
}
#workload-insights-report .wi-step pre {
  white-space: pre-wrap; overflow-wrap: anywhere; background: #F8FAFC;
  border-radius: 6px; padding: 10px 12px; margin: 10px 0 0;
  font-size: 0.82rem; color: #102E46;
}
#workload-insights-report .wi-howto-sql { margin-top: 12px; }
#workload-insights-report .wi-script-actions { display: flex; gap: 8px; margin: 10px 0 8px; }
#workload-insights-report .wi-copy-btn {
  font: inherit; font-size: 0.74rem; font-weight: 600; color: #0369A1;
  background: #FFFFFF; border: 1px solid #BAE6FD; border-radius: 6px;
  padding: 5px 11px; cursor: pointer;
}
#workload-insights-report .wi-copy-btn:hover { background: #F0F9FF; }
#workload-insights-report .wi-dba-note {
  color: #7F2A26; background: #FDEDEC; border: 1px solid #F1C4C1;
  border-left: 4px solid #D9534F; border-radius: 6px; padding: 10px 12px;
  font-size: 0.85rem; line-height: 1.55; margin: 14px 0 0;
}
#workload-insights-report .wi-config-lead {
  color: #64748B; font-size: 0.88rem; line-height: 1.55; margin: 12px 0 14px;
}
#workload-insights-report .wi-config {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 0 0 12px;
}
#workload-insights-report .wi-config-card {
  background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 10px; padding: 14px 16px;
}
#workload-insights-report .wi-config-careful {
  background: #FEF9E7; border-color: #FDE68A;
}
#workload-insights-report .wi-config-card h4 {
  margin: 0 0 8px; font-size: 0.82rem; font-weight: 700; color: #102E46;
}
#workload-insights-report .wi-config-card ul {
  margin: 0; padding-left: 18px; color: #475569; font-size: 0.8rem; line-height: 1.55;
}
#workload-insights-report .wi-config-card li { margin: 0 0 8px; }
#workload-insights-report .wi-config-card li:last-child { margin-bottom: 0; }
#workload-insights-report .wi-howto-sql summary {
  cursor: pointer; font-size: 0.85rem; font-weight: 600; color: #11567F;
}
#workload-insights-report .wi-howto-sql pre {
  max-height: 320px; overflow: auto; white-space: pre; line-height: 1.5;
}
#workload-insights-report .wi-unlocks {
  margin: 0; padding-left: 22px; list-style: disc outside;
  color: #64748B; font-size: 0.9rem; line-height: 1.9;
}
@media (max-width: 1000px) {
  #workload-insights-report .wi-kpis { grid-template-columns: repeat(2, 1fr); }
  #workload-insights-report .wi-grid-2,
  #workload-insights-report .wi-stat-grid,
  #workload-insights-report .wi-config { grid-template-columns: 1fr; }
}
"""
