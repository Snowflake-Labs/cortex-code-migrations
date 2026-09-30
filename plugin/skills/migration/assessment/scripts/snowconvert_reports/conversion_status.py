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
STATUS_REQUIRE_ATTENTION = "Require Attention"
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
    "Require Attention" instead of "Success".
    """
    out: list[dict] = []
    for part in entry.get("parts") or []:
        if not isinstance(part, dict):
            continue
        for issue in part.get("issues") or []:
            if isinstance(issue, dict):
                out.append(issue)
    return out


def map_conversion_status(entry: dict) -> str:
    """Map registry conversion status + issue presence to the UI status value.

    Rules:
    - ``isMissing == true`` → "Missing" (takes precedence)
    - ``conversion.status == "pending"`` and no actionable issues  → "Pending Conversion"
    - ``conversion.status == "pending"`` and actionable issues → "Require Attention"
    - ``conversion.status == "completed"`` and actionable issues → "Require Attention"
    - ``conversion.status == "completed"`` and no actionable issues → "Success"
    - otherwise: "Require Attention" if actionable issues else "Pending Conversion"

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
