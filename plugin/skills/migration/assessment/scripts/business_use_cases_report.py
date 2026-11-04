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
) -> str:
    """Readiness HTML for one use-cases artifact and its optional companions."""
    cases = [case for case in use_cases.get("useCases") or [] if isinstance(case, dict)]
    if not cases:
        return _page(EMPTY_LEAD, EMPTY_NOTICE, "")

    shared = _shared_counts(wave_plan)
    hours = _effort_hours(effort)
    counted = len(cases)
    noun = "business use case" if counted == 1 else "business use cases"
    lead = (
        f"{counted} {noun} found. Each one can migrate on its own, "
        "with every object it needs."
    )
    body = _summary(cases, wave_plan, use_cases.get("undeployable"), effort) + "".join(
        _card(case, shared.get(str(case.get("id"))), hours.get(str(case.get("id"))))
        for case in cases
    )
    return _page(lead, APP_NOTICE, body)


PENDING_NOTICE = "The deployment plan for these objects is in the assessment report in the app."
PENDING_EMPTY = (
    "Pending objects appear here after the assessment plans them. "
    "They are also listed in the assessment report in the app."
)
PENDING_NONE = "Every object belongs to a business use case."


def render_pending_objects_html(
    wave_plan: dict | None = None,
    effort: dict | None = None,
) -> str:
    """Readiness list of the objects no business use case includes."""
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
    stats = _stat(pending, "Pending objects") + _stat(len(waves), "Groups")
    cards = "".join(_pending_card(wave, hours.get(_seed_id(wave))) for wave in waves)
    outside = "object" if pending == 1 else "objects"
    lead = (
        f"{pending:,} {outside} no business use case includes. "
        "Each group migrates with everything it needs."
    )
    return _pending_page(lead, PENDING_NOTICE, f'<div class="buc-stats">{stats}</div>{cards}')


def _pending_page(lead: str, notice: str, body: str) -> str:
    return (
        '<div id="pending-objects-report">'
        "<h1>Pending objects</h1>"
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
    name = str(seed.get("name") or "Pending objects").strip() or "Pending objects"
    pending = _int(wave.get("pendingObjectCount"))
    own = "object" if pending == 1 else "objects"
    purpose = f"{pending:,} {own} no business use case includes, deployed with everything they need."
    counts = [
        _count(wave.get("objectCount"), "Objects"),
        _count(pending, "Pending"),
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
    if pending > 0:
        stats.append(_stat(pending, "Outside a use case"))
    notes = []
    if effort is None:
        notes.append("Effort for each use case is in the assessment report in the app.")
    if pending > 0:
        outside = "object" if pending == 1 else "objects"
        notes.append(
            f"{pending:,} {outside} no use case includes are listed under Pending objects "
            "in the assessment report in the app."
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


def _card(case: dict, shared: int | None, hours: float | None) -> str:
    metrics = case.get("metrics") if isinstance(case.get("metrics"), dict) else {}
    name = str(case.get("name") or "Untitled").strip() or "Untitled"
    purpose = str(case.get("purpose") or "").strip()
    enables = str(case.get("enablesOnSnowflake") or "").strip()
    counts = [
        _count(metrics.get("objectCount"), "Objects"),
        _count(metrics.get("sqlObjectCount"), "SQL"),
        _count(metrics.get("etlCount"), "ETL"),
        _count(metrics.get("schemaCount"), "Schemas"),
        _count(metrics.get("databaseCount"), "Databases"),
    ]
    if _int(metrics.get("scriptCount")) > 0:
        counts.append(_count(metrics.get("scriptCount"), "Scripts"))
    if _int(metrics.get("biCount")) > 0:
        counts.append(_count(metrics.get("biCount"), "Reports"))
    purpose_html = f'<p class="buc-purpose">{html.escape(purpose)}</p>' if purpose else ""
    enables_html = (
        '<section class="buc-panel buc-panel-enable">'
        "<h3>What it enables on Snowflake</h3>"
        f"<p>{html.escape(enables)}</p>"
        "</section>"
        if enables
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
            "this one then only deploys what is still pending."
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
