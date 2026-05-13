# Action: Migrate Functions and Procedures

## On Entry

Call `testing_progress()` and tell the user:
> **Migrating functions and procedures** (Wave `<N>`). `<done_count>/<total>` done so far, `<ready_count>` ready to work on, `<blocked_count>` blocked on dependencies.

Deploy, test, and fix functions and procedures using two-sided testing (source output vs Snowflake output). Processes one object at a time in dependency order.

The parent skill (`migrate-objects/SKILL.md`) passes `<testing_data_source>`, either `"source_database"` or `"synthetic"`.

## Step 1: Get Next Object

You should already have an object to fix. If not, use the dependency graph to pick the next object in the wave:

```
next_object()
```

**If all objects in the wave have passed**, proceed to Step 4.

## Step 2: Prepare Test Data

Once you have an object name (e.g., `dbo.CalculateLineTotal`), check whether test artifacts and baselines already exist for it:

```bash
ls <project_dir>/artifacts/**/test/*<object_name>*.yml 2>/dev/null

snow stage list-files @<DATABASE>.VALIDATION.BASELINES \
  --pattern ".*<object_name>.*" \
  -c <SNOWFLAKE_CONNECTION_NAME> 2>/dev/null
```

**Artifacts and baselines exist?** → proceed to Step 3.

**Missing either?** → **Spawn a foreground subagent** (Task tool) to seed + capture:

```
Read and follow baseline-capture/SKILL.md

Context:
- Object: <object_name>
- Project dir: <project_dir>
- Source connection: <source_connection_name>
- Snowflake connection: <connection_name>
- Database: <database_name>
- testing_data_source: <testing_data_source>

Seed test YAMLs (per testing_data_source) and capture source baselines for this object.
Report back: seeder chosen (query_logs / ai_assisted / synthetic), test case count, baseline count, upload status.
```

`baseline-capture/SKILL.md` reads `testing_data_source` to pick the seeder:
- `source_database` → asks Query Logs vs AI-Assisted Swarm
- `synthetic` → Branch-Driven Synthetic ([synthetic-seeder](../baseline-capture/synthetic-seeder/SKILL.md))

All three seeders end by running `scai test capture` via `baseline-capture/CAPTURE.md`, so the loop's test command is identical regardless of path.

## Step 3: Run the Migrate-Object Loop

Load the core migration loop for the current object:

→ `../migrate-object/SKILL.md`

This handles:
1. Pre-apply known migration rules (regex + Cortex semantic search)
2. Resolve EWI markers
3. Deploy to Snowflake
4. Run `scai test validate` (baselines captured during prep above are reused for every iteration)
5. If tests fail → diagnose and fix → redeploy → retest
6. If tests pass → deduce rule (if code changed) → update registry → commit

After the object passes (or user decides to skip it), go back to **Step 1** for the next object.

## Step 4: Wave Complete

When all functions/procedures in the wave have passed testing:

```
testing_progress()
```

Tell the user:
> **Wave `<N>` functions/procedures complete.** `<passed>` passed, `<failed>` failed, `<blocked>` blocked on dependencies.

Return control to the parent skill. The parent will retry any views that were blocked on these functions.

## References

These files are part of the migrate-objects skill and are used by the migrate-object loop:

| File | Purpose |
|------|---------|
| `../migrate-object/SKILL.md` | Core deploy → test → diagnose → fix loop |
| `../migrate-object/DIAGNOSE_FIX.md` | Diagnose test failures and apply fixes |
| `../migrate-object/DEDUCE_RULE.md` | Extract reusable rules from successful fixes |
| `../baseline-capture/SKILL.md` | Seed YAMLs + capture source baselines (routes to QUERY_LOGS, SWARM, or synthetic-seeder based on `testing_data_source`) |
| `../baseline-capture/synthetic-seeder/SKILL.md` | LLM-driven synthetic test generation (branch-driven seeder) |
| `../setup/SKILL.md` | One-time validation framework setup |
