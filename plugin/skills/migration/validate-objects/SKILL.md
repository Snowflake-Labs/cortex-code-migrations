---
name: validate-objects
description: Validate migrated data between source and Snowflake using cloud validation (SPCS). Setup, run, background Monitor (or poll fallback), and end-of-run summary. Triggers: validate data, validate tables, data validation, check data.
parent_skill: migration
---

# Validate Objects

## On Entry

Tell the user:
> **Data Validation** — I'll compare your migrated data against the source to verify row counts, schema matches, and data integrity.

## Step 1: Configure Session

Call `configure()` to retrieve the current configuration.

Check the returned values for `snowflake_connection`, `source_connection`, and `snowflake_database`:

- **All three set** → confirm them with the user (e.g. "Using snowflake_connection=X, source_connection=Y, database=Z — correct?"). If the user wants changes, call `configure` with the updated values.
- **Any missing** → ask the user for the missing values, then call `configure` with all of them.

Ensure the shared infrastructure is up before validating: run `data_infrastructure(mode="up")` — pass `compute_pool="<POOL>"` for SPCS (ask the user for the pool name) or omit it for a local orchestrator.

## Step 2: Validate

Load [actions/validate_tables.md](actions/validate_tables.md) (Steps 4–6: background Monitor or poll fallback, error-first report, teardown).

## Step 3: Wave progress

The **error-first data validation report** (Result + Workflow, Errors, Suggested fixes) is produced in [actions/validate_tables.md](actions/validate_tables.md) **Step 5** via `job_status(job_id, details=true)`. Do not substitute `migration_status()` for that report.

After `validate_tables.md` completes (including the summary and teardown offer), optionally call `migration_status()` for wave-level context only:

- If the wave is complete, the next `configure()` call will auto-advance to the next wave.
- When `migration_status()` shows no remaining waves (all-waves-done), invoke [../data-infrastructure/teardown/SKILL.md](../data-infrastructure/teardown/SKILL.md) unconditionally before returning to the parent — in addition to the per-wave teardown prompt in `validate_tables.md` Step 6 when applicable.
