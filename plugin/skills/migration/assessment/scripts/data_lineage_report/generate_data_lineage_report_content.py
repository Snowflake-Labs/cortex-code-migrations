"""Data Lineage report tab content (Sources -> Pipelines -> Targets -> Reports overview).

Renders the "Data Lineage" tab from a data-lineage.json artifact produced by
`scai assessment data-lineage`. Returns (content_html, js, css) strings that
generate_multi_report.py drops into the multi-tab report, following the
Anti-Patterns tab's architecture. Uses only stdlib.

Cards and edges are positioned in one shared, unscaled pixel space computed by
`lineage_layout.layout_lineage` — the renderer never re-derives geometry, so a
card's border and its edge's endpoint always agree. The report pane is fluid
and usually wider than that base width, so the tab script stretches the x axis
to fill it: lanes and cards are re-placed from the base geometry this renderer
emits as data attributes, and edges are then rebuilt from the cards' resulting
boxes, which keeps the pixel space shared at any width. Selecting a card
focuses the map: everything off its connected path is hidden and the survivors
are restacked from the top of each lane, again from constants this renderer
emits rather than values duplicated in the script. Per the locked design,
`Inferred`, `Observed`, and `Status` are never rendered.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .lineage_layout import (
    BUCKET_CARD_INSET,
    BUCKET_GAP,
    BUCKET_HEADER_HEIGHT,
    BucketLayout,
    CANVAS_PADDING,
    CHILD_INSET,
    LANE_CARD_INSET,
    LANE_HEADER_HEIGHT,
    LANE_HEADER_ICON,
    LineageLayout,
    MIN_CANVAS_HEIGHT,
    NODE_HEIGHT,
    NODE_MAX_WIDTH,
    ROW_GAP,
    TOGGLE_INSET_X,
    TOGGLE_INSET_Y,
    bucket_key,
    bucket_title,
    edge_path,
    icon_name,
    layout_lineage,
)

_DEFAULT_CANVAS_WIDTH = 1160
_CLI_COMMAND = "scai assessment data-lineage"

_LANES = ("source", "pipeline", "target", "report")
_LANE_TITLE = {
    "source": "Sources",
    "pipeline": "Pipelines",
    "target": "Targets",
    "report": "Reports",
}
_LANE_COPY = {
    "source": "Read by a pipeline or a report.",
    "pipeline": "ETL that moves the data.",
    "target": "Written by a pipeline.",
    "report": "Reports that read systems on this map.",
}
_KIND_LABEL = {
    "system": "System",
    "etl_pipeline": "ETL pipeline",
    "etl_system": "ETL system",
    "etl_package": "ETL package",
    "report_system": "Power BI",
    "report_report": "Power BI report",
    "unresolved": "Unresolved",
}

# Vendored verbatim (path/g geometry only) from @snowflake/stellar-icons
# (dashboard-ui/node_modules/@snowflake/stellar-icons/data/generated/icons/*.svg,
# viewBox "0 0 16 16"): database.svg, file.svg, data-pipelines.svg,
# cloud-saas.svg, unknown.svg, info-circle.svg. The packaged `fill="#5D6A85"` is swapped for
# `currentColor` so the tab's own CSS controls icon color, same as every
# other inline SVG on the page; the shapes themselves are untouched.
_ICON_VIEWBOX = "0 0 16 16"
_ICON_PATHS: Dict[str, str] = {
    "Database": (  # database.svg
        '<path fill="currentColor" fill-rule="evenodd" d="M8.001 2c1.303 0 2.509.263 3.406.71.868.434 '
        '1.595 1.126 1.595 2.039q0 .086-.008.169.008.09.008.182v5.822l-.006.134v.011l-.002.011c-.08.923-'
        ".767 1.658-1.646 2.143-.782.43-1.783.704-2.874.766L8 14.001c-1.315 0-2.53-.307-3.433-.83C3.678 "
        "12.659 3 11.873 3 10.902V5.1q0-.095.008-.186A2 2 0 0 1 3 4.75c0-.912.727-1.605 1.595-2.038C5.492 "
        "2.263 6.697 2 8 2m4.001 4.427a4 4 0 0 1-.595.36c-.897.447-2.103.71-3.406.71-1.304 0-2.509-.262-"
        "3.406-.71A4 4 0 0 1 4 6.426V10.9c0 .464.33.98 1.068 1.407.726.419 1.762.694 2.933.694l.419-.012c"
        ".962-.055 1.813-.296 2.445-.644.732-.404 1.089-.898 1.131-1.348l.006-.118zM8.001 3c-1.17 0-2.207"
        ".275-2.933.694-.633.366-.966.798-1.047 1.205.073.305.371.668 1.021.993.731.365 1.777.605 2.959"
        '.605s2.228-.24 2.959-.605c.65-.325.946-.688 1.02-.993-.081-.407-.413-.839-1.046-1.205-.635-.366'
        '-1.508-.623-2.5-.681z" clip-rule="evenodd"/>'
    ),
    "DataPipelines": (  # data-pipelines.svg
        '<path fill="currentColor" fill-rule="evenodd" d="M14 2a1 1 0 0 1 1 1v3a1 1 0 0 1-.898.995L14 7h'
        "-3l-.102-.005a1 1 0 0 1-.893-.892L10 6V5H9a.5.5 0 0 0-.5.5V7c0 .385-.146.734-.385 1 .239.266.385"
        ".615.385 1v1.5a.5.5 0 0 0 .5.5h1v-1a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1v3a1 1 0 0 1-.898.995L14 14h-3"
        "l-.102-.005a1 1 0 0 1-.893-.893L10 13v-1H9a1.5 1.5 0 0 1-1.5-1.5V9a.5.5 0 0 0-.5-.5H6v1a1 1 0 0 "
        "1-.897.995L5 10.5H2l-.103-.005a1 1 0 0 1-.892-.892L1 9.5v-3a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1v1h1a.5"
        ".5 0 0 0 .5-.5V5.5A1.5 1.5 0 0 1 9 4h1V3a1 1 0 0 1 1-1zm-3 11h3v-3h-3zM2 9.5h3v-3H2zM11 6h3V3h-3z"
        '" clip-rule="evenodd"/>'
    ),
    "Unknown": (  # unknown.svg
        '<g fill="currentColor">'
        '<path d="M8 10.17a.814.814 0 1 1 0 1.63.814.814 0 0 1 0-1.63M8.094 4.805A1.928 1.928 0 0 1 9.148'
        ' 8.33l-.37.248a.63.63 0 0 0-.278.524V9.5h-1v-.398c0-.543.27-1.051.72-1.354l.37-.248a.928.928 0 '
        '0 0-.506-1.695l-.073-.001a1 1 0 0 0-1.011 1V7H6v-.196a2 2 0 0 1 2.022-2z"/>'
        '<path fill-rule="evenodd" d="M6.939 1.446a1.5 1.5 0 0 1 2.122 0l5.493 5.493a1.5 1.5 0 0 1 0 2.121'
        "l-5.493 5.493-.114.104c-.59.48-1.459.446-2.008-.104L1.446 9.06a1.5 1.5 0 0 1 0-2.12zm1.415.707a."
        "5.5 0 0 0-.708 0L2.153 7.646a.5.5 0 0 0 0 .707l5.493 5.494c.17.17.436.192.63.064l.078-.064 5.493"
        '-5.494a.5.5 0 0 0 0-.707z" clip-rule="evenodd"/>'
        "</g>"
    ),
    "File": (  # file.svg
        '<g fill="currentColor">'
        '<path d="M9 11H5v-1h4zM11 9H5V8h6z"/>'
        '<path fill-rule="evenodd" d="M8.598 1.01a.5.5 0 0 1 .256.136l4 4A.5.5 0 0 1 13 5.5v8a1.5 1.5 0 0'
        " 1-1.5 1.5h-7A1.5 1.5 0 0 1 3 13.5v-11A1.5 1.5 0 0 1 4.5 1h4zM4.5 2a.5.5 0 0 0-.5.5v11a.5.5 0 0 "
        "0 .5.5h7a.5.5 0 0 0 .5-.5V6H9.501A1.5 1.5 0 0 1 8 4.5V2zM9 4.5a.5.5 0 0 0 .501.5h1.792L9 2.707z"
        '" clip-rule="evenodd"/>'
        "</g>"
    ),
    "CloudSaas": (  # cloud-saas.svg
        '<g fill="currentColor">'
        '<path d="M13.313 8.813a.875.875 0 1 1 0 1.75.875.875 0 0 1 0-1.75"/>'
        '<path fill-rule="evenodd" d="M15.5 7a.5.5 0 0 1 .5.5v4.243a.5.5 0 0 1-.151.359l-3.734 3.631a.5.5'
        " 0 0 1-.702-.005l-4.142-4.141a.5.5 0 0 1 0-.707l3.734-3.734.076-.062A.5.5 0 0 1 11.358 7zm-7.168 "
        '4.233 3.438 3.439 3.23-3.14V8h-3.435z" clip-rule="evenodd"/>'
        '<path d="M7.918 3.004a3.97 3.97 0 0 1 3.651 2.965q.192.005.378.031h-1.413A2.97 2.97 0 0 0 8.01 '
        "4.013L7.73 4a2.967 2.967 0 0 0-2.966 2.967l.004.163q.004.08.012.158l.064.594-.596-.041c-.065-.005"
        "-.108-.008-.15-.008A2.1 2.1 0 0 0 2 9.933l.01.215a2.1 2.1 0 0 0 2.09 1.885H6v1H4.1a3.1 3.1 0 0 1"
        '-3.096-2.94L1 9.933c0-1.599 1.211-2.916 2.767-3.082A3.967 3.967 0 0 1 7.73 3z"/>'
        "</g>"
    ),
    "InfoCircle": (  # info-circle.svg
        '<g fill="currentColor">'
        '<path d="M8.5 12h-1V7h1zM8 4a.75.75 0 1 1 0 1.5A.75.75 0 0 1 8 4"/>'
        '<path fill-rule="evenodd" d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1m0 1a6 6 0 1 0 0 12A6 6 0 0 0 8 2"'
        ' clip-rule="evenodd"/>'
        "</g>"
    ),
}

_MALFORMED_EXCEPTIONS = (TypeError, ValueError, KeyError, AttributeError)


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _humanize_kind(kind: str) -> str:
    key = (kind or "").strip().lower()
    if key in _KIND_LABEL:
        return _KIND_LABEL[key]
    return key.replace("_", " ").title() if key else "Unknown"


def _is_unresolved_kind(node: Dict[str, Any]) -> bool:
    return (node.get("Kind") or "").strip().lower() == "unresolved"


# Both buckets hold references to objects the supplied code never defined --
# Unknown ones merely kept an owner name to be grouped under. They are one
# class of gap, so they carry one visual treatment.
_WARNING_BUCKETS = ("Unknown", "Unresolved")


def _is_warning_node(node: Dict[str, Any]) -> bool:
    return bucket_key(node) in _WARNING_BUCKETS


def _accent_color(node: Dict[str, Any]) -> str:
    if _is_warning_node(node):
        return "#F5D68A"
    if node.get("Lane") == "target":
        return "#7EC8A0"
    return "#7FA8D9"


def _icon_svg(name: str) -> str:
    inner = _ICON_PATHS.get(name, _ICON_PATHS["Unknown"])
    css_name = name.lower()
    return f'<svg class="dl-icon dl-icon-{css_name}" viewBox="{_ICON_VIEWBOX}" width="16" height="16" fill="none" aria-hidden="true">{inner}</svg>'


def generate_data_lineage_html_content(path) -> Tuple[str, str, str]:
    """Load the schema-v1 data-lineage artifact at `path` and render the tab.

    Never raises: `path=None` (no override given and nothing discovered),
    a missing file, non-UTF8 bytes, invalid JSON syntax, a non-object
    top-level JSON value, and a downstream rendering error (e.g. a
    nonnumeric `Summary.UnresolvedSource`/`UnresolvedTarget`) all render the
    tab's empty state instead, so the rest of the multi-tab report still
    generates.
    """
    if path is None:
        # generate_multi_report.py always renders this tab, even when no
        # --data-lineage-json override was given and --project-dir discovery
        # found nothing at the stable path -- that "nothing to load" case is
        # exactly the missing-file empty state, just without ever touching
        # the filesystem.
        return _render_empty_state(), _js_with_graph(_EMPTY_GRAPH_JSON), _CSS

    try:
        raw_bytes = Path(path).read_bytes()
    except OSError:
        return _render_empty_state(), _js_with_graph(_EMPTY_GRAPH_JSON), _CSS

    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        # Not a JSON syntax error -- the bytes never even reached the parser --
        # so use the generic "could not be read" reason, not "invalid JSON".
        return _render_empty_state(reason="unreadable"), _js_with_graph(_EMPTY_GRAPH_JSON), _CSS

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # A genuine JSON syntax error: "invalid JSON" is an accurate claim here.
        return _render_empty_state(reason="invalid_json"), _js_with_graph(_EMPTY_GRAPH_JSON), _CSS

    if not isinstance(data, dict):
        # Valid JSON (e.g. a JSON array/string/null), just the wrong shape --
        # not a JSON syntax error, so don't claim "invalid JSON".
        return _render_empty_state(reason="unreadable"), _js_with_graph(_EMPTY_GRAPH_JSON), _CSS

    try:
        content, graph_json = _render_content(data)
    except _MALFORMED_EXCEPTIONS:
        # Valid JSON object with a malformed field (e.g. a nonnumeric
        # UnresolvedSource/UnresolvedTarget) -- same "don't claim invalid
        # JSON" rule applies.
        return _render_empty_state(reason="unreadable"), _js_with_graph(_EMPTY_GRAPH_JSON), _CSS

    return content, _js_with_graph(graph_json), _CSS


_EMPTY_STATE_EXTRA_LINE = {
    # Generic "data lineage artifact" copy, not a hardcoded "data-lineage.json"
    # filename: `--data-lineage-json` lets the actual override filename vary,
    # so the empty state must never claim a specific name that may not match
    # what was actually found.
    "invalid_json": "An existing data lineage artifact was found, but it contains invalid JSON.",
    "unreadable": "An existing data lineage artifact was found, but it could not be read.",
}


def _render_empty_state(reason: Optional[str] = None) -> str:
    """`reason` is None for a missing file, or one of `_EMPTY_STATE_EXTRA_LINE`'s
    keys for a file that exists but couldn't be turned into a rendered tab.
    The base remediation paragraph (naming the CLI regeneration command) is
    always shown; a malformed/unreadable file additionally gets one
    grammatical, accurate extra line -- never a claim of "invalid JSON" for
    an input that was actually valid JSON with the wrong shape or content.
    """
    body = f"<p>Data lineage assessment data is not available. Run <code>{_esc(_CLI_COMMAND)}</code> to generate it.</p>"
    extra = _EMPTY_STATE_EXTRA_LINE.get(reason)
    if extra:
        body += f"<p>{extra}</p>"
    return '<div id="data-lineage-report">' + _render_page_header() + '<div class="empty-state"><h3>No Data Available</h3>' + body + "</div></div>"


_DL_H1 = '<h1 style="font-size: 1.875rem; font-weight: 800; color: #102E46; margin-bottom: 8px;">Data Lineage</h1>'
_DL_BLURB = "Follow how data moves from sources through pipelines to targets and reports."
# The introduction carries the ask for reporting-layer files because an empty
# Reports lane cannot make it: a reader whose project supplied no report files
# sees nothing there and has no way to learn that supplying them is what fills
# it. Every string is authored here, never derived from the artifact.
_DL_INTRO_PARAGRAPHS = (
    _DL_BLURB,
    "This map is the data lineage graph of the code supplied for assessment: the systems data "
    "is consumed from, the ETL pipelines that move it, the systems it lands in, and the reports "
    "that read them. Read it left to right to follow a path from a source system to where its "
    "data ends up.",
    "Reporting-layer files make that picture richer. When report files such as Power BI .pbit "
    "or .pbix are included in the code supplied for assessment, every report that queries these "
    "systems is drawn in the Reports lane. Without them the map stops at the systems the "
    "pipelines write, and who consumes the data stays unknown.",
)
_DL_INTRO = "".join(
    '<p style="color: #64748B; font-size: 1rem; line-height: 1.6; '
    f'margin-bottom: {24 if index == len(_DL_INTRO_PARAGRAPHS) - 1 else 10}px;">'
    f"{_esc(paragraph)}</p>"
    for index, paragraph in enumerate(_DL_INTRO_PARAGRAPHS)
)
# What used to be a "How to read this map" text block above the KPIs now hangs
# off an info icon on the thing each sentence describes, so the explanation sits
# where the reader is already looking. Every string is authored here, never
# derived from the artifact, but it still goes through `_esc` because it lands
# in `title`/`aria-label` attribute values.
_LANE_INFO = {
    "source": (
        "Systems that ETL pipelines or reports read from. Select a source card to focus the map on "
        "the pipelines, targets, and reports that depend on it. Supported system cards can be "
        "expanded to schema detail."
    ),
    "pipeline": (
        "ETL jobs that move or transform data. Select a pipeline to focus the map on the "
        "sources it reads and the targets it writes."
    ),
    "target": (
        "Systems that ETL pipelines write to. Select a target card to focus the map on the "
        "upstream pipelines and sources that feed it. Supported system cards can be "
        "expanded to schema detail."
    ),
    "report": (
        "Reports that query systems on this map. Select a report card to focus the map on "
        "the systems it reads or writes."
    ),
}
_BUCKET_LANE_ROLE = {
    "source": "read from by ETL pipelines",
    "pipeline": "that run ETL pipelines",
    "target": "written to by ETL pipelines",
    "report": "that publish reports",
}
# Unknown and Unresolved are the same class of gap -- a reference an ETL
# pipeline makes to an object that was not found in the code supplied for
# assessment. What separates them is only whether an owner came with the
# reference, which is what decides whether the missing object can be
# attributed to a named system or has to be counted anonymously. Both say so,
# so neither reads as a different kind of problem than it is.
_BUCKET_INFO_UNKNOWN = (
    "Objects referenced by ETL pipelines that were not found in the code supplied for "
    "assessment. The reference named an owner, so these are grouped under that owner's "
    "name -- but the platform behind it is unknown. Include that code for more complete "
    "lineage."
)
_BUCKET_INFO_UNRESOLVED = (
    "Objects referenced by ETL pipelines that were not found in the code supplied for "
    "assessment, and whose reference named no owner -- so there is no system to attribute "
    "them to and they are counted here rather than shown by name. Include that code for "
    "more complete lineage."
)
# `MissingInputs[].Kind` is an artifact enum-like contract literal written by
# `DataLineageProjector` (C#) -- an exact PascalCase string, not a
# human-readable label -- so this comparison is intentionally exact-case and
# must stay that way: normalizing case here would silently start suppressing
# (or, per the approved design, failing to suppress) rows whose `Kind` isn't
# actually this literal. The artifact always emits `LandingWithoutReportingLayer`
# when it applies; only the HTML tab suppresses it from the rendered
# "Missing inputs" section -- every other `MissingInputs` kind still renders.
_SUPPRESSED_MISSING_INPUT_KIND = "LandingWithoutReportingLayer"


def _render_page_header() -> str:
    return f'<div class="dl-page-header">{_DL_H1}{_DL_INTRO}</div>'


def _info_icon(text: str, extra_class: str = "") -> str:
    """A hover/focus explanation pinned to the element it describes.

    `title` here is only the no-JS fallback: `dlInitInfoTips` moves it to
    `data-dl-tip` and drives a tooltip this page controls, because the native
    one needs a ~1s stationary hover before it appears -- long enough that
    hovering the icon reads as doing nothing. `role="img"` plus `aria-label`
    is what exposes the text to a screen reader (`title` alone on a `<span>`
    is not reliably announced), and `tabindex` makes it reachable by keyboard.
    """
    label = _esc(text)
    classes = f"dl-info {extra_class}".strip()
    return (
        f'<span class="{classes}" role="img" tabindex="0" aria-label="{label}" '
        f'title="{label}">{_icon_svg("InfoCircle")}</span>'
    )


def _bucket_info_text(lane: str, key: str) -> str:
    if key == "Unresolved":
        return _BUCKET_INFO_UNRESOLVED
    if key == "Unknown":
        return _BUCKET_INFO_UNKNOWN
    return f"{bucket_title(key)} systems {_BUCKET_LANE_ROLE[lane]}."


def _render_content(data: Dict[str, Any]) -> Tuple[str, str]:
    """Return the tab body and, separately, the click-to-highlight graph JSON.

    They are separate returns because they end up in different places on the
    page: the body is mounted inside the report's Vue root, the graph is not.
    See `_graph_payload_json`.
    """
    summary = data.get("Summary", {}) or {}
    canvas = data.get("Canvas", {}) or {}
    nodes = canvas.get("Nodes", []) or []
    edges = canvas.get("Edges", []) or []
    missing_inputs = data.get("MissingInputs", []) or []
    narrative = data.get("Narrative")
    findings = data.get("Findings", []) or []

    layout = layout_lineage(nodes, canvas_width=_DEFAULT_CANVAS_WIDTH)

    content = (
        '<div id="data-lineage-report">'
        + _render_page_header()
        + _render_kpis(summary)
        + _render_unresolved_banner(summary)
        + _render_details_strip()
        + _render_canvas(nodes, edges, layout)
        + _render_missing_inputs(missing_inputs)
        + _render_narrative_and_findings(narrative, findings)
        + "</div>"
    )
    return content, _graph_payload_json(nodes, edges, layout)


def _render_kpis(summary: Dict[str, Any]) -> str:
    cards = (
        ("Systems", summary.get("Systems", 0)),
        ("Pipelines", summary.get("Pipelines", 0)),
        ("Reports", summary.get("Reports", 0)),
    )
    items = "".join(
        f'<div class="effort-card"><div class="effort-card-num">{_esc(value)}</div>'
        f'<div class="effort-card-lbl">{_esc(label)}</div></div>'
        for label, value in cards
    )
    return f'<div class="effort-cards dl-kpis">{items}</div>'


def _render_unresolved_banner(summary: Dict[str, Any]) -> str:
    """Exact locked copy: `On this map: {n} unresolved references in Sources
    and {m} in Targets.` — a single "unresolved references" phrase, shared
    across both clauses when both lanes are present; the zero lane is
    omitted entirely rather than shown as "0 in ...". A nonnumeric count
    (malformed artifact) raises, which the caller treats as unreadable."""
    unresolved_source = int(summary.get("UnresolvedSource", 0) or 0)
    unresolved_target = int(summary.get("UnresolvedTarget", 0) or 0)
    if not unresolved_source and not unresolved_target:
        return ""
    if unresolved_source and unresolved_target:
        text = f"On this map: {unresolved_source} unresolved references in Sources and {unresolved_target} in Targets."
    elif unresolved_source:
        text = f"On this map: {unresolved_source} unresolved references in Sources."
    else:
        text = f"On this map: {unresolved_target} unresolved references in Targets."
    return f'<div class="dl-unresolved-banner">{text}</div>'


def _bucket_icon_name(lane: str, key: str) -> str:
    if key in ("Unknown", "Unresolved"):
        return "Unknown"
    return LANE_HEADER_ICON[lane]


def _render_bucket_band(bucket: BucketLayout) -> str:
    """Layout-only band: never interactive, never selectable, and excluded
    from `_graph_payload_json`. `data-x`/`data-w` mirror `.dl-lane`'s own
    base-geometry attributes so `dlScaleCanvas` rescales it the same
    uniform way (cards do not carry these -- see `dlPlaceCard`, which derives
    a card's placement from its lane's own resulting box instead).

    `data-lane` plus `data-bucket` is what identifies a band while focusing a
    selection: a bucket key alone is ambiguous, since `Unknown` and
    `Unresolved` bands exist in more than one lane."""
    icon = _icon_svg(_bucket_icon_name(bucket.lane, bucket.key))
    title = _esc(bucket.title)
    count = bucket.item_count
    count_label = "item" if count == 1 else "items"
    x = bucket.x + BUCKET_CARD_INSET
    width = bucket.width - 2 * BUCKET_CARD_INSET
    warning = ' dl-warning' if bucket.key in _WARNING_BUCKETS else ""
    return (
        f'<div class="dl-bucket{warning}" data-lane="{_esc(bucket.lane)}" data-bucket="{_esc(bucket.key)}" '
        f'data-x="{x}" data-w="{width}" '
        f'style="position: absolute; left: {x}px; top: {bucket.y}px; width: {width}px; '
        f'height: {bucket.height}px; box-sizing: border-box;">'
        '<div class="dl-bucket-header">'
        f'<span class="dl-bucket-icon">{icon}</span>'
        f'<span class="dl-bucket-title">{title}</span>'
        f'{_info_icon(_bucket_info_text(bucket.lane, bucket.key))}'
        f'<span class="dl-bucket-count">{count} {count_label}</span>'
        "</div></div>"
    )


def _placed_nodes(nodes: List[Dict[str, Any]], layout: LineageLayout) -> List[Dict[str, Any]]:
    """The node dicts `layout_lineage` actually placed, in artifact order.

    `layout_lineage` places (and thus `layout.cards` describes) only the
    first *valid-lane* occurrence of an id. If an earlier duplicate had an
    unrecognized Lane and was dropped, this raw node dict is not necessarily
    the one that got placed -- only the occurrence whose own Lane matches
    what was placed is authoritative, so a dropped duplicate's Label/Kind
    never gets shown in the placed card's slot. Detail nodes whose parent is
    missing or in another lane were never placed and so are absent here.
    """
    placed = []
    seen = set()
    for node in nodes:
        node_id = str(node.get("Id"))
        if node_id in seen:
            continue
        card = layout.cards.get(node_id)
        if card is None or node.get("Lane") != card.lane:
            continue
        seen.add(node_id)
        placed.append(node)
    return placed


def _children_by_parent(placed: List[Dict[str, Any]], layout: LineageLayout) -> Dict[str, List[Dict[str, Any]]]:
    """Parent id -> its detail nodes, in artifact order (the projector's
    descending-traffic order). Keyed off `CardLayout.parent_id` rather than
    the raw `ParentId`, so an orphan the layout rejected can never appear."""
    children: Dict[str, List[Dict[str, Any]]] = {}
    for node in placed:
        parent_id = layout.cards[str(node.get("Id"))].parent_id
        if parent_id is not None:
            children.setdefault(parent_id, []).append(node)
    return children


def _render_canvas(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]], layout: LineageLayout) -> str:
    # `layout` decides which lanes exist -- Reports is dropped when nothing
    # lands in it -- so the bands follow the layout rather than every lane the
    # artifact could carry. Lane order still comes from `_LANES`.
    drawn_lanes = [lane for lane in _LANES if lane in layout.lanes]
    lane_bands = "".join(_render_lane_band(lane, layout) for lane in drawn_lanes)
    bucket_bands = "".join(
        _render_bucket_band(bucket) for lane in drawn_lanes for bucket in layout.buckets[lane]
    )
    placed = _placed_nodes(nodes, layout)
    children_by_parent = _children_by_parent(placed, layout)
    cards = []
    rails = []
    toggles = []
    # The browser restack walks cards in DOM order, so emitting each parent
    # immediately followed by its children is what keeps an expanded parent's
    # children under it instead of overlapping the next card in the band.
    for node in placed:
        node_id = str(node.get("Id"))
        if layout.cards[node_id].parent_id is not None:
            continue
        children = children_by_parent.get(node_id, [])
        cards.append(_render_card(node, layout, child_count=len(children)))
        for child in children:
            cards.append(_render_card(child, layout))
        if children:
            rails.append(_render_child_rail(node_id, layout))
            toggles.append(_render_expand_toggle(node, node_id, layout))
    detail_ids = {node_id for node_id, card in layout.cards.items() if card.parent_id is not None}
    svg = _render_edges_svg(edges, layout, detail_ids)
    return (
        '<div class="dl-canvas-wrap">'
        # The report pane is fluid, so the canvas is a block that fills it and
        # only falls back to horizontal scrolling below the base layout width.
        # `data-layout-width` is that base width: the script divides the pane's
        # real width by it to get the x-axis scale for lanes, cards, and edges.
        f'<div class="dl-canvas" data-layout-width="{layout.width}" '
        f'data-card-max-w="{NODE_MAX_WIDTH}" data-card-inset="{LANE_CARD_INSET}" '
        # Focusing a selection restacks the surviving cards from the top of
        # each lane, which is `layout_lineage`'s own vertical arithmetic run
        # again in the browser -- so it reads these constants from here rather
        # than repeating their values in the script.
        f'data-canvas-padding="{CANVAS_PADDING}" data-lane-header-h="{LANE_HEADER_HEIGHT}" '
        f'data-bucket-header-h="{BUCKET_HEADER_HEIGHT}" data-node-h="{NODE_HEIGHT}" '
        f'data-row-gap="{ROW_GAP}" data-bucket-gap="{BUCKET_GAP}" data-min-h="{MIN_CANVAS_HEIGHT}" '
        f'data-child-inset="{CHILD_INSET}" '
        f'data-toggle-inset-x="{TOGGLE_INSET_X}" data-toggle-inset-y="{TOGGLE_INSET_Y}" '
        f'style="position: relative; min-width: {layout.width}px; height: {layout.height}px; box-sizing: border-box;">'
        + lane_bands
        + bucket_bands
        + "".join(rails)
        + "".join(cards)
        + "".join(toggles)
        + svg
        + "</div></div>"
    )


def _render_lane_band(lane: str, layout: LineageLayout) -> str:
    lane_layout = layout.lanes[lane]
    icon = _icon_svg(LANE_HEADER_ICON[lane])
    title = _esc(_LANE_TITLE[lane])
    copy = _esc(_LANE_COPY[lane])
    count = lane_layout.item_count
    count_label = "item" if count == 1 else "items"
    inner_height = max(0, layout.height - 2 * CANVAS_PADDING)
    return (
        f'<div class="dl-lane" data-lane="{lane}" data-x="{lane_layout.x}" data-w="{lane_layout.width}" '
        f'style="position: absolute; left: {lane_layout.x}px; top: {CANVAS_PADDING}px; '
        f'width: {lane_layout.width}px; height: {inner_height}px; box-sizing: border-box;">'
        '<div class="dl-lane-header">'
        f'<span class="dl-lane-icon">{icon}</span>'
        f'<span class="dl-lane-title">{title}</span>'
        f'{_info_icon(_LANE_INFO[lane], "dl-lane-info")}'
        f'<span class="dl-lane-desc">{copy}</span>'
        f'<span class="dl-lane-count">{count} {count_label}</span>'
        "</div></div>"
    )


def _fallback_system_card_label(node: Dict[str, Any], is_detail: bool = False) -> str:
    """A fallback (no-Database) system card's `Label` is the raw bucket key
    (e.g. `SqlServer`), so it reads inconsistently next to that same bucket's
    already-humanized header (`SQL Server`). Reuses `bucket_title`'s existing
    map -- never invents new copy -- and only for the fallback case; a
    database-grain card's `Label` is a real database name and must render
    verbatim.

    Humanization additionally requires `Platform` to be present: a card can
    also fall back to a database/schema identity (bucket = database, else
    schema) when neither `Platform` nor `CustomKind` is known, and per the
    JSON contract `Platform` is then omitted entirely. That schema/database
    identity is an arbitrary name, not a platform key, so it must never be
    run through `bucket_title`'s platform-name map -- even if it happens to
    collide with one of its keys. `Platform` holds `CustomKind`'s value when
    that is what produced the bucket (`Platform` = `Source.Platform`, else
    `CustomKind`), so this gate preserves CustomKind-as-Platform cards
    (e.g. `Files`) going through humanization exactly like a real platform.

    `is_detail` comes from `CardLayout.parent_id` -- the layout's own verdict
    on whether this node is a child -- never from `ParentId`'s truthiness: a
    whitespace-only value is a malformed field the layout already discarded,
    and reading it raw would strip an aggregate card's humanization.
    """
    kind_lower = str(node.get("Kind", "")).strip().lower()
    if (
        not is_detail
        and kind_lower == "etl_system"
        and node.get("Platform")
        and node.get("Label") == node.get("Platform")
    ):
        return bucket_title(str(node.get("Label", "")))
    if is_detail or kind_lower != "system" or node.get("Database") or not node.get("Platform"):
        # A detail node's Label is the schema it represents -- an arbitrary
        # identifier, never a platform key, so it bypasses the map for the
        # same reason a database-grain card's Label does.
        return str(node.get("Label", ""))
    return bucket_title(str(node.get("Label", "")))


def _grain_nouns(node: Dict[str, Any]) -> Tuple[str, str]:
    """What this platform calls the thing a card expands into, singular and
    plural. An Oracle schema is a user; Teradata's schema-level container is
    a database."""
    kind = str(node.get("Kind") or "").strip().lower()
    platform = str(node.get("Platform") or "").strip()
    if platform == "PowerBI" and kind in ("report_system", "report_report"):
        return "report", "reports"
    if platform == "Ssis" and kind in ("etl_system", "etl_package"):
        return "package", "packages"
    if platform == "Oracle":
        return "user", "users"
    if platform == "Teradata":
        return "database", "databases"
    return "schema", "schemas"


def _detail_meta(node: Dict[str, Any]) -> str:
    platform = str(node.get("Platform") or "").strip()
    singular = _grain_nouns(node)[0]
    if platform:
        return f"{bucket_title(platform)} {singular}"
    return singular.capitalize()


def _render_expand_toggle(node: Dict[str, Any], parent_id: str, layout: LineageLayout) -> str:
    """The control is a sibling of the card it expands, not a child of it: a
    collapsed card is `role="button"`, so nesting a `<button>` inside it is
    invalid content and folds the toggle's copy into the card's accessible
    name. `data-toggle-for` is how the delegated handler learns which card it
    belongs to, so nothing has to walk the DOM or take an id apart.

    It is placed at the card's bottom-right corner and pulled back inside by
    the CSS translate, which right/bottom-aligns it without anyone measuring
    the button's rendered width. Every word it shows or announces ships as a
    data attribute: only Python knows whether this platform expands into
    schemas or databases.
    """
    card = layout.cards[parent_id]
    label = _esc(_fallback_system_card_label(node))
    plural = _grain_nouns(node)[1]
    expand = f"Expand {label} {plural}"
    collapse = f"Collapse {label} {plural}"
    return (
        f'<button type="button" class="dl-expand-toggle" data-toggle-for="{_esc(parent_id)}" '
        f'aria-expanded="false" aria-label="{expand}" '
        f'data-expand-label="{expand}" data-collapse-label="{collapse}" '
        f'data-expand-text="Expand" data-collapse-text="Collapse" '
        f'style="position: absolute; left: {card.x + layout.card_width - TOGGLE_INSET_X}px; '
        f'top: {card.y + NODE_HEIGHT - TOGGLE_INSET_Y}px;">Expand</button>'
    )


def _render_card(node: Dict[str, Any], layout: LineageLayout, child_count: int = 0) -> str:
    node_id = str(node.get("Id"))
    card = layout.cards[node_id]
    is_detail = card.parent_id is not None
    label = _esc(_fallback_system_card_label(node, is_detail))
    kind = node.get("Kind", "")
    accent = _accent_color(node)
    icon = _icon_svg(icon_name(kind, node.get("Label", ""), node.get("Platform")))
    meta = _esc(_detail_meta(node) if is_detail else _humanize_kind(kind))
    width = layout.card_width - CHILD_INSET if is_detail else layout.card_width
    if is_detail:
        # Rendered collapsed, and hidden from assistive technology as well as
        # from view -- `display: none` alone would be undone the moment a
        # future rule made a collapsed child merely transparent.
        singular, plural = _grain_nouns(node)
        classes = "dl-card dl-detail-card dl-collapsed dl-hidden"
        hierarchy = (
            f'data-parent-id="{_esc(card.parent_id)}" '
            # The header counts name the grain too, and only Python knows it.
            f'data-grain-one="{_esc(singular)}" data-grain-many="{_esc(plural)}" '
        )
        a11y = 'role="button" tabindex="-1" aria-pressed="false" aria-hidden="true"'
    else:
        classes = "dl-card dl-warning" if _is_warning_node(node) else "dl-card"
        hierarchy = f'data-child-count="{child_count}" ' if child_count else ""
        a11y = 'role="button" tabindex="0" aria-pressed="false"'
    # data-id carries the artifact-controlled id as an HTML attribute value only
    # (html.escape makes it safe there) -- it is never interpolated into an
    # inline event-handler string, which the click-delegation script reads via
    # getAttribute() instead of eval-adjacent string concatenation.
    # No data-x/data-w here: unlike lanes/buckets, a card is never uniformly
    # rescaled from a base pair -- dlPlaceCard derives its placement from its
    # own lane's already-scaled, resulting box (see dlScaleCanvas), so a
    # per-card base-geometry attribute would just be unread dead weight.
    return (
        f'<div class="{classes}" data-id="{_esc(node_id)}" data-lane="{_esc(node.get("Lane", ""))}" '
        f'data-bucket="{_esc(bucket_key(node))}" {hierarchy}'
        f'style="position: absolute; left: {card.x}px; top: {card.y}px; width: {width}px; '
        f'height: {layout.card_height}px;" {a11y}>'
        f'<div class="dl-card-accent" style="background: {accent};"></div>'
        f'<div class="dl-card-icon">{icon}</div>'
        f'<div class="dl-card-title">{label}</div>'
        f'<div class="dl-card-meta">{meta}</div>'
        "</div>"
    )


def _render_child_rail(parent_id: str, layout: LineageLayout) -> str:
    """The vertical tie between an expanded parent and its last visible child.
    Sits outside the parent card because that card clips its overflow and is a
    fixed height; the script gives it its real top/height on every restack."""
    card = layout.cards[parent_id]
    return (
        f'<div class="dl-child-rail dl-hidden" data-rail-for="{_esc(parent_id)}" aria-hidden="true" '
        f'style="position: absolute; left: {card.x + CHILD_INSET // 2}px; top: {card.y + NODE_HEIGHT}px; '
        'height: 0px;"></div>'
    )


def _render_edges_svg(edges: List[Dict[str, Any]], layout: LineageLayout, detail_ids: Set[str]) -> str:
    paths = []
    for edge in edges:
        geo = edge_path(edge, layout)
        if geo is None:
            continue
        # A detail edge belongs to the expanded grain, which nothing is in
        # until the reader expands a card -- so it ships hidden, and the
        # script's first dlApplyView() confirms rather than establishes that.
        if geo.from_id in detail_ids or geo.to_id in detail_ids:
            attrs = 'class="dl-edge dl-detail-edge dl-hidden" aria-hidden="true" '
        else:
            attrs = 'class="dl-edge" '
        paths.append(
            f'<path {attrs}data-from="{_esc(geo.from_id)}" data-to="{_esc(geo.to_id)}" '
            f'd="{geo.d}" marker-end="url(#dl-arrow)"></path>'
        )
    # Two markers, both userSpaceOnUse (fixed pixel size regardless of the
    # path's stroke-width): the default hairline arrow, and a selected-blue
    # twin the JS swaps `marker-end` to when an edge gains `.dl-selected`.
    # Named markers are more broadly supported than SVG2 `context-stroke`.
    return (
        # `width: 100%` overrides the base width attribute so the overlay grows
        # with the canvas instead of clipping the scaled-out edges. There is
        # deliberately no viewBox: the SVG is resized, never scaled, so its user
        # space stays 1:1 with the cards' pixels and strokes and arrowheads keep
        # their authored size.
        f'<svg class="dl-edges" width="{layout.width}" height="{layout.height}" '
        'style="position: absolute; inset: 0; width: 100%; pointer-events: none; z-index: 1;">'
        "<defs>"
        '<marker id="dl-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" '
        'markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#D8DEE7"></path></marker>'
        '<marker id="dl-arrow-selected" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" '
        'markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#1A6CE7"></path></marker>'
        "</defs>"
        + "".join(paths)
        + "</svg>"
    )


def _render_details_strip() -> str:
    fields = ("Name", "Role", "Type", "Lane", "Upstream", "Downstream")
    field_html = "".join(
        f'<div class="dl-detail-field"><span class="dl-detail-label">{f}</span>'
        f'<span id="dl-detail-{f.lower()}" class="dl-detail-value"></span></div>'
        for f in fields
    )
    # aria-live announces the swapped-in details when a card is selected --
    # the selection happens elsewhere on the page (the canvas), so a screen
    # reader gets no other signal that this strip changed.
    return (
        '<div id="dl-details" class="dl-details" aria-live="polite">'
        '<div id="dl-detail-empty" class="dl-detail-empty-copy">Select a card to see its details.</div>'
        f'<div id="dl-detail-fields" class="dl-detail-fields" hidden>{field_html}</div>'
        "</div>"
    )


def _visible_missing_inputs(missing_inputs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [m for m in missing_inputs if m.get("Kind") != _SUPPRESSED_MISSING_INPUT_KIND]


def _render_missing_inputs(missing_inputs: List[Dict[str, Any]]) -> str:
    visible = _visible_missing_inputs(missing_inputs)
    if not visible:
        return ""
    rows = "".join(
        '<div class="dl-ask">'
        f'<div class="dl-ask-copy">{_esc(m.get("Ask", ""))}</div>'
        f'<div class="dl-ask-meta">{_esc(m.get("Technology", ""))} &middot; {_esc(m.get("Count", 0))}</div>'
        "</div>"
        for m in visible
    )
    return f'<h2 class="dl-section-title">Missing inputs</h2><div class="dl-asks">{rows}</div>'


def _render_narrative_and_findings(narrative: Any, findings: List[Dict[str, Any]]) -> str:
    parts = []
    if narrative:
        parts.append(f'<h2 class="dl-section-title">Narrative</h2><p class="dl-narrative">{_esc(narrative)}</p>')
    if findings:
        items = "".join(
            '<div class="dl-finding">'
            f'<div class="dl-finding-title">{_esc(f.get("Title", ""))}</div>'
            f'<div class="dl-finding-body">{_esc(f.get("Body", ""))}</div>'
            "</div>"
            for f in findings
        )
        parts.append(f'<h2 class="dl-section-title">Findings</h2><div class="dl-findings">{items}</div>')
    return "".join(parts)


def _node_payload(node: Dict[str, Any], layout: LineageLayout) -> Dict[str, Any]:
    """One graph node. `parentId`/`schema` appear only on detail nodes, which
    is how the script tells the two grains apart without parsing an id."""
    card = layout.cards[str(node.get("Id"))]
    entry: Dict[str, Any] = {
        "id": str(node.get("Id")),
        # Must match `_render_card`'s displayed title exactly (e.g. the
        # SqlServer -> SQL Server fallback-card humanization): this is the
        # details strip's Name, and it would otherwise disagree with the card
        # the user just clicked.
        "label": _fallback_system_card_label(node, card.parent_id is not None),
        "kind": node.get("Kind", ""),
        "lane": node.get("Lane", ""),
    }
    if card.parent_id is not None:
        entry["parentId"] = card.parent_id
        # Must match `_render_card`'s meta line for the same reason `label`
        # must match its title: this is the details strip's Type, and `kind`
        # alone would report every child as a bare "System".
        entry["typeLabel"] = _detail_meta(node)
        schema = str(node.get("Schema") or "").strip()
        if schema:
            entry["schema"] = schema
    return entry


def _graph_payload_json(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]], layout: LineageLayout) -> str:
    """Serialize Canvas.Nodes/Edges for the click-to-highlight script.

    The result is JS source, not HTML: `_js_with_graph` assigns it to a
    variable in the tab's own `<script>` block, which sits outside the
    report's Vue root. It cannot live in the tab body — Vue 3 compiles the
    mounted template and drops a `<script>` element out of it entirely, so a
    payload embedded there would be gone by the time this script ran.

    Artifact strings are therefore not HTML-escaped (that would corrupt the
    JSON). Instead every literal `<` is rewritten to the JSON- and
    JS-legal unicode escape `\\u003c`, so an artifact label can never
    introduce a raw `<` into the script element's text content — not just
    `</script`, which is the only sequence that closes the tag, but also
    `<!--`, which would otherwise put the HTML parser into
    script-data-double-escaped state with different (and easy to get wrong)
    closing rules. `ensure_ascii` keeps U+2028/U+2029 escaped too; raw, they
    are line terminators to a JS parser but not to a JSON one.
    """
    # Same rule as `_render_canvas`: only the occurrence whose own Lane
    # matches the one `layout_lineage` actually placed is "the" node for this
    # id, so the payload and the canvas never disagree about which duplicate
    # occurrence is authoritative.
    visible_nodes = _placed_nodes(nodes, layout)

    payload = {
        "nodes": [
            _node_payload(n, layout)
            for n in visible_nodes
        ],
        "edges": [
            {"from": geo.from_id, "to": geo.to_id}
            for geo in (edge_path(e, layout) for e in edges)
            if geo is not None
        ],
    }
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return raw.replace("<", "\\u003c")


_EMPTY_GRAPH_JSON = '{"nodes":[],"edges":[]}'


def _js_with_graph(graph_json: str) -> str:
    """Prefix the tab's script with its graph payload assignment.

    Both halves are emitted into the report's standalone Data Lineage script
    block, outside the Vue root, so the payload survives template
    compilation and is already defined when the IIFE below reads it. The
    variable name is repeated in `_JS`; a test pins the two together.
    """
    return f"var __SCAI_DATA_LINEAGE_GRAPH__ = {graph_json};\n{_JS}"


_JS = """
(function () {
    var ROOT = '#data-lineage-report';
    var graph = (typeof __SCAI_DATA_LINEAGE_GRAPH__ === 'object' && __SCAI_DATA_LINEAGE_GRAPH__) || {};
    var nodesById = {};
    (graph.nodes || []).forEach(function (n) { nodesById[n.id] = n; });
    var dlAllIds = new Set(Object.keys(nodesById));
    var childrenByParent = {};
    dlAllIds.forEach(function (id) {
        var parentId = nodesById[id].parentId;
        if (parentId) { (childrenByParent[parentId] = childrenByParent[parentId] || []).push(id); }
    });
    var edges = graph.edges || [];
    var dlSelectedId = null;
    // Expansion is per aggregate card, so one platform can be expanded while
    // another stays folded and the canvas mixes the two grains correctly.
    var dlExpandedParents = {};
    function dlAnyExpanded() { return Object.keys(dlExpandedParents).length > 0; }

    var KIND_LABELS = { system: 'System', etl_pipeline: 'ETL pipeline', etl_system: 'ETL system', etl_package: 'ETL package', report_system: 'Power BI', report_report: 'Power BI report', unresolved: 'Unresolved' };
    function dlHumanizeKind(kind) {
        if (KIND_LABELS[kind]) { return KIND_LABELS[kind]; }
        if (!kind) { return 'Unknown'; }
        return kind.replace(/_/g, ' ').replace(/\\b\\w/g, function (c) { return c.toUpperCase(); });
    }
    function dlRoleForLane(lane) {
        if (lane === 'source') { return 'Source'; }
        if (lane === 'pipeline') { return 'Pipeline'; }
        if (lane === 'target') { return 'Target'; }
        if (lane === 'report') { return 'Report'; }
        return '';
    }

    // Which grain an edge belongs to, decided from node metadata rather than
    // by parsing an id: a detail edge counts only while its parent is
    // expanded, and an aggregate edge only while both endpoints are folded.
    function dlEdgeIsAtVisibleGrain(edge) {
        var from = nodesById[edge.from];
        var to = nodesById[edge.to];
        var fromParent = from && from.parentId;
        var toParent = to && to.parentId;
        // First, unconditionally: an expanded card has handed its edges to
        // its children, so nothing may start or end on it whatever shape a
        // future artifact gives the edge.
        if (dlExpandedParents[edge.from] || dlExpandedParents[edge.to]) { return false; }
        if (fromParent) { return Boolean(dlExpandedParents[fromParent]); }
        if (toParent) { return Boolean(dlExpandedParents[toParent]); }
        return true;
    }

    // The ids focus may traverse. An expanded parent is deliberately absent:
    // it carries no edges at this grain, and it stays on screen only as its
    // children's container (see dlComputeVisibleIds).
    function dlActiveIds() {
        var active = new Set();
        dlAllIds.forEach(function (id) {
            var parentId = nodesById[id].parentId;
            if (parentId) {
                if (dlExpandedParents[parentId]) { active.add(id); }
                return;
            }
            if (!dlExpandedParents[id]) { active.add(id); }
        });
        return active;
    }

    // Mirrors lineage_layout.connected_lineage: walk edges both directions from the
    // selected id, restricted to the active ids, skipping dangling refs and
    // self-loops. Both the edge list and the id universe are arguments so
    // expansion, focus, and resize cannot drift apart on what "visible" means.
    function dlConnectedLineage(selected, activeEdges, activeIds) {
        if (!selected || !activeIds.has(selected)) {
            return { selected: null, upstream: [], downstream: [], path: {} };
        }
        var forward = {};
        var backward = {};
        activeEdges.forEach(function (e) {
            if (!e.from || !e.to || e.from === e.to) { return; }
            if (!activeIds.has(e.from) || !activeIds.has(e.to)) { return; }
            (forward[e.from] = forward[e.from] || []).push(e.to);
            (backward[e.to] = backward[e.to] || []).push(e.from);
        });
        function walk(start, adjacency) {
            var seen = {};
            var stack = [start];
            while (stack.length) {
                var current = stack.pop();
                (adjacency[current] || []).forEach(function (next) {
                    if (next !== start && !seen[next]) { seen[next] = true; stack.push(next); }
                });
            }
            return Object.keys(seen);
        }
        var downstream = walk(selected, forward);
        var upstream = walk(selected, backward);
        var path = {};
        downstream.concat(upstream).forEach(function (id) { path[id] = true; });
        return { selected: selected, upstream: upstream, downstream: downstream, path: path };
    }

    function dlSetText(id, value) {
        var el = document.getElementById(id);
        if (el) { el.textContent = value; }
    }

    function dlFillDetails(connected) {
        var empty = document.getElementById('dl-detail-empty');
        var fields = document.getElementById('dl-detail-fields');
        if (!connected.selected) {
            if (empty) { empty.hidden = false; }
            if (fields) { fields.hidden = true; }
            return;
        }
        var node = nodesById[connected.selected];
        if (!node) { return; }
        if (empty) { empty.hidden = true; }
        if (fields) { fields.hidden = false; }
        dlSetText('dl-detail-name', node.label || '');
        dlSetText('dl-detail-role', dlRoleForLane(node.lane));
        // Every detail node is Kind `system`, which would report an Oracle
        // schema as "System". The renderer publishes the grain it already
        // names on the card, since only it knows this platform's word for it.
        dlSetText('dl-detail-type', node.typeLabel || dlHumanizeKind(node.kind));
        dlSetText('dl-detail-lane', node.lane || '');
        dlSetText('dl-detail-upstream', String(connected.upstream.length));
        dlSetText('dl-detail-downstream', String(connected.downstream.length));
    }

    // A bucket key repeats across lanes (`Unknown`/`Unresolved` exist in more
    // than one), so a band is identified by the (lane, bucket) pair. The
    // separator is a NUL, which cannot occur in either attribute value.
    function dlBucketSlot(lane, bucket) { return lane + '\\u0000' + bucket; }

    function dlEdgeKey(from, to) { return from + '\\u0000' + to; }

    // Hidden has to mean hidden for everyone: the class and the ARIA state are
    // set together so a future rule that merely fades an element cannot
    // silently leave it announced.
    function dlSetHidden(el, hidden) {
        el.classList.toggle('dl-hidden', hidden);
        if (hidden) { el.setAttribute('aria-hidden', 'true'); }
        else { el.removeAttribute('aria-hidden'); }
    }

    // A rail is decoration -- it says nothing the cards it joins do not
    // already say -- so it stays aria-hidden on screen as well as off, and
    // never goes through dlSetHidden.
    function dlSetRailShown(rail, shown) {
        rail.classList.toggle('dl-hidden', !shown);
    }

    // Sole owner of a card's role, pressed state and tab order. An expanded
    // parent becomes a container rather than a *disabled* button: it is still
    // the anchor its children and its Collapse control are positioned against.
    function dlSetCardSemantics(card, shown, expanded, selected) {
        if (expanded) {
            card.setAttribute('role', 'group');
            card.removeAttribute('aria-pressed');
        } else {
            card.setAttribute('role', 'button');
            card.setAttribute('aria-pressed', selected ? 'true' : 'false');
        }
        card.setAttribute('tabindex', shown && !expanded ? '0' : '-1');
    }

    function dlPluralItems(count) { return count + (count === 1 ? ' item' : ' items'); }

    // Header counts state how many cards a lane/band holds, so while focused
    // they have to count what is actually on screen. The pre-selection text is
    // captured once (never recomputed) so deselecting restores it verbatim.
    function dlCaptureBaseCounts() {
        document.querySelectorAll(ROOT + ' .dl-lane-count, ' + ROOT + ' .dl-bucket-count').forEach(function (el) {
            el.setAttribute('data-base-count', el.textContent);
        });
    }

    // A lane can hold more than one platform, and they need not share a word
    // for what a card expands into, so children are tallied per grain noun
    // and kept in first-seen order rather than merged under one label.
    function dlChildGroups(store, key) {
        return (store[key] = store[key] || { byNoun: {}, order: [] });
    }

    function dlCountChild(groups, card) {
        var one = card.getAttribute('data-grain-one') || '';
        var many = card.getAttribute('data-grain-many') || one;
        var group = groups.byNoun[one + '\\u0000' + many];
        if (!group) {
            group = { one: one, many: many, count: 0 };
            groups.byNoun[one + '\\u0000' + many] = group;
            groups.order.push(group);
        }
        group.count += 1;
    }

    // Counts state how many *cards* a lane/band holds, which stays the number
    // of aggregate cards at either grain -- an expanded card's children are
    // appended ("1 item \\u00B7 9 schemas") rather than replacing that number.
    function dlSetCount(el, count, groups) {
        if (!el) { return; }
        if (count === null) { el.textContent = el.getAttribute('data-base-count') || el.textContent; return; }
        var text = dlPluralItems(count);
        ((groups && groups.order) || []).forEach(function (group) {
            text += ' \\u00B7 ' + group.count + ' ' + (group.count === 1 ? group.one : group.many);
        });
        el.textContent = text;
    }

    // Everything a focus restacks. The edge overlay is in the list because its
    // `height` attribute maps to CSS height, which beats its `inset: 0`
    // stretch: left alone it overhangs the shrunken canvas.
    var DL_SIZED = ' .dl-lane, ' + ROOT + ' .dl-bucket, ' + ROOT + ' .dl-card, ' + ROOT + ' .dl-edges';

    // Captured before any focus rearranges it, so deselecting restores exactly
    // what Python laid out rather than recomputing it. dlScaleCanvas only ever
    // touches left/width, so top/height stay valid across resizes.
    function dlCaptureBaseGeometry() {
        document.querySelectorAll(ROOT + DL_SIZED).forEach(function (el) {
            el.setAttribute('data-base-top', el.style.top);
            el.setAttribute('data-base-height', el.style.height);
        });
        if (canvas) { canvas.setAttribute('data-base-height', canvas.style.height); }
    }

    function dlRestoreBaseGeometry() {
        document.querySelectorAll(ROOT + DL_SIZED).forEach(function (el) {
            var top = el.getAttribute('data-base-top');
            var height = el.getAttribute('data-base-height');
            if (top !== null) { el.style.top = top; }
            if (height !== null) { el.style.height = height; }
        });
        if (canvas) {
            var canvasHeight = canvas.getAttribute('data-base-height');
            if (canvasHeight !== null) { canvas.style.height = canvasHeight; }
        }
    }

    // lineage_layout's vertical constants, read from the canvas rather than
    // repeated here. Returns null if any is absent or unparseable: skipping
    // the restack is far better than falling back to numbers baked into this
    // script, which would silently drift from the Python layout.
    var dlGeomCache = null;
    function dlGeom() {
        if (dlGeomCache !== null) { return dlGeomCache; }
        if (!canvas) { return null; }
        var names = {
            canvasPadding: 'data-canvas-padding',
            laneHeaderHeight: 'data-lane-header-h',
            bucketHeaderHeight: 'data-bucket-header-h',
            nodeHeight: 'data-node-h',
            rowGap: 'data-row-gap',
            bucketGap: 'data-bucket-gap',
            minHeight: 'data-min-h',
            childInset: 'data-child-inset',
            toggleInsetX: 'data-toggle-inset-x',
            toggleInsetY: 'data-toggle-inset-y'
        };
        var geom = {};
        var keys = Object.keys(names);
        for (var i = 0; i < keys.length; i++) {
            var value = parseFloat(canvas.getAttribute(names[keys[i]]));
            if (isNaN(value)) { return null; }
            geom[keys[i]] = value;
        }
        dlGeomCache = geom;
        return geom;
    }

    // Hiding the unrelated cards in place would strand the survivors down a
    // canvas sized for the whole graph -- the opposite of easier to read. So
    // while focused, the visible cards and their bands are restacked from the
    // top of each lane using layout_lineage's own arithmetic, and the canvas
    // shrinks to the tallest lane.
    function dlCompactToVisible() {
        var geom = dlGeom();
        if (!geom) { return; }
        var laneEls = [];
        var bucketsByLane = {};
        var cardsByBucket = {};
        canvas.querySelectorAll('.dl-lane').forEach(function (el) { laneEls.push(el); });
        canvas.querySelectorAll('.dl-bucket').forEach(function (el) {
            var lane = el.getAttribute('data-lane') || '';
            (bucketsByLane[lane] = bucketsByLane[lane] || []).push(el);
        });
        // DOM order is parent-then-children, so handing out consecutive rows
        // in that order keeps children under their parent and pushes the rest
        // down -- which is what stops two expanded parents from overlapping.
        canvas.querySelectorAll('.dl-card').forEach(function (el) {
            if (el.classList.contains('dl-hidden')) { return; }
            var slot = dlBucketSlot(el.getAttribute('data-lane') || '', el.getAttribute('data-bucket') || '');
            (cardsByBucket[slot] = cardsByBucket[slot] || []).push(el);
        });

        var contentTop = geom.canvasPadding + geom.laneHeaderHeight;
        var tallestLane = 0;
        laneEls.forEach(function (laneEl) {
            var lane = laneEl.getAttribute('data-lane') || '';
            var y = contentTop;
            (bucketsByLane[lane] || []).forEach(function (bucketEl) {
                var cards = cardsByBucket[dlBucketSlot(lane, bucketEl.getAttribute('data-bucket') || '')] || [];
                if (!cards.length) { return; }
                if (y > contentTop) { y += geom.bucketGap; }
                var height = geom.bucketHeaderHeight + cards.length * geom.nodeHeight + (cards.length - 1) * geom.rowGap;
                bucketEl.style.top = y + 'px';
                bucketEl.style.height = height + 'px';
                cards.forEach(function (card, row) {
                    card.style.top = (y + geom.bucketHeaderHeight + row * (geom.nodeHeight + geom.rowGap)) + 'px';
                });
                y += height;
            });
            tallestLane = Math.max(tallestLane, y - contentTop);
        });

        var canvasHeight = Math.max(geom.minHeight, 2 * geom.canvasPadding + geom.laneHeaderHeight + tallestLane);
        canvas.style.height = canvasHeight + 'px';
        laneEls.forEach(function (laneEl) {
            laneEl.style.height = Math.max(0, canvasHeight - 2 * geom.canvasPadding) + 'px';
        });
        var overlay = canvas.querySelector('.dl-edges');
        if (overlay) { overlay.style.height = canvasHeight + 'px'; }
    }

    // Which cards belong on screen, from expansion and focus together. An
    // expanded parent stays only as its children's container, so it is added
    // last -- because a child survived, never because focus reached it.
    function dlComputeVisibleIds(connected) {
        var visible = new Set();
        var focused = Boolean(connected.selected);
        dlAllIds.forEach(function (id) {
            var parentId = nodesById[id].parentId;
            if (parentId) {
                if (!dlExpandedParents[parentId]) { return; }
            } else if (dlExpandedParents[id]) {
                return;
            }
            if (focused && id !== connected.selected && !connected.path[id]) { return; }
            visible.add(id);
        });
        Object.keys(dlExpandedParents).forEach(function (parentId) {
            if (!dlAllIds.has(parentId)) { return; }
            if (!focused) { visible.add(parentId); return; }
            (childrenByParent[parentId] || []).forEach(function (childId) {
                if (visible.has(childId)) { visible.add(parentId); }
            });
        });
        return visible;
    }

    // The one view pipeline. Expansion and focus are two inputs to it, never
    // two competing passes: the grain settles first, focus is computed over
    // the edges that survive it, and only then does anything move on screen.
    function dlApplyView() {
        var activeEdges = edges.filter(dlEdgeIsAtVisibleGrain);
        var activeIds = dlActiveIds();
        // Collapsing a parent takes its children off the graph, so a
        // selection pointing at one of them no longer means anything.
        if (dlSelectedId && !activeIds.has(dlSelectedId)) { dlSelectedId = null; }
        var connected = dlConnectedLineage(dlSelectedId, activeEdges, activeIds);
        var visible = dlComputeVisibleIds(connected);
        var activeEdgeKeys = {};
        activeEdges.forEach(function (e) { activeEdgeKeys[dlEdgeKey(e.from, e.to)] = true; });
        var focusing = Boolean(dlSelectedId) || dlAnyExpanded();

        var aggregatesPerLane = {};
        var aggregatesPerBucket = {};
        var childrenPerLane = {};
        var childrenPerBucket = {};
        document.querySelectorAll(ROOT + ' .dl-card').forEach(function (card) {
            var id = card.getAttribute('data-id');
            var parentId = card.getAttribute('data-parent-id');
            var lane = card.getAttribute('data-lane') || '';
            var slot = dlBucketSlot(lane, card.getAttribute('data-bucket') || '');
            var shown = visible.has(id);
            var isExpanded = Boolean(dlExpandedParents[id]);
            card.classList.remove('dl-selected', 'dl-path', 'dl-hidden');
            card.classList.toggle('dl-expanded', isExpanded);
            if (parentId) { card.classList.toggle('dl-collapsed', !dlExpandedParents[parentId]); }
            dlSetHidden(card, !shown);
            dlSetCardSemantics(card, shown, isExpanded, id === dlSelectedId);
            if (!shown) { return; }
            if (id === dlSelectedId) { card.classList.add('dl-selected'); }
            else if (connected.path[id]) { card.classList.add('dl-path'); }
            if (parentId) {
                dlCountChild(dlChildGroups(childrenPerLane, lane), card);
                dlCountChild(dlChildGroups(childrenPerBucket, slot), card);
            } else {
                aggregatesPerLane[lane] = (aggregatesPerLane[lane] || 0) + 1;
                aggregatesPerBucket[slot] = (aggregatesPerBucket[slot] || 0) + 1;
            }
        });
        document.querySelectorAll(ROOT + ' .dl-bucket').forEach(function (bucket) {
            var slot = dlBucketSlot(bucket.getAttribute('data-lane') || '', bucket.getAttribute('data-bucket') || '');
            var shown = aggregatesPerBucket[slot] || 0;
            dlSetHidden(bucket, focusing && shown === 0);
            dlSetCount(bucket.querySelector('.dl-bucket-count'), focusing ? shown : null, childrenPerBucket[slot]);
        });
        document.querySelectorAll(ROOT + ' .dl-lane').forEach(function (lane) {
            var name = lane.getAttribute('data-lane') || '';
            var shown = aggregatesPerLane[name] || 0;
            dlSetCount(lane.querySelector('.dl-lane-count'), focusing ? shown : null, childrenPerLane[name]);
        });
        document.querySelectorAll(ROOT + ' .dl-edge').forEach(function (edge) {
            var from = edge.getAttribute('data-from');
            var to = edge.getAttribute('data-to');
            edge.classList.remove('dl-selected', 'dl-hidden');
            var isSelected = false;
            // Drawable only at the grain currently on screen, and only while
            // both of its endpoints are still on screen.
            var drawable = Boolean(activeEdgeKeys[dlEdgeKey(from, to)]) && visible.has(from) && visible.has(to);
            if (drawable && dlSelectedId) {
                // The edge touches the selection, or joins two path nodes.
                var touches = from === dlSelectedId || to === dlSelectedId || (connected.path[from] && connected.path[to]);
                if (touches) { edge.classList.add('dl-selected'); isSelected = true; }
                else { drawable = false; }
            }
            dlSetHidden(edge, !drawable);
            edge.setAttribute('marker-end', isSelected ? 'url(#dl-arrow-selected)' : 'url(#dl-arrow)');
        });
        // Both the visible word and the accessible name come from the
        // renderer: only Python knows whether this platform expands into
        // schemas or databases. The control is a sibling of its card, so it
        // no longer disappears with it -- it has to be hidden in step.
        document.querySelectorAll(ROOT + ' .dl-expand-toggle').forEach(function (toggle) {
            var hostId = toggle.getAttribute('data-toggle-for');
            var expanded = Boolean(dlExpandedParents[hostId]);
            dlSetHidden(toggle, !visible.has(hostId));
            toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
            var text = toggle.getAttribute(expanded ? 'data-collapse-text' : 'data-expand-text');
            if (text !== null) { toggle.textContent = text; }
            var label = toggle.getAttribute(expanded ? 'data-collapse-label' : 'data-expand-label');
            if (label !== null) { toggle.setAttribute('aria-label', label); }
        });
        dlFillDetails(connected);
        if (focusing) { dlCompactToVisible(); } else { dlRestoreBaseGeometry(); }
        dlLayoutChildRails();
        dlLayoutToggles();
        dlRelayoutVisibleEdges();
    }

    // Selection id comes only from data-id (an HTML attribute value, already
    // safe via html.escape when rendered) via getAttribute() -- never from an
    // inline onclick string built by interpolating the artifact-controlled id
    // into executable JS.
    function dlToggleCard(id) {
        // An expanded card is a container, not a participant: it carries no
        // edges, so selecting it could only ever focus on nothing.
        if (dlExpandedParents[id]) { return; }
        dlSelectedId = (dlSelectedId === id) ? null : id;
        dlApplyView();
    }

    function dlToggleExpansion(parentId) {
        if (dlExpandedParents[parentId]) { delete dlExpandedParents[parentId]; }
        else { dlExpandedParents[parentId] = true; }
        dlApplyView();
    }

    // The pane is fluid and wider than the rendered base layout on most
    // screens, so stretch the x axis to fill it: lanes and buckets are
    // re-placed from their base data-x/data-w (never from the already-scaled
    // inline style, which would compound across resizes). Cards do not share
    // that uniform stretch -- see dlPlaceCard -- but every edge is still
    // rebuilt from the cards' own resulting boxes, so an endpoint cannot
    // drift off a card border no matter what the scale is. The bezier shape
    // matches lineage_layout.edge_path: control points on the horizontal
    // midpoint.
    function dlPlace(el, scale) {
        var baseX = parseFloat(el.getAttribute('data-x'));
        var baseW = parseFloat(el.getAttribute('data-w'));
        if (isNaN(baseX) || isNaN(baseW)) { return; }
        el.style.left = Math.round(baseX * scale) + 'px';
        el.style.width = Math.round(baseW * scale) + 'px';
    }

    // Uniformly stretching a card the same way as its lane would grow it past
    // NODE_MAX_WIDTH on a wide pane. Instead the card is capped at
    // cardMaxWidth and centered inside its lane's own (already-placed, scaled)
    // box -- reading the lane by name (data-lane), never by parsing a node id.
    // Takes the lane's already-read {left, width} geometry rather than the
    // lane element itself: offsetLeft/offsetWidth force a layout reflow, and a
    // bucket can hold many cards sharing that very same lane box, so the
    // caller reads each lane's geometry exactly once and reuses it here.
    function dlPlaceCard(card, laneGeom, cardMaxWidth, cardInset, childInset) {
        if (!laneGeom) { return; }
        var width = Math.max(0, Math.min(cardMaxWidth, laneGeom.width - 2 * cardInset));
        var left = laneGeom.left + Math.round((laneGeom.width - width) / 2);
        // A child is indented from its parent and narrower by the same amount,
        // so its right edge stays flush and the indent reads as containment.
        if (card.getAttribute('data-parent-id')) {
            left += childInset;
            width = Math.max(0, width - childInset);
        }
        card.style.left = Math.round(left) + 'px';
        card.style.width = Math.round(width) + 'px';
    }

    // Two passes on purpose: `offsetLeft` and friends flush pending layout, so
    // writing a `d` between two reads makes the browser reflow once per edge on
    // a canvas that can carry hundreds. Measure everything, then write.
    function dlLayoutEdges(cardsById) {
        var paths = [];
        document.querySelectorAll(ROOT + ' .dl-edge').forEach(function (edge) {
            var from = cardsById[edge.getAttribute('data-from')];
            var to = cardsById[edge.getAttribute('data-to')];
            if (!from || !to) { return; }
            var x1 = from.offsetLeft + from.offsetWidth;
            var y1 = from.offsetTop + Math.round(from.offsetHeight / 2);
            var x2 = to.offsetLeft;
            var y2 = to.offsetTop + Math.round(to.offsetHeight / 2);
            var midX = (x1 + x2) / 2;
            paths.push({
                edge: edge,
                d: 'M ' + x1 + ' ' + y1 + ' C ' + midX + ' ' + y1 + ', ' + midX + ' ' + y2 + ', ' + x2 + ' ' + y2
            });
        });
        paths.forEach(function (path) { path.edge.setAttribute('d', path.d); });
    }

    // A hidden card has no box (offsetLeft/offsetWidth are 0), so geometry
    // derived from one is garbage. Rebuilding from the visible cards after
    // every visibility change keeps a reappearing edge correct even if the
    // pane was resized while it was hidden.
    function dlRelayoutVisibleEdges() {
        if (!canvas) { return; }
        var cardsById = {};
        canvas.querySelectorAll('.dl-card').forEach(function (card) {
            if (!card.classList.contains('dl-hidden')) { cardsById[card.getAttribute('data-id')] = card; }
        });
        dlLayoutEdges(cardsById);
    }

    // The toggle sits beside its card in the DOM, so it has to be carried to
    // wherever that card ends up -- after a width scale and after a restack.
    // Its card is named by data-toggle-for, and its own right/bottom alignment
    // is a CSS translate, so nothing here reads a rendered box.
    function dlLayoutToggles() {
        var geom = dlGeom();
        if (!canvas || !geom) { return; }
        var cardsById = {};
        canvas.querySelectorAll('.dl-card').forEach(function (card) {
            cardsById[card.getAttribute('data-id')] = card;
        });
        canvas.querySelectorAll('.dl-expand-toggle').forEach(function (toggle) {
            var card = cardsById[toggle.getAttribute('data-toggle-for')];
            if (!card) { return; }
            var left = parseFloat(card.style.left) + parseFloat(card.style.width);
            var top = parseFloat(card.style.top) + geom.nodeHeight;
            if (isNaN(left) || isNaN(top)) { return; }
            toggle.style.left = (left - geom.toggleInsetX) + 'px';
            toggle.style.top = (top - geom.toggleInsetY) + 'px';
        });
    }

    // The rail ties an expanded parent to the last child still on screen. It
    // reads the cards' own inline geometry (which both the restack and the
    // resize keep current) rather than forcing a reflow of its own.
    function dlLayoutChildRails() {
        var geom = dlGeom();
        if (!canvas || !geom) { return; }
        var cardsById = {};
        canvas.querySelectorAll('.dl-card').forEach(function (card) {
            cardsById[card.getAttribute('data-id')] = card;
        });
        canvas.querySelectorAll('.dl-child-rail').forEach(function (rail) {
            var parentId = rail.getAttribute('data-rail-for');
            var parentCard = cardsById[parentId];
            var lastChild = null;
            (childrenByParent[parentId] || []).forEach(function (childId) {
                var childCard = cardsById[childId];
                if (childCard && !childCard.classList.contains('dl-hidden')) { lastChild = childCard; }
            });
            if (!parentCard || parentCard.classList.contains('dl-hidden') || !lastChild) {
                dlSetRailShown(rail, false);
                return;
            }
            var top = parseFloat(parentCard.style.top) + geom.nodeHeight;
            var bottom = parseFloat(lastChild.style.top) + geom.nodeHeight / 2;
            rail.style.left = (parseFloat(parentCard.style.left) + geom.childInset / 2) + 'px';
            rail.style.top = top + 'px';
            rail.style.height = Math.max(0, bottom - top) + 'px';
            dlSetRailShown(rail, true);
        });
    }

    function dlScaleCanvas(canvas) {
        var baseWidth = parseFloat(canvas.getAttribute('data-layout-width'));
        var paneWidth = canvas.clientWidth;
        // clientWidth is 0 while the tab is hidden; the observer re-runs this
        // once it is shown, so bail rather than collapse the canvas.
        if (!baseWidth || !paneWidth) { return; }
        var scale = paneWidth / baseWidth;
        if (scale < 1) { scale = 1; }
        var cardMaxWidth = parseFloat(canvas.getAttribute('data-card-max-w'));
        var cardInset = parseFloat(canvas.getAttribute('data-card-inset')) || 0;
        var childInset = parseFloat(canvas.getAttribute('data-child-inset')) || 0;
        if (isNaN(cardMaxWidth)) { cardMaxWidth = Infinity; }
        var lanesByName = {};
        canvas.querySelectorAll('.dl-lane').forEach(function (lane) {
            dlPlace(lane, scale);
            lanesByName[lane.getAttribute('data-lane')] = lane;
        });
        // Read each scaled lane's resulting box exactly once here, rather than
        // once per card in the loop below -- offsetLeft/offsetWidth force a
        // layout reflow, and a bucket can hold many cards sharing one lane box.
        var laneGeomByName = {};
        Object.keys(lanesByName).forEach(function (name) {
            var laneEl = lanesByName[name];
            laneGeomByName[name] = { left: laneEl.offsetLeft, width: laneEl.offsetWidth };
        });
        canvas.querySelectorAll('.dl-bucket').forEach(function (bucket) { dlPlace(bucket, scale); });
        var cardsById = {};
        canvas.querySelectorAll('.dl-card').forEach(function (card) {
            dlPlaceCard(card, laneGeomByName[card.getAttribute('data-lane')], cardMaxWidth, cardInset, childInset);
            // Hidden cards are still re-placed (so they are correct when shown
            // again) but never feed edge geometry -- their box is collapsed.
            if (!card.classList.contains('dl-hidden')) { cardsById[card.getAttribute('data-id')] = card; }
        });
        dlLayoutChildRails();
        dlLayoutToggles();
        dlLayoutEdges(cardsById);
    }

    // Hovering an info icon used to only change its color: the `title`
    // attribute the markup ships is a no-JS fallback, and the browser's own
    // tooltip needs about a second of stationary hover before it appears. This
    // takes the text over and shows it immediately.
    //
    // The tooltip lives at the report root rather than inside the header it
    // belongs to, and is positioned `fixed`: both the lane and bucket headers
    // are fixed-height with `overflow: hidden`, so a tooltip rendered as their
    // child would be clipped to a sliver. Nothing between here and the
    // viewport uses a transform, so `fixed` really does escape that clipping
    // (a transformed ancestor would make it a containing block instead).
    function dlInitInfoTips() {
        var root = document.querySelector(ROOT);
        var triggers = root ? root.querySelectorAll('.dl-info') : [];
        if (!triggers.length) { return; }

        var tip = document.createElement('div');
        tip.className = 'dl-tip';
        // The text is already on each trigger's aria-label, so announcing the
        // tooltip too would just repeat it.
        tip.setAttribute('aria-hidden', 'true');
        tip.hidden = true;
        root.appendChild(tip);
        var current = null;

        function dlHideTip() {
            current = null;
            tip.hidden = true;
        }

        function dlShowTip(trigger) {
            var text = trigger.getAttribute('data-dl-tip');
            if (!text) { return; }
            current = trigger;
            tip.textContent = text;
            // Park it offscreen for the measuring pass so the reader never
            // sees a frame of it at the previous trigger's position.
            tip.style.left = '-9999px';
            tip.style.top = '0px';
            tip.hidden = false;

            var box = trigger.getBoundingClientRect();
            var margin = 8;
            var viewportWidth = document.documentElement.clientWidth;
            var viewportHeight = document.documentElement.clientHeight;
            var left = box.left + box.width / 2 - tip.offsetWidth / 2;
            // Clamp so an icon in the rightmost lane -- or a narrow window --
            // still gets a fully readable tooltip.
            if (left > viewportWidth - tip.offsetWidth - margin) { left = viewportWidth - tip.offsetWidth - margin; }
            if (left < margin) { left = margin; }
            var top = box.bottom + 6;
            if (top + tip.offsetHeight > viewportHeight - margin) { top = box.top - tip.offsetHeight - 6; }
            tip.style.left = left + 'px';
            tip.style.top = top + 'px';
        }

        triggers.forEach(function (trigger) {
            // Moving `title` off the element is what keeps the browser's own
            // delayed tooltip from surfacing a second later on top of this one.
            var text = trigger.getAttribute('title');
            if (text) {
                trigger.setAttribute('data-dl-tip', text);
                trigger.removeAttribute('title');
            }
            trigger.addEventListener('mouseenter', function () { dlShowTip(trigger); });
            trigger.addEventListener('focus', function () { dlShowTip(trigger); });
            trigger.addEventListener('mouseleave', dlHideTip);
            trigger.addEventListener('blur', dlHideTip);
        });

        // WCAG 1.4.13: content shown on hover has to be dismissable without
        // moving the pointer. Scrolling hides it too -- the tooltip is
        // viewport-positioned, so it would otherwise hang over a canvas that
        // has already moved out from under it.
        document.addEventListener('keydown', function (e) {
            if ((e.key === 'Escape' || e.key === 'Esc') && current) { dlHideTip(); }
        });
        window.addEventListener('scroll', dlHideTip, true);
    }

    dlInitInfoTips();

    var canvas = document.querySelector(ROOT + ' .dl-canvas');
    if (canvas) {
        dlCaptureBaseCounts();
        dlCaptureBaseGeometry();
        dlScaleCanvas(canvas);
        // Nothing is expanded or selected yet, so this only confirms the state
        // Python rendered -- but it is the same call every later change makes,
        // which is what keeps the two from ever describing different canvases.
        dlApplyView();
        if (typeof ResizeObserver === 'function') {
            new ResizeObserver(function () { dlScaleCanvas(canvas); }).observe(canvas);
        } else {
            window.addEventListener('resize', function () { dlScaleCanvas(canvas); });
        }
        canvas.addEventListener('click', function (e) {
            // This branch has to return: falling through would reach the
            // deselect-on-empty-canvas fallback below and clear the reader's
            // selection every time they expanded a card. The card it belongs
            // to is named by data-toggle-for -- an HTML attribute value, read
            // with getAttribute() and never parsed or spliced into a selector.
            var toggle = e.target.closest && e.target.closest('.dl-expand-toggle');
            if (toggle) {
                var toggleFor = toggle.getAttribute('data-toggle-for');
                if (toggleFor) { dlToggleExpansion(toggleFor); }
                return;
            }
            var card = e.target.closest && e.target.closest('.dl-card');
            if (card) { dlToggleCard(card.getAttribute('data-id')); return; }
            // Only the bucket *header* is layout-only-and-inert per the
            // interaction contract -- clicking it does nothing, so the current
            // selection (if any) must survive rather than being cleared by the
            // "click empty space to deselect" fallback below. The rest of a
            // bucket's box (the blank space between/below its cards, which is
            // still geometrically inside `.dl-bucket`) is empty canvas and must
            // still clear the selection, so the check is scoped to the header
            // element, not the whole bucket.
            var bucketHeader = e.target.closest && e.target.closest('.dl-bucket-header');
            if (bucketHeader) { return; }
            dlSelectedId = null;
            dlApplyView();
        });
        canvas.addEventListener('keydown', function (e) {
            if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') { return; }
            // A real button already turns Enter/Space into a click, which the
            // delegated click handler above expands on.
            if (e.target.closest && e.target.closest('.dl-expand-toggle')) { return; }
            var card = e.target.closest && e.target.closest('.dl-card');
            if (!card) { return; }
            e.preventDefault();
            dlToggleCard(card.getAttribute('data-id'));
        });
    }
})();
"""

_BASE_CSS = """
/* The host report renders a bare <svg> as a block, which would put every icon
   on a line of its own and overflow the lane header and card boxes. */
#data-lineage-report .dl-icon { display: inline-block; vertical-align: middle; }
/* `flex: 0 0 auto` keeps the icon at its full 16px next to `.dl-bucket-title`,
   which is a `flex: 1 1 auto` ellipsis box and would otherwise squeeze it. */
#data-lineage-report .dl-info { display: inline-flex; align-items: center; vertical-align: middle; flex: 0 0 auto; color: #94A3B8; cursor: help; }
#data-lineage-report .dl-info:hover { color: #1A6CE7; }
#data-lineage-report .dl-info:focus-visible { outline: 2px solid #1A6CE7; outline-offset: 2px; border-radius: 50%; }
#data-lineage-report .dl-lane-info { margin-left: 6px; }
/* `position: fixed` is what lets this escape the `overflow: hidden` on the
   lane and bucket headers it is triggered from; `pointer-events: none` keeps
   it from stealing the hover that is showing it. */
#data-lineage-report .dl-tip { position: fixed; z-index: 1000; max-width: 320px; background: #102E46; color: #fff; font-size: 12px; line-height: 1.45; padding: 8px 10px; border-radius: 6px; box-shadow: 0 4px 12px rgba(16, 46, 70, 0.24); pointer-events: none; }
#data-lineage-report .dl-tip[hidden] { display: none; }
#data-lineage-report .dl-kpis { margin-bottom: 18px; }
#data-lineage-report .dl-unresolved-banner { background: #FFF7E6; border: 1px solid #F5D68A; border-radius: 8px; padding: 10px 14px; margin-bottom: 16px; font-size: 13px; color: #7A5B00; }
#data-lineage-report .dl-canvas-wrap { width: 100%; overflow-x: auto; margin-bottom: 20px; }
#data-lineage-report .dl-canvas { background: #fff; border: 1px solid #E2E8F0; border-radius: 8px; }
#data-lineage-report .dl-lane { background: #FAFBFC; border: 1px solid #EBEEF3; border-radius: 6px; }
#data-lineage-report .dl-lane-icon { color: #5D6A85; margin-right: 6px; }
#data-lineage-report .dl-lane-title { font-weight: 700; font-size: 14px; color: #102E46; }
#data-lineage-report .dl-lane-desc { display: block; font-size: 12px; line-height: 16px; color: #64748B; margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#data-lineage-report .dl-lane-count { display: block; font-size: 11px; line-height: 14px; color: #94A3B8; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.04em; }
#data-lineage-report .dl-bucket { background: #FCFCFD; border: 1px dashed #E2E8F0; border-radius: 6px; }
#data-lineage-report .dl-bucket.dl-warning { background: #FFF7E6; border-color: #F5D68A; }
#data-lineage-report .dl-bucket-icon { color: #94A3B8; }
#data-lineage-report .dl-bucket-title { font-weight: 600; font-size: 12px; color: #334155; flex: 1 1 auto; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#data-lineage-report .dl-bucket-count { font-size: 11px; color: #94A3B8; white-space: nowrap; }
#data-lineage-report .dl-card { z-index: 2; background: #fff; border: 1px solid #E4E8EE; border-radius: 6px; box-sizing: border-box; padding: 8px 10px 8px 14px; cursor: pointer; overflow: hidden; }
#data-lineage-report .dl-card:focus-visible { outline: 2px solid #1A6CE7; outline-offset: 1px; }
#data-lineage-report .dl-card-accent { position: absolute; left: 0; top: 0; bottom: 0; width: 4px; }
#data-lineage-report .dl-card-icon { color: #5D6A85; line-height: 16px; }
#data-lineage-report .dl-card-title { font-weight: 600; font-size: 13px; line-height: 20px; color: #102E46; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#data-lineage-report .dl-card-meta { font-size: 11px; line-height: 16px; color: #64748B; }
#data-lineage-report .dl-card.dl-selected { outline: 2px solid #1A6CE7; outline-offset: 1px; }
#data-lineage-report .dl-card.dl-path { background: #F5FAFE; }
#data-lineage-report .dl-card.dl-warning { background: #FFF7E6; border-color: #F5D68A; }
/* #7A5B00 on #FFF7E6 clears WCAG AA (>= 4.5:1) for small text; the base
   .dl-card-meta gray (#64748B) does not on this much-lighter background. */
#data-lineage-report .dl-card.dl-warning .dl-card-meta { color: #7A5B00; }
/* Warning status must survive focus: a warning card that also lands on the
   highlighted path (.dl-path) keeps its yellow background/border rather than
   being masked by the path's light-blue tint. Explicit compound selector so
   this holds regardless of the .dl-path / .dl-warning declaration order
   above (same specificity, so order alone would otherwise decide it). */
#data-lineage-report .dl-card.dl-path.dl-warning { background: #FFF7E6; border-color: #F5D68A; }
/* System expansion: a card with detail nodes reveals them in place. The
   parent stays put as the anchor its children and its toggle are positioned
   against, muted because at that point it is a grouping rather than a
   participant in the lineage. */
/* The toggle is a sibling of its card, positioned at that card's bottom-right
   corner; the translate pulls it back inside so it stays right/bottom aligned
   without anything having to measure its rendered width. */
#data-lineage-report .dl-expand-toggle { position: absolute; transform: translate(-100%, -100%); z-index: 3; padding: 1px 6px; border: 1px solid #D8DEE7; border-radius: 4px; background: #fff; color: #1A6CE7; font-size: 11px; line-height: 14px; cursor: pointer; }
#data-lineage-report .dl-expand-toggle:focus-visible { outline: 2px solid #1A6CE7; outline-offset: 1px; }
#data-lineage-report .dl-expand-toggle.dl-hidden { display: none; }
#data-lineage-report .dl-card.dl-expanded { background: #F8FAFC; border-color: #D8DEE7; cursor: default; }
#data-lineage-report .dl-card.dl-expanded .dl-card-title { color: #64748B; }
#data-lineage-report .dl-card.dl-detail-card { border-style: dashed; }
#data-lineage-report .dl-card.dl-detail-card.dl-collapsed { display: none; }
#data-lineage-report .dl-child-rail { width: 2px; background: #E2E8F0; z-index: 1; }
#data-lineage-report .dl-child-rail.dl-hidden { display: none; }
#data-lineage-report .dl-edge { fill: none; stroke: #D8DEE7; stroke-width: 1; }
#data-lineage-report .dl-edge.dl-selected { stroke: #1A6CE7; stroke-width: 2; }
/* Focus mode: a selection removes everything outside its connected lineage
   from view, so the remaining path is readable on a dense canvas. */
#data-lineage-report .dl-card.dl-hidden { display: none; }
#data-lineage-report .dl-edge.dl-hidden { display: none; }
#data-lineage-report .dl-bucket.dl-hidden { display: none; }
#data-lineage-report .dl-details { border: 1px solid #E2E8F0; border-radius: 8px; padding: 14px; margin-bottom: 20px; background: #F8FAFC; }
#data-lineage-report .dl-detail-empty-copy { color: #64748B; font-size: 13px; }
#data-lineage-report .dl-detail-fields { display: flex; flex-wrap: wrap; gap: 18px; }
/* `display: flex` above overrides the UA stylesheet's `[hidden] { display: none }`,
   so the `hidden` attribute needs its own, later, more specific rule to keep working. */
#data-lineage-report .dl-detail-fields[hidden] { display: none; }
#data-lineage-report .dl-detail-empty-copy[hidden] { display: none; }
#data-lineage-report .dl-detail-field { display: flex; flex-direction: column; min-width: 100px; }
#data-lineage-report .dl-detail-label { font-size: 11px; color: #94A3B8; text-transform: uppercase; letter-spacing: 0.04em; }
#data-lineage-report .dl-detail-value { font-size: 13px; color: #102E46; font-weight: 600; }
#data-lineage-report .dl-section-title { font-size: 1.1rem; font-weight: 700; color: #102E46; margin: 28px 0 12px; }
#data-lineage-report .dl-asks { display: flex; flex-direction: column; gap: 8px; }
#data-lineage-report .dl-ask { border: 1px solid #E2E8F0; border-radius: 6px; padding: 10px 12px; }
#data-lineage-report .dl-ask-meta { font-size: 12px; color: #64748B; margin-top: 4px; }
#data-lineage-report .dl-findings { display: flex; flex-direction: column; gap: 10px; }
#data-lineage-report .dl-finding { border-left: 4px solid #005C8F; padding: 6px 12px; background: #fff; }
#data-lineage-report .dl-finding-title { font-weight: 600; font-size: 13px; color: #102E46; }
#data-lineage-report .dl-finding-body { font-size: 13px; color: #334155; margin-top: 2px; }
"""

# The first card row starts exactly LANE_HEADER_HEIGHT below the lane's top, so
# the header is pinned to that same box and every line inside it is sized in px:
# the header would otherwise inherit the host report's 1.6 line-height and grow
# until the item count sat underneath the first card.
_CSS = _BASE_CSS + (
    "#data-lineage-report .dl-lane-header { padding: 12px; line-height: 20px; "
    f"height: {LANE_HEADER_HEIGHT}px; box-sizing: border-box; overflow: hidden; }}\n"
    "#data-lineage-report .dl-bucket-header { display: flex; align-items: center; gap: 6px; "
    "padding: 8px 12px; line-height: 24px; "
    f"height: {BUCKET_HEADER_HEIGHT}px; box-sizing: border-box; overflow: hidden; }}\n"
)
