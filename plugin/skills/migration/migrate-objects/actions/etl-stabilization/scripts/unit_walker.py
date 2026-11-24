#!/usr/bin/env python3
# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
"""Multi-unit claim walker for the performance-improvement-proposal.

Parallelize packages (units), never parallel writers on the same orchestration SQL.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def claims_path(etl_root: Path) -> Path:
    return etl_root / "stabilization-claims.json"


def _lock_path(etl_root: Path) -> Path:
    return etl_root / "stabilization-claims.lock"


def load_claims(etl_root: Path) -> dict:
    path = claims_path(etl_root)
    if not path.is_file():
        return {"claims": {}, "updated_at": now_iso()}
    return json.loads(path.read_text(encoding="utf-8"))


def save_claims(etl_root: Path, data: dict) -> None:
    """Atomic write under an exclusive lock file."""
    data["updated_at"] = now_iso()
    path = claims_path(etl_root)
    lock = _lock_path(etl_root)
    lock.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create-or-wait lock via O_EXCL loop (portable, no fcntl required).
    deadline = time.time() + 30
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            if time.time() > deadline:
                raise TimeoutError(f"timed out waiting for {lock}")
            time.sleep(0.05)
    try:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def list_units(etl_root: Path) -> list[Path]:
    units = []
    for child in sorted(etl_root.iterdir()):
        if not child.is_dir():
            continue
        if child.name in {"etl_configuration", "etl_instrumentation", "openflow", "stabilization-library"}:
            continue
        if any(child.glob("*.sql")) or any(child.rglob("dbt_project.yml")):
            units.append(child)
    return units


def claim_unit(etl_root: Path, unit: Path, *, worker: str, lease_s: int = 3600) -> bool:
    data = load_claims(etl_root)
    key = unit.name
    now = time.time()
    existing = data["claims"].get(key)
    if existing:
        status = existing.get("status")
        if status == "done":
            return False
        if existing.get("expires_at", 0) > now and existing.get("worker") != worker:
            return False
    data["claims"][key] = {
        "worker": worker,
        "unit": str(unit),
        "claimed_at": now_iso(),
        "expires_at": now + lease_s,
        "status": "claimed",
    }
    save_claims(etl_root, data)
    return True


def release_unit(etl_root: Path, unit: Path, worker: str, status: str = "done") -> None:
    data = load_claims(etl_root)
    key = unit.name
    c = data["claims"].get(key)
    if c and c.get("worker") == worker:
        c["status"] = status
        # Keep done claims non-claimable; only free the lease for abandoned work.
        if status == "done":
            c["expires_at"] = time.time() + 10**9
        else:
            c["expires_at"] = time.time()
        c["released_at"] = now_iso()
    save_claims(etl_root, data)


def resolve_worker(worker: str | None) -> str:
    return worker or os.environ.get("USER") or f"walker-{uuid.uuid4().hex[:8]}"


def claim_batch(etl_root: Path, *, max_units: int, worker: str | None = None) -> tuple[str, list[str]]:
    worker_id = resolve_worker(worker)
    claimed: list[str] = []
    for unit in list_units(etl_root):
        if len(claimed) >= max_units:
            break
        if claim_unit(etl_root, unit, worker=worker_id):
            claimed.append(str(unit))
    return worker_id, claimed


def main() -> None:
    ap = argparse.ArgumentParser(description="ETL unit claim walker")
    ap.add_argument("etl_root", type=Path, help="snowflake/_etl directory")
    ap.add_argument("--max-units", type=int, default=4)
    ap.add_argument("--worker", default=None)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--release", metavar="UNIT", help="Release a claimed unit (name or path)")
    ap.add_argument("--release-status", default="done")
    args = ap.parse_args()
    if args.list:
        print(json.dumps([str(u) for u in list_units(args.etl_root)], indent=2))
        return
    worker_id = resolve_worker(args.worker)
    if args.release:
        unit = Path(args.release)
        if not unit.is_absolute():
            unit = args.etl_root / unit.name
        release_unit(args.etl_root, unit, worker_id, status=args.release_status)
        print(json.dumps({"worker": worker_id, "released": str(unit), "status": args.release_status}, indent=2))
        return
    worker_id, claimed = claim_batch(args.etl_root, max_units=args.max_units, worker=worker_id)
    print(json.dumps({"worker": worker_id, "claimed": claimed}, indent=2))


if __name__ == "__main__":
    main()
