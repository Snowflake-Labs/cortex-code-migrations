"""Derived progress ledger for the mine phase.

Authority is the on-disk CLI state + artifacts (§1.1); this run.json is a derived
cache of progress/PENDING records, never the sole authority. Written atomically.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Manifest:
    schema_version: int = SCHEMA_VERSION
    phase: str = "mine"
    mine_status: str = "pending"  # pending | completed
    validate_status: str = "pending"  # pending | completed
    compile_status: str = "pending"  # pending | completed
    generate_status: str = "pending"  # pending | completed
    enrich_status: str = "pending"  # pending | completed
    enrichment: dict = field(default_factory=lambda: {
        "fragments": 0, "rejections": 0, "retries": 0,
        "iterations": 0, "ready": False, "rejections_by_type": {},
    })
    pending: list = field(default_factory=list)  # [{"object", "reason"}]
    updated_at: str = field(default_factory=_now)

    @classmethod
    def path(cls, project_dir: str) -> Path:
        return Path(project_dir) / ".scai" / "testbed" / "run.json"

    @classmethod
    def load(cls, project_dir: str) -> "Manifest":
        p = cls.path(project_dir)
        if not p.exists():
            return cls()
        # A corrupt derived cache (truncated write, non-object payload, hand-edit)
        # must not abort resume: authority is the on-disk CLI state, so degrade to a
        # fresh ledger rather than propagating the read/parse error. A mid-write
        # truncation can land mid-codepoint (UnicodeDecodeError) or race a reader
        # (OSError), so guard the whole triple — the same set run_pipeline's predicate
        # readers guard.
        try:
            raw = json.loads(p.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in raw.items() if k in known}
        # A known field carrying the wrong runtime type (a hand-edited `"pending": "oops"`)
        # constructs fine but blows up later (record_pending does list.append), so degrade
        # to fresh now — same "never propagate a bad cache" contract as the guards above.
        blank = cls()
        if any(not isinstance(v, type(getattr(blank, k))) for k, v in filtered.items()):
            return cls()
        return cls(**filtered)

    def record_pending(self, obj: str, reason: str) -> None:
        self.pending.append({"object": obj, "reason": reason})

    def mark_mine_complete(self) -> None:
        self.mine_status = "completed"

    def mark_compile_complete(self) -> None:
        self.compile_status = "completed"
        self.phase = "compile"

    def mark_validate_complete(self) -> None:
        self.validate_status = "completed"
        self.phase = "validate"

    def mark_generate_complete(self) -> None:
        self.generate_status = "completed"
        self.phase = "generate"

    def mark_enrich_complete(self) -> None:
        self.enrich_status = "completed"
        self.enrichment["ready"] = True

    def record_fragments(self, n: int) -> None:
        # Overwrite, not sum: re-application of the same fragments must not inflate the tally (design §7, Inv 3).
        self.enrichment["fragments"] = n

    def record_rejection(self, prompt_type: str) -> None:
        self.enrichment["rejections"] += 1
        by_type = self.enrichment["rejections_by_type"]
        by_type[prompt_type] = by_type.get(prompt_type, 0) + 1

    def record_retry(self) -> None:
        self.enrichment["retries"] += 1

    def record_iteration(self) -> None:
        self.enrichment["iterations"] += 1

    def rejection_budget_exhausted(self, prompt_type: str, cap: int) -> bool:
        return self.enrichment["rejections_by_type"].get(prompt_type, 0) >= cap

    def iteration_budget_exhausted(self, cap: int) -> bool:
        return self.enrichment["iterations"] >= cap

    def reset_enrich_budget(self) -> None:
        # Explicit fresh-human-run override only; never implicit, or a crash-loop would reset and bound nothing.
        self.enrichment = {"fragments": 0, "rejections": 0, "retries": 0,
                           "iterations": 0, "ready": False, "rejections_by_type": {}}

    def save(self, project_dir: str) -> None:
        self.updated_at = _now()
        p = self.path(project_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2))
        os.replace(tmp, p)  # atomic on POSIX
