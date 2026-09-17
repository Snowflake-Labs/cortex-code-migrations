#!/usr/bin/env python3
"""APPLY BRIEF — route remediation-brief items into the `unsupported` pack's tracking ledger.

WHY THIS EXISTS. findings/61 SS13.4 P1 ("brief-driven stub"): Step 1 loads the brief that
`etl-aifirst/scripts/remediation_brief.py` (I-17) already wrote, acts only on `stabilization_*`
lanes, sends `conversion_*` back to convert, and makes every `residual` explicit -- no open-ended
SQL rewrite. This module is that Step 1, plus the honest-ledger bookkeeping that lets a unit exit
Stabilization without lying about what got done.

WHAT "ACT" MEANS HERE. Per `platforms/unsupported/lane-actions-guide.md`, the acting *loop* that
repairs `stabilization_repair`/`stabilization_harden` items is out of scope for this stub (P2/P3).
So for those two lanes this module does not transition status at all -- it only attaches the
brief's own context (lane, intent_excerpt, allowed_actions, reverify) to the matched element so the
existing fixer machinery (dbt-fixer / orchestration-fixer) has it to work with. The only statuses
this module ever *writes* are `return-to-convert` (conversion_emitter/conversion_ir -- not this
profile's job) and `residual` (residual lane, unknown lanes, and stabilization_* items with no
source/IR pointer to repair from -- lane-actions-guide.md rule 2: "do not guess").

CORRELATION. The brief mixes two identifier styles (findings/61 SS10): AIM-derived items carry a
full element name/path in `element_ids`; Gate B/integrity-derived items carry node-id-bearing
tokens in `element_ids`/`models`, bare (`"5"`) or embedded in the emitter's own naming (`int_m_5` --
`remediation_brief.py`'s own `_digit_tokens`). Any identifier that carries a digit token is matched
by exact digit-token equality against the element name's own digit tokens, never by substring --
substring identity on a numeric node id over-matches every element whose name happens to contain
that digit as a substring (`"5"` or `"int_m_5"` would both wrongly hit `int_m_15`/`int_m_50`/
`int_m_51`). Identifiers with no digit token at all (pure AIM paths like `Package\\El_A`) keep
substring identity, since they carry no numeric id to compare exactly. An item matching no tracked
element is still recorded in the ledger, never dropped -- "residual means explicit, not silent"
(lane-actions-guide.md rule 3) applies to correlation failures too, not just the residual lane.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import track_status

LANE_DISPOSITIONS = {
    "conversion_emitter": "return-to-convert",
    "conversion_ir": "return-to-convert",
    "stabilization_repair": None,
    "stabilization_harden": None,
    "residual": "residual",
}


def _digit_tokens(text):
    return {t for t in re.split(r"[^A-Za-z0-9]+", str(text)) if t.isdigit()}


def _item_identifiers(item):
    ids = [str(v) for v in item.get("element_ids", []) or []]
    ids += [str(v) for v in item.get("models", []) or []]
    return ids


def _item_tokens(item):
    tokens = set()
    for ident in _item_identifiers(item):
        tokens |= _digit_tokens(ident)
    return tokens


def match_elements(item: dict, element_names: list[str]) -> list[str]:
    """Correlate a brief item to tracked element names. See module docstring for the two strategies.

    Any identifier carrying a digit token (bare `"5"` or embedded like `"int_m_5"`) is compared by
    exact digit-token equality, never substring -- substring identity on a numeric node id
    over-matches every element name that happens to contain that digit as a substring (`"int_m_5"`
    is a substring of `"int_m_51"`/`"int_m_50"`, wrongly matching both). Identifiers with no digit
    token at all (pure AIM paths) keep substring identity, since there is no numeric id to compare.
    """
    identifiers = [i for i in _item_identifiers(item) if i]
    no_digit_ids = [i for i in identifiers if not _digit_tokens(i)]
    matched = {name for name in element_names if any(i in name or name in i for i in no_digit_ids)}
    tokens = _item_tokens(item)
    if tokens:
        matched |= {name for name in element_names if tokens & _digit_tokens(name)}
    return sorted(matched)


def build_ledger(brief: dict, element_names: list[str]) -> list[dict]:
    """Pure routing: brief items + tracked element names -> ledger entries.

    No disk I/O, no status transitions -- kept separate from `apply_ledger` so the routing rules
    are directly unit-testable (`ai/CLAUDE.md`: "compute and render stay separate").
    """
    ledger = []
    for item in brief.get("items", []):
        lane = item.get("lane", "")
        note = None
        if lane not in LANE_DISPOSITIONS:
            disposition = "residual"
            note = f"unrecognized lane '{lane}' -- filed residual rather than guessing"
        else:
            disposition = LANE_DISPOSITIONS[lane]
            if disposition is None:
                # lane-actions-guide.md rule 2: no source/IR pointer, no repair attempt.
                source_says = (item.get("intent_excerpt") or {}).get("source_says")
                if not source_says:
                    disposition = "residual"
                    note = "no intent_excerpt.source_says -- re-filed residual per lane-actions-guide.md rule 2"

        matched = match_elements(item, element_names)
        ledger.append({
            "item_id": item.get("id"),
            "lane": lane,
            "disposition": disposition,
            "matched_elements": matched,
            "note": note,
            # Carried through verbatim so a later fixer (or a human) can act on a
            # stabilization_* item without re-opening the brief file to find its context.
            "intent_excerpt": item.get("intent_excerpt"),
            "allowed_actions": item.get("allowed_actions"),
            "from": item.get("from"),
        })
    return ledger


def apply_ledger(status_path: Path, ledger: list[dict]) -> None:
    """Write transitions for every ledger entry that carries a disposition, then persist the
    ledger itself onto the session so it survives as the "honest ledger" record.

    Entries with `disposition is None` (stabilization_repair/harden matched to an element) are
    deliberately left untouched here -- see module docstring."""
    for entry in ledger:
        if entry["disposition"] is None:
            continue
        reason = entry["item_id"] or entry["lane"] or "remediation-brief"
        for name in entry["matched_elements"]:
            track_status.cmd_update(status_path, name, entry["disposition"], reason)

    session = track_status.load_json(status_path)
    session["brief_ledger"] = ledger
    session["last_updated"] = track_status.now_iso()
    track_status.save_json(status_path, session)


def _element_names(session: dict) -> list[str]:
    return [el["name"] for el in session["elements"]]


def cmd_apply(status_path: Path, brief_path: Path) -> None:
    if not brief_path.is_file():
        print(f"Error: remediation brief not found at {brief_path}", file=sys.stderr)
        sys.exit(1)

    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    schema = brief.get("schema")
    if schema != "aim.remediation-brief.v1":
        print(f"Error: unrecognized brief schema '{schema}' (expected aim.remediation-brief.v1)", file=sys.stderr)
        sys.exit(1)

    session = track_status.load_json(status_path)
    ledger = build_ledger(brief, _element_names(session))
    apply_ledger(status_path, ledger)

    counts: dict[str, int] = {}
    for entry in ledger:
        key = entry["disposition"] or f"{entry['lane']} (pending, ledger-only)"
        counts[key] = counts.get(key, 0) + 1
    unmatched = sum(1 for entry in ledger if not entry["matched_elements"])

    print(f"Brief applied: {len(ledger)} item(s) from {brief_path}")
    for key, n in sorted(counts.items()):
        print(f"  {key}: {n}")
    print(f"  unmatched (no correlated element): {unmatched}")


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session_status", help="path to tracking/session_status.json")
    ap.add_argument("remediation_brief", help="path to Reports/AiFirstRemediation/remediation-brief.json")
    args = ap.parse_args(argv)
    cmd_apply(Path(args.session_status), Path(args.remediation_brief))


if __name__ == "__main__":
    main(sys.argv[1:])
