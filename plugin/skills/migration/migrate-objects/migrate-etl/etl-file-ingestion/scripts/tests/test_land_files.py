"""Tests for land-files.py — the manifest semantics the upload depends on."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

# The script is a CLI entry point with a hyphen in its name, so it loads by path.
# @dataclass resolves annotations through sys.modules, hence the registration.
SCRIPT = Path(__file__).resolve().parent.parent / "land-files.py"
_spec = importlib.util.spec_from_file_location("land_files", SCRIPT)
land_files = importlib.util.module_from_spec(_spec)
sys.modules["land_files"] = land_files
_spec.loader.exec_module(land_files)


def source(
    source_id: str,
    selection: dict,
    prefix: str,
    location: str,
    policy: str = "basename",
    state: str = "resolved",
    mapping: dict | None = None,
) -> dict:
    entry = {
        "id": source_id,
        "packageName": "Pkg",
        "originalLocations": [location],
        "selection": selection,
        "destinationKeyPolicy": policy,
        "resolutionState": state,
    }
    if mapping is None:
        mapping = {"expectedStagePrefix": f"@public.landing_stage/{prefix}"}
    if mapping:
        entry["mapping"] = mapping
    return entry


def manifest(*sources: dict, version: str = "1.0") -> dict:
    return {
        "schemaVersion": version,
        "stage": {"name": "public.landing_stage"},
        "sources": list(sources),
    }


def plan(manifest_dict: dict, path_roots=None, only=None):
    return land_files.build_plan(manifest_dict, path_roots or [], only or set())


class PlanBuildingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def touch(self, relative: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("a,b\n", encoding="utf-8")
        return path

    def test_exact_selection_uploads_the_named_file(self) -> None:
        self.touch("data/employees.csv")
        report = plan(
            manifest(
                source(
                    "s1",
                    {"kind": "exact", "fileName": "employees.csv", "recurse": False},
                    "Emp/",
                    str(self.root / "data" / "employees.csv"),
                )
            )
        )
        self.assertEqual(len(report.transfers), 1)
        self.assertEqual(report.transfers[0].stage_dest, "@public.landing_stage/Emp/")
        self.assertEqual(report.transfers[0].file_names, ["employees.csv"])

    def test_glob_ignores_files_the_filespec_does_not_match(self) -> None:
        self.touch("hr/people.csv")
        self.touch("hr/notes.txt")
        report = plan(
            manifest(
                source(
                    "s1",
                    {"kind": "glob", "fileSpec": "*.csv", "recurse": False},
                    "Hr/",
                    str(self.root / "hr"),
                )
            )
        )
        self.assertEqual([t.file_names for t in report.transfers], [["people.csv"]])

    def test_non_recursive_glob_does_not_descend(self) -> None:
        self.touch("sales/top.csv")
        self.touch("sales/2026/nested.csv")
        report = plan(
            manifest(
                source(
                    "s1",
                    {"kind": "glob", "fileSpec": "*.csv", "recurse": False},
                    "Sales/",
                    str(self.root / "sales"),
                )
            )
        )
        self.assertEqual([t.file_names for t in report.transfers], [["top.csv"]])

    def test_basename_policy_flattens_recursed_directories(self) -> None:
        self.touch("sales/01/a.csv")
        self.touch("sales/02/b.csv")
        report = plan(
            manifest(
                source(
                    "s1",
                    {"kind": "glob", "fileSpec": "*.csv", "recurse": True},
                    "Sales/",
                    str(self.root / "sales"),
                )
            )
        )
        self.assertEqual(
            {t.stage_dest for t in report.transfers}, {"@public.landing_stage/Sales/"}
        )

    def test_relative_policy_preserves_subdirectories(self) -> None:
        self.touch("sales/2026/01/a.csv")
        self.touch("sales/2026/02/b.csv")
        report = plan(
            manifest(
                source(
                    "s1",
                    {"kind": "glob", "fileSpec": "*.csv", "recurse": True},
                    "Sales/",
                    str(self.root / "sales"),
                    policy="relativeFromRoot",
                )
            )
        )
        self.assertEqual(
            sorted(t.stage_dest for t in report.transfers),
            [
                "@public.landing_stage/Sales/2026/01/",
                "@public.landing_stage/Sales/2026/02/",
            ],
        )

    def test_repeated_names_under_basename_warn_once_not_per_file(self) -> None:
        for directory in ("01", "02"):
            for name in ("a.csv", "b.csv"):
                self.touch(f"sales/{directory}/{name}")
        report = plan(
            manifest(
                source(
                    "s1",
                    {"kind": "glob", "fileSpec": "*.csv", "recurse": True},
                    "Sales/",
                    str(self.root / "sales"),
                )
            )
        )
        self.assertEqual(len(report.warnings), 1)
        self.assertEqual(report.errors, [])
        self.assertIn("2 file name(s) repeat", report.warnings[0][1])

    def test_two_sources_landing_on_one_object_is_an_error(self) -> None:
        self.touch("a/shared.csv")
        self.touch("b/shared.csv")
        report = plan(
            manifest(
                source(
                    "s1",
                    {"kind": "exact", "fileName": "shared.csv", "recurse": False},
                    "Same/",
                    str(self.root / "a" / "shared.csv"),
                ),
                source(
                    "s2",
                    {"kind": "exact", "fileName": "shared.csv", "recurse": False},
                    "Same/",
                    str(self.root / "b" / "shared.csv"),
                ),
            )
        )
        self.assertEqual(len(report.errors), 1)
        self.assertIn("both land on", report.errors[0][1])

    def test_unresolved_source_is_skipped_not_failed(self) -> None:
        report = plan(
            manifest(
                source(
                    "s1",
                    {"kind": "glob", "fileSpec": "*.csv", "recurse": False},
                    "Var/",
                    r"C:\runtime\@[User::Folder]",
                    state="requiresMapping",
                )
            )
        )
        self.assertEqual(len(report.skipped), 1)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.transfers, [])

    def test_source_without_stage_mapping_is_skipped(self) -> None:
        self.touch("hr/people.csv")
        report = plan(
            manifest(
                source(
                    "s1",
                    {"kind": "glob", "fileSpec": "*.csv", "recurse": False},
                    "Hr/",
                    str(self.root / "hr"),
                    mapping={},
                )
            )
        )
        self.assertEqual(len(report.skipped), 1)
        self.assertEqual(report.transfers, [])

    def test_missing_directory_is_an_error(self) -> None:
        report = plan(
            manifest(
                source(
                    "s1",
                    {"kind": "glob", "fileSpec": "*.csv", "recurse": False},
                    "Gone/",
                    str(self.root / "nope"),
                )
            )
        )
        self.assertEqual(len(report.errors), 1)
        self.assertEqual(report.transfers, [])

    def test_glob_matching_nothing_is_reported_but_not_an_error(self) -> None:
        self.touch("flat/a.csv")
        report = plan(
            manifest(
                source(
                    "s1",
                    {"kind": "glob", "fileSpec": "*.parquet", "recurse": False},
                    "None/",
                    str(self.root / "flat"),
                )
            )
        )
        self.assertEqual(len(report.empty), 1)
        self.assertEqual(report.errors, [])

    def test_path_root_maps_a_recorded_windows_path_onto_this_host(self) -> None:
        self.touch("c/poc/employees.csv")
        report = plan(
            manifest(
                source(
                    "s1",
                    {"kind": "exact", "fileName": "employees.csv", "recurse": False},
                    "Emp/",
                    r"C:\poc\employees.csv",
                )
            ),
            path_roots=land_files.parse_path_roots([f"C:={self.root / 'c'}"]),
        )
        self.assertEqual(len(report.transfers), 1)

    def test_source_id_filter_limits_the_plan(self) -> None:
        self.touch("a/one.csv")
        self.touch("b/two.csv")
        report = plan(
            manifest(
                source("s1", {"kind": "exact", "fileName": "one.csv", "recurse": False}, "A/", str(self.root / "a" / "one.csv")),
                source("s2", {"kind": "exact", "fileName": "two.csv", "recurse": False}, "B/", str(self.root / "b" / "two.csv")),
            ),
            only={"s2"},
        )
        self.assertEqual([t.source_id for t in report.transfers], ["s2"])

    def test_stage_prefix_missing_its_trailing_slash_gets_one(self) -> None:
        self.touch("data/employees.csv")
        report = plan(
            manifest(
                source(
                    "s1",
                    {"kind": "exact", "fileName": "employees.csv", "recurse": False},
                    "Emp",
                    str(self.root / "data" / "employees.csv"),
                    mapping={"expectedStagePrefix": "@public.landing_stage/Emp"},
                )
            )
        )
        self.assertEqual(report.transfers[0].stage_dest, "@public.landing_stage/Emp/")

    def test_stage_prefix_that_is_not_a_landing_path_is_refused(self) -> None:
        self.touch("data/employees.csv")
        report = plan(
            manifest(
                source(
                    "s1",
                    {"kind": "exact", "fileName": "employees.csv", "recurse": False},
                    "Emp/",
                    str(self.root / "data" / "employees.csv"),
                    mapping={"expectedStagePrefix": "@public.landing_stage/x/; SELECT 1"},
                )
            )
        )
        self.assertEqual(report.transfers, [])
        self.assertEqual(len(report.errors), 1)
        self.assertIn("not a landing_stage path", report.errors[0][1])

    def test_relative_subfolder_with_spaces_lands_under_its_own_name(self) -> None:
        self.touch("sales/2024 Q1/a.csv")
        report = plan(
            manifest(
                source(
                    "s1",
                    {"kind": "glob", "fileSpec": "*.csv", "recurse": True},
                    "Sales/",
                    str(self.root / "sales"),
                    policy="relativeFromRoot",
                )
            )
        )
        self.assertEqual(report.errors, [])
        self.assertEqual(
            [t.stage_dest for t in report.transfers], ["@public.landing_stage/Sales/2024 Q1/"]
        )

    def test_stage_prefix_with_a_space_passes_but_one_with_a_quote_is_refused(self) -> None:
        # The stage destination goes into the PUT as a quoted literal: a space is safe
        # there, but a quote would close the literal and let the rest run as SQL.
        self.touch("data/employees.csv")
        report = plan(
            manifest(
                source(
                    "spaced",
                    {"kind": "exact", "fileName": "employees.csv", "recurse": False},
                    "Emp/",
                    str(self.root / "data" / "employees.csv"),
                    mapping={"expectedStagePrefix": "@public.landing_stage/2024 Q1/"},
                ),
                source(
                    "quoted",
                    {"kind": "exact", "fileName": "employees.csv", "recurse": False},
                    "Emp/",
                    str(self.root / "data" / "employees.csv"),
                    mapping={"expectedStagePrefix": "@public.landing_stage/x' AUTO_COMPRESS = TRUE '/"},
                ),
            )
        )
        self.assertEqual(
            [(t.source_id, t.stage_dest) for t in report.transfers],
            [("spaced", "@public.landing_stage/2024 Q1/")],
        )
        self.assertEqual([source_id for source_id, _ in report.errors], ["quoted"])
        self.assertIn("not a landing_stage path", report.errors[0][1])

    def test_unknown_schema_version_stops_rather_than_guessing(self) -> None:
        with self.assertRaises(SystemExit):
            plan(manifest(version="2.0"))


class CollisionStopsBeforePutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.calls: list = []

    def touch(self, relative: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("a,b\n", encoding="utf-8")

    def run_main(self, manifest_dict: dict) -> int:
        manifest_path = self.root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_dict), encoding="utf-8")
        original = land_files.run_transfers
        argv = sys.argv

        def fake_run(report, args):
            self.calls.append(report)
            return set()

        land_files.run_transfers = fake_run
        sys.argv = [
            "land-files.py",
            str(manifest_path),
            "--connection",
            "test",
            "--database",
            "demo",
        ]
        try:
            return land_files.main()
        finally:
            land_files.run_transfers = original
            sys.argv = argv

    def test_cross_source_collision_does_not_upload(self) -> None:
        self.touch("a/shared.csv")
        self.touch("b/shared.csv")
        code = self.run_main(
            manifest(
                source(
                    "s1",
                    {"kind": "exact", "fileName": "shared.csv", "recurse": False},
                    "Same/",
                    str(self.root / "a" / "shared.csv"),
                ),
                source(
                    "s2",
                    {"kind": "exact", "fileName": "shared.csv", "recurse": False},
                    "Same/",
                    str(self.root / "b" / "shared.csv"),
                ),
            )
        )
        self.assertEqual(code, 1)
        self.assertEqual(self.calls, [])

    def test_missing_path_still_uploads_the_other_source(self) -> None:
        self.touch("a/one.csv")
        code = self.run_main(
            manifest(
                source(
                    "missing",
                    {"kind": "exact", "fileName": "gone.csv", "recurse": False},
                    "Gone/",
                    str(self.root / "nope" / "gone.csv"),
                ),
                source(
                    "present",
                    {"kind": "exact", "fileName": "one.csv", "recurse": False},
                    "Here/",
                    str(self.root / "a" / "one.csv"),
                ),
            )
        )
        self.assertEqual(code, 1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual([t.source_id for t in self.calls[0].transfers], ["present"])


class PutQueryTests(unittest.TestCase):
    def test_put_always_disables_compression_and_overwrites(self) -> None:
        query = land_files.put_query("/data/a.csv", "@public.landing_stage/P/", 8)
        self.assertIn("AUTO_COMPRESS = FALSE", query)
        self.assertIn("OVERWRITE = TRUE", query)
        self.assertIn("PARALLEL = 8", query)
        self.assertTrue(query.startswith("PUT 'file:///data/a.csv' '@public.landing_stage/P/'"))

    def test_single_quote_in_a_path_is_escaped_for_the_sql_literal(self) -> None:
        query = land_files.put_query("/data/o'brien.csv", "@s/", 4)
        self.assertIn("'file:///data/o''brien.csv'", query)

    def test_windows_backslashes_become_forward_slashes_in_the_file_uri(self) -> None:
        # Inside a single-quoted Snowflake literal, \t in C:\data\temp would read as a tab.
        query = land_files.put_query(r"C:\data\temp\a*.csv", "@s/", 4)
        self.assertTrue(query.startswith("PUT 'file://C:/data/temp/a*.csv' '@s/'"))

    def test_stage_destination_with_spaces_is_quoted_in_the_put(self) -> None:
        query = land_files.put_query("/data/a.csv", "@public.landing_stage/Sales/2024 Q1/", 8)
        self.assertTrue(
            query.startswith("PUT 'file:///data/a.csv' '@public.landing_stage/Sales/2024 Q1/' ")
        )


if __name__ == "__main__":
    unittest.main()
