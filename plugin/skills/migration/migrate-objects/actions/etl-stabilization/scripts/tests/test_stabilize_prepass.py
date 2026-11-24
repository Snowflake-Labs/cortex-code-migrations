"""Tests for stabilize_prepass.py Stage-0 receipt behavior."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))
from stabilize_prepass import run_prepass  # noqa: E402

FDM_MARKER = (
    "!!!RESOLVE EWI!!! /*** SSC-FDM-0007 - MISSING DEPENDENT OBJECTS. ***/!!!\n"
    "SELECT 1;\n"
)

SSIS0004_THEN_HARD = (
    "!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0004 - SSIS CONTROL FLOW ELEMENT "
    "ScriptTask cannot be converted. ***/!!!\n"
    "-- comment inside the same block\n"
    "NULL;\n"
    "!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0013 - PROPERTY EXPRESSION. ***/!!!\n"
    "---- User::sLogBeginning\n"
    ";\n"
)


def _write_sql(unit: Path, rel: str, text: str) -> Path:
    path = unit / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestStabilizePrepass(unittest.TestCase):
    def test_early_exit_when_no_resolve_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            unit = Path(tmp)
            _write_sql(unit, "pkg.sql", "SELECT 1;\n")
            receipt = run_prepass(unit, apply_library_entries=False)
            self.assertTrue(receipt["early_exit"])
            self.assertEqual(receipt["markers_in"], 0)
            self.assertEqual(receipt["markers_out"], 0)
            self.assertFalse(receipt["agent_required"])
            self.assertEqual(receipt["residual"], [])
            self.assertTrue((unit / "stabilization" / "original" / "pkg.sql").is_file())
            self.assertTrue((unit / "stabilization" / "planning" / "prepass_receipt.json").is_file())

    def test_informational_fdm_is_stripped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            unit = Path(tmp)
            sql = _write_sql(unit, "pkg.sql", FDM_MARKER)
            receipt = run_prepass(unit, apply_library_entries=False)
            self.assertFalse(receipt["early_exit"])
            self.assertEqual(receipt["markers_out"], 0)
            self.assertEqual(receipt["strip"]["disposition"].get("informational_strip"), 1)
            self.assertNotIn("!!!RESOLVE EWI!!!", sql.read_text(encoding="utf-8"))
            self.assertIn("!!!RESOLVE EWI!!!", (unit / "stabilization" / "original" / "pkg.sql").read_text())

    def test_ssis0004_stays_residual_and_does_not_swallow_next_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            unit = Path(tmp)
            sql = _write_sql(unit, "pkg.sql", SSIS0004_THEN_HARD)
            receipt = run_prepass(unit, apply_library_entries=False)
            text = sql.read_text(encoding="utf-8")
            self.assertIn("SSC-EWI-SSIS0004", text)
            self.assertIn("SSC-EWI-SSIS0013", text)
            self.assertNotIn("ERROR_MESSAGE", text)
            codes = [tuple(row["codes"]) for row in receipt["residual"]]
            self.assertIn(("SSC-EWI-SSIS0004",), codes)
            self.assertIn(("SSC-EWI-SSIS0013",), codes)
            self.assertEqual(len(receipt["residual"]), 2)

    def test_receipt_residual_is_keyed_by_file_and_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            unit = Path(tmp)
            _write_sql(unit, "pkg.sql", SSIS0004_THEN_HARD)
            receipt = run_prepass(unit, apply_library_entries=False)
            keys = [(row["file"], row["marker"]) for row in receipt["residual"]]
            self.assertEqual(len(keys), len(set(keys)))
            for row in receipt["residual"]:
                self.assertEqual(row["file"], "pkg.sql")
                self.assertIn("!!!RESOLVE EWI!!!", row["marker"])

    def test_existing_original_backup_is_not_refreshed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            unit = Path(tmp)
            _write_sql(unit, "pkg.sql", FDM_MARKER)
            original = unit / "stabilization" / "original" / "pkg.sql"
            original.parent.mkdir(parents=True)
            original.write_text("CONVERTER OUTPUT\n", encoding="utf-8")
            run_prepass(unit, apply_library_entries=False)
            self.assertEqual(original.read_text(encoding="utf-8"), "CONVERTER OUTPUT\n")

    def test_missing_rewriter_modules_do_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            unit = Path(tmp)
            _write_sql(unit, "pkg.sql", "SELECT 1;\n")
            receipt = run_prepass(unit, apply_library_entries=True)
            self.assertTrue(receipt["early_exit"])
            disk = json.loads((unit / "stabilization" / "planning" / "prepass_receipt.json").read_text())
            self.assertEqual(disk["rewriters"]["applied_count"], 0)


if __name__ == "__main__":
    unittest.main()
