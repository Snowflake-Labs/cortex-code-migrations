# Action: Migrate Functions and Procedures

Deploy, test, and fix functions and procedures using two-sided testing (source output vs Snowflake output). Processes one object at a time in dependency order.

The parent skill (`migrate-objects/SKILL.md`) passes `<testing_data_source>` — either `"source_database"` or `"synthetic"`.

## Step 1: Get Next Object

You should already have an object to fix. If not, use the dependency graph to pick the next object in the wave:

```
next_object()
```

**If all objects in the wave have passed**, proceed to Step 4.

## Step 2: Prepare Test Data

Once you have an object name (e.g., `dbo.CalculateLineTotal`), prepare test data based on `<testing_data_source>`.

### If `testing_data_source == "source_database"`

Check if baselines exist:

```bash
ls <project_dir>/artifacts/**/test/*<object_name>*.yml 2>/dev/null
ls <project_dir>/.scai/baselines/**/*<object_name>* 2>/dev/null
```

**No baselines exist?**

Tell the user: *"No baselines found for `<object_name>`. We need to capture source baselines before we can validate."*

→ **Spawn a foreground subagent** (Task tool) to capture baselines:

```
Read and follow baseline-capture/SKILL.md

Context:
- Object: <object_name>
- Project dir: <project_dir>
- Source connection: <source_connection_name>
- Snowflake connection: <connection_name>
- Database: <database_name>

Capture source baselines for this object.
Report back: path chosen (query_logs or ai_assisted), test case count, baseline count, upload status.
```

**Baselines exist?** → proceed to Step 3.

### If `testing_data_source == "synthetic"`

Check if AI-generated test artifacts already exist for this object:

```bash
ls <project_dir>/artifacts/unit_tests/**/test/*<object_name>*.yml 2>/dev/null
```

**Artifacts exist** → proceed to Step 3 (they will be reused via `--reuse-tests`).

**No artifacts** → generate them for this single object:

```bash
SKILL_DIR="<absolute path to plugin/skills/migration/tools/ai-migrator>"
SOURCE_DIR="<project_dir>/source"
CONVERTED_DIR="<project_dir>/snowflake"
TARGET_DIR="<project_dir>/.scai/jobs/unit-testing/$(date +%Y%m%d_%H%M%S)_$(openssl rand -hex 2)"

uv run --project ${SKILL_DIR} migrate \
    --source ${SOURCE_DIR} \
    --converted ${CONVERTED_DIR} \
    --converted-with-code ${CONVERTED_DIR} \
    --target ${TARGET_DIR} \
    --source-dialect MS_SQL_SERVER \
    --model cortex/claude-sonnet-4-5 \
    --no-repair \
    --objects '["<object_name>"]'

mkdir -p <project_dir>/artifacts/unit_tests
cp -r ${TARGET_DIR}/tests/* <project_dir>/artifacts/unit_tests/
```

For detailed flags and output format, see [../../unittest/SKILL.md](../../unittest/SKILL.md).

## Step 3: Run the Migrate-Object Loop

Load the core migration loop for the current object:

→ `../migrate-object/SKILL.md`

Pass `<testing_data_source>` to the migrate-object loop. It will run the appropriate tests in each deploy-test-fix iteration.

This handles:
1. Pre-apply known migration rules (regex + Cortex semantic search)
2. Resolve EWI markers
3. Deploy to Snowflake
4. Run tests (source DB baselines or synthetic data, based on `testing_data_source`)
5. If tests fail → diagnose and fix → redeploy → retest
6. If tests pass → deduce rule (if code changed) → update registry → commit

After the object passes (or user decides to skip it), go back to **Step 1** for the next object.

## Step 4: Wave Complete

When all functions/procedures in the wave have passed testing:

```
testing_progress()
```

Present the final summary:

```
Functions/Procedures in Wave <N>:
  Passed:  <count>
  Failed:  <count> (user skipped or max iterations reached)
  Blocked: <count> (dependencies not met)
```

Return control to the parent skill. The parent will retry any views that were blocked on these functions.

## References

These files are part of the migrate-objects skill and are used by the migrate-object loop:

| File | Purpose |
|------|---------|
| `../migrate-object/SKILL.md` | Core deploy → test → diagnose → fix loop |
| `../migrate-object/DIAGNOSE_FIX.md` | Diagnose test failures and apply fixes |
| `../migrate-object/DEDUCE_RULE.md` | Extract reusable rules from successful fixes |
| `../baseline-capture/SKILL.md` | Capture source baselines (routes to QUERY_LOGS or SWARM) |
| `../../unittest/SKILL.md` | Synthetic data testing reference (AI Migrator commands) |
| `../setup/SKILL.md` | One-time validation framework setup |
