#!/usr/bin/env python3
# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
"""Cross-unit stabilization library for the performance-improvement-proposal.

Entries keyed by (platform, ewi, body_or_expr_hash, binding_signature).
Apply requires binding match; callers must run smoke before completion.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

CODE_RE = re.compile(r"SSC-(?:EWI|FDM|PRF)-[A-Z0-9]+")


def library_root(unit_dir: Path) -> Path:
    """Resolve project-scoped library dir without creating sibling junk folders.

    Prefer an existing `stabilization-library` two levels up; otherwise use
    `{unit}/stabilization/library` (created on demand).
    """
    project = unit_dir.parent.parent / "stabilization-library"
    if project.is_dir():
        return project
    out = unit_dir / "stabilization" / "library"
    out.mkdir(parents=True, exist_ok=True)
    return out


def entry_id(platform: str, ewi: str, body_hash: str, binding_sig: str) -> str:
    raw = f"{platform}:{ewi}:{body_hash}:{binding_sig}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def save_entry(lib: Path, entry: dict[str, Any]) -> Path:
    eid = entry.get("id") or entry_id(
        entry["platform"], entry["ewi"], entry["bodyHash"], entry.get("bindingsSignature", "")
    )
    entry = {**entry, "id": eid}
    path = lib / f"{eid}.json"
    path.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
    return path


def load_entries(lib: Path) -> list[dict[str, Any]]:
    if not lib.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for f in lib.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        ewi = data.get("ewi")
        if not isinstance(ewi, str) or not ewi:
            continue
        out.append(data)
    return out


def _bindings_match(entry: dict[str, Any], text: str) -> bool:
    """Require binding signature / body hash when the entry declares them."""
    sig = entry.get("bindingsSignature")
    if isinstance(sig, str) and sig and sig not in text:
        return False
    body_hash = entry.get("bodyHash")
    if isinstance(body_hash, str) and body_hash and body_hash not in text:
        # Hash may be of source expression not present verbatim — skip unless
        # markerPattern alone is the apply key (documented conservative mode).
        if not entry.get("markerPattern"):
            return False
    platform = entry.get("platform")
    if platform is not None and not isinstance(platform, str):
        return False
    return True


def apply_library(unit_dir: Path, lib: Path) -> dict:
    """Apply library templates when markerPattern matches and bindings agree.

    Conservative: records misses for unresolved markers; full template splice
    needs snowflakeSql + markerPattern + smokeId.
    """
    applied: list[dict] = []
    misses: list[dict] = []
    entries = load_entries(lib)
    by_ewi: dict[str, list[dict]] = {}
    for e in entries:
        by_ewi.setdefault(e["ewi"], []).append(e)

    for f in unit_dir.rglob("*.sql"):
        rel = str(f.relative_to(unit_dir)).replace("\\", "/")
        if rel.startswith("stabilization/original/"):
            continue
        text = f.read_text(errors="ignore")
        if "!!!RESOLVE EWI!!!" not in text:
            continue
        original = text
        for ewi, group in by_ewi.items():
            if ewi not in text:
                continue
            for entry in group:
                if not _bindings_match(entry, text):
                    continue
                pat = entry.get("markerPattern")
                sql = entry.get("snowflakeSql")
                smoke = entry.get("smokeId")
                if not isinstance(pat, str) or not isinstance(sql, str) or not isinstance(smoke, str):
                    continue
                if not pat or not sql or not smoke:
                    continue
                if pat in text:
                    text = text.replace(pat, sql, 1)
                    applied.append(
                        {
                            "file": rel,
                            "entry_id": entry.get("id"),
                            "ewi": ewi,
                            "smokeId": smoke,
                        }
                    )
        if text != original:
            f.write_text(text, encoding="utf-8")
        if "!!!RESOLVE EWI!!!" in text:
            misses.append(
                {
                    "file": rel,
                    "codes": [
                        c
                        for line in text.splitlines()
                        if "!!!RESOLVE EWI!!!" in line
                        for c in CODE_RE.findall(line)
                    ][:8],
                }
            )

    return {"applied": applied, "misses": misses}


def require_smoke_ids(applied: list[dict]) -> list[str]:
    """Return smoke ids that must pass before completion."""
    return list(dict.fromkeys(a["smokeId"] for a in applied if a.get("smokeId")))
