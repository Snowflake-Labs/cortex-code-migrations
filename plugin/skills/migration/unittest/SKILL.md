---
name: Unit Test
description: Generate and execute unit tests for migrated SQL objects. Produces YAML test artifacts via AI Migrator and runs them against live databases via the standalone test runner. Supports baseline capture, LLM-generated tests, and interactive fix-retest loops. Triggers: test, run tests, generate tests, execute tests, verify migration, fix failing tests, capture baselines, unit test.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---


# Unit Test Sub-Skill

Generate unit tests for migrated objects and execute them against live databases. Test generation uses AI Migrator in `--no-repair` mode to produce YAML artifacts; test execution uses the standalone `run_migration_tests` CLI for fast, LLM-free verification. For behavioral equivalence, baseline capture via `test-runner` is also supported.

## When to Load

Load this sub-skill when:
- Generating unit tests for migrated objects
- Producing test artifacts for later re-execution
- Running AI Migrator in no-repair / generate-only mode
- Capturing source baselines for comparison
- Creating a test baseline before starting a fix cycle
- Running stored tests against live databases
- Verifying fixes by re-executing the same tests
- Checking migration correctness without generating new tests
- Quick validation after manual SQL edits
- Interactive fix-and-retest loops after test failures

## Required Environment Variables

Both test generation and execution connect to live databases. The following environment variables must be set before running any CLI command.

### Snowflake Variables

| Variable | How to obtain |
|----------|---------------|
| `SNOWFLAKE_CONNECTION_NAME` | Already known from the current migration project session (the connection name passed to `configure`). |
| `SNOWFLAKE_PAT` | Run `snow connection list` to identify the active connection, then read the PAT/password from the corresponding entry in the Snowflake CLI config toml file (e.g. `~/.snowflake/connections.toml`). |

### SQL Server Variables

AI Migrator reads SQL Server connection details automatically from `~/.snowflake/snowct/sqlserver.toml` when `SCAI_SOURCE_CONNECTION_NAME` is set. To determine which connection to use:

1. Check `source_connection` from the migration project session (set via `configure`).
2. If `source_connection` is not set, **list available connections** from `~/.snowflake/snowct/sqlserver.toml` and **ask the user** which one to use. Then call `configure` with `source_connection=<chosen_name>` to persist it.

| Variable | Required | How to obtain |
|----------|----------|---------------|
| `SCAI_SOURCE_CONNECTION_NAME` | Yes | The source connection name from the migration project session (set via `configure`). AI Migrator reads all connection details automatically from `~/.snowflake/snowct/sqlserver.toml`. |

```bash
export SNOWFLAKE_CONNECTION_NAME="<connection_name>"
export SNOWFLAKE_PAT="<pat_or_password>"
export SCAI_SOURCE_CONNECTION_NAME="<source_connection_name>"
```

If `source_connection` is not set in the session, list available connections from `~/.snowflake/snowct/sqlserver.toml` and ask the user which one to use.

## Script Execution

All `uv run` commands **must** include `--project ${SKILL_DIR}` so that `uv` resolves dependencies from the ai-migrator `pyproject.toml`. `SKILL_DIR` is the absolute path to `tools/ai-migrator/` relative to this skill (i.e. `../tools/ai-migrator` from this file, which contains the `pyproject.toml`, `uv.lock`, and `packages/` directory).

```bash
SKILL_DIR="<absolute path to tools/ai-migrator>"
```

## Directory Conventions

| Directory | Purpose |
|-----------|---------|
| `source/` (`SOURCE_DIR`) | Original source SQL files extracted from the source database. |
| `snowflake/` (`CONVERTED_DIR`) | **SnowConvert output directory.** This is the top-level directory produced by SnowConvert — it contains both the converted SQL files and the `Reports/SnowConvert/` folder with `TopLevelCodeUnits*.csv` (required for object discovery). **Do NOT use `ai-converted/.../fixed/`** — that directory lacks the Reports metadata and will fail with exit code 24. |
| `.scai/jobs/unit-testing/<datetime>_<short_id>/` | Per-run working directory (`TARGET_DIR`). Each invocation creates a new timestamped directory (e.g. `20260317_143022_a1b2`). |
| `artifacts/unit_tests/` | Persistent test artifact store. After generation, copy test YAML files here. Execution reads from here via `--reuse-tests`. |
| `test-results/` | Only created when `test-runner validate --output-dir test-results` is passed. By default, validate results are written to Snowflake (`<DATABASE>.VALIDATION.RESULTS`) and nothing lands on disk. |

---

## Test Generation

Two complementary approaches for generating tests.

### Baseline Capture (recommended for behavioral equivalence)

Captures actual source database output as test baselines. No LLM needed — runs the procedures on the source database and records results.

**Best for:** verifying that Snowflake produces identical output to the source.

`test-runner capture` uploads baselines to `@<DATABASE>.VALIDATION.BASELINES` and keeps nothing on disk; `test-runner validate` reads them back from the same stage. `-c` is required — without a Snowflake connection (either `-c` or `target_connection.name` in `settings/test_config.yaml`) capture errors out because it has nowhere to upload to.

```bash
cd <project_dir>
test-runner capture \
    --project-root <project_dir> \
    --source-connection <SOURCE_CONNECTION_NAME> \
    -c <SNOWFLAKE_CONNECTION_NAME> \
    -d <DATABASE_NAME> \
    --objects <object_name> \
    --workers 16
```

For all objects, drop `--objects`.

#### Opt-in: Keep Local Copies (`--keep-baselines`)

`--keep-baselines` additionally writes JSON copies under `artifacts/**/baselines/<YYYYMMDD>/`. Only pass it when the user explicitly asks for local files — Snowflake-only is the default for customer data-residency, and opting out is their decision. **Confirm with the user before adding this flag:**

> "`--keep-baselines` will leave baseline JSONs on your laptop under `artifacts/**/baselines/`. The default is Snowflake-only. Do you want a local copy?"

### LLM-Generated Tests (for diverse edge-case coverage)

Generate unit tests by running AI Migrator in `--no-repair` mode. Tests are generated and executed against both source and target databases, but failures do **not** trigger the repair loop. After generation, copy the resulting test artifacts to `artifacts/unit_tests/` for long-term storage and re-execution.

#### Generate Tests for Specific Objects

```bash
TARGET_DIR=.scai/jobs/unit-testing/$(date +%Y%m%d_%H%M%S)_$(openssl rand -hex 2)

uv run --project ${SKILL_DIR} migrate \
    --source ${SOURCE_DIR} \
    --converted ${CONVERTED_DIR} \
    --converted-with-code ${CONVERTED_DIR} \
    --target ${TARGET_DIR} \
    --source-dialect MS_SQL_SERVER \
    --model cortex/claude-sonnet-4-5 \
    --no-repair \
    --objects '["dbo.MyProc", "dbo.MyFunc"]'
```

This generates tests and writes YAML artifacts to `${TARGET_DIR}/tests/`. Copy them to the persistent store:

```bash
mkdir -p artifacts/unit_tests
cp -r ${TARGET_DIR}/tests/* artifacts/unit_tests/
```

#### Generate Tests for All Objects in a Project

```bash
TARGET_DIR=.scai/jobs/unit-testing/$(date +%Y%m%d_%H%M%S)_$(openssl rand -hex 2)

uv run --project ${SKILL_DIR} migrate \
    --source ${SOURCE_DIR} \
    --converted ${CONVERTED_DIR} \
    --converted-with-code ${CONVERTED_DIR} \
    --target ${TARGET_DIR} \
    --source-dialect MS_SQL_SERVER \
    --model cortex/claude-sonnet-4-5 \
    --no-repair \
    --workers 8

cp -r ${TARGET_DIR}/tests/* artifacts/unit_tests/
```

#### Background Execution (Recommended for Large Projects)

```bash
TARGET_DIR=.scai/jobs/unit-testing/$(date +%Y%m%d_%H%M%S)_$(openssl rand -hex 2)

nohup uv run --project ${SKILL_DIR} migrate \
    --source ${SOURCE_DIR} \
    --converted ${CONVERTED_DIR} \
    --converted-with-code ${CONVERTED_DIR} \
    --target ${TARGET_DIR} \
    --source-dialect MS_SQL_SERVER \
    --no-repair \
    > ${PROJECT_DIR}/test_generation.log 2>&1 &
echo "PID: $!"
```

After the background job finishes, copy artifacts: `cp -r ${TARGET_DIR}/tests/* artifacts/unit_tests/`

### Generation Key Flags

| Flag | Description |
|------|-------------|
| `--no-repair` | Skip the repair loop; generate and run tests only |
| `--source` | Path to source SQL files |
| `--converted` | Path to SnowConvert output directory (typically `snowflake/`). Must contain `Reports/SnowConvert/TopLevelCodeUnits*.csv`. |
| `--converted-with-code` | Same path as `--converted`. Tells AI Migrator the converted directory already contains the code (no extra suffix appended). |
| `--target` | Output directory (test artifacts written here) |
| `--source-dialect` | Source database dialect (MS_SQL_SERVER, ORACLE, etc.) |
| `--model` | LLM model for test generation |
| `--objects` | JSON list of object names to process |
| `--workers` | Number of parallel workers |

### Output Format (YAML)

Test artifacts are written as one YAML file per object, preserving the same field structure as the original JSONL format (`object_name`, `test_count`, `tests[]` with `inserts`/`calls` arrays):

```
${TARGET_DIR}/tests/
  test_manifest.yaml                        # Discovery manifest
  procedure/
    db_schema_proc/
      test/
        db_schema_proc.yml                  # Per-object YAML
```

#### YAML Structure

Each per-object file contains `object_name`, `test_count`, and `tests[]` with `source_test`/`target_test` preserving `inserts` and `calls` as arrays:

```yaml
object_name: dbo.MyProc
object_type: PROCEDURE
source_path: source/proc.sql
converted_path: converted/proc.sql
source_dialect: MS SQL Server
target_dialect: Snowflake
exported_at: "2026-03-10T12:00:00Z"
test_count: 1
tests:
  - test_id: 0
    source_test:
      inserts:
        - "INSERT INTO t VALUES (1)"
        - "INSERT INTO t VALUES (2)"
      calls:
        - "EXEC dbo.MyProc @orderId=1"
      generation_outcome: SUCCESS
    target_test:
      inserts:
        - "INSERT INTO t VALUES (1)"
        - "INSERT INTO t VALUES (2)"
      calls:
        - "CALL dbo.MyProc(1)"
      generation_outcome: SUCCESS
```

#### Manifest (`test_manifest.yaml`)

```yaml
exported_at: "2026-03-10T12:00:00Z"
source_dialect: MS SQL Server
target_dialect: Snowflake
object_count: 3
tests:
  - object_name: dbo.MyProc
    object_type: PROCEDURE
    source_path: source/proc.sql
    converted_path: converted/proc.sql
    source_dialect: MS SQL Server
    test_file: tests/procedure/dbo_MyProc/test/dbo_MyProc.yml
    test_count: 1
```

### Aggregating Multi-Batch Results

When using the orchestrator or running multiple CLI invocations with different object subsets, test artifacts end up in separate target directories. Use the aggregation utility to merge them:

```python
from ai_migrator.orchestrator.scripts.test_artifact_utils import aggregate_test_artifacts
from pathlib import Path

task_dirs = [Path(".scai/jobs/unit-testing/run_1"), Path(".scai/jobs/unit-testing/run_2")]
output = Path("artifacts/unit_tests")
count = aggregate_test_artifacts(task_dirs, output)
print(f"Aggregated tests for {count} objects")
```

---

## Test Execution

Run pre-existing test artifacts against live databases. No LLM is involved and no new tests are generated — this is a pure execution pass that reports pass/fail per object.

### Baseline Validation (test-runner)

Compares Snowflake output against previously captured source baselines.

```bash
cd <project_dir>
test-runner validate \
    --project-root <project_dir> \
    -c <SNOWFLAKE_CONNECTION_NAME> \
    -d <DATABASE_NAME> \
    --objects <object_name> \
    --workers 16
```

Results written to `test-results/results.json`.

After execution, update the registry with test results:

Call the `update_testing` tool with `results_path` = `<project_dir>/test-results/results.json`.

### YAML Artifact Execution (run_migration_tests)

Runs stored YAML test artifacts generated by AI Migrator. Returns exit code 0 (all pass) or 1 (any fail).

#### Prerequisites

Test artifacts must already exist in `artifacts/unit_tests/` from a prior generation run (see Test Generation above) or be committed to the repository. The CLI needs:
- `--source` and `--converted` directories (for building dependency/object SQL context)
- `--target` directory (workspace for execution output)
- `--reuse-tests` pointing to `artifacts/unit_tests/`

#### Execute All Tests

```bash
TARGET_DIR=.scai/jobs/unit-testing/$(date +%Y%m%d_%H%M%S)_$(openssl rand -hex 2)

uv run --project ${SKILL_DIR} run_migration_tests \
    --source ${SOURCE_DIR} \
    --converted ${CONVERTED_DIR} \
    --converted-with-code ${CONVERTED_DIR} \
    --target ${TARGET_DIR} \
    --reuse-tests artifacts/unit_tests \
    --source-dialect MS_SQL_SERVER \
    --workers 8
```

#### Execute Tests for Specific Objects

```bash
TARGET_DIR=.scai/jobs/unit-testing/$(date +%Y%m%d_%H%M%S)_$(openssl rand -hex 2)

uv run --project ${SKILL_DIR} run_migration_tests \
    --source ${SOURCE_DIR} \
    --converted ${CONVERTED_DIR} \
    --converted-with-code ${CONVERTED_DIR} \
    --target ${TARGET_DIR} \
    --reuse-tests artifacts/unit_tests \
    --source-dialect MS_SQL_SERVER \
    --objects '["dbo.MyProc", "dbo.MyFunc"]'
```

#### Execute with Object Filtering

```bash
TARGET_DIR=.scai/jobs/unit-testing/$(date +%Y%m%d_%H%M%S)_$(openssl rand -hex 2)

# Filter by regex pattern
uv run --project ${SKILL_DIR} run_migration_tests \
    --source ${SOURCE_DIR} \
    --converted ${CONVERTED_DIR} \
    --converted-with-code ${CONVERTED_DIR} \
    --target ${TARGET_DIR} \
    --reuse-tests artifacts/unit_tests \
    --select "dbo\.tbl_.*"

# Limit number of objects
uv run --project ${SKILL_DIR} run_migration_tests \
    --source ${SOURCE_DIR} \
    --converted ${CONVERTED_DIR} \
    --converted-with-code ${CONVERTED_DIR} \
    --target ${TARGET_DIR} \
    --reuse-tests artifacts/unit_tests \
    --limit 10
```

### Execution Key Flags

| Flag | Description |
|------|-------------|
| `--source` | Path to source SQL files |
| `--converted` | Path to SnowConvert output directory (typically `snowflake/`). Must contain `Reports/SnowConvert/TopLevelCodeUnits*.csv`. |
| `--converted-with-code` | Same path as `--converted`. Tells the test runner the converted directory already contains the code. |
| `--target` | Output directory for execution results |
| `--reuse-tests` | Path to directory containing test artifacts |
| `--source-dialect` | Source database dialect |
| `--objects` | JSON list of object names to test |
| `--select` | Regex pattern to filter objects by name |
| `--limit` | Maximum number of objects to test |
| `--workers` | Number of parallel execution threads |

### Execution Output

The CLI prints a summary and returns exit code 0 (all pass) or 1 (any fail):

```
Loading tests from artifacts/unit_tests/test_manifest.yaml...
Found 15 objects with 15 tests
Loading project from source/ and converted/...
Matched 15 objects with tests
After filtering: 15 objects, 15 tests

Executing tests on Snowflake + Source (8 workers)...

========================================
Objects: 15 tested
Tests:   15 total, 12 passed, 3 failed
========================================
```

Per-object results are also written to `${TARGET_DIR}/progress.json` for programmatic consumption. The detailed report is at `artifacts/unit_tests/results/run_<timestamp>/test_report.json`.

### Updating the Registry

After generation or execution produces a `test_report.json`, call the `update_unit_testing` MCP tool to write pass/fail results into the project's code unit registry:

```
update_unit_testing(report_path="artifacts/unit_tests/results/run_<timestamp>/test_report.json")
```

This sets `codeStatus.testing.status` to `completed` (all tests passed) or `failed` for each object, along with detailed counts. Always call this after every test run so that `testing_progress` and the migration dashboard reflect current results.

### Update Registry After Execution

After either mode completes, update the Code Unit Registry so that `testing_progress` and `next_object` reflect the latest results:

- **Baseline mode:** Call `update_testing` with `results_path` = `<project_dir>/test-results/results.json`
- **YAML artifact mode:** Call `update_testing` with `results_path` = `${TARGET_DIR}/progress.json`

Both formats are auto-detected. The tool writes `codeStatus.testing.status` (completed/failed) and pass/fail counts into each registry entry.

---

## Fix-Retest Loop

For diagnosing failures, applying fixes, and re-testing, load the migrate-object skill which owns the deploy → test → diagnose → fix loop:

→ Load [../migrate-objects/migrate-object/SKILL.md](../migrate-objects/migrate-object/SKILL.md)

That skill handles deployment verification, `update_deployment`, `update_testing`, rule search, manual fix, and rule extraction in a single cohesive loop.

---

## Sub-Skills

### Test Bed

Generate synthetic test infrastructure (schema, tables, data) from the code unit registry for comprehensive 2-sided testing.

> **Note:** This sub-skill is experimental and not yet available in the plugin. See `experimentals/unittest/test-bed/SKILL.md`.

---

## Next Steps

After test generation or execution:
- **Update the registry** -> Call `update_unit_testing` with the `test_report.json` path (see above)
- **Execute stored tests** → See Test Execution section above
- **All tests pass** → Objects are verified; proceed to human review
- **Some tests fail** → Load [migrate-object](../migrate-objects/migrate-object/SKILL.md) for the fix-retest loop
- **Need fresh tests** → See Test Generation section above
- **Create synthetic test data** → See Test Bed sub-skill above (experimental)
- **Commit to repo** → Store test artifacts in version control for CI/CD
