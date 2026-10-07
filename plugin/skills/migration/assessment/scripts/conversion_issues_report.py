"""Conversion-issues tab for the AIM assessment report."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path


EMPTY_COPY = (
    "No conversion issues. AIM did not record SSC-EWI issues on in-scope code units."
)
SUPPORT_EMAIL = "aim-support@snowflake.com"
SHARE_FORM_URL = (
    "https://docs.google.com/forms/d/e/1FAIpQLSepvYNbuCp-sE-PCeqG2kWFuGNZjNUHGGI5WW6SLlo8B9_W6w/viewform?usp=dialog"
)
_ZIP_FROM_REPORT = "../artifacts/assessment/conversion-issues/conversion_issues.zip"
# Lines kept on each side of the conflictive line before the reader expands.
FOCUS_CONTEXT = 4
_QUOTED = re.compile(r"'([^']{3,})'")


def load_conversion_issues(path: Path | None) -> dict | None:
    """Return the artifact, or None when the file is missing or unreadable."""
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def render_conversion_issues_nav() -> str:
    return (
        '<a @click="activeTab = \'conversion-issues\'" class="nav-link" '
        'data-tab="conversion-issues" :class="{active: activeTab === \'conversion-issues\'}">'
        "Conversion Issues Report</a>"
    )


def conversion_issues_css() -> str:
    """Styles for the tab. Must live in document head: Vue drops <style> in #app."""
    return _css()


def render_conversion_issues_tab(artifact: dict | None) -> str:
    body = _empty() if not artifact else _report(artifact)
    return f"""
        <div class="tab-content ci-tab" :class="{{active: activeTab === 'conversion-issues'}}">
            {body}
        </div>
    """


def _empty() -> str:
    return f'<div class="ci-empty"><p>{html.escape(EMPTY_COPY)}</p></div>'


def _report(artifact: dict) -> str:
    customer = _text(artifact.get("customer"))
    source_language = _text(artifact.get("source_language"))
    share_url = SHARE_FORM_URL if artifact.get("share_url") == SHARE_FORM_URL else ""
    zip_path = _text(artifact.get("zip_path"))
    pairs = _int(artifact.get("distinct_pairs"))
    top_n = _int(artifact.get("top_n"))
    panels = artifact.get("panels") if isinstance(artifact.get("panels"), list) else []

    buttons = []
    tables = []
    for index, panel in enumerate(panels):
        if not isinstance(panel, dict):
            continue
        panel_id = _dom_id(_text(panel.get("id")) or f"panel-{index}")
        label = _text(panel.get("label")) or panel_id
        count = _int(panel.get("instance_count"))
        count_html = (
            f' <span class="ci-cat-count">({count:,})</span>' if index else ""
        )
        buttons.append(
            '<button type="button" class="ci-cat-btn" '
            + _vue_bind(
                ":class",
                "{ 'ci-selected': ciPanel === '" + _vue_str(panel_id) + "' }",
            )
            + " "
            + _vue_bind("@click", "ciSelectPanel('" + _vue_str(panel_id) + "')")
            + f">{html.escape(label)}{count_html}</button>"
        )
        tables.append(
            '<div class="ci-panel" '
            + _vue_bind("v-show", "ciPanel === '" + _vue_str(panel_id) + "'")
            + ">"
            f"{_panel(panel, panel_id, label, index == 0, pairs, top_n, source_language)}"
            "</div>"
        )

    return f"""
        <div class="ci-report">
            <h1 class="ci-title">Conversion Issues Report for {html.escape(customer)}</h1>
            <p class="ci-subtitle">Share your conversion issues with Snowflake. Contact <a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a>.</p>
            <div class="ci-stepper">
                <div class="ci-stepper-kicker">How to use this report</div>
                <div class="ci-stepper-grid">
                    <div class="ci-step">
                        <div class="ci-step-num">1</div>
                        <div class="ci-step-title">Review conversion issues</div>
                        <div class="ci-step-body">Browse conversion issues sorted by occurrence count to understand what needs attention.</div>
                    </div>
                    <div class="ci-step">
                        <div class="ci-step-num">2</div>
                        <div class="ci-step-title">Locate the conversion issues ZIP</div>
                        <div class="ci-step-body">{_zip_step(zip_path)}</div>
                    </div>
                    <div class="ci-step">
                        <div class="ci-step-num">3</div>
                        <div class="ci-step-title">Share issues</div>
                        <div class="ci-step-body"><a class="ci-share" href="{html.escape(share_url)}" target="_blank" rel="noopener noreferrer">Share issues</a></div>
                    </div>
                </div>
            </div>
            <div class="ci-cat-nav">{''.join(buttons)}</div>
            {''.join(tables)}
        </div>
    """


def _panel(
    panel: dict,
    panel_id: str,
    label: str,
    is_summary: bool,
    pairs: int,
    top_n: int,
    source_language: str,
) -> str:
    instance_count = _int(panel.get("instance_count"))
    rows = panel.get("rows") if isinstance(panel.get("rows"), list) else []
    shown = len([row for row in rows if isinstance(row, dict)])
    uncapped = panel.get("distinct_pairs")
    pair_count = _int(uncapped) if isinstance(uncapped, int) else (pairs if is_summary else shown)
    if is_summary:
        first_label = "Total Conversion Issues Instances"
        heading = f"Overall Top {top_n:,} Conversion Issues"
    else:
        first_label = f"Conversion Issues Instances in {label}"
        heading = f"Top {shown:,} Conversion Issues for {label}"
    return f"""
        <div class="ci-stats">
            <div class="ci-stat-card"><div class="ci-stat-num">{instance_count:,}</div><div class="ci-stat-lbl">{html.escape(first_label)}</div></div>
            <div class="ci-stat-card"><div class="ci-stat-num">{pair_count:,}</div><div class="ci-stat-lbl">Distinct Pairs</div></div>
            <div class="ci-stat-card"><div class="ci-stat-num">{shown:,}</div><div class="ci-stat-lbl">Top-N Analyzed</div></div>
            <div class="ci-stat-card"><div class="ci-stat-num">{html.escape(source_language)}</div><div class="ci-stat-lbl">Source Language</div></div>
        </div>
        <h3 class="ci-heading">{html.escape(heading)}</h3>
        {_table(panel, panel_id, source_language)}
    """


def source_hit_index(
    source_lines: list[str],
    converted_lines: list[str],
    code: str,
    description: str,
) -> int | None:
    """Line in the original file that the EWI is about, when it can be found."""
    for index, line in enumerate(source_lines):
        if "-- <<< EWI" in line:
            return index
    quotes = sorted(_QUOTED.findall(description), key=len, reverse=True)
    for quote in quotes:
        folded = quote.casefold()
        for index, line in enumerate(source_lines):
            if folded in line.casefold():
                return index
    for index, line in enumerate(converted_lines):
        if not _is_marker_for(line, code, description):
            continue
        for follow in converted_lines[index + 1 : index + 6]:
            stripped = follow.strip()
            if not stripped or stripped.startswith("!!!RESOLVE") or stripped.startswith("--"):
                continue
            for source_index, source_line in enumerate(source_lines):
                if stripped == source_line.strip():
                    return source_index
        break
    return None


def converted_hit_indexes(lines: list[str], code: str, description: str) -> list[int]:
    """Marker lines for this code and description."""
    return [
        index
        for index, line in enumerate(lines)
        if _is_marker_for(line, code, description)
    ]


def focus_span(line_count: int, hits: list[int], context: int = FOCUS_CONTEXT) -> tuple[int, int]:
    """Inclusive line range shown before the reader expands to the full object."""
    if line_count <= 0:
        return 0, -1
    if not hits:
        return 0, min(line_count - 1, context * 2)
    start = max(0, min(hits) - context)
    end = min(line_count - 1, max(hits) + context)
    return start, end


def _is_marker_for(line: str, code: str, description: str) -> bool:
    if "!!!RESOLVE EWI!!!" not in line:
        return False
    if code and code not in line:
        return False
    if description and description not in line:
        return False
    return True


def _code_sample(
    view_id: str,
    heading: str,
    text: str,
    hits: list[int],
    hit_class: str,
) -> str:
    lines = text.split("\n") if text else []
    start, end = focus_span(len(lines), hits)
    above = start
    below = (len(lines) - 1 - end) if lines else 0
    full = "ciCodeIsFull('" + _vue_str(view_id) + "')"
    body: list[str] = []
    if above > 0:
        body.append(
            '<div class="ci-omitted" '
            + _vue_bind("v-show", "!" + full)
            + f">... {above:,} lines above ...</div>"
        )
    hit_set = set(hits)
    for index, line in enumerate(lines):
        classes = "ci-line"
        if index in hit_set:
            classes += " " + hit_class
        shown = full if index < start or index > end else ""
        attr = (" " + _vue_bind("v-show", shown)) if shown else ""
        content = html.escape(line) if line else "&#8203;"
        body.append(f'<div class="{classes}"{attr}>{content}</div>')
    if below > 0:
        body.append(
            '<div class="ci-omitted" '
            + _vue_bind("v-show", "!" + full)
            + f">... {below:,} lines below ...</div>"
        )
    toggle = ""
    if above > 0 or below > 0:
        count = len(lines)
        toggle = (
            '<button type="button" class="ci-code-toggle" '
            + _vue_bind("v-show", "!" + full)
            + " "
            + _vue_bind("@click.stop", "ciShowFullCode('" + _vue_str(view_id) + "')")
            + f">Show full code ({count:,} lines)</button>"
            + '<button type="button" class="ci-code-toggle" '
            + _vue_bind("v-show", full)
            + " "
            + _vue_bind("@click.stop", "ciShowFocusedCode('" + _vue_str(view_id) + "')")
            + ">Show focused view</button>"
        )
    return (
        f"<h4>{html.escape(heading)}</h4>"
        '<div class="ci-code-view">'
        '<div class="ci-code-lang">SQL</div>'
        f'<div class="ci-code-body">{"".join(body)}</div>'
        "</div>"
        + toggle
    )


def _table(panel: dict, panel_id: str, source_language: str) -> str:
    rows = panel.get("rows") if isinstance(panel.get("rows"), list) else []
    codes: list[str] = []
    types: list[str] = []
    body = []
    for row_index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        code = _text(row.get("code"))
        issue_type = _text(row.get("issue_type"))
        if code and code not in codes:
            codes.append(code)
        if issue_type and issue_type not in types:
            types.append(issue_type)
        detail_id = f"{panel_id}-{row_index}"
        object_types = row.get("object_types") if isinstance(row.get("object_types"), list) else []
        type_text = ", ".join(_text(item) for item in object_types)
        sample = row.get("sample") if isinstance(row.get("sample"), dict) else {}
        source_text = _text(sample.get("source_code"))
        converted_text = _text(sample.get("converted_excerpt"))
        source_lines = source_text.split("\n") if source_text else []
        converted_lines = converted_text.split("\n") if converted_text else []
        description = _text(row.get("description"))
        source_hit = source_hit_index(source_lines, converted_lines, code, description)
        source_heading = (
            f"Original input code ({source_language})" if source_language else "Original input code"
        )
        badge = "ci-badge-parsing" if issue_type == "Parsing Issue" else "ci-badge-ewi"
        visible = (
            "ciRowVisible('"
            + _vue_str(panel_id)
            + "', '"
            + _vue_str(code)
            + "', '"
            + _vue_str(issue_type)
            + "')"
        )
        body.append(
            '<tr class="ci-row" '
            + _vue_bind("v-show", visible)
            + " "
            + _vue_bind("@click", "ciToggleDetail('" + _vue_str(detail_id) + "')")
            + ">"
            + f"<td class=\"ci-num\">{_int(row.get('rank'))}</td>"
            + f"<td class=\"ci-code\">{html.escape(code)}</td>"
            + f"<td class=\"ci-type\"><span class=\"ci-badge {badge}\">{html.escape(issue_type)}</span></td>"
            + f"<td class=\"ci-desc\">{html.escape(_text(row.get('description')))}</td>"
            + f"<td class=\"ci-count\">{_int(row.get('count')):,}</td>"
            + f"<td class=\"ci-pct\">{_percent(row.get('percent'))}</td>"
            + f"<td class=\"ci-objects\">{html.escape(type_text)}</td>"
            + "</tr>"
            + '<tr class="ci-detail" '
            + _vue_bind(
                "v-show",
                "ciOpenDetail === '" + _vue_str(detail_id) + "' && " + visible,
            )
            + ">"
            + "<td colspan=\"7\">"
            + f"<h4>Problem Description</h4><p>{html.escape(_text(row.get('problem_description')))}</p>"
            + f"<h4>Recommended Fix</h4><p>{html.escape(_text(row.get('recommended_fix')))}</p>"
            + _code_sample(
                detail_id + "-source",
                source_heading,
                source_text,
                [] if source_hit is None else [source_hit],
                "ci-hit-source",
            )
            + _code_sample(
                detail_id + "-converted",
                "Converted output",
                converted_text,
                converted_hit_indexes(converted_lines, code, description),
                "ci-hit-converted",
            )
            + "</td></tr>"
        )

    return f"""
        <div class="ci-table-wrap">
        <table class="ci-table">
            <colgroup>
                <col class="ci-col-rank">
                <col class="ci-col-code">
                <col class="ci-col-type">
                <col class="ci-col-desc">
                <col class="ci-col-count">
                <col class="ci-col-pct">
                <col class="ci-col-objects">
            </colgroup>
            <thead>
                <tr>
                    <th>#</th>
                    <th class="ci-filterable">{_filter("EWI Code", "code", panel_id, codes)}</th>
                    <th class="ci-filterable">{_filter("Issue Type", "type", panel_id, types)}</th>
                    <th>Description</th>
                    <th class="ci-count">Count</th>
                    <th class="ci-pct">%</th>
                    <th>Object Types</th>
                </tr>
            </thead>
            <tbody data-ci-body="{html.escape(panel_id)}">{''.join(body)}</tbody>
        </table>
        </div>
    """


def _filter(label: str, kind: str, panel_id: str, values: list[str]) -> str:
    key = _vue_str(panel_id) + ":" + kind
    options = []
    for value in values:
        encoded = _vue_str(value)
        options.append(
            '<label class="ci-filter-item">'
            "<input type=\"checkbox\" "
            + _vue_bind(":checked", "ciFilterOn('" + key + "', '" + encoded + "')")
            + " "
            + _vue_bind(
                "@change",
                "ciToggleFilter('" + key + "', '" + encoded + "', $event.target.checked)",
            )
            + f"> {html.escape(value)}</label>"
        )
    return (
        f"{html.escape(label)} "
        '<button type="button" class="ci-filter-arrow" '
        f'aria-label="Filter {html.escape(label)}" '
        + _vue_bind("@click.stop", "ciToggleMenu('" + key + "')")
        + ">&#9660;</button>"
        '<div class="ci-filter-menu" '
        + _vue_bind(":class", "{ 'ci-open': ciOpenMenu === '" + key + "' }")
        + ">"
        '<div class="ci-filter-clear" '
        + _vue_bind("@click", "ciClearFilter('" + key + "')")
        + ">Clear filters</div>"
        f"{''.join(options)}</div>"
    )


def _zip_step(zip_path: str) -> str:
    """Show the project path and, when it is the stable ZIP, a same-folder download."""
    shown = html.escape(zip_path)
    href = _zip_href(zip_path)
    path = f"<code>{shown}</code>" if zip_path else "<span>No ZIP was written.</span>"
    if not href:
        return path
    return (
        path
        + f'<a class="ci-download" href="{html.escape(href)}" download="conversion_issues.zip">'
        "Download ZIP</a>"
    )


def _zip_href(zip_path: str) -> str | None:
    """Link the report in assessment/ back to the stable project ZIP."""
    normalized = zip_path.replace("\\", "/")
    marker = "artifacts/assessment/conversion-issues/conversion_issues.zip"
    if normalized == marker or normalized.endswith("/" + marker):
        return _ZIP_FROM_REPORT
    return None


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _percent(value: object) -> str:
    try:
        return f"{float(value):.1f}%"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "0.0%"


def conversion_issues_initial_panel(artifact: dict | None) -> str:
    """Panel shown on first paint. The summary panel is first when it exists."""
    panels = artifact.get("panels") if isinstance(artifact, dict) else None
    if isinstance(panels, list):
        for panel in panels:
            if isinstance(panel, dict):
                return _dom_id(_text(panel.get("id")) or "summary")
    return "summary"


def _dom_id(value: str) -> str:
    cleaned = "".join(char if char.isalnum() else "-" for char in value).strip("-")
    return cleaned or "panel"


def _vue_str(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "")


def _vue_bind(name: str, expression: str) -> str:
    """A Vue binding safe to drop into a double-quoted HTML attribute."""
    return name + '="' + html.escape(expression, quote=True) + '"'


def _css() -> str:
    return """
        .ci-report { color: #1E252F; }
        .ci-title { font-size: 1.875rem; font-weight: 800; color: #102E46; margin: 0 0 8px; }
        .ci-subtitle { color: #64748B; font-size: 1rem; margin: 0 0 24px; line-height: 1.5; }
        .ci-subtitle a { color: #2563eb; text-decoration: none; }
        .ci-stepper { border: 1px solid #e2e8f0; border-radius: 12px; padding: 24px 28px; margin-bottom: 32px; }
        .ci-stepper-kicker { text-transform: uppercase; font-size: 0.7rem; color: #94a3b8; font-weight: 600; letter-spacing: 0.08em; margin-bottom: 18px; }
        .ci-stepper-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 28px; }
        .ci-step { text-align: center; }
        .ci-step-num { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 50%; background: #e0edff; color: #2563eb; font-weight: 700; font-size: 0.9rem; margin-bottom: 10px; }
        .ci-step-title { font-weight: 700; color: #102E46; font-size: 0.95rem; margin-bottom: 4px; }
        .ci-step-body { color: #64748B; font-size: 0.85rem; line-height: 1.45; }
        .ci-step-body code { display: inline-block; background: #f1f5f9; padding: 3px 8px; border-radius: 6px; font-size: 0.8rem; word-break: break-all; text-align: left; }
        .ci-download { display: inline-block; margin-top: 10px; background: #fff; color: #1A6CE7; border: 1px solid #1A6CE7; padding: 6px 16px; border-radius: 6px; font-size: 0.85rem; font-weight: 600; text-decoration: none; }
        .ci-download:hover { background: #eff6ff; }
        .ci-share { display: inline-block; background: #2563eb; color: #fff; padding: 6px 16px; border-radius: 6px; font-size: 0.85rem; font-weight: 600; text-decoration: none; }
        .ci-share:hover { background: #1d4ed8; }
        .ci-cat-nav { display: flex; flex-wrap: wrap; gap: 0; margin-bottom: 1.2rem; border-bottom: 1px solid #E5E7EB; }
        .ci-cat-btn { padding: 0.5rem 0.875rem; border: none; border-bottom: 2px solid transparent; background: transparent; border-radius: 0; cursor: pointer; font-size: 0.875rem; font-weight: 500; color: #5C6775; margin-bottom: -1px; white-space: nowrap; }
        .ci-cat-btn:hover { color: #2A3342; border-bottom-color: #D5DAE4; }
        .ci-cat-btn.ci-selected { color: #1A6CE7; border-bottom: 2px solid #1A6CE7; }
        .ci-cat-count { font-size: 0.7rem; opacity: 0.7; }
        .ci-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 1.5rem; }
        .ci-stat-card { background: #fff; border: 1px solid #E2E8F0; border-radius: 12px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
        .ci-stat-num { font-size: 28px; font-weight: 800; color: #1E252F; }
        .ci-stat-lbl { font-size: 14px; font-weight: 400; color: #5D6A85; line-height: 1.25rem; margin-top: 4px; }
        .ci-heading { font-size: 1.1rem; color: #102E46; margin: 1rem 0 0.6rem; border-bottom: 2px solid #eee; padding-bottom: 0.3rem; font-weight: 600; }
        .ci-table-wrap { overflow-x: auto; margin-bottom: 24px; }
        .ci-table { width: 100%; min-width: 960px; border-collapse: collapse; background: #fff; border: 1px solid #E2E8F0; table-layout: fixed; }
        .ci-col-rank { width: 3rem; }
        .ci-col-code { width: 11rem; }
        .ci-col-type { width: 8.5rem; }
        .ci-col-count { width: 5.5rem; }
        .ci-col-pct { width: 5rem; }
        .ci-col-objects { width: 11rem; }
        .ci-table th, .ci-table td { padding: 0.75rem; text-align: left; border-bottom: 1px solid #E2E8F0; font-size: 0.85rem; vertical-align: top; color: #1E252F; }
        .ci-table th { background: #F8FAFC; font-weight: 600; white-space: nowrap; }
        .ci-table .ci-count, .ci-table .ci-pct { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
        .ci-code { font-weight: 600; color: #11567F; white-space: nowrap; }
        .ci-desc { white-space: normal; overflow-wrap: anywhere; }
        .ci-objects { white-space: normal; }
        .ci-row { cursor: pointer; }
        .ci-row:hover { background: #F1F5F9; }
        .ci-badge { display: inline-block; padding: 0.18rem 0.5rem; border-radius: 10px; font-size: 0.7rem; font-weight: 600; white-space: nowrap; }
        .ci-badge-ewi { background: #d4edda; color: #155724; }
        .ci-badge-parsing { background: #f8d7da; color: #721c24; }
        .ci-filterable { position: relative; }
        .ci-filter-arrow { cursor: pointer; font-size: 0.55rem; color: #999; background: none; border: none; padding: 0 2px; vertical-align: middle; }
        .ci-filter-menu { display: none; position: absolute; top: 100%; left: 0; min-width: 180px; max-height: 260px; overflow-y: auto; background: #fff; border: 1px solid #ddd; border-radius: 6px; box-shadow: 0 4px 16px rgba(0,0,0,0.13); z-index: 20; margin-top: 4px; padding: 4px 0; text-align: left; font-weight: 400; }
        .ci-filter-menu.ci-open { display: block; }
        .ci-filter-item { display: flex; align-items: center; gap: 6px; padding: 0.35rem 0.75rem; font-size: 0.8rem; color: #333; cursor: pointer; white-space: nowrap; }
        .ci-filter-item:hover { background: #eef1f5; }
        .ci-filter-clear { padding: 0.35rem 0.75rem; font-size: 0.75rem; color: #1A6CE7; cursor: pointer; border-bottom: 1px solid #eee; margin-bottom: 2px; text-align: center; }
        .ci-detail td { background: #F8FAFC; }
        .ci-detail h4 { margin: 0.8rem 0 0.3rem; color: #102E46; font-size: 0.9rem; }
        .ci-detail p { margin: 0; line-height: 1.5; color: #334155; }
        .ci-detail pre { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 8px; padding: 1rem; overflow-x: auto; font-size: 0.8rem; line-height: 1.5; white-space: pre-wrap; }
        .ci-code-view { border: 1px solid #d0d7de; border-radius: 8px; overflow: hidden; margin: 0.4rem 0; }
        .ci-code-lang { background: #1e293b; color: #fff; font-size: 0.75rem; font-weight: 600; padding: 0.35rem 0.75rem; }
        .ci-code-body { background: #f8fafc; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.8rem; line-height: 1.5; overflow-x: auto; padding: 0.35rem 0; }
        .ci-line { min-height: 1.5em; padding: 0 0.75rem; white-space: pre; }
        .ci-hit-source { background: #fde68a; }
        .ci-hit-converted { background: #fecdd3; }
        .ci-omitted { color: #94a3b8; text-align: center; padding: 0.35rem 0.75rem; }
        .ci-code-toggle { background: #fff; border: 1px solid #cbd5e1; border-radius: 6px; color: #1e293b; cursor: pointer; font-size: 0.8rem; margin: 0.35rem 0 0.8rem; padding: 0.35rem 0.7rem; }
        .ci-code-toggle:hover { background: #f8fafc; }
        .ci-empty { padding: 24px; color: #64748B; }
    """
