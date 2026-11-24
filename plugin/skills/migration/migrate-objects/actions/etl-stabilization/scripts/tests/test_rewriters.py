"""Golden tests for etl-stabilization rewriters."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from helpers import SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))
from rewriters import apply_rewriters, residual_codes  # noqa: E402

GOLDENS = SCRIPTS_DIR / "rewriters" / "goldens"


class TestRewriterGoldens(unittest.TestCase):
    def test_each_before_sql_matches_after_sql(self) -> None:
        befores = sorted(GOLDENS.glob("*.before.sql"))
        self.assertTrue(befores, "expected rewriter goldens")
        for before in befores:
            after = GOLDENS / before.name.replace(".before.sql", ".after.sql")
            with self.subTest(golden=before.name):
                self.assertTrue(after.is_file(), f"missing {after.name}")
                with tempfile.TemporaryDirectory() as tmp:
                    unit = Path(tmp)
                    sql = unit / "pkg.sql"
                    sql.write_text(before.read_text(encoding="utf-8"), encoding="utf-8")
                    result = apply_rewriters(unit)
                    self.assertEqual(
                        sql.read_text(encoding="utf-8"),
                        after.read_text(encoding="utf-8"),
                    )
                    self.assertEqual(result["applied"], [])
                    self.assertTrue(result["residual"])

    def test_ssis0013_and_ssis0002_stay_residual(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            unit = Path(tmp)
            text = (GOLDENS / "ssis0013_simple.before.sql").read_text(encoding="utf-8")
            (unit / "pkg.sql").write_text(text, encoding="utf-8")
            result = apply_rewriters(unit)
            self.assertIn("SSC-EWI-SSIS0013", result["residual"][0]["codes"])
            self.assertIn("!!!RESOLVE EWI!!!", (unit / "pkg.sql").read_text(encoding="utf-8"))

    def test_residual_codes_ignore_rewriter_comments(self) -> None:
        text = (
            "-- [stabilize-rewriter] SSC-EWI-SSIS0013 simple var expand\n"
            "EXECUTE IMMEDIATE :User_sLogBeginning;\n"
            "!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0053 - leftover ***/!!!\n"
        )
        self.assertEqual(residual_codes(text), ["SSC-EWI-SSIS0053"])


if __name__ == "__main__":
    unittest.main()
