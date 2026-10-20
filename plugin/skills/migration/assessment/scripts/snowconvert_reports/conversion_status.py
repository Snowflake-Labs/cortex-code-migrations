# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Registry conversion status, shared by every reader that needs it.

The waves synthesizer and the testing-readiness reader both have to answer
"did this code unit convert cleanly?", and ETL units answer it differently
from SQL units — their SnowConvert issues hang off ``parts[*]`` rather than
the top-level ``issues`` array. One implementation here is what keeps the
two readers from drifting apart.
"""

from __future__ import annotations

STATUS_SUCCESS = "Success"
STATUS_REQUIRE_ATTENTION = "Requires Attention"
STATUS_PENDING = "Pending Conversion"
STATUS_NOT_SUPPORTED = "Not Supported"
STATUS_MISSING = "Missing"

# SnowConvert raises four families of issue: EWI (something did not convert),
# OOS (out of scope), FDM (a functional difference to be aware of) and PRF (a
# performance note). Only the first two are work. The registry stores code +
# count with no severity, so the code is the only thing to classify on.
ACTIONABLE_ISSUE_FAMILIES = ("EWI", "OOS")


def is_etl(entry: dict) -> bool:
    return entry.get("kind") == "etl"


def is_actionable_issue(issue: dict) -> bool:
    code = (issue.get("code") or "").upper()
    return any(family in code for family in ACTIONABLE_ISSUE_FAMILIES)


def has_actionable_issues(entry: dict) -> bool:
    """True when the entry carries an EWI or OOS, ETL parts included."""
    issues = list(entry.get("issues") or [])
    if is_etl(entry):
        issues += aggregate_etl_issues(entry)
    return any(is_actionable_issue(i) for i in issues if isinstance(i, dict))


def aggregate_etl_issues(entry: dict) -> list[dict]:
    """Concatenate ``parts[*].issues`` for an ETL entry.

    Top-level ``entry.issues`` is empty for ETL; the SnowConvert EWIs / FDMs
    raised during conversion are attached per-part. Used by
    ``map_conversion_status`` so an ETL with conversion gaps surfaces as
    "Requires Attention" instead of "Success".
    """
    out: list[dict] = []
    for part in entry.get("parts") or []:
        if not isinstance(part, dict):
            continue
        for issue in part.get("issues") or []:
            if isinstance(issue, dict):
                out.append(issue)
    return out


_ISSUE_FAMILY_ORDER = ("EWI", "OOS", "FDM", "PRF")


def _issue_family(code: str) -> str:
    upper = code.upper()
    for family in _ISSUE_FAMILY_ORDER:
        if family in upper:
            return family
    return "Other"


def _issue_count(issue: dict) -> int:
    count = issue.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        return 1
    return count


def summarize_issues(entry: dict) -> list[dict]:
    """One row per issue code: family, code, and summed count.

    SQL units contribute ``issues``. ETL units also contribute
    ``parts[*].issues``, the same fold as ``has_actionable_issues``. A blank
    code is skipped. A code that matches no family is kept as ``Other``.
    """
    issues = [issue for issue in (entry.get("issues") or []) if isinstance(issue, dict)]
    if is_etl(entry):
        issues += aggregate_etl_issues(entry)

    totals: dict[str, tuple[str, int]] = {}
    for issue in issues:
        code = (issue.get("code") or "").strip()
        if not code:
            continue
        family, count = totals.get(code, (_issue_family(code), 0))
        totals[code] = (family, count + _issue_count(issue))

    def sort_key(item: tuple[str, tuple[str, int]]) -> tuple[int, str]:
        code, (family, _count) = item
        try:
            rank = _ISSUE_FAMILY_ORDER.index(family)
        except ValueError:
            rank = len(_ISSUE_FAMILY_ORDER)
        return (rank, code)

    return [
        {"family": family, "code": code, "count": count}
        for code, (family, count) in sorted(totals.items(), key=sort_key)
    ]


def map_conversion_status(entry: dict) -> str:
    """Map registry conversion status + issue presence to the UI status value.

    Rules:
    - ``isMissing == true`` → "Missing" (takes precedence)
    - ``conversion.status == "pending"`` and no actionable issues  → "Pending Conversion"
    - ``conversion.status == "pending"`` and actionable issues → "Requires Attention"
    - ``conversion.status == "completed"`` and actionable issues → "Requires Attention"
    - ``conversion.status == "completed"`` and no actionable issues → "Success"
    - otherwise: "Requires Attention" if actionable issues else "Pending Conversion"

    Advisory-only units (FDM / PRF and nothing else) read as converted: those
    codes are a difference to read about, not work, and counting them as
    attention left the status column saying "Require Attention" for almost
    every object in a project.
    """
    if entry.get("isMissing"):
        return STATUS_MISSING

    conv = (
        entry.get("codeStatus", {}).get("conversion", {}).get("status", "") or ""
    ).strip().lower()
    actionable = has_actionable_issues(entry)

    if conv == "completed":
        return STATUS_REQUIRE_ATTENTION if actionable else STATUS_SUCCESS
    return STATUS_REQUIRE_ATTENTION if actionable else STATUS_PENDING
