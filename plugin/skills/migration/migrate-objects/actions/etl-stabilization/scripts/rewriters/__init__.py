# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
"""Golden hard-EWI rewriters for the performance-improvement-proposal.

Only patterns with golden tests and a proven live conversion should be enabled.
Unknowns stay residual. SSIS0013 and SSIS0002 are not enabled: the engine emits
those High EWIs when it already refused the naive rewrite.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

CODE_RE = re.compile(r"SSC-(?:EWI|FDM|PRF)-[A-Z0-9]+")

# Kept as reference only. Do not add these to ENABLED_REWRITERS until a golden
# comes from real engine output and a live run proves the rewrite.
SSIS0013_SIMPLE = re.compile(
    r"!!!RESOLVE EWI!!!\s*/\*\*\*\s*SSC-EWI-SSIS0013[^*]*\*\*\*/!!!\s*\n"
    r"\s*----\s*((?:User|Project|Package)::\S+)\s*\n"
    r"\s*;?",
    re.M,
)

SSIS0002_PATH_CONCAT = re.compile(
    r"!!!RESOLVE EWI!!!\s*/\*\*\*\s*SSC-EWI-SSIS0002[^*]*"
    r"@\[\$?Project::SourceFileUNC\]\s*\+\s*\"(\\\\[^\"]+)\"[^*]*\*\*\*/!!!",
    re.M,
)

Rewriter = Callable[[str], tuple[str, list[dict]]]
ENABLED_REWRITERS: tuple[Rewriter, ...] = ()


def residual_codes(text: str) -> list[str]:
    """Codes from lines that still carry !!!RESOLVE EWI!!!, not comment residue."""
    codes: list[str] = []
    for line in text.splitlines():
        if "!!!RESOLVE EWI!!!" not in line:
            continue
        codes.extend(CODE_RE.findall(line))
    return list(dict.fromkeys(codes))


def apply_rewriters(unit_dir: Path) -> dict:
    applied_all: list[dict] = []
    residual: list[dict] = []

    for f in unit_dir.rglob("*.sql"):
        rel = str(f.relative_to(unit_dir)).replace("\\", "/")
        if rel.startswith("stabilization/original/"):
            continue
        text = f.read_text(errors="ignore")
        if "!!!RESOLVE EWI!!!" not in text:
            continue
        original = text
        for rewriter in ENABLED_REWRITERS:
            text, applied = rewriter(text)
            for row in applied:
                row["file"] = rel
                applied_all.append(row)
        if text != original:
            f.write_text(text, encoding="utf-8")
        if "!!!RESOLVE EWI!!!" in text:
            residual.append(
                {
                    "file": rel,
                    "codes": residual_codes(text),
                    "reason": "after_rewriters",
                }
            )

    return {"applied": applied_all, "residual": residual}
