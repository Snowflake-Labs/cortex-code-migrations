"""Tests for sync_guard.py -- SNOW-4221309 shared procedure/dbt-project sync-back guard,
extended under SNOW-4221304 for two units staging the same shared file.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import run_script


class TestSyncGuard(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.canonical = self.tmp_path / "canonical.sql"
        self.backup = self.tmp_path / "backup.sql"
        self.fix_log = self.tmp_path / "fix-log.md"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self) -> "subprocess.CompletedProcess":
        return run_script(
            "sync_guard.py",
            "--canonical", str(self.canonical),
            "--backup", str(self.backup),
            "--fix-log", str(self.fix_log),
            "--element", "m_shared",
        )

    def test_no_canonical_file_yet_is_ok(self):
        self.backup.write_text("select 1;")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_canonical_matches_backup_is_ok(self):
        self.canonical.write_text("select 1;")
        self.backup.write_text("select 1;")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_canonical_drifted_without_sync_winner_blocks(self):
        self.canonical.write_text("select 2; -- someone else's fix")
        self.backup.write_text("select 1;")
        result = self._run()
        self.assertEqual(result.returncode, 1)
        self.assertIn("differs from the pre-fix backup", result.stderr)
        self.assertIn("sync-winner", result.stderr)

    def test_canonical_drifted_with_sync_winner_proceeds(self):
        self.canonical.write_text("select 2; -- someone else's fix")
        self.backup.write_text("select 1;")
        self.fix_log.write_text(
            "<!-- sync-winner: element=m_shared winner=this-unit reason=verified-superset -->\n"
        )
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sync_winner_for_a_different_element_does_not_count(self):
        self.canonical.write_text("select 2;")
        self.backup.write_text("select 1;")
        self.fix_log.write_text(
            "<!-- sync-winner: element=m_other winner=this-unit reason=x -->\n"
        )
        result = self._run()
        self.assertEqual(result.returncode, 1)

    def test_missing_backup_blocks(self):
        self.canonical.write_text("select 1;")
        result = self._run()
        self.assertEqual(result.returncode, 1)
        self.assertIn("backup", result.stderr.lower())


    def test_missing_canonical_still_compares_a_sibling(self):
        current = self.tmp_path / "current.sql"
        sibling = self.tmp_path / "sibling.sql"
        current.write_text("select 1;")
        sibling.write_text("select 2;")
        result = run_script(
            "sync_guard.py",
            "--canonical", str(self.canonical),
            "--backup", str(self.backup),
            "--current", str(current),
            "--sibling", str(sibling),
            "--fix-log", str(self.fix_log),
            "--element", "m_shared",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("sibling staged copy", result.stderr)
        self.assertFalse(self.canonical.exists())

    def test_staged_root_finds_a_differing_sibling_without_the_flag(self):
        staged = self.tmp_path / "Output" / "ETL"
        current = staged / "UnitA" / "procs" / "m_shared.sql"
        sibling = staged / "UnitB" / "procs" / "m_shared.sql"
        current.parent.mkdir(parents=True)
        sibling.parent.mkdir(parents=True)
        current.write_text("select 1;")
        sibling.write_text("select 2;")
        result = run_script(
            "sync_guard.py",
            "--canonical", str(self.canonical),
            "--backup", str(self.backup),
            "--current", str(current),
            "--staged-root", str(staged),
            "--fix-log", str(self.fix_log),
            "--element", "m_shared",
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("sibling staged copy", result.stderr)
        self.assertFalse(self.canonical.exists())

    def test_staged_root_with_one_unit_still_syncs(self):
        staged = self.tmp_path / "Output" / "ETL"
        current = staged / "UnitA" / "procs" / "m_shared.sql"
        current.parent.mkdir(parents=True)
        current.write_text("select 1;")
        result = run_script(
            "sync_guard.py",
            "--canonical", str(self.canonical),
            "--backup", str(self.backup),
            "--current", str(current),
            "--staged-root", str(staged),
            "--fix-log", str(self.fix_log),
            "--element", "m_only",
            "--apply",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.canonical.read_text(), "select 1;")

class TestSyncGuardSharedAcrossUnits(unittest.TestCase):
    """SNOW-4221304: two units stage the same shared file -- canonical, backup,
    this unit's current fix, and a sibling unit's current fix must all agree
    (or an explicit sync-winner decision must say whose version wins) before
    a write is authorized.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.canonical = self.tmp_path / "canonical.sql"
        self.backup = self.tmp_path / "backup.sql"
        self.current = self.tmp_path / "current.sql"
        self.sibling = self.tmp_path / "sibling.sql"
        self.fix_log = self.tmp_path / "fix-log.md"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, *, siblings: tuple[Path, ...] = (), apply: bool = False):
        args = [
            "--canonical", str(self.canonical),
            "--backup", str(self.backup),
            "--current", str(self.current),
            "--fix-log", str(self.fix_log),
            "--element", "m_shared",
        ]
        for sibling in siblings:
            args += ["--sibling", str(sibling)]
        if apply:
            args.append("--apply")
        return run_script("sync_guard.py", *args)

    # -- Acceptance 1: stronger canonical, weaker current arriving second --

    def test_stronger_canonical_blocks_weaker_current_and_leaves_canonical_untouched(self):
        self.backup.write_text("select 1;")
        self.canonical.write_text("select 1; -- stronger fix landed first")
        self.current.write_text("select 1; -- weaker fix")

        result = self._run(apply=True)

        self.assertEqual(result.returncode, 1)
        self.assertIn("differs from the pre-fix backup", result.stderr)
        self.assertEqual(self.canonical.read_text(), "select 1; -- stronger fix landed first")

    # -- Acceptance 2: non-shared / only-one-unit file syncs cleanly --

    def test_single_unit_file_with_no_siblings_syncs_via_apply(self):
        self.backup.write_text("select 1;")
        self.current.write_text("select 1; -- this unit's fix")
        # No canonical yet -- first write, and no sibling supplied.

        result = self._run(apply=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.canonical.read_text(), "select 1; -- this unit's fix")

    def test_retrying_apply_after_canonical_already_matches_current_is_a_no_op(self):
        self.backup.write_text("select 1;")
        self.current.write_text("select 1; -- already synced")
        self.canonical.write_text("select 1; -- already synced")

        result = self._run(apply=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.canonical.read_text(), "select 1; -- already synced")

    # -- Acceptance 3: canonical drift / sibling drift / winner decisions --

    def test_canonical_drift_blocks_without_sync_winner(self):
        self.backup.write_text("select 1;")
        self.canonical.write_text("select 2; -- someone else's fix")
        self.current.write_text("select 1; -- this unit's fix")

        result = self._run()

        self.assertEqual(result.returncode, 1)
        self.assertIn("differs from the pre-fix backup", result.stderr)

    def test_sibling_drift_blocks_without_sync_winner(self):
        self.backup.write_text("select 1;")
        self.canonical.write_text("select 1;")
        self.current.write_text("select 1; -- this unit's fix")
        self.sibling.write_text("select 1; -- sibling's different fix")

        result = self._run(siblings=(self.sibling,))

        self.assertEqual(result.returncode, 1)
        self.assertIn("sibling staged copy", result.stderr)
        self.assertIn("sync-winner", result.stderr)

    def test_explicit_this_unit_winner_authorizes_sibling_drift_overwrite(self):
        self.backup.write_text("select 1;")
        self.canonical.write_text("select 1;")
        self.current.write_text("select 1; -- this unit's fix")
        self.sibling.write_text("select 1; -- sibling's different fix")
        self.fix_log.write_text(
            "<!-- sync-winner: element=m_shared winner=this-unit reason=verified-superset -->\n"
        )

        result = self._run(siblings=(self.sibling,), apply=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.canonical.read_text(), "select 1; -- this unit's fix")

    def test_explicit_other_unit_winner_blocks_sibling_drift_overwrite(self):
        self.backup.write_text("select 1;")
        self.canonical.write_text("select 1;")
        self.current.write_text("select 1; -- this unit's fix")
        self.sibling.write_text("select 1; -- sibling's different fix")
        self.fix_log.write_text(
            "<!-- sync-winner: element=m_shared winner=other-unit reason=sibling-is-superset -->\n"
        )

        result = self._run(siblings=(self.sibling,), apply=True)

        self.assertEqual(result.returncode, 1)
        self.assertIn("does not authorize overwriting canonical with this unit's version", result.stderr)
        self.assertEqual(self.canonical.read_text(), "select 1;")

    def test_explicit_other_unit_winner_also_blocks_canonical_drift_overwrite(self):
        self.backup.write_text("select 1;")
        self.canonical.write_text("select 2; -- the other unit's fix, already landed")
        self.current.write_text("select 1; -- this unit's own, different fix")
        self.fix_log.write_text(
            "<!-- sync-winner: element=m_shared winner=other-unit reason=other-unit-is-superset -->\n"
        )

        result = self._run(apply=True)

        self.assertEqual(result.returncode, 1)
        self.assertIn("does not authorize overwriting canonical with this unit's version", result.stderr)
        self.assertEqual(self.canonical.read_text(), "select 2; -- the other unit's fix, already landed")

    def test_missing_backup_blocks_even_with_current_and_siblings(self):
        self.canonical.write_text("select 1;")
        self.current.write_text("select 1; -- fix")
        self.sibling.write_text("select 1; -- fix")

        result = self._run(siblings=(self.sibling,))

        self.assertEqual(result.returncode, 1)
        self.assertIn("backup", result.stderr.lower())

    def test_sibling_matching_current_does_not_block(self):
        self.backup.write_text("select 1;")
        self.canonical.write_text("select 1;")
        self.current.write_text("select 1; -- converged fix")
        self.sibling.write_text("select 1; -- converged fix")

        result = self._run(siblings=(self.sibling,), apply=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.canonical.read_text(), "select 1; -- converged fix")


if __name__ == "__main__":
    unittest.main()
