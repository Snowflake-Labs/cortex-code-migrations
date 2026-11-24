# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for performance-improvement-proposal Stage-0, timing, batch-update, rewriters."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from helpers import base_session, load_json, run_track_status, write_json  # noqa: E402
from timing import write_timing, load_timing  # noqa: E402
from stabilize_prepass import run_prepass  # noqa: E402


class TestTiming(unittest.TestCase):
    def test_write_timing_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            unit = Path(tmp)
            path = write_timing(unit, "S0-prepass", wall_ms=12.5, markers_in=3, markers_out=1)
            self.assertTrue(path.is_file())
            data = load_timing(unit, "S0-prepass")
            assert data is not None
            self.assertEqual(data["schema_version"], 1)
            self.assertEqual(data["markers_in"], 3)
            self.assertEqual(data["proposal"], "performance-improvement-proposal")


class TestBatchUpdate(unittest.TestCase):
    def test_batch_update_one_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "session_status.json"
            write_json(status_path, base_session())
            updates = Path(tmp) / "updates.json"
            updates.write_text(
                json.dumps(
                    {
                        "updates": [
                            {"name": "el_fixed_a", "status": "test-passed"},
                            {"name": "el_needs_user", "status": "residual", "reason": "hard_ewi"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = run_track_status("batch-update", str(status_path), "--updates-file", str(updates))
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            session = load_json(status_path)
            by_name = {e["name"]: e for e in session["elements"]}
            self.assertEqual(by_name["el_fixed_a"]["status"], "test-passed")
            self.assertEqual(by_name["el_needs_user"]["status"], "residual")


class TestPrepassEarlyExit(unittest.TestCase):
    def test_early_exit_no_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            unit = Path(tmp)
            (unit / "pkg.sql").write_text("SELECT 1;\n", encoding="utf-8")
            receipt = run_prepass(unit, apply_library_entries=False)
            self.assertTrue(receipt["early_exit"])
            self.assertFalse(receipt["agent_required"])
            self.assertTrue((unit / "stabilization" / "planning" / "prepass_receipt.json").is_file())
            self.assertIsNotNone(load_timing(unit, "S0-prepass"))


class TestPrepassFailClosed(unittest.TestCase):
    def test_ssis0004_stays_residual(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            unit = Path(tmp)
            sql = unit / "pkg.sql"
            sql.write_text(
                "BEGIN\n"
                "!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0004 - Microsoft.ScriptTask ***/!!!\n"
                "NULL;\n"
                "END;\n",
                encoding="utf-8",
            )
            receipt = run_prepass(unit, apply_library_entries=False)
            text = sql.read_text(encoding="utf-8")
            self.assertIn("!!!RESOLVE EWI!!!", text)
            self.assertEqual(receipt["markers_out"], 1)
            self.assertTrue(receipt["agent_required"])


if __name__ == "__main__":
    unittest.main()
