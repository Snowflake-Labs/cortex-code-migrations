#!/usr/bin/env python3
# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
"""Stabilize stage timing helpers for the performance-improvement-proposal.

Writes phases/<stage>/timing.json with markers_in/out, wall_ms, agent_count, sql_calls.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


TIMING_SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def timing_path(unit_dir: Path, stage: str) -> Path:
    return unit_dir / "stabilization" / "phases" / stage / "timing.json"


def write_timing(
    unit_dir: Path,
    stage: str,
    *,
    wall_ms: float,
    markers_in: int = 0,
    markers_out: int = 0,
    agent_count: int = 0,
    sql_calls: int = 0,
    extra: dict[str, Any] | None = None,
) -> Path:
    path = timing_path(unit_dir, stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": TIMING_SCHEMA_VERSION,
        "stage": stage,
        "wall_ms": round(wall_ms, 3),
        "markers_in": markers_in,
        "markers_out": markers_out,
        "agent_count": agent_count,
        "sql_calls": sql_calls,
        "recorded_at": now_iso(),
        "proposal": "performance-improvement-proposal",
    }
    if extra:
        payload["extra"] = extra
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


@contextmanager
def stage_timer(unit_dir: Path, stage: str, **kwargs: Any) -> Iterator[dict[str, Any]]:
    """Context manager that records wall time for a stabilize stage."""
    state: dict[str, Any] = {
        "markers_in": kwargs.get("markers_in", 0),
        "markers_out": kwargs.get("markers_out", 0),
        "agent_count": kwargs.get("agent_count", 0),
        "sql_calls": kwargs.get("sql_calls", 0),
        "extra": kwargs.get("extra"),
    }
    t0 = time.perf_counter()
    try:
        yield state
    finally:
        wall_ms = (time.perf_counter() - t0) * 1000.0
        write_timing(
            unit_dir,
            stage,
            wall_ms=wall_ms,
            markers_in=int(state.get("markers_in", 0)),
            markers_out=int(state.get("markers_out", 0)),
            agent_count=int(state.get("agent_count", 0)),
            sql_calls=int(state.get("sql_calls", 0)),
            extra=state.get("extra"),
        )


def load_timing(unit_dir: Path, stage: str) -> dict[str, Any] | None:
    path = timing_path(unit_dir, stage)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
