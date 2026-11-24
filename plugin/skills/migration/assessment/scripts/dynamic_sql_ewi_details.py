# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0

"""Customer-facing copy for Dynamic SQL EWI category rows and KPI tooltips.

Used by the HTML report. The dashboard API keeps a matching map in
``ai/crates/mcp-server/src/assessment/dynamic_sql.rs``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from snowconvert_reports.ewi_heatmap import ewi_doc_url

KPI_TOOLTIPS = {
    "code_units": (
        "Code units that contain at least one unresolved Dynamic SQL occurrence."
    ),
    "unresolved": (
        "Dynamic SQL instances SnowConvert could not convert, across those code units."
    ),
}

FALLBACK_WHY = (
    "This issue code was recorded on unresolved Dynamic SQL that SnowConvert "
    "could not convert."
)
FALLBACK_RECOMMENDATION = (
    "Review the occurrence, rewrite it as static SQL where you can, or use "
    "Snowflake EXECUTE IMMEDIATE after validating the SQL the procedure builds."
)

# Engine issue templates rewritten as customer-facing prose (What / Why / Rec).
DETAILS_BY_CODE: Dict[str, Dict[str, str]] = {
    "SSC-EWI-0030": {
        "what_it_is": (
            "A statement runs SQL that is built as a string at runtime (dynamic SQL)."
        ),
        "why_flagged": (
            "The SQL that will execute is not fully known at conversion time, so "
            "SnowConvert cannot convert that statement the same way as static SQL."
        ),
        "snowflake_recommendation": (
            "Rewrite the statement as static SQL where you can. If it must stay "
            "dynamic, use Snowflake EXECUTE IMMEDIATE and review every string the "
            "procedure builds."
        ),
    },
    "SSC-EWI-0125": {
        "what_it_is": (
            "A variable that feeds dynamic SQL could not be resolved to a known "
            "value at conversion time. SnowConvert converted the assignment on its own."
        ),
        "why_flagged": (
            "The analyzer could not determine what the variable holds when EXECUTE "
            "runs, so the generated EXECUTE IMMEDIATE may not match the original statement."
        ),
        "snowflake_recommendation": (
            "Confirm the converted assignment still produces SQL that Snowflake "
            "EXECUTE IMMEDIATE can run. Prefer static SQL, or simplify how the string "
            "is built so SnowConvert can see the statement."
        ),
    },
    "SSC-EWI-0126": {
        "what_it_is": (
            "A dynamic SQL block could not be fully reconstructed. Variable "
            "substitutions or the EXECUTE IMMEDIATE body may be incorrect."
        ),
        "why_flagged": (
            "SnowConvert could not rebuild the original dynamic SQL block from the "
            "converted pieces."
        ),
        "snowflake_recommendation": (
            "Review the generated block, fix substitutions, and verify the EXECUTE "
            "IMMEDIATE body against the source."
        ),
    },
    "SSC-EWI-0129": {
        "what_it_is": (
            "A variable used in dynamic SQL has too many possible values from "
            "conditional assignments for SnowConvert to resolve."
        ),
        "why_flagged": (
            "Branching assignments exceeded the analyzer's cap, so the value at "
            "EXECUTE time is unknown."
        ),
        "snowflake_recommendation": (
            "Reduce branching when building the SQL string, or rewrite as static "
            "SQL or a smaller set of EXECUTE IMMEDIATE paths."
        ),
    },
}


def _sentence_case_template(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    letters = [c for c in raw if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        lowered = raw.lower()
        return lowered[0].upper() + lowered[1:]
    return raw


def enrich_ewi_details(code: str, entry: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Fill What / Why / Recommendation / docs URL for one EWI code."""
    src = entry if isinstance(entry, dict) else {}
    known = DETAILS_BY_CODE.get(str(code or "").strip())
    description = _sentence_case_template(str(src.get("description") or ""))
    what = (
        str(src.get("what_it_is") or "").strip()
        or (known["what_it_is"] if known else "")
        or description
        or str(src.get("title") or code or "")
    )
    why = (
        str(src.get("why_flagged") or "").strip()
        or (known["why_flagged"] if known else "")
        or FALLBACK_WHY
    )
    rec = (
        str(src.get("snowflake_recommendation") or "").strip()
        or (known["snowflake_recommendation"] if known else "")
        or FALLBACK_RECOMMENDATION
    )
    url = str(src.get("doc_url") or "").strip() or (ewi_doc_url(code) or "")
    return {
        "what_it_is": what,
        "why_flagged": why,
        "snowflake_recommendation": rec,
        "doc_url": url,
    }
