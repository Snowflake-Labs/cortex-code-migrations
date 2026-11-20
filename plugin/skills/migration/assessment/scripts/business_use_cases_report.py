"""Readiness section for the business use cases found in an assessment.

The static HTML report lists each use case and the gaps a reader can see
without the dashboard server. Lineage and the deployment plan stay in the
assessment report in the app.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

BUSINESS_USE_CASES_CSS = """
        #business-use-cases-report h1,
        #pending-objects-report h1 {
            font-size: 1.75rem;
            font-weight: 700;
            color: #102E46;
            margin: 0 0 8px;
        }
        .buc-lead { color: #5D6A85; margin: 0 0 12px; max-width: 68ch; line-height: 1.45; }
        .buc-notice {
            background: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-radius: 12px;
            padding: 8px 14px;
            margin: 0 0 12px;
            color: #334155;
        }
        .buc-notice p { margin: 0; line-height: 1.5; }
        .buc-stats { display: flex; flex-wrap: wrap; gap: 12px; margin: 0 0 8px; }
        .buc-stat {
            min-width: 132px;
            background: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-radius: 12px;
            padding: 10px 14px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.04);
        }
        .buc-stat strong {
            display: block;
            font-size: 22px;
            font-weight: 800;
            color: #1E252F;
            line-height: 1.1;
        }
        .buc-stat span { color: #5D6A85; font-size: 14px; }
        .buc-aside { color: #5D6A85; margin: 8px 0 0; line-height: 1.4; font-size: 0.875rem; }
        .buc-card {
            background: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-radius: 12px;
            margin: 10px 0 0;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.04);
        }
        .buc-card-head { padding: 12px 16px 0; }
        .buc-title-row {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 16px;
        }
        .buc-card h2 {
            margin: 0;
            font-size: 1rem;
            font-weight: 700;
            color: #102E46;
        }
        .buc-purpose {
            margin: 2px 0 0;
            color: #64748B;
            font-size: 0.8125rem;
            line-height: 1.4;
        }
        .buc-counts {
            display: flex;
            flex-wrap: wrap;
            align-items: baseline;
            gap: 2px 14px;
            margin: 8px 16px 0;
            padding: 7px 0 0;
            border-top: 1px solid #E2E8F0;
            background: transparent;
        }
        .buc-count {
            display: inline-flex;
            align-items: baseline;
            gap: 4px;
            min-width: 0;
            background: transparent;
            border: 0;
            padding: 0;
        }
        .buc-count strong {
            display: inline;
            font-size: 0.875rem;
            font-weight: 700;
            color: #1E252F;
            line-height: 1.2;
        }
        .buc-count span {
            color: #5D6A85;
            font-size: 0.72rem;
            font-weight: 500;
            letter-spacing: 0;
            text-transform: none;
        }
        .buc-count-effort {
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            flex: none;
            gap: 0;
            margin: 0;
            padding: 0;
            border: 0;
            background: transparent;
            white-space: nowrap;
        }
        .buc-panels {
            display: grid;
            gap: 8px;
            margin: 8px 0 0;
            padding: 8px 16px 12px;
            border-top: 1px solid #F1F5F9;
        }
        .buc-panel,
        .buc-panel-enable {
            background: transparent;
            border: 0;
            padding: 0;
            height: auto;
        }
        .buc-card h3 {
            margin: 0 0 3px;
            font-size: 0.72rem;
            font-weight: 600;
            letter-spacing: 0;
            text-transform: none;
            color: #5D6A85;
        }
        .buc-panel p { margin: 0; color: #1E252F; font-size: 0.8125rem; line-height: 1.4; }
        .buc-card ul {
            columns: 2;
            column-gap: 28px;
            margin: 0;
            padding: 0;
            list-style: none;
        }
        .buc-card li {
            position: relative;
            break-inside: avoid;
            margin: 0 0 4px;
            padding-left: 11px;
            color: #334155;
            font-size: 0.8125rem;
            line-height: 1.35;
        }
        .buc-card li::before {
            content: "";
            position: absolute;
            left: 0;
            top: 0.48em;
            width: 4px;
            height: 4px;
            border-radius: 50%;
            background: #CBD5E1;
        }
        .buc-confirmed { margin: 4px 0 0; color: #166534; font-size: 0.8125rem; line-height: 1.4; }
        .buc-context {
            background: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-radius: 12px;
            margin: 10px 0 0;
            padding: 12px 16px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.04);
        }
        .buc-context h2, .buc-context summary {
            margin: 0; font-size: 1rem; font-weight: 700; color: #102E46;
        }
        .buc-context summary { cursor: pointer; list-style-position: outside; }
        .buc-context > p { margin: 2px 0 8px; color: #64748B; font-size: 0.8125rem; line-height: 1.4; }
        .buc-context ul { margin: 0; padding: 0; list-style: none; }
        .buc-context li { padding: 8px 0 0; border-top: 1px solid #F1F5F9; margin: 8px 0 0; }
        .buc-context li:first-child { border-top: 0; margin-top: 0; padding-top: 0; }
        .buc-context li p { margin: 2px 0 0; color: #334155; font-size: 0.8125rem; line-height: 1.4; }
        .buc-context li p.buc-context-meta { color: #64748B; font-size: 0.75rem; }
        .buc-tag {
            display: inline-block;
            margin-left: 8px;
            padding: 1px 8px;
            border-radius: 999px;
            font-size: 0.7rem;
            font-weight: 600;
            vertical-align: middle;
        }
        .buc-tag-reviewed { background: #DCFCE7; color: #166534; }
        .buc-tag-missing { background: #F1F5F9; color: #475569; }
        .buc-tag-unusable { background: #FEF3C7; color: #92400E; }
        .buc-ai {
            margin: 6px 0 0;
            padding: 6px 10px;
            border-radius: 8px;
            background: #EFF6FF;
            color: #1E3A8A;
            font-size: 0.8125rem;
            line-height: 1.4;
        }
        @media (max-width: 860px) {
            .buc-card ul { columns: 1; }
        }
"""

APP_NOTICE = (
    "These use cases are ready to review in the assessment report in the app. "
    "Lineage and the deployment plan are there."
)

EMPTY_LEAD = "No business use cases were found."
EMPTY_NOTICE = (
    "When the assessment finds them, they are listed here and in the assessment report in the app."
)

# The optional inputs a customer can add to the source code. The report owns the wording of what
# each one adds, so the agent that writes use-case-context.json never has to invent it.
CONTEXT_KINDS = ("bi", "scheduler", "agentJobs", "usage")
CONTEXT_STATUSES = ("reviewed", "notProvided", "unusable")
CONTEXT_LABELS = {
    "bi": "BI layer (reports, dashboards)",
    "scheduler": "Scheduler export (Control-M, cron)",
    "agentJobs": "SQL Server Agent jobs",
    "usage": "Query logs (object usage)",
}
CONTEXT_WOULD_ADD = {
    "bi": (
        "Shows which reports and dashboards read the warehouse, so use cases are confirmed "
        "by who consumes them instead of proposed from structure."
    ),
    "scheduler": (
        "Shows which workflows actually run, how often and in which order, so live jobs are "
        "separated from dead ones and chains of jobs can be grouped into one outcome."
    ),
    "agentJobs": (
        "Shows which packages run, on what schedule and whether the job is enabled, so live "
        "packages are separated from dead ones."
    ),
    "usage": (
        "Shows which tables and views are still read, by how many users and when last, the "
        "strongest proof that a use case is real and still used."
    ),
}
CONTEXT_CONFIRMED_BY = {
    "bi": "BI reports",
    "scheduler": "the scheduler export",
    "agentJobs": "SQL Server Agent jobs",
    "usage": "query logs",
}
_CONTEXT_TAGS = {
    "reviewed": ("Reviewed", "buc-tag-reviewed"),
    "notProvided": ("Not provided", "buc-tag-missing"),
    "unusable": ("Could not be used", "buc-tag-unusable"),
}
_CONTEXT_PANEL_TITLE = "What these use cases are based on"
_CONTEXT_PANEL_NOTE = (
    "The source code is always reviewed. An input marked Not provided would make this "
    "list more complete."
)

_CLEAN_CONSIDERATION = (
    "Nothing it needs is missing and every object converted cleanly; "
    "confirm its schedule and consumers with its owners."
)


def load_json_object(path: Path) -> dict | None:
    """Read a JSON object. A missing, unreadable, or non-object file is None."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def render_business_use_cases_html(
    use_cases: dict,
    wave_plan: dict | None = None,
    effort: dict | None = None,
    context: dict | None = None,
) -> str:
    """Readiness HTML for one use-cases artifact and its optional companions."""
    cases = [case for case in use_cases.get("useCases") or [] if isinstance(case, dict)]
    if not cases:
        return _page(EMPTY_LEAD, EMPTY_NOTICE, "")

    shared = _shared_counts(wave_plan)
    hours = _effort_hours(effort)
    confirmed = _confirmations(context)
    counted = len(cases)
    noun = "business use case" if counted == 1 else "business use cases"
    lead = (
        f"{counted} {noun} found. Each one can migrate on its own, "
        "with every object it needs."
    )
    body = (
        _summary(cases, wave_plan, use_cases.get("undeployable"), effort)
        + _context_panel(context)
        + "".join(
            _card(
                case,
                shared.get(str(case.get("id"))),
                hours.get(str(case.get("id"))),
                confirmed.get(str(case.get("id"))),
            )
            for case in cases
        )
    )
    return _page(lead, APP_NOTICE, body)


def _context_panel(context: dict | None) -> str:
    """What the use cases were based on, and what providing more would add."""
    rows = _context_inputs(context)
    if not rows:
        return ""
    items = "".join(_context_item(row) for row in rows)
    note = (
        f"<p>{html.escape(_CONTEXT_PANEL_NOTE)}</p>"
        if any(row["status"] != "reviewed" for row in rows)
        else ""
    )
    return (
        '<section class="buc-context">'
        f"<h2>{html.escape(_CONTEXT_PANEL_TITLE)}</h2>"
        f"{note}<ul>{items}</ul>"
        "</section>"
    )


def _context_inputs(context: dict | None) -> list[dict]:
    """Every known kind, in order. A missing file or a missing kind is Not provided."""
    rows: dict[str, dict] = {}
    if isinstance(context, dict):
        for row in context.get("inputs") or []:
            if (
                isinstance(row, dict)
                and row.get("kind") in CONTEXT_KINDS
                and row.get("status") in CONTEXT_STATUSES
                and row["kind"] not in rows
            ):
                rows[row["kind"]] = row
    return [rows.get(kind) or {"kind": kind, "status": "notProvided"} for kind in CONTEXT_KINDS]


def _context_item(row: dict) -> str:
    kind, status = str(row["kind"]), str(row["status"])
    tag, tag_class = _CONTEXT_TAGS[status]
    label = str(row.get("label") or "").strip() or CONTEXT_LABELS[kind]
    finding = str(row.get("finding") or "").strip()
    if status == "notProvided":
        text = CONTEXT_WOULD_ADD[kind]
    elif status == "unusable":
        text = finding or "The file could not be read."
    else:
        text = finding
    files = [str(name).strip() for name in row.get("files") or [] if str(name).strip()]
    meta = [", ".join(files)] if files else []
    entries = _int(row.get("entries"))
    matched = row.get("matched")
    if entries > 0 and isinstance(matched, int) and not isinstance(matched, bool):
        meta.append(f"{matched:,} of {entries:,} entries found in the source code")
    elif entries > 0:
        meta.append(f"{entries:,} entries reviewed")
    text_html = f"<p>{html.escape(text)}</p>" if text else ""
    meta_html = f'<p class="buc-context-meta">{html.escape(" · ".join(meta))}</p>' if meta else ""
    return (
        "<li>"
        f"<strong>{html.escape(label)}</strong>"
        f'<span class="buc-tag {tag_class}">{html.escape(tag)}</span>'
        f"{text_html}{meta_html}"
        "</li>"
    )


def _confirmations(context: dict | None) -> dict[str, str]:
    """The one line each use case shows when an input confirmed it, keyed by use case id."""
    lines: dict[str, str] = {}
    if not isinstance(context, dict):
        return lines
    for row in context.get("useCases") or []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        kinds = [kind for kind in row.get("confirmedBy") or [] if kind in CONTEXT_CONFIRMED_BY]
        if not kinds:
            continue
        names = [CONTEXT_CONFIRMED_BY[kind] for kind in dict.fromkeys(kinds)]
        who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"
        note = str(row.get("note") or "").strip()
        lines[str(row["id"])] = f"Confirmed by {who}." + (f" {note}" if note else "")
    return lines


PENDING_NOTICE = "The deployment plan for these objects is in the assessment report in the app."
PENDING_EMPTY = (
    "Other objects appear here after the assessment plans them. "
    "They are also listed in the assessment report in the app."
)
PENDING_NONE = "Every object belongs to a business use case."

ESTATE_ORDER = ("unknown", "dataOnly", "plumbing", "copy", "technicalGroup")
ESTATE_REASONS = {
    "technicalGroup": (
        "Shared technical code",
        "Frameworks, utilities and shared routines the review judged technical. They serve "
        "every use case rather than one business outcome, so they migrate in waves of their own.",
    ),
    "copy": (
        "Copies and older versions",
        "Objects the assessment flagged as a duplicate or an older version of another object. "
        "They migrate so nothing is lost, but no business outcome depends on them.",
    ),
    "plumbing": (
        "Operational objects",
        "Temporary, staging, test, logging, audit and control objects. They keep the platform "
        "running rather than producing a business result on their own.",
    ),
    "dataOnly": (
        "Data with no process in the code",
        "Tables nothing in the converted code loads or reads, and views that only pass such a "
        "table through. The data migrates; what loads or reads it lives outside the code "
        "provided, such as an ETL tool, a script or a BI report.",
    ),
    "unknown": (
        "Not traced to an outcome",
        "Objects the code loads or uses whose chain never reaches an export, a report, a "
        "schedule or a log the analysis could see. The missing link is most often a BI layer, "
        "a scheduler or the scripts that run them.",
    ),
}
_REASONS_TITLE = "Objects that did not land in a business use case"
_REASONS_LEAD = (
    "A business use case needs evidence of the outcome it serves. These objects migrate "
    "either way; this is why the analysis could not tie them to one."
)
_REASONS_NO_CONTEXT = (
    "BI reports, scheduler exports and query logs were not reviewed for this run. Providing "
    "them can tie more of these objects to a use case."
)
_REASONS_CHAT = (
    "Ask in the chat about any of these objects to see more about why they sit outside a use case."
)


def render_pending_objects_html(
    wave_plan: dict | None = None,
    effort: dict | None = None,
    context: dict | None = None,
) -> str:
    """The objects no business use case includes, the waves that migrate them and why."""
    if not isinstance(wave_plan, dict):
        return _pending_page(PENDING_EMPTY, PENDING_NOTICE, "")
    waves = _pending_waves(wave_plan)
    if not waves:
        return _pending_page(PENDING_NONE, PENDING_NOTICE, "")

    summary = wave_plan.get("summary") if isinstance(wave_plan.get("summary"), dict) else {}
    pending = _int(summary.get("pendingObjectCount")) or sum(
        _int(wave.get("pendingObjectCount")) for wave in waves
    )
    hours = _pending_hours(effort)
    stats = _stat(pending, "Other objects") + _stat(len(waves), "Waves")
    cards = "".join(_pending_card(wave, hours.get(_seed_id(wave))) for wave in waves)
    outside = "object is" if pending == 1 else "objects are"
    lead = (
        f"{pending:,} {outside} not in a business use case. They still migrate: each wave "
        "below deploys a group of them with everything it needs."
    )
    body = f'<div class="buc-stats">{stats}</div>{_reasons(summary, context)}{cards}'
    return _pending_page(lead, PENDING_NOTICE, body)


def _reasons(plan_summary: dict, context: dict | None) -> str:
    counts = plan_summary.get("pendingReasons")
    counts = counts if isinstance(counts, dict) else {}
    items = []
    for category in sorted(ESTATE_ORDER, key=lambda name: -_int(counts.get(name))):
        total = _int(counts.get(category))
        if total <= 0:
            continue
        title, body = ESTATE_REASONS[category]
        unit = "object" if total == 1 else "objects"
        heading = f"{title} ({total:,} {unit})."
        items.append(f"<li><strong>{html.escape(heading)}</strong> {html.escape(body)}</li>")
    missing = [row for row in _context_inputs(context) if row["status"] != "reviewed"]
    for row in missing:
        tag = _CONTEXT_TAGS[row["status"]][0]
        label = str(row.get("label") or "").strip() or CONTEXT_LABELS[row["kind"]]
        if row["status"] == "notProvided":
            text = CONTEXT_WOULD_ADD[row["kind"]]
        else:
            text = str(row.get("finding") or "").strip() or "The file could not be read."
        items.append(f"<li><strong>{html.escape(f'{tag}: {label}.')}</strong> {html.escape(text)}</li>")
    if not _context_inputs(context):
        items.append(f"<li>{html.escape(_REASONS_NO_CONTEXT)}</li>")
    return (
        '<details class="buc-context">'
        f"<summary>{html.escape(_REASONS_TITLE)}</summary>"
        f'<p class="buc-aside">{html.escape(_REASONS_LEAD)}</p>'
        f'<ul>{"".join(items)}</ul>'
        f'<p class="buc-aside">{html.escape(_REASONS_CHAT)}</p>'
        "</details>"
    )


def _pending_page(lead: str, notice: str, body: str) -> str:
    return (
        '<div id="pending-objects-report">'
        "<h1>Other objects</h1>"
        f'<p class="buc-lead">{html.escape(lead)}</p>'
        f'<div class="buc-notice"><p>{html.escape(notice)}</p></div>'
        f"{body}</div>"
    )


def _pending_waves(wave_plan: dict) -> list[dict]:
    waves = []
    for wave in wave_plan.get("waves") or []:
        if not isinstance(wave, dict):
            continue
        seed = wave.get("seed") if isinstance(wave.get("seed"), dict) else {}
        if seed.get("kind") == "pending":
            waves.append(wave)
    return waves


def _pending_card(wave: dict, hours: float | None) -> str:
    seed = wave.get("seed") if isinstance(wave.get("seed"), dict) else {}
    metrics = wave.get("metrics") if isinstance(wave.get("metrics"), dict) else {}
    name = str(seed.get("name") or "Other objects").strip() or "Other objects"
    pending = _int(wave.get("pendingObjectCount"))
    own = "object" if pending == 1 else "objects"
    purpose = f"{pending:,} {own} not in a business use case, deployed with everything they need."
    counts = [
        _count(wave.get("objectCount"), "Objects"),
        _count(pending, "New in this wave"),
        _count(metrics.get("sqlObjectCount"), "SQL"),
        _count(metrics.get("etlCount"), "ETL"),
        _count(metrics.get("schemaCount"), "Schemas"),
        _count(metrics.get("databaseCount"), "Databases"),
    ]
    return (
        '<article class="buc-card">'
        '<header class="buc-card-head">'
        '<div class="buc-title-row">'
        f"<h2>{html.escape(name)}</h2>"
        f"{_effort_count(hours)}"
        "</div>"
        f'<p class="buc-purpose">{html.escape(purpose)}</p>'
        "</header>"
        f'<div class="buc-counts">{"".join(counts)}</div>'
        "</article>"
    )


def _seed_id(wave: dict) -> str:
    seed = wave.get("seed") if isinstance(wave.get("seed"), dict) else {}
    return str(seed.get("id") or "")


def _pending_hours(effort: dict | None) -> dict[str, float]:
    hours: dict[str, float] = {}
    if not isinstance(effort, dict) or effort.get("status") == "unsupported_dialect":
        return hours
    for row in effort.get("pending_waves") or []:
        if not isinstance(row, dict) or row.get("id") is None:
            continue
        value = row.get("total_estimated_hours")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            hours[str(row["id"])] = float(value)
    return hours


def _page(lead: str, notice: str, body: str) -> str:
    return (
        '<div id="business-use-cases-report">'
        "<h1>Business use cases</h1>"
        f'<p class="buc-lead">{html.escape(lead)}</p>'
        f'<div class="buc-notice"><p>{html.escape(notice)}</p></div>'
        f"{body}</div>"
    )


def _summary(
    cases: list[dict],
    wave_plan: dict | None,
    undeployable: object,
    effort: dict | None,
) -> str:
    summary = (wave_plan or {}).get("summary") or {}
    pending = _int(summary.get("pendingObjectCount"))
    stats = [_stat(len(cases), "Use cases")]
    planned = summary.get("plannedObjectCount")
    if isinstance(planned, int):
        stats.append(_stat(planned, "Objects in use cases"))
    notes = []
    if effort is None:
        notes.append("Effort for each use case is in the assessment report in the app.")
    if pending > 0:
        outside = "object" if pending == 1 else "objects"
        notes.append(
            f"{pending:,} {outside} not in a use case still migrate; they are listed under "
            "Other objects in the assessment report in the app, with why each is outside a use case."
        )
    notes.extend(_undeployable_notes(undeployable))
    return (
        f'<div class="buc-stats">{"".join(stats)}</div>'
        + "".join(f'<p class="buc-aside">{html.escape(note)}</p>' for note in notes)
    )


def _undeployable_notes(undeployable: object) -> list[str]:
    if not isinstance(undeployable, list):
        return []
    notes = []
    for row in undeployable:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "One use case").strip() or "One use case"
        reason = str(row.get("reason") or "").strip()
        detail = f"{name}. {reason}" if reason else name
        notes.append(f"Identified but cannot deploy yet: {detail}")
    return notes


def _stat(count: int, label: str) -> str:
    return (
        '<div class="buc-stat">'
        f"<strong>{count:,}</strong><span>{html.escape(label)}</span>"
        "</div>"
    )


_TYPE_NOUNS = {
    "TABLE": ("table", "tables"),
    "VIEW": ("view", "views"),
    "PROCEDURE": ("procedure", "procedures"),
    "FUNCTION": ("function", "functions"),
    "ETL": ("ETL package", "ETL packages"),
    "SCRIPT": ("script", "scripts"),
    "REPORT": ("report", "reports"),
}


def _type_noun(type_name: str, count: int) -> str:
    nouns = _TYPE_NOUNS.get(type_name.upper())
    if nouns:
        return nouns[0] if count == 1 else nouns[1]
    lower = type_name.lower().replace("_", " ")
    return lower if count == 1 else f"{lower}s"


def _and_list(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def _flow_end_parts(seeds: list[dict]) -> list[str]:
    """The ends by kind, largest first, then the objects the project does not hold."""
    counts: dict[str, int] = {}
    missing = 0
    for seed in seeds:
        if seed.get("isMissing"):
            missing += 1
        else:
            kind = str(seed.get("type") or "").upper()
            counts[kind] = counts.get(kind, 0) + 1
    parts = [
        f"{count:,} {_type_noun(kind, count)}"
        for kind, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    if missing:
        parts.append(f"{missing:,} {'object' if missing == 1 else 'objects'} the project does not hold")
    return parts


def _flow_ends_note(case: dict) -> str:
    """Where the flow ends and who reads what it ends in. Mirrors flowEndsNote in the dashboard."""
    seeds = [seed for seed in case.get("seeds") or [] if isinstance(seed, dict)]
    if not seeds:
        return ""
    parts = _flow_end_parts(seeds)
    if len(seeds) == 1:
        ends = f"It ends in {parts[0]}."
    else:
        ends = f"It ends in {len(seeds):,} objects: {_and_list(parts)}."
    sentences = [
        ends,
        "Each end is a last step: nothing else in the flow reads what it produces, so that is where its data leaves the flow.",
    ]
    if any(seed.get("isMissing") for seed in seeds):
        sentences.append(
            "The objects the project does not hold have no definition here, so what reads them cannot be seen."
        )
    metrics = case.get("metrics") if isinstance(case.get("metrics"), dict) else {}
    reports = _int(metrics.get("biCount"))
    if reports > 0:
        sentences.append(f"{reports:,} {'report' if reports == 1 else 'reports'} in the project read this flow.")
    else:
        sentences.append(
            "No report in the project reads this flow, so any consumer outside the project, such as a BI layer, "
            "is not visible in this analysis."
        )
    return " ".join(sentences)


# The end of "the project does not show …" for each kind of missing evidence.
# Mirrors MISSING_EVIDENCE in the dashboard's planning-format.ts.
_MISSING_EVIDENCE = {
    "bi": "a report or BI tool that reads it",
    "scheduler": "a schedule that runs its jobs",
    "usage": "query logs showing it is still read",
    "loader": "the code that loads some of its tables",
    "exit": "an export or feed that sends its data out",
}


def _ai_analysis_note(case: dict) -> str:
    """That a use case deduced from its code looks like one, and what would confirm it; "" for any other."""
    if case.get("origin") != "aiAnalysis":
        return ""
    missing = [_MISSING_EVIDENCE[kind] for kind in case.get("missingEvidence") or [] if kind in _MISSING_EVIDENCE]
    lacks = _and_list(missing) if missing else "who uses its output"
    return (
        f"Its code looks like a business use case, but the project does not show "
        f"{lacks}. Providing it would confirm this use case."
    )


def _card(
    case: dict,
    shared: int | None,
    hours: float | None,
    confirmed: str | None = None,
) -> str:
    metrics = case.get("metrics") if isinstance(case.get("metrics"), dict) else {}
    name = str(case.get("name") or "Untitled").strip() or "Untitled"
    purpose = str(case.get("purpose") or "").strip()
    why = " ".join(
        part
        for part in (
            str(case.get("whyFound") or "").strip(),
            str(case.get("enablesOnSnowflake") or "").strip(),
        )
        if part
    )
    counts = [
        _count(metrics.get("objectCount"), "Objects"),
        _count(metrics.get("sqlObjectCount"), "SQL"),
        _count(metrics.get("etlCount"), "ETL"),
        _count(metrics.get("schemaCount"), "Schemas"),
        _count(metrics.get("databaseCount"), "Databases"),
    ]
    if _int(metrics.get("scriptCount")) > 0:
        counts.append(_count(metrics.get("scriptCount"), "Scripts"))
    macros = _int(metrics.get("macroCount")) or _int((metrics.get("typeCounts") or {}).get("MACRO"))
    if macros > 0:
        counts.append(_count(macros, "Macros"))
    if _int(metrics.get("bteqCount")) > 0:
        counts.append(_count(metrics.get("bteqCount"), "BTEQ"))
    if _int(metrics.get("biCount")) > 0:
        counts.append(_count(metrics.get("biCount"), "Reports"))
    purpose_html = f'<p class="buc-purpose">{html.escape(purpose)}</p>' if purpose else ""
    if confirmed:
        purpose_html += f'<p class="buc-confirmed">{html.escape(confirmed)}</p>'
    ai_note = _ai_analysis_note(case)
    if ai_note:
        purpose_html += f'<p class="buc-ai">{html.escape(ai_note)}</p>'
    ends = _flow_ends_note(case)
    ends_html = f"<p>{html.escape(ends)}</p>" if ends else ""
    enables_html = (
        '<section class="buc-panel buc-panel-enable">'
        "<h3>Why migrate this</h3>"
        f"<p>{html.escape(why)}</p>"
        f"{ends_html}"
        "</section>"
        if why
        else ""
    )
    items = "".join(f"<li>{html.escape(item)}</li>" for item in _considerations(case, shared))
    return (
        '<article class="buc-card">'
        '<header class="buc-card-head">'
        '<div class="buc-title-row">'
        f"<h2>{html.escape(name)}</h2>"
        f"{_effort_count(hours)}"
        "</div>"
        f"{purpose_html}"
        "</header>"
        f'<div class="buc-counts">{"".join(counts)}</div>'
        '<div class="buc-panels">'
        f"{enables_html}"
        '<section class="buc-panel">'
        "<h3>Considerations</h3>"
        f"<ul>{items}</ul>"
        "</section>"
        "</div>"
        "</article>"
    )


def _effort_count(hours: float | None) -> str:
    if hours is None:
        return ""
    return (
        '<div class="buc-count buc-count-effort">'
        f"<strong>{_hours(hours)}</strong><span>Effort</span></div>"
    )


def _count(value: object, label: str) -> str:
    return (
        '<div class="buc-count">'
        f"<strong>{_int(value):,}</strong><span>{html.escape(label)}</span>"
        "</div>"
    )


def _considerations(case: dict, shared: int | None) -> list[str]:
    """The same gaps the app lists for a use case, without anything the server draws."""
    metrics = case.get("metrics") if isinstance(case.get("metrics"), dict) else {}
    conversion = case.get("conversion") if isinstance(case.get("conversion"), dict) else {}
    items: list[str] = []
    missing = _int(metrics.get("missingCount"))
    if missing == 1:
        items.append(
            "1 object it depends on is not in the project; "
            "find or recreate it before this use case deploys."
        )
    elif missing > 1:
        items.append(
            f"{missing:,} objects it depends on are not in the project; "
            "find or recreate them before this use case deploys."
        )
    if _int(metrics.get("biCount")) == 0:
        items.append(
            "No report was found reading its output; confirm who consumes it before migrating."
        )
    needs_work = _int(conversion.get("requiresAttention")) + _int(conversion.get("notConverted"))
    if needs_work > 0:
        ewi = _int(conversion.get("ewiCount"))
        ewis = f" ({ewi:,} EWIs)" if ewi > 0 else ""
        if needs_work == 1:
            items.append(f"1 of its objects needs conversion work{ewis} before it can deploy.")
        else:
            items.append(
                f"{needs_work:,} of its objects need conversion work{ewis} before they can deploy."
            )
    if shared:
        if shared == 1:
            shared_text = "1 of its objects is shared with other use cases"
        else:
            shared_text = f"{shared:,} of its objects are shared with other use cases"
        items.append(
            f"{shared_text}. Whichever migrates first deploys them; "
            "this one then only deploys what is not deployed yet."
        )
    questions = case.get("openQuestions") if isinstance(case.get("openQuestions"), list) else []
    for question in questions:
        text = str(question).strip()
        if text and text not in items:
            items.append(text)
    if not items:
        items.append(_CLEAN_CONSIDERATION)
    return items


def _shared_counts(wave_plan: dict | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not isinstance(wave_plan, dict):
        return counts
    for wave in wave_plan.get("waves") or []:
        if not isinstance(wave, dict):
            continue
        seed = wave.get("seed") if isinstance(wave.get("seed"), dict) else {}
        if seed.get("kind") == "useCase" and seed.get("id"):
            counts[str(seed["id"])] = _int(wave.get("sharedObjectCount"))
    return counts


def _effort_hours(effort: dict | None) -> dict[str, float]:
    hours: dict[str, float] = {}
    if not isinstance(effort, dict) or effort.get("status") == "unsupported_dialect":
        return hours
    for row in effort.get("use_cases") or []:
        if not isinstance(row, dict) or row.get("id") is None:
            continue
        value = row.get("total_estimated_hours")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            hours[str(row["id"])] = float(value)
    return hours


def _hours(value: float) -> str:
    shown = f"{int(value):,}" if value == int(value) else f"{value:,.1f}"
    unit = "hour" if value == 1 else "hours"
    return f"{shown} {unit}"


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)
