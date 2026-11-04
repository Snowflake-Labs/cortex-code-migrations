---
name: configure-testing
description: Verify the Snowflake side is ready for the chosen testing path (source-data or testbed). The path choice is made by the `chooseTestingPath` prompt node before this skill runs. Persists via `configure(testing_data_source=…)`.
license: Proprietary. See License-Skills for complete terms
---

# Configure the testing framework

Invoked by the setup state machine after `chooseTestingPath` has set
`testing_data_source`. This skill verifies the Snowflake environment is
ready for the chosen path and (on the source-data path) asks about query
logs.

## On entry

`configure()` carries the user's preference in `testing_data_source`
(already set by the `chooseTestingPath` prompt node).

- **Already set** → show a one-line recap, then jump to **Verify** below:
  > Continuing in **source-data mode** with `<test_seed_source>`
  > (`<execution_log_path>` if logs). Say "change testing path" to switch.

  If `testing_data_source == "testbed"`:
  > Continuing in **testbed mode**. Say "change testing path" to
  > switch.

  If `testing_data_source == "synthetic"`:
  > Continuing in **synthetic-data mode** (legacy INSERT-authored tests).
  > Say "change testing path" to switch.

  If the user says "change testing path", clear the existing values and
  re-ask Q1 (query logs, if applicable).

## Sell block

In two or three sentences of your own, tell the user that we are now configuring the **testing framework**, which checks that the migrated procedures and functions produce the same output on Snowflake as on the source. Draw on these facts; do not recite them:

- It runs each procedure on the source and on Snowflake and compares the results; the source is the reference, and each mismatch is a failure they can drill into.
- It covers multiple result sets, OUTPUT/INOUT parameters and DML (table changes are compared).
- Tests are isolated: a fresh clone of the data on Snowflake, snapshot or transactional isolation on the source.
- Expected outputs are captured once and stored in Snowflake with the test outcomes, so fixes can be retried without re-querying the source.
- Sources: SQL Server, Oracle, Redshift, PostgreSQL and Teradata.

## Q1: query logs (source-data only)

If the user picked testbed or synthetic, skip this section.

Ask:

> **Optional:** do you have query logs (CSV) capturing real proc invocations from your source DB?
> - **Yes** → provide the path; the seeder will populate `test_cases:` automatically from real call sites for procs that appear in the log.
> - **No** → the seeder will scaffold stubs; AI fills them later by querying the source DB.

Persist via `configure(...)` (still no `ensure_metadata_schema=true`):

- Yes → `configure(test_seed_source="logs", execution_log_path="<path>")`
- No → `configure(test_seed_source="source_db_query")`

## Verify

Call `configure(ensure_metadata_schema=true)` (no other args). This:

1. Invalidates the cached `schema_manager` and `prereqs` reports for the
   current `(snowflake_connection, snowflake_database)`, and clears
   `schema_version` in `.scai/config/plugin.local.yml` so a matching plugin
   version no longer skips the probe. It does **not** clear
   `schema_metadata_database` and does **not** recreate a vanished metadata
   database.
2. Re-runs `ensure_schemas`. `check_validation` now sees
   `testing_data_source` is set and **runs** `scai test validate
   --create-schema` (capture's own setup step), even if VALIDATION exists. `check_dmv`
   **auto-deploys DATA_MIGRATION / DATA_VALIDATION** via
   `scai data migrate-schema` once data migration is opted in.
3. Re-runs `ensure_prereqs`. `clone_perms` now sees `testing_data_source`
   is set and actually probes (was `not_applicable` before).

## Parse status lines and route

Look at the lines in the configure response. All `ok` / `not_applicable`
→ done; return to the parent setup skill.

Any failure → surface the verbatim message and **stop**. Don't try to
auto-fix. The user reads the relevant section of
[../migrate-objects/references/testing-framework-perms.md](../migrate-objects/references/testing-framework-perms.md),
applies the GRANT or fixes the connection externally, then says "done" /
"recheck" — call `configure(ensure_metadata_schema=true)` and re-parse. Loop until
everything is green.

- `schema_status_validation: error("<msg>")` → surface `<msg>`; common cause is missing `CREATE SCHEMA on DATABASE` or `OWNERSHIP on VALIDATION`. Reference doc covers both.
- `schema_status_dmv: error("<msg>")` → surface `<msg>`; `scai data migrate-schema` failed while installing DATA_MIGRATION / DATA_VALIDATION in the metadata database. Common cause is missing `CREATE SCHEMA` on that database.
- `installing("…")` on any `schema_status_*` → still running, not a failure: tell the user, then call `configure()` with no arguments to keep waiting.
- `prereq_status_clone_perms: failed("<msg>")` → surface `<msg>`; cause is missing `CREATE DATABASE ON ACCOUNT` (needed for clone-based test isolation). Reference doc has the GRANT. If the account can't grant it, ask the user to have pre-created databases named under `testing_sandbox_databases` in test_config.yaml (reference doc), then recheck.
- `schema_status_metadata: error("...not visible...recreate_metadata_database=true")` → surface the message. Ask the user whether to restore/GRANT USAGE / repoint `metadata_database`, or start fresh. Only after they confirm starting fresh, call `configure(recreate_metadata_database=true)`. Do **not** treat this as a transient recheck.
- `schema_status_metadata: error("...cannot tell whether...already bootstrapped...")` → surface. Pre-upgrade stamp under a non-default pin, or the latch names a different metadata database. If the user confirms the database already exists, call `configure(ensure_metadata_schema=true)` (recheck latches it). Only after they confirm starting **empty**, call `configure(recreate_metadata_database=true)`.
- `schema_status_metadata: error("...not reachable...")` → surface. Mixed-case / quoted stored name; rename per `configure-snowflake-target.md`, do **not** recreate.
- `schema_status_metadata: error("...could not verify...still exists...")` → surface and retry with `configure(ensure_metadata_schema=true)` once the session is healthy. Do **not** recreate; existence is unknown.
- Any other `error(...)` on either block → surface, suggest `configure(ensure_metadata_schema=true)` once if transient-looking, escalate to the user if it persists.

## If the user won't pick a path

A table-and-view-only migration never runs equivalence tests. If the user
says they don't need the testing framework at all, opt out permanently:

```
configure(tasks={"configureTesting": {"enabled": false}})
```

## On completion

Return to the parent setup skill. The state machine routes to the next
step based on the testing path:

- **testbed** (and legacy **synthetic**) → `generateTestbed`, then data
  infrastructure. The next step bootstraps non-table coupling state; each
  dependency-ready table walker later mines, validates/enriches, generates,
  and loads that table's CSV. Tell the user that's coming. On SQL Server
  the rows load into an empty `AIMSBX_TB_*` catalog `configure` creates
  and binds as `source:`; elsewhere, or if that create failed, an
  extracted source is preserved and gets no rows.
- **source-data** → data infrastructure. Autonomous skips the opt-in question
  and always continues to source-connection + sandbox bring-up. Manual is
  asked whether they need data migration/validation infrastructure.
