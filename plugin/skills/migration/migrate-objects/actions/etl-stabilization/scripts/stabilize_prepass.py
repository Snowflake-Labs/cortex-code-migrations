#!/usr/bin/env python3
# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
"""Mandatory Stage-0 Stabilize Compiler for the performance-improvement-proposal.

Inventory → classify → informational strip → residual hard EWIs (including
SSIS0004) → optional golden rewriters / library apply when those modules exist →
residual list keyed by file and marker. Writes prepass_receipt.json. Snapshots
stabilization/original/ before rewriting when it is missing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

# Pin local skill-script imports to this directory (not CWD / PYTHONPATH).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backup_unit import snapshot_unit
from timing import stage_timer, write_timing


def _noop_rewriters(_unit_dir: Path) -> dict:
    return {"applied": [], "residual": []}


def _noop_library(_unit_dir: Path, _root: Path | None = None) -> dict:
    return {"applied": [], "misses": []}


def _noop_library_root(unit_dir: Path) -> Path:
    root = unit_dir / "stabilization" / "library"
    root.mkdir(parents=True, exist_ok=True)
    return root


try:
    from rewriters import apply_rewriters
except ImportError:  # pragma: no cover - package layout / later stack PR
    try:
        from scripts.rewriters import apply_rewriters  # type: ignore
    except ImportError:
        apply_rewriters = _noop_rewriters

try:
    from stabilization_library import apply_library, library_root
except ImportError:  # pragma: no cover
    try:
        from scripts.stabilization_library import apply_library, library_root  # type: ignore
    except ImportError:
        apply_library = _noop_library
        library_root = _noop_library_root

RESOLVE_RE = re.compile(r"!!!RESOLVE EWI!!!")
CODE_RE = re.compile(r"SSC-(?:EWI|FDM|PRF)-[A-Z0-9]+")

INFORMATIONAL_FDM = {
    "SSC-FDM-0007",
    "SSC-FDM-SSIS0003",
    "SSC-FDM-SSIS0007",
    "SSC-FDM-SSIS0008",
    "SSC-FDM-TS0049",
    "SSC-FDM-TS0052",
    "SSC-FDM-0137",
}

HARD_RESIDUAL = {
    "SSC-EWI-SSIS0002",
    "SSC-EWI-SSIS0013",
    "SSC-EWI-SSIS0053",
    "SSC-EWI-SSIS0004",
    "SSC-EWI-SSIS0044",
    "SSC-EWI-SSIS0046",
}


def count_resolve(root: Path) -> int:
    n = 0
    for f in root.rglob("*.sql"):
        if "stabilization/original" in str(f).replace("\\", "/"):
            continue
        n += f.read_text(errors="ignore").count("!!!RESOLVE EWI!!!")
    return n


def inventory(unit_dir: Path) -> dict:
    codes: Counter[str] = Counter()
    resolve = 0
    files = []
    dbt_projects = []
    for f in unit_dir.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix.lower() not in {".sql", ".yml", ".yaml"}:
            continue
        rel = str(f.relative_to(unit_dir)).replace("\\", "/")
        if rel.startswith("stabilization/original/"):
            continue
        text = f.read_text(errors="ignore")
        n = text.count("!!!RESOLVE EWI!!!")
        resolve += n
        file_codes = CODE_RE.findall(text)
        codes.update(file_codes)
        files.append({"path": rel, "resolve": n, "codes": dict(Counter(file_codes))})
        if f.name == "dbt_project.yml":
            dbt_projects.append(str(f.parent.relative_to(unit_dir)))
    return {
        "files_scanned": len(files),
        "resolve_markers": resolve,
        "codes": dict(codes),
        "dbt_projects": dbt_projects,
        "files": files,
    }


def classify_and_strip(unit_dir: Path) -> dict:
    disposition: Counter[str] = Counter()
    residual = []
    applied = []

    for f in unit_dir.rglob("*.sql"):
        rel = str(f.relative_to(unit_dir)).replace("\\", "/")
        if rel.startswith("stabilization/original/"):
            continue
        text = f.read_text(errors="ignore")
        if "!!!RESOLVE EWI!!!" not in text:
            continue
        lines = text.splitlines(keepends=True)
        out: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if "!!!RESOLVE EWI!!!" in line:
                block = line
                codes = CODE_RE.findall(line)
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    if "!!!RESOLVE EWI!!!" in nxt:
                        break
                    stripped = nxt.strip()
                    if stripped.startswith("--") or stripped in {"", "NULL;", "NULL"}:
                        block += nxt
                        codes += CODE_RE.findall(nxt)
                        j += 1
                        continue
                    break
                codes = list(dict.fromkeys(codes))
                if codes and all(c in INFORMATIONAL_FDM for c in codes):
                    cleaned = re.sub(
                        r"!!!RESOLVE EWI!!!\s*/\*\*\*.*?\*\*\*/!!!",
                        "",
                        block,
                        flags=re.S,
                    )
                    cleaned = re.sub(r"!!!RESOLVE EWI!!!", "", cleaned)
                    out.append(cleaned)
                    disposition["informational_strip"] += 1
                    applied.append({"file": rel, "action": "informational_strip", "codes": codes})
                elif any(c in HARD_RESIDUAL for c in codes):
                    out.append(block)
                    disposition["residual_hard"] += 1
                    residual.append({"file": rel, "codes": codes, "reason": "hard_ewi"})
                else:
                    out.append(block)
                    disposition["residual_unknown"] += 1
                    residual.append({"file": rel, "codes": codes or ["UNKNOWN"], "reason": "unknown"})
                i = j
            else:
                out.append(line)
                i += 1
        new_text = "".join(out)
        if new_text != text:
            f.write_text(new_text, encoding="utf-8")

    return {
        "disposition": dict(disposition),
        "applied": applied,
        "residual": residual,
    }


def collect_residual(unit_dir: Path) -> list[dict]:
    """Remaining !!!RESOLVE EWI!!! markers, keyed by file and marker line."""
    residual: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for f in unit_dir.rglob("*.sql"):
        rel = str(f.relative_to(unit_dir)).replace("\\", "/")
        if rel.startswith("stabilization/original/"):
            continue
        for line in f.read_text(errors="ignore").splitlines():
            if "!!!RESOLVE EWI!!!" not in line:
                continue
            marker = line.strip()
            key = (rel, marker)
            if key in seen:
                continue
            seen.add(key)
            codes = CODE_RE.findall(line)
            residual.append(
                {
                    "file": rel,
                    "codes": list(dict.fromkeys(codes)) or ["UNKNOWN"],
                    "reason": "hard_ewi" if any(c in HARD_RESIDUAL for c in codes) else "unknown",
                    "marker": marker,
                }
            )
    return residual


def run_prepass(unit_dir: Path, *, apply_library_entries: bool = True) -> dict:
    unit_dir = unit_dir.resolve()
    stab = unit_dir / "stabilization"
    stab.mkdir(parents=True, exist_ok=True)
    (stab / "planning").mkdir(exist_ok=True)
    (stab / "tracking").mkdir(exist_ok=True)
    snapshot_unit(unit_dir, refresh=False)

    markers_in = count_resolve(unit_dir)
    with stage_timer(unit_dir, "S0-prepass", markers_in=markers_in) as t:
        inv = inventory(unit_dir)
        early_exit = inv["resolve_markers"] == 0
        strip = {"disposition": {}, "applied": [], "residual": []}
        rewrite = {"applied": [], "residual": []}
        lib = {"applied": [], "misses": []}

        if not early_exit:
            strip = classify_and_strip(unit_dir)
            rewrite = apply_rewriters(unit_dir)
            if apply_library_entries:
                lib = apply_library(unit_dir, library_root(unit_dir))

        markers_out = count_resolve(unit_dir)
        t["markers_in"] = markers_in
        t["markers_out"] = markers_out
        t["agent_count"] = 0
        t["extra"] = {
            "early_exit": early_exit,
            "disposition": strip.get("disposition", {}),
            "rewriter_applied": len(rewrite.get("applied", [])),
            "library_applied": len(lib.get("applied", [])),
        }

        receipt = {
            "proposal": "performance-improvement-proposal",
            "unit_dir": str(unit_dir),
            "early_exit": early_exit,
            "markers_in": markers_in,
            "markers_out": markers_out,
            "inventory": {k: inv[k] for k in ("files_scanned", "resolve_markers", "codes", "dbt_projects")},
            "strip": {
                "disposition": strip.get("disposition", {}),
                "applied_count": len(strip.get("applied", [])),
            },
            "rewriters": {
                "applied_count": len(rewrite.get("applied", [])),
                "residual_count": len(rewrite.get("residual", [])),
            },
            "library": {
                "applied_count": len(lib.get("applied", [])),
                "misses": len(lib.get("misses", [])),
            },
            "residual": collect_residual(unit_dir),
            "agent_required": not early_exit and markers_out > 0,
        }
        receipt_path = stab / "planning" / "prepass_receipt.json"
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        write_timing(
            unit_dir,
            "S0-prepass-receipt",
            wall_ms=0,
            markers_in=markers_in,
            markers_out=markers_out,
            extra={"receipt": str(receipt_path)},
        )
    return receipt


def main() -> None:
    ap = argparse.ArgumentParser(description="Stage-0 Stabilize Compiler prepass")
    ap.add_argument("unit_dir", type=Path, help="Converted ETL unit folder")
    ap.add_argument("--no-library", action="store_true")
    args = ap.parse_args()
    if not args.unit_dir.is_dir():
        print(f"Error: unit_dir not found: {args.unit_dir}", file=sys.stderr)
        sys.exit(1)
    receipt = run_prepass(args.unit_dir, apply_library_entries=not args.no_library)
    print(json.dumps({"ok": True, "early_exit": receipt["early_exit"],
                      "markers_in": receipt["markers_in"],
                      "markers_out": receipt["markers_out"],
                      "agent_required": receipt["agent_required"]}, indent=2))


if __name__ == "__main__":
    main()
