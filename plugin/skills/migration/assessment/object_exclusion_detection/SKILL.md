---
name: object-exclusion-detection
description: Identify database objects that can be excluded from migration (temporary/staging, deprecated/legacy, testing, duplicates, version conflicts) by running the SCAI assessment object-exclusion command.
parent_skill: assessment
license: Proprietary. See License-Skills for complete terms
---

# Object Exclusion Detection

This skill is a thin wrapper over the SCAI CLI command `scai assessment object-exclusion`. SCAI does the analysis directly from SnowConvert outputs (registry preferred, CSV fallback) and writes a JSON file the parent assessment skill consumes for the multi-tab HTML report.

## Critical Rules

- **Use ONLY the SCAI CLI.** No inline parsing, no custom analyzers. `scai assessment object-exclusion` is the single source of truth.
- **Inputs come from the parent.** The parent `assessment` skill resolves all inputs from `project_dir` and passes the project directory and a desired output directory to this skill, which runs SCAI.
- **One artifact per run.** SCAI writes a single timestamped JSON: `object_exclusion_analysis_YYYYMMDD_HHMMSS.json`. Hand that file's path back to the parent skill via its `--exclusion-json` input.

## Inputs (auto-detected by parent)

The parent `assessment` skill provides these:

| Input | Resolution under `project_dir` |
|-------|--------------------------------|
| Project directory (preferred) | `<project_dir>` — SCAI auto-detects registry vs CSV |
| CSV reports directory (explicit) | `<project_dir>/reports/SnowConvert/` |
| Output directory | `<project_dir>/assessment/` (create if missing) |

## Workflow

### Step 1: Run SCAI

Prefer `--project-dir` so SCAI auto-selects registry mode when a registry is present and falls back to CSV otherwise:

```bash
scai assessment object-exclusion \
  --project-dir <project_dir> \
  -o <output_dir>
```

If the project layout is non-standard and SCAI can't find the reports, fall back to explicit CSV mode:

```bash
scai assessment object-exclusion \
  --csv-dir <project_dir>/reports/SnowConvert \
  -o <output_dir>
```

SCAI prints a summary table to stdout and writes one file:

```
<output_dir>/object_exclusion_analysis_YYYYMMDD_HHMMSS.json
```

### Step 2: Locate the latest output

After the command completes, capture the path of the newest `object_exclusion_analysis_*.json` in `<output_dir>` and pass it back to the parent skill. Do not parse or re-write the file.

### Step 3: Hand off to the parent

Return the artifact path to the parent `assessment` skill. The parent feeds it into the multi-tab report as `--exclusion-json <output_dir>/object_exclusion_analysis_YYYYMMDD_HHMMSS.json`. This skill never generates HTML directly.

## SCAI Command Reference

| Option | Description |
|--------|-------------|
| `--project-dir <PATH>` | SnowConvert project directory. Auto-detects registry (`<dir>/.scai/registry/`) or falls back to CSVs in `<dir>/converted/Reports/`. |
| `--csv-dir <PATH>` | Explicit path to a SnowConvert reports directory containing `TopLevelCodeUnits.*.csv` and `ObjectReferences.*.csv`. Use only when project layout is non-standard. |
| `-o`, `--output-dir <PATH>` | Output directory for the analysis JSON. Defaults to current working directory. |

Exactly one of `--project-dir` or `--csv-dir` is required.

## Output Schema

SCAI writes a single JSON file with this structure (fields shown are the canonical SCAI schema):

```json
{
  "summary": {
    "report_directory": "...",
    "total_objects_found": 0,
    "temp_staging_objects_count": 0,
    "deprecated_legacy_objects_count": 0,
    "testing_objects_count": 0,
    "duplicate_objects_count": 0,
    "unique_duplicate_objects_count": 0,
    "objects_by_schema": [{"schema": "dbo", "object_count": 0}],
    "objects_with_multiple_versions": 0,
    "potentially_normal_objects_count": 0,
    "has_dependency_data": true
  },
  "temp_staging_objects": [],
  "deprecated_legacy_objects": [],
  "testing_objects": [],
  "duplicates": [],
  "version_analysis": {
    "version_groups": [],
    "total_version_conflicts": 0
  },
  "potentially_misclassified_objects": {},
  "has_dependency_data": true
}
```

The parent skill's multi-tab report reads these keys directly. Do not transform or rewrite the file.

## What SCAI Detects

(Documented for skill operators — SCAI handles all of this; no configuration is exposed to this skill.)

- **Temporary / staging:** `tmp_`, `temp_`, `staging_`, `stg_`, `work_`, `#`, `##`, plus all objects in dedicated `STAGING|STG|TEMP|TMP|WORK|WRK` schemas.
- **Deprecated / legacy:** `_old`, `_bak`, `_backup`, `_archive`, `_deprecated`, date-stamped backups (`_bak_YYYYMMDD`), version suffixes (`_v1`, `_v2`, …), copy patterns (`_copy`, `_copyN`).
- **Testing:** `_test`, `_fake`, `_demo`, `_sample`, `_dummy`, `_mock` (prefix, suffix, and infix forms).
- **Duplicates:** Same `full_name` defined in multiple source files; primary/recommended version selected automatically.
- **Version conflicts:** Multiple variants of the same base object (e.g., `MyProc`, `MyProc_v2`, `MyProc_bak`); production version selected automatically.
- **Potentially misclassified:** Deprecated-looking objects referenced by N+ normal objects — surfaced for manual review.

Dependency-aware analysis is automatic when the registry is available or `ObjectReferences.*.csv` is present.

## Failure Modes

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| `Error: Object exclusion analysis failed: …` | Reports/registry not found at expected path | Verify the parent ran `scai code convert` successfully; re-resolve `--csv-dir` to the actual SnowConvert reports directory |
| Empty arrays in output | No matching patterns in this workload | Normal — proceed to multi-report generation |
| `summary.has_dependency_data` is false | No `ObjectReferences.*.csv` in CSV mode | Re-run with `--project-dir` so SCAI can find the registry, or include the references CSV |

## Related

- Parent: `../SKILL.md` (consumes the SCAI artifact via `--exclusion-json`)
- SCAI built-in help: `scai assessment object-exclusion --help`
