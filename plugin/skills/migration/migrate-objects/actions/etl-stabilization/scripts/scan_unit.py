#!/usr/bin/env python3
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

"""Scan a SnowConvert ETL unit folder and produce a structural JSON index.

Usage:
    python scan_unit.py <unit_folder> [<source_file>] [--platform <platform_id>]

Arguments:
    unit_folder     Path to the converted ETL unit folder
    source_file     (Optional) Path to the original source definition file
                    (e.g., .dtsx for SSIS, .xml for Informatica)
    --platform      (Optional) Platform ID (ssis, informatica, ...).
                    Auto-detected from file extension if omitted.

Output:
    <unit_folder>/stabilization/planning/scan.json
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from path_resolver import planning_dir, scan_results_path

RE_CREATE = re.compile(
    r"^CREATE\s+OR\s+REPLACE\s+(TASK|PROCEDURE)\s+(\S+)",
    re.IGNORECASE,
)
RE_START_TAG = re.compile(
    r"^----\s+Start(?:\s+block)?\s+'([^']+)'",
    re.IGNORECASE,
)
RE_END_TAG = re.compile(
    r"^----\s+End(?:\s+block)?\s+'([^']+)'",
    re.IGNORECASE,
)
RE_EWI = re.compile(
    r"!!!RESOLVE EWI!!!\s*/\*\*\*\s*((?:SSC|AIM)-\S+)(?:\s+-\s+(.*?))?\s*\*\*\*/!!!",
)
RE_FDM = re.compile(
    r"^--\*\*\s+((?:SSC|AIM)-\S+)(?:\s+-\s+(.*?))?\s*\*\*$",
)
RE_DBT = re.compile(r"\bEXECUTE\s+DBT\s+PROJECT\b", re.IGNORECASE)
RE_DBT_PROJECT_NAME = re.compile(r"\bEXECUTE\s+DBT\s+PROJECT\s+'([^']+)'", re.IGNORECASE)
# Scripting data-flow linkage: a workflow task invokes a mapping procedure with
# `CALL [schema.]m_<mapping>(:scope)`, the scripting analog of EXECUTE DBT PROJECT.
RE_MAPPING_CALL = re.compile(
    r"\bCALL\s+((?:[A-Za-z0-9_\"]+\.)?m_[A-Za-z0-9_]+)\s*\(",
    re.IGNORECASE,
)


def find_orchestration_file(unit_path: Path) -> Path | None:
    """Find the main orchestration SQL file in the unit root."""
    stem_match = unit_path / f"{unit_path.name}.sql"
    if stem_match.is_file():
        return stem_match
    sql_files = [f for f in unit_path.iterdir() if f.suffix == ".sql" and f.is_file()]
    if len(sql_files) == 1:
        return sql_files[0]
    return None


PLACEHOLDER_VALUES = {
    "YOUR_PROJECT_NAME",
    "YOUR_PROFILE_NAME",
    "your_project_name",
    "your_profile_name",
    "YOUR_SCHEMA",
    "YOUR_DB",
}


def assess_dbt_health(project_path: Path) -> dict:
    """Validate a dbt project's structure and report health signals.

    Returns a dict with:
      - has_valid_config: bool — dbt_project.yml exists and has real values
      - has_placeholder_config: bool — dbt_project.yml has YOUR_PROJECT_NAME etc.
      - model_count: int
      - macro_count: int
      - ewi_count: int — total EWI markers across all model files
      - ewi_codes: list[str] — unique EWI codes found
      - health_issues: list[str] — human-readable issue descriptions
    """
    health: dict = {
        "has_valid_config": True,
        "has_placeholder_config": False,
        "model_count": 0,
        "macro_count": 0,
        "ewi_count": 0,
        "ewi_codes": [],
        "health_issues": [],
    }

    dbt_yml = project_path / "dbt_project.yml"
    if not dbt_yml.is_file():
        health["has_valid_config"] = False
        health["health_issues"].append("Missing dbt_project.yml")
        return health

    yml_text = dbt_yml.read_text(encoding="utf-8", errors="replace")
    for placeholder in PLACEHOLDER_VALUES:
        if placeholder in yml_text:
            health["has_valid_config"] = False
            health["has_placeholder_config"] = True
            health["health_issues"].append(f"Placeholder '{placeholder}' in dbt_project.yml")

    sources_yml = project_path / "models" / "sources.yml"
    if sources_yml.is_file():
        sources_content = sources_yml.read_text(encoding="utf-8", errors="replace")
        for placeholder in PLACEHOLDER_VALUES:
            if placeholder in sources_content:
                health["has_placeholder_config"] = True
                health["health_issues"].append(f"Placeholder '{placeholder}' in sources.yml")

    models_dir = project_path / "models"
    if models_dir.is_dir():
        model_files = list(models_dir.rglob("*.sql"))
        health["model_count"] = len(model_files)

        ewi_codes_seen: set[str] = set()
        for model_file in model_files:
            text = model_file.read_text(encoding="utf-8", errors="replace")
            for m in RE_EWI.finditer(text):
                health["ewi_count"] += 1
                ewi_codes_seen.add(m.group(1))
        health["ewi_codes"] = sorted(ewi_codes_seen)

    macros_dir = project_path / "macros"
    if macros_dir.is_dir():
        health["macro_count"] = sum(1 for f in macros_dir.rglob("*.sql") if f.is_file())

    return health


def find_dbt_projects(unit_path: Path) -> list[dict]:
    """Find all subdirectories containing dbt_project.yml."""
    projects = []
    for root, dirs, files in os.walk(unit_path):
        if "dbt_project.yml" in files:
            project_root = Path(root)
            rel = os.path.relpath(root, unit_path)

            has_sources_yml = False
            models_dir = project_root / "models"
            if models_dir.is_dir():
                has_sources_yml = (
                    (models_dir / "sources.yml").is_file()
                    or (models_dir / "sources.yaml").is_file()
                )

            health = assess_dbt_health(project_root)

            projects.append({
                "name": project_root.name,
                "path": rel,
                "model_count": health["model_count"],
                "has_sources_yml": has_sources_yml,
                "macro_count": health["macro_count"],
                "has_valid_config": health["has_valid_config"],
                "has_placeholder_config": health["has_placeholder_config"],
                "ewi_count": health["ewi_count"],
                "ewi_codes": health["ewi_codes"],
                "health_issues": health["health_issues"],
            })
            dirs.clear()
    return sorted(projects, key=lambda p: p["path"])


def assess_proc_health(proc_path: Path) -> dict:
    """Health signals for a converted mapping procedure (scripting flavor), the
    stored-procedure analog of assess_dbt_health.

    Uses the marker-aware block/EWI scan (locate_blocks / extract_ewis):
      - proc_name: the CREATE OR REPLACE PROCEDURE target, or None
      - block_count: materialized transformation blocks (0 until R6 markers land)
      - ewi_count / ewi_codes: unresolved ``!!!RESOLVE EWI!!!`` markers (these
        break CREATE); FDM annotations are not counted here
      - create_blocking_ewis: bool — any unresolved EWI is present
      - health_issues: human-readable signals
    """
    health: dict = {
        "proc_name": None,
        "block_count": 0,
        "ewi_count": 0,
        "ewi_codes": [],
        "create_blocking_ewis": False,
        "health_issues": [],
    }

    with open(proc_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = RE_CREATE.match(line.strip())
            if m and m.group(1).upper() == "PROCEDURE":
                health["proc_name"] = m.group(2)
                break

    health["block_count"] = len(locate_blocks(proc_path))

    resolve_codes: set[str] = set()
    for marker in extract_ewis(proc_path):
        if marker["kind"] == "EWI":
            health["ewi_count"] += 1
            resolve_codes.add(marker["code"])
    health["ewi_codes"] = sorted(resolve_codes)
    health["create_blocking_ewis"] = health["ewi_count"] > 0
    if health["create_blocking_ewis"]:
        health["health_issues"].append(
            f"{health['ewi_count']} unresolved EWI marker(s) block CREATE"
        )
    return health


def is_mapping_proc_file(sql_path: Path) -> bool:
    """True if ``sql_path`` is a converted mapping-procedure (data-flow) file:
    it defines at least one CREATE OR REPLACE PROCEDURE and no
    CREATE OR REPLACE TASK (a TASK marks the orchestration/workflow file)."""
    has_proc = False
    with open(sql_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = RE_CREATE.match(line.strip())
            if m:
                kind = m.group(1).upper()
                if kind == "TASK":
                    return False
                if kind == "PROCEDURE":
                    has_proc = True
    return has_proc


def find_mapping_procs(unit_path: Path, orch_file: Path | None = None) -> list[dict]:
    """Discover converted mapping procedures in a scripting ETL unit, the
    stored-procedure analog of find_dbt_projects.

    A mapping procedure is a standalone ``.sql`` file holding a
    ``CREATE OR REPLACE PROCEDURE public.m_<mapping>(...)`` data-flow body; the
    orchestration/workflow file (CREATE TASK) is excluded. Returns ``[]`` for a
    dbt unit (which has no such files), so the dbt path is unaffected.
    """
    orch_resolved = orch_file.resolve() if orch_file else None
    procs: list[dict] = []
    for root, _dirs, files in os.walk(unit_path):
        for fn in sorted(files):
            if not fn.endswith(".sql"):
                continue
            sql_path = Path(root) / fn
            if orch_resolved and sql_path.resolve() == orch_resolved:
                continue
            if not is_mapping_proc_file(sql_path):
                continue
            health = assess_proc_health(sql_path)
            procs.append({
                "name": sql_path.stem,
                "path": os.path.relpath(sql_path, unit_path),
                "proc_name": health["proc_name"],
                "block_count": health["block_count"],
                "ewi_count": health["ewi_count"],
                "ewi_codes": health["ewi_codes"],
                "create_blocking_ewis": health["create_blocking_ewis"],
                "health_issues": health["health_issues"],
            })
    return sorted(procs, key=lambda p: p["path"])


def _is_ai_first_flat_reports_dir(candidate: Path) -> bool:
    """True if `candidate` (a `Reports/` directory) directly holds the AI-First
    producer's flat report layout: `ETL.Elements.*.csv` / `ETL.Issues.*.csv` /
    `ObjectReferences.*.csv` and/or the `AiFirstIssues/` / `AiFirstRemediation/` /
    `AiFirstLineage/` subdirectories -- the ground-truth shape confirmed against a
    real AI-First producer run (`m3-true-e2e-2026-08-18`): no `SnowConvert`
    subdirectory in this layout, `Reports/` itself is the root. Gated on these
    markers so an unrelated `Reports/` directory (neither shape) still resolves to
    "not found", same as today.
    """
    if (
        any(candidate.glob("ETL.Elements.*.csv"))
        or any(candidate.glob("ETL.Issues.*.csv"))
        or any(candidate.glob("ObjectReferences.*.csv"))
    ):
        return True
    return any(
        (candidate / name).is_dir()
        for name in ("AiFirstIssues", "AiFirstRemediation", "AiFirstLineage")
    )


def find_reports_dir(unit_path: Path) -> Path | None:
    """Walk upward from the unit folder for the directory that states the ETL assessment.

    Two layouts are real. A native SnowConvert run nests the CSVs under `Reports/SnowConvert/`;
    other runs, including the AI-First convert path, write them directly into `Reports/`. Looking
    only for the nested form found nothing in a flat tree, and the scan then reported no reports
    directory at all -- which reads as "this unit has no assessment" rather than "one layout was
    searched".
    """
    current = unit_path.resolve()
    while current != current.parent:
        # Only a Reports/ (nested or flat) that actually states elements ends the walk. An
        # empty or unrelated one must not stop it and mask a real assessment further up.
        nested = current / "Reports" / "SnowConvert"
        if nested.is_dir() and any(nested.glob("ETL.Elements.*.csv")):
            return nested
        flat = current / "Reports"
        if flat.is_dir() and any(flat.glob("ETL.Elements.*.csv")):
            return flat
        current = current.parent
    return None


def _row_names_this_unit(file_name: str, unit_name: str, source_file_name: str | None) -> bool:
    """`FileName` states the source document as the converter saw it, extension included."""
    if source_file_name and file_name == source_file_name:
        return True
    # Extension-agnostic: the unit folder is named after the document that produced it.
    return bool(file_name) and Path(file_name).stem == unit_name


def load_assessment_csv(
    reports_dir: Path, unit_name: str, source_file_name: str | None = None
) -> dict[str, dict] | None:
    """Load ETL.Elements.*.csv and return a dict keyed by element FullName.

    Rows were selected by comparing `FileName` against a manufactured `f"{unit_name}.dtsx"`, which
    only ever matched SSIS. An Informatica `.xml` or an Alteryx `.yxmd` unit dropped every row, so
    the scan reported zero elements while the CSV in front of it described all of them. Match the
    real document name when the caller knows it, and otherwise compare stems rather than assuming
    an extension.
    """
    csvs = sorted(reports_dir.glob("ETL.Elements.*.csv"))
    if not csvs:
        return None

    csv_path = csvs[-1]
    elements: dict[str, dict] = {}

    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not _row_names_this_unit(row.get("FileName") or "", unit_name, source_file_name):
                continue
            full_name = row.get("FullName", "")
            elements[full_name] = {
                "status": row.get("Status", ""),
                "category": row.get("Category", ""),
                "subtype": row.get("Subtype", ""),
                "ewi_count": int(row.get("EWI Count", 0) or 0),
                "ewis": row.get("EWIs", ""),
                "fdm_count": int(row.get("FDM Count", 0) or 0),
                "fdms": row.get("FDMs", ""),
                "prf_count": int(row.get("PRF Count", 0) or 0),
                "prfs": row.get("PRFs", ""),
                "additional_info": row.get("Additional Info", ""),
            }

    return elements if elements else None


def statements_from_assessment(
    unit_name: str, assessment: dict[str, dict], dbt_projects: list[dict]
) -> list[dict]:
    """Derive the unit's elements from the assessment when there is no orchestration SQL to parse.

    Elements were only ever read out of orchestration markers. A unit whose conversion produced dbt
    models and no orchestration container -- what the AI-First path emits for a data-flow document
    -- therefore yielded an empty `statements`, and because tracking builds its element list from
    `statements[].elements`, every downstream phase saw nothing to work on while the assessment
    listed the full inventory.

    Shaped as one synthetic statement so no consumer changes: `track_status.py init` already walks
    `statements[].elements`, and the roadmap is built from what it records.
    """
    if not assessment:
        return []

    project = dbt_projects[0]["name"] if dbt_projects else None
    elements: list[dict] = []
    for full_name, meta in assessment.items():
        entry: dict = {
            "name": full_name,
            # The element inventory states status and kind, not EWI text. Issues stay empty here
            # rather than being invented; a row's own EWIs are carried when the CSV states them.
            "issues": _issues_from_assessment_row(meta),
            "has_dbt_project": bool(project),
            "has_mapping_call": False,
            "assessment_status": meta.get("status", ""),
            "assessment_subtype": meta.get("subtype", ""),
            "assessment_category": meta.get("category", ""),
        }
        if project:
            entry["linked_dbt_project"] = project
        elements.append(entry)

    return [
        {
            "name": unit_name,
            "type": "DATA_FLOW",
            "line": None,
            "issues": [],
            "has_dbt_project": bool(project),
            "has_mapping_call": False,
            "elements": elements,
            "derived_from": "assessment",
        }
    ]


def _issues_from_assessment_row(meta: dict) -> list[dict]:
    """The CSV states EWI/FDM codes as delimited strings with no description column, so a code is
    all that can honestly be carried; the description is left empty rather than fabricated."""
    issues: list[dict] = []
    seen: set[str] = set()
    for key in ("ewis", "fdms", "prfs"):
        for code in re.split(r"[,;\s]+", str(meta.get(key) or "")):
            code = code.strip()
            if code and code not in seen:
                seen.add(code)
                issues.append({"code": code, "description": ""})
    return issues


def collect_issues(lines: list[str]) -> list[dict]:
    """Extract EWI and FDM markers from a set of lines."""
    issues = []
    seen = set()
    for line in lines:
        for m in RE_EWI.finditer(line):
            code, desc = m.group(1), m.group(2) or ""
            key = (code, desc)
            if key not in seen:
                seen.add(key)
                issues.append({"code": code, "description": desc})
        m = RE_FDM.match(line.strip())
        if m:
            code, desc = m.group(1), m.group(2) or ""
            key = (code, desc)
            if key not in seen:
                seen.add(key)
                issues.append({"code": code, "description": desc})
    return issues


def has_dbt_project(lines: list[str]) -> bool:
    return any(RE_DBT.search(line) for line in lines)


def extract_dbt_project_name(lines: list[str]) -> str | None:
    for line in lines:
        m = RE_DBT_PROJECT_NAME.search(line)
        if m:
            return m.group(1)
    return None


def has_mapping_call(lines: list[str]) -> bool:
    """True if any line CALLs a mapping procedure (scripting data-flow linkage,
    the analog of has_dbt_project's EXECUTE DBT PROJECT)."""
    return any(RE_MAPPING_CALL.search(line) for line in lines)


def linked_mapping_proc(lines: list[str]) -> str | None:
    """The mapping procedure a workflow task CALLs (e.g. ``public.m_load``), or
    None. The scripting analog of extract_dbt_project_name."""
    for line in lines:
        m = RE_MAPPING_CALL.search(line)
        if m:
            return m.group(1)
    return None


def parse_orchestration(sql_path: Path) -> list[dict]:
    """Parse the orchestration SQL into statements and elements."""
    with open(sql_path, encoding="utf-8") as f:
        lines = f.readlines()

    statements: list[dict] = []
    pending_prefix_lines: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        m = RE_CREATE.match(line.strip())
        if m:
            stmt_type = m.group(1).upper()
            stmt_name = m.group(2)
            stmt_start = i

            stmt_lines = [line]
            i += 1
            while i < len(lines):
                next_line = lines[i]
                if RE_CREATE.match(next_line.strip()):
                    break
                stmt_lines.append(next_line)
                i += 1

            elements = parse_elements(stmt_lines)

            element_line_indices = set()
            for el in elements:
                element_line_indices.update(range(el["_start_offset"], el["_end_offset"]))

            non_element_lines = [
                stmt_lines[j]
                for j in range(len(stmt_lines))
                if j not in element_line_indices
            ]
            stmt_issues = collect_issues(pending_prefix_lines + non_element_lines)

            enriched_elements = []
            for el in elements:
                entry = {
                    "name": el["name"],
                    "issues": el["issues"],
                    "has_dbt_project": el["has_dbt_project"],
                    "has_mapping_call": el.get("has_mapping_call", False),
                }
                if el.get("linked_dbt_project"):
                    entry["linked_dbt_project"] = el["linked_dbt_project"]
                if el.get("linked_mapping_proc"):
                    entry["linked_mapping_proc"] = el["linked_mapping_proc"]
                enriched_elements.append(entry)

            stmt = {
                "name": stmt_name,
                "type": stmt_type,
                "line": stmt_start + 1,
                "issues": stmt_issues,
                "has_dbt_project": has_dbt_project(non_element_lines),
                "has_mapping_call": has_mapping_call(non_element_lines),
                "elements": enriched_elements,
            }
            stmt_linked_proc = linked_mapping_proc(non_element_lines)
            if stmt_linked_proc:
                stmt["linked_mapping_proc"] = stmt_linked_proc
            statements.append(stmt)
            pending_prefix_lines = []
        else:
            pending_prefix_lines.append(line)
            i += 1

    return statements


def parse_elements(stmt_lines: list[str]) -> list[dict]:
    """Extract elements from ---- Start tags within a statement's lines."""
    elements: list[dict] = []
    current_el = None

    for offset, line in enumerate(stmt_lines):
        m = RE_START_TAG.match(line.strip())
        if m:
            if current_el is not None:
                current_el["_end_offset"] = offset
                current_el["issues"] = collect_issues(current_el["_lines"])
                current_el["has_dbt_project"] = has_dbt_project(current_el["_lines"])
                current_el["linked_dbt_project"] = extract_dbt_project_name(current_el["_lines"])
                current_el["has_mapping_call"] = has_mapping_call(current_el["_lines"])
                current_el["linked_mapping_proc"] = linked_mapping_proc(current_el["_lines"])
                elements.append(current_el)

            current_el = {
                "name": m.group(1),
                "_start_offset": offset,
                "_end_offset": None,
                "_lines": [line],
            }
        elif current_el is not None:
            current_el["_lines"].append(line)

    if current_el is not None:
        current_el["_end_offset"] = len(stmt_lines)
        current_el["issues"] = collect_issues(current_el["_lines"])
        current_el["has_dbt_project"] = has_dbt_project(current_el["_lines"])
        current_el["linked_dbt_project"] = extract_dbt_project_name(current_el["_lines"])
        current_el["has_mapping_call"] = has_mapping_call(current_el["_lines"])
        current_el["linked_mapping_proc"] = linked_mapping_proc(current_el["_lines"])
        elements.append(current_el)

    return elements


# --------------------------------------------------------------------------- #
# Block location — expose the per-block offsets parse_elements already
# computes as absolute file positions, so downstream tools can locate a
# materialized block by its marker instead of by line number. Purely additive:
# the scan.json output and every existing function are unchanged.
# --------------------------------------------------------------------------- #
def locate_blocks(sql_path: Path) -> list[dict]:
    """Return every ``---- Start [block] '<FullName>'`` block with its absolute
    location in ``sql_path``.

    Each block dict has:
      - ``statement`` / ``statement_type``: the enclosing CREATE OR REPLACE unit
      - ``name``: the block FullName from the Start marker
      - ``start_line`` / ``end_line``: 1-based, inclusive line range
      - ``line_count``: number of lines in the block
      - ``byte_start`` / ``byte_end``: UTF-8 byte range (end exclusive)
      - ``body``: the exact block text (== ``file_bytes[byte_start:byte_end]``)

    Boundaries are faithful to scan_unit's element model: a block spans from its
    Start marker up to (but not including) the next Start marker, or the end of
    its enclosing statement — so a trailing ``---- End block`` line is part of the
    span, and the last block of a statement absorbs its remaining lines.

    The file is read with ``newline=""`` so original line endings are preserved
    and the byte offsets slice the raw file byte-for-byte (LF, CRLF, or mixed).
    """
    with open(sql_path, encoding="utf-8", newline="") as f:
        lines = f.readlines()

    # byte_at[i] = number of UTF-8 bytes before line i (byte offset of line i's start)
    byte_at = [0] * (len(lines) + 1)
    for idx, ln in enumerate(lines):
        byte_at[idx + 1] = byte_at[idx] + len(ln.encode("utf-8"))

    blocks: list[dict] = []
    i = 0
    line_count = len(lines)
    while i < line_count:
        m = RE_CREATE.match(lines[i].strip())
        if not m:
            i += 1
            continue
        # Statement split mirrors parse_orchestration; block detection reuses
        # parse_elements so the marker contract stays single-sourced.
        stmt_type = m.group(1).upper()
        stmt_name = m.group(2)
        stmt_start = i
        stmt_lines = [lines[i]]
        i += 1
        while i < line_count and not RE_CREATE.match(lines[i].strip()):
            stmt_lines.append(lines[i])
            i += 1

        for el in parse_elements(stmt_lines):
            start_idx = stmt_start + el["_start_offset"]
            end_idx = stmt_start + el["_end_offset"]  # exclusive line index
            blocks.append({
                "statement": stmt_name,
                "statement_type": stmt_type,
                "name": el["name"],
                "start_line": start_idx + 1,
                "end_line": end_idx,
                "line_count": end_idx - start_idx,
                "byte_start": byte_at[start_idx],
                "byte_end": byte_at[end_idx],
                "body": "".join(lines[start_idx:end_idx]),
            })
    return blocks


def extract_ewis(sql_path: Path) -> list[dict]:
    """Return every EWI/FDM marker in ``sql_path`` with its code, description,
    kind, absolute location, and containing block (ewi-extract).

    Each marker dict has:
      - ``code`` / ``description``: parsed from the marker
      - ``kind``: ``"EWI"`` (``!!!RESOLVE EWI!!! /*** <code> - <desc> ***/!!!``,
        compilation-breaking) or ``"FDM"`` (``--** <code> - <desc> **`` annotation)
      - ``line``: 1-based line number
      - ``col``: 0-based character offset of the marker start within the line
      - ``byte_offset``: UTF-8 byte offset of the marker start in the file
      - ``block`` / ``statement``: the enclosing block FullName and its statement
        (via locate_blocks), or None for markers outside any block (e.g. preamble)

    Markers are returned in file order and are NOT de-duplicated — each occurrence
    is a distinct location a fixer must resolve (unlike collect_issues, which
    de-dupes by code+description for the scan summary).
    """
    with open(sql_path, encoding="utf-8", newline="") as f:
        lines = f.readlines()

    byte_at = [0] * (len(lines) + 1)
    for idx, ln in enumerate(lines):
        byte_at[idx + 1] = byte_at[idx] + len(ln.encode("utf-8"))

    blocks = locate_blocks(sql_path)

    def containing(line_no: int) -> dict | None:
        for b in blocks:
            if b["start_line"] <= line_no <= b["end_line"]:
                return b
        return None

    markers: list[dict] = []
    for idx, line in enumerate(lines):
        line_no = idx + 1
        matches = [
            ("EWI", m.group(1), m.group(2) or "", m.start()) for m in RE_EWI.finditer(line)
        ]
        fm = RE_FDM.match(line.strip())
        if fm:
            # RE_FDM matched the stripped line, so "--**" is always present on it
            matches.append(("FDM", fm.group(1), fm.group(2) or "", line.find("--**")))
        for kind, code, desc, col in matches:
            b = containing(line_no)
            markers.append({
                "code": code,
                "description": desc,
                "kind": kind,
                "line": line_no,
                "col": col,
                "byte_offset": byte_at[idx] + len(line[:col].encode("utf-8")),
                "block": b["name"] if b else None,
                "statement": b["statement"] if b else None,
            })
    markers.sort(key=lambda m: (m["line"], m["col"]))
    return markers


def enrich_with_assessment(
    statements: list[dict], assessment: dict[str, dict] | None
) -> None:
    """Add assessment data from CSV to elements and statements."""
    if not assessment:
        return
    for stmt in statements:
        for el in stmt["elements"]:
            csv_row = assessment.get(el["name"])
            if csv_row:
                el["assessment"] = csv_row


def _file_hash(path: Path) -> str:
    """Compute MD5 hash of a file's contents."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def print_summary(result: dict) -> None:
    """Print a human-readable summary to stdout."""
    print(f"\n{'=' * 60}")
    print(f"  ETL Unit Scan: {result['unit_name']}")
    print(f"{'=' * 60}")
    orch = result.get('orchestration_file')
    print(f"  Orchestration : {orch or '(none)'}")
    dbt_projects = result["dbt_projects"]
    print(f"  dbt projects  : {len(dbt_projects)}")
    for dp in dbt_projects:
        src_tag = " [sources.yml]" if dp.get("has_sources_yml") else ""
        print(f"    - {dp['name']} ({dp.get('model_count', '?')} models){src_tag}  [{dp['path']}]")
    mapping_procs = result.get("mapping_procs", [])
    if mapping_procs:
        print(f"  mapping procs : {len(mapping_procs)}")
        for mp in mapping_procs:
            blk = mp.get("block_count", 0)
            ewi_tag = f" [{mp['ewi_count']} EWI]" if mp.get("ewi_count") else ""
            print(f"    - {mp['name']} ({blk} block{'s' if blk != 1 else ''}){ewi_tag}  [{mp['path']}]")
    if result["reports_dir"]:
        print(f"  Reports dir   : {result['reports_dir']}")
    else:
        print("  Reports dir   : (not found)")
    print()

    total_issues = 0
    total_elements = 0
    dbt_elements = 0

    for stmt in result["statements"]:
        s_issues = len(stmt["issues"])
        s_dbt = stmt["has_dbt_project"]
        el_count = len(stmt["elements"])
        total_elements += el_count

        el_issues = sum(len(e["issues"]) for e in stmt["elements"])
        el_dbt = sum(1 for e in stmt["elements"] if e["has_dbt_project"])
        dbt_elements += el_dbt

        total_issues += s_issues + el_issues
        tag = " [dbt]" if s_dbt else ""
        print(f"  {stmt['type']:10s} {stmt['name']}{tag}")
        if s_issues:
            for iss in stmt["issues"]:
                print(f"             issue: {iss['code']} - {iss['description']}")
        for el in stmt["elements"]:
            dtag = " [dbt]" if el["has_dbt_project"] else ""
            ei = len(el["issues"])
            issue_note = f" ({ei} issue{'s' if ei != 1 else ''})" if ei else ""
            print(f"    -> {el['name']}{dtag}{issue_note}")

    print()
    print(f"  Statements : {len(result['statements'])}")
    print(f"  Elements   : {total_elements}")
    print(f"  Issues     : {total_issues}")
    print(f"  dbt elements: {dbt_elements}")
    print(f"{'=' * 60}\n")


PLATFORM_EXTENSIONS: dict[str, str] = {
    ".dtsx": "ssis",
    ".yxmd": "alteryx",
}

AMBIGUOUS_EXTENSIONS: set[str] = {".xml"}


def detect_platform(source_path: Path | None, explicit_platform: str | None) -> str | None:
    """Determine platform_id from explicit flag or file extension.

    Returns None for ambiguous extensions (.xml) that could belong to multiple
    platforms. The caller (SKILL.md Step 1b) is responsible for prompting the
    user when platform_id is None.
    """
    if explicit_platform:
        return explicit_platform
    if source_path:
        ext = source_path.suffix.lower()
        if ext in AMBIGUOUS_EXTENSIONS:
            print(
                f"Warning: '{ext}' extension is ambiguous (could be Informatica, "
                f"or another platform). Use --platform <platform_id> to specify.",
                file=sys.stderr,
            )
            return None
        return PLATFORM_EXTENSIONS.get(ext)
    return None


UNSUPPORTED_PACK_ID = "unsupported"


def platforms_dir() -> Path:
    """`{SKILL_DIR}/platforms/`, resolved relative to this script (which lives in `scripts/`)."""
    return Path(__file__).resolve().parent.parent / "platforms"


def resolve_pack_id(detected_platform: str | None, platforms_root: Path | None = None) -> tuple[str, dict]:
    """Select the Stabilization pack to use, never leaving a silent `platform_id: null`.

    `findings/61` SS13.2: a named pack is used only when its directory actually exists; anything
    else (no platform resolved, or a named-but-missing directory) falls back to the agnostic
    `unsupported` pack. The fallback decision is returned alongside the pack id so the caller can
    record it loudly (scan.json + tracking), not just act on it silently.
    """
    root = platforms_root if platforms_root is not None else platforms_dir()
    if detected_platform:
        if (root / detected_platform).is_dir():
            return detected_platform, {"fallback": False, "reason": None}
        return UNSUPPORTED_PACK_ID, {
            "fallback": True,
            "reason": f"named platform '{detected_platform}' has no pack directory under {root}",
        }
    return UNSUPPORTED_PACK_ID, {
        "fallback": True,
        "reason": "no named platform resolved (omitted/null platform, or ambiguous source extension)",
    }


def _ai_first_reports_root(reports_dir: Path) -> Path:
    """The `Reports/` directory that hosts `AiFirstIssues/` / `AiFirstRemediation/` /
    `AiFirstLineage/` as direct children -- not necessarily `reports_dir` itself.

    Legacy layout: `find_reports_dir` returns `Reports/SnowConvert/`, so the AiFirst*
    siblings live one level up, in `reports_dir.parent` (== `Reports/`). AI-First flat
    layout: `find_reports_dir` returns `Reports/` itself (no `SnowConvert` subdirectory),
    so the AiFirst* siblings are `reports_dir`'s own children. The two shapes are
    distinguished by `reports_dir`'s own name, which `find_reports_dir` fully determines.
    """
    return reports_dir.parent if reports_dir.name == "SnowConvert" else reports_dir


def ai_first_issues_path(reports_dir: Path | None) -> Path | None:
    """`{output_root}/Reports/AiFirstIssues/issues.json` -- the AI-First marker beside `reports_dir`."""
    if reports_dir is None:
        return None
    return _ai_first_reports_root(reports_dir) / "AiFirstIssues" / "issues.json"


def remediation_brief_path(reports_dir: Path | None) -> Path | None:
    """`{output_root}/Reports/AiFirstRemediation/remediation-brief.json` (`findings/61` SS10)."""
    if reports_dir is None:
        return None
    return _ai_first_reports_root(reports_dir) / "AiFirstRemediation" / "remediation-brief.json"


def check_unsupported_brief(reports_dir: Path | None) -> str:
    """Classify brief availability for a unit that selected the `unsupported` pack.

    Returns "missing_required" only when the unit carries AI-First artifacts (Gate A/B + AIM ran)
    but no remediation brief was written beside them -- that combination must fail loudly rather
    than let `unsupported` proceed as if it were a known platform (`findings/61` SS13.2 row 3).
    A unit with no AI-First artifacts at all is not held to that bar: it never had a brief to
    write, so "not_applicable" is the honest state, not a failure.
    """
    brief_path = remediation_brief_path(reports_dir)
    if brief_path is not None and brief_path.is_file():
        return "present"
    issues_path = ai_first_issues_path(reports_dir)
    if issues_path is not None and issues_path.is_file():
        return "missing_required"
    return "not_applicable"

# --------------------------------------------------------------------------- #
# AI-First element derivation -- an AI-First data-flow unit (one Alteryx .yxmd
# -> one dbt project) has no orchestration SQL container at all: no block markers,
# no `---- Start` tags, nothing for `parse_orchestration`/`parse_elements` to walk.
# `find_orchestration_file` correctly returns None for it every time, so the
# `if orch_file:` branch in `main()` never populates `statements`, and every
# downstream consumer (track_status.py init, apply_brief.py) sees zero elements
# to correlate against -- not a bug in those consumers, a genuine gap here: this
# platform's structure was never modeled. What *does* exist on disk for this unit
# is a flat dbt model tree plus the AI-First producer's own reports (ETL.Elements/
# ETL.Issues CSVs, AiFirstIssues/AiFirstRemediation JSON) -- see
# platforms/unsupported/element-types.md ("model -- a .sql file under models/").
# This section derives the same `statements`/`elements` shape `parse_orchestration`
# produces, but from those artifacts instead of SQL block markers.
# --------------------------------------------------------------------------- #

RE_DIGIT_TOKEN = re.compile(r"[^A-Za-z0-9]+")


def _digit_tokens(text: str) -> set[str]:
    """Split on non-alphanumeric separators and keep pure-digit tokens -- the same
    node-id extraction `apply_brief.py`'s `_digit_tokens` uses to correlate a brief
    item's bare `element_ids` (e.g. ``"2"``) against a dbt model name the emitter
    derived from it (e.g. ``"m_2"`` splits to tokens ``{"m", "2"}``)."""
    return {t for t in RE_DIGIT_TOKEN.split(str(text)) if t.isdigit()}


def find_ai_first_models(project_path: Path) -> list[dict]:
    """Enumerate the dbt model files under a project's `models/` dir.

    Each model `.sql` file is the atomic "element" for an AI-First unit -- there is no
    finer-grained source structure to recover (no orchestration SQL, no block markers).
    """
    models_dir = project_path / "models"
    if not models_dir.is_dir():
        return []
    return [
        {"name": f.stem, "path": str(f)}
        for f in sorted(models_dir.rglob("*.sql"))
    ]


def load_issues_csv(reports_dir: Path) -> dict[str, list[dict]]:
    """Load ETL.Issues.*.csv, keyed by `ComponentFullName`.

    Distinct key vocabulary from `load_assessment_csv`'s ETL.Elements.*.csv: Elements rows
    are keyed by the emitter's bare node id (e.g. ``"2"``), Issues rows are keyed by the dbt
    model name the emitter attributed the issue to (e.g. ``"m_2"``) -- confirmed against a
    real AI-First producer run. Using the model name here lets issues attach directly to the
    model-derived elements without a digit-token join.
    """
    csvs = sorted(reports_dir.glob("ETL.Issues.*.csv"))
    if not csvs:
        return {}

    issues: dict[str, list[dict]] = {}
    with open(csvs[-1], encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            component = row.get("ComponentFullName", "")
            if not component:
                continue
            issues.setdefault(component, []).append({
                "code": row.get("Code", ""),
                "description": row.get("Description", ""),
            })
    return issues


def derive_ai_first_statements(
    dbt_projects: list[dict],
    unit_path: Path,
    reports_dir: Path | None,
    assessment: dict[str, dict] | None = None,
) -> list[dict]:
    """Build a `statements`-shaped element list for an AI-First unit, one wrapping
    "statement" per dbt project and one element per model file -- the AI-First analog of
    `parse_orchestration`, sourced from artifacts that actually exist for this unit shape
    (see module note above) instead of SQL block markers.

    `assessment` (ETL.Elements.*.csv, keyed by bare node id) is joined onto a model by
    digit-token containment when unambiguous, so a model inherits the same EWI/FDM/PRF
    counts a legacy-platform element would get from `enrich_with_assessment` -- that
    function's own name-equality lookup never fires here (model names aren't bare node ids).
    """
    issues_by_component = load_issues_csv(reports_dir) if reports_dir else {}

    statements: list[dict] = []
    for project in dbt_projects:
        project_path = unit_path / project["path"]
        elements = []
        for model in find_ai_first_models(project_path):
            entry: dict = {
                "name": model["name"],
                "path": model["path"],
                "issues": issues_by_component.get(model["name"], []),
                "has_dbt_project": True,
                "linked_dbt_project": project["name"],
            }
            if assessment:
                model_tokens = _digit_tokens(model["name"])
                matches = [
                    row for full_name, row in assessment.items()
                    if full_name.isdigit() and full_name in model_tokens
                ]
                if len(matches) == 1:
                    entry["assessment"] = matches[0]
            elements.append(entry)

        statements.append({
            "name": project["name"],
            "type": "DBT_PROJECT",
            "line": 1,
            "issues": [],
            "has_dbt_project": True,
            "elements": elements,
        })
    return statements


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scan_unit.py <unit_folder> [<source_file>] [--platform <platform_id>]", file=sys.stderr)
        sys.exit(1)

    unit_path = Path(sys.argv[1]).resolve()
    if not unit_path.is_dir():
        print(f"Error: '{unit_path}' is not a directory", file=sys.stderr)
        sys.exit(1)

    source_path: Path | None = None
    explicit_platform: str | None = None

    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--platform" and i + 1 < len(sys.argv):
            explicit_platform = sys.argv[i + 1]
            i += 2
        elif source_path is None and not sys.argv[i].startswith("--"):
            source_path = Path(sys.argv[i]).resolve()
            if not source_path.is_file():
                print(f"Error: source file '{source_path}' not found", file=sys.stderr)
                sys.exit(1)
            i += 1
        else:
            print(f"Error: unexpected argument '{sys.argv[i]}'", file=sys.stderr)
            sys.exit(1)

    detected_platform_id = detect_platform(source_path, explicit_platform)
    pack_id, platform_selection = resolve_pack_id(detected_platform_id)

    unit_name = unit_path.name

    orch_file = find_orchestration_file(unit_path)
    dbt_projects = find_dbt_projects(unit_path)
    mapping_procs = find_mapping_procs(unit_path, orch_file)

    if not orch_file and not dbt_projects and not mapping_procs:
        print(f"Error: no orchestration SQL, dbt projects, or mapping procedures found in '{unit_path}'", file=sys.stderr)
        sys.exit(1)

    reports_dir = find_reports_dir(unit_path)

    assessment = None
    if reports_dir:
        source_file_name = source_path.name if source_path else None
        assessment = load_assessment_csv(reports_dir, unit_name, source_file_name)

    statements: list[dict] = []
    if orch_file:
        statements = parse_orchestration(orch_file)

    if statements:
        enrich_with_assessment(statements, assessment)
    elif dbt_projects:
        # The dbt tree is what conversion actually produced, so it is the better element
        # inventory when it exists: one element per model file, issues joined from the
        # issues CSV. `statements_from_assessment` stays the fallback below for a unit
        # with no dbt project, where the assessment is the only inventory there is.
        statements = derive_ai_first_statements(dbt_projects, unit_path, reports_dir, assessment)
        enrich_with_assessment(statements, assessment)
    else:
        statements = statements_from_assessment(unit_name, assessment or {}, dbt_projects)

    orch_hash = None
    if orch_file:
        orch_hash = _file_hash(orch_file)

    source_file_str = str(source_path) if source_path else None

    unsupported_brief_status = None
    if pack_id == UNSUPPORTED_PACK_ID:
        unsupported_brief_status = check_unsupported_brief(reports_dir)

    result = {
        "unit_name": unit_name,
        "unit_path": str(unit_path),
        "orchestration_file": str(orch_file) if orch_file else None,
        "orchestration_file_hash": orch_hash,
        "source_file_path": source_file_str,
        "platform_id": pack_id,
        "detected_platform_id": detected_platform_id,
        "platform_selection": platform_selection,
        "unsupported_brief_status": unsupported_brief_status,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "statements": statements,
        "dbt_projects": dbt_projects,
        "mapping_procs": mapping_procs,
        "reports_dir": str(reports_dir) if reports_dir else None,
    }

    out_dir = planning_dir(unit_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = scan_results_path(unit_path)

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"Scan results written to: {out_file}")
    if source_path:
        print(f"Source file: {source_path}")
    print(f"Platform: {pack_id}")
    if platform_selection["fallback"]:
        print(f"Platform selection: fallback to '{pack_id}' ({platform_selection['reason']})", file=sys.stderr)
    print_summary(result)

    if unsupported_brief_status == "missing_required":
        print(
            f"FAIL: unit '{unit_name}' has AI-First artifacts (Reports/AiFirstIssues/issues.json) "
            f"but no remediation brief at Reports/AiFirstRemediation/remediation-brief.json. "
            f"Refusing to proceed under 'unsupported' as if this were a known platform "
            f"-- re-run the AI-First full driver to emit the brief first.",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
