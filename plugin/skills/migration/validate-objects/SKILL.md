---
name: validate-objects
description: Validate migrated data between source and Snowflake using the shared configured infrastructure. Dispatch, background Monitor, and end-of-run summary. Triggers: validate data, validate tables, data validation, check data.
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

Use the shared infrastructure configured during setup. Do not ask local vs
SPCS again, choose a pool, or start/repair infrastructure from a per-object
validation task. If dispatch reports that infrastructure is unavailable,
return the remediation to the main agent; it resumes the saved placement
through [`../data-infrastructure/SKILL.md`](../data-infrastructure/SKILL.md).
Only an explicit user request changes that persisted setup.

## Step 2: Validate

Load [actions/validate_tables.md](actions/validate_tables.md) (Steps 4–6: background Monitor, error-first report, main-agent teardown).

## Step 3: Wave progress

The **error-first data validation report** (Result + Workflow, Errors,
Suggested fixes) is produced in
[actions/validate_tables.md](actions/validate_tables.md) **Step 5** from
Monitor's terminal `detail.completion`. Use `job_status(details=true)` only
for deeper failure diagnostics; do not substitute `migration_status()`.

After `validate_tables.md` completes, optionally call `migration_status()` for wave-level context only:

- If the wave is complete, the next `configure()` call will auto-advance to the next wave.
- A per-object subagent does not tear down shared infrastructure. The main
  agent owns end-of-wave/session teardown after all active slots finish.
