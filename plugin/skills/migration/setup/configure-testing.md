---
name: configure-testing
description: Pick the testing path for migrated procedures and functions — source-data or synthetic — then verify the Snowflake side is ready. Persists via `configure(testing_data_source=…)`.
license: Proprietary. See License-Skills for complete terms
---

# Configure the testing framework

Invoked by the setup state machine after the Snowflake target is set. The
choice is made once per project and drives how every procedure and
function gets its test cases later.

## On entry

`configure()` carries the user's preference in `testing_data_source`.

- **Already set** → returning user. Skip the sell block and both
  questions. Show a one-line recap, then jump to **Verify** below to
  confirm the environment is still ready in this session:
  > Continuing in **source-data mode** with `<test_seed_source>`
  > (`<execution_log_path>` if logs). Say "change testing path" to switch.

  If `testing_data_source == "synthetic"`:
  > Continuing in **synthetic-data mode**. Say "change testing path" to
  > switch.

  If the user says "change testing path", fall through to the sell block
  with the existing values cleared (re-ask Q1, then Q2 if applicable).

- **Not set** → first-time visit. Run everything below in order.

## Sell block (first-time only)

Show the user this block verbatim:

> **Now we'll configure the testing framework.** This makes sure your migrated procedures and functions on Snowflake produce the same output as the originals on your source database. A quick orientation before we pick how to run it:
>
> - **It's an automated comparison.** For each procedure, the framework runs it on your source DB *and* on Snowflake, then compares the two results. Anything that doesn't match shows up as a failure you can drill into.
> - **Your source DB is the reference.** Whatever your source procedure produces is treated as the "correct" answer; the goal is to make Snowflake match.
> - **It handles the hard cases.** Procedures that return multiple result sets, that use OUTPUT/INOUT parameters, or that modify tables (DML) are all covered — for DML, table changes are compared, not just return values.
> - **Tests are isolated.** Each test runs against a fresh clone of your data on the Snowflake side; the source side uses snapshot or transactional isolation. Tests can't pollute each other or your real data.
> - **Results are saved in Snowflake.** Expected outputs from your source DB are captured once and stored in Snowflake, so the framework can compare against them repeatedly while you iterate on a fix — no need to re-query the source. Test outcomes are also stored in Snowflake, ready to review or share later.
> - **Multi-dialect.** Works for SQL Server, Oracle, Redshift, PostgreSQL, and Teradata source databases.

## Q1: synthetic-data or source-data

Show the two-path framing, then ask:

> **Two testing paths, picked once per project:**
>
> **Source-data tests** — when your source DB has representative production-like data. Test cases come from real values (either query logs or queries against the source).
>
> **Synthetic-data tests** — when source data isn't representative or you want isolated logic tests. The agent analyzes each proc's branches and generates seed data + assertions from scratch.
>
> Does your source DB have representative production-like data?
> - **A) Yes** → use source data
> - **B) No** → use synthetic data tests

Persist the answer **without** `recheck=true` yet — the recheck is batched
into **Verify** below.

- A → `configure(testing_data_source="source_database")`
- B → `configure(testing_data_source="synthetic")`

Picking **synthetic** also queues testbed generation as the final setup
step — mention it when you confirm the choice, so the extra work isn't a
surprise.

## Q2: query logs (source-data only)

If the user picked synthetic, skip this section.

Ask:

> **Optional:** do you have query logs (CSV) capturing real proc invocations from your source DB?
> - **Yes** → provide the path; the seeder will populate `test_cases:` automatically from real call sites for procs that appear in the log.
> - **No** → the seeder will scaffold stubs; AI fills them later by querying the source DB.

Persist via `configure(...)` (still no `recheck=true`):

- Yes → `configure(test_seed_source="logs", execution_log_path="<path>")`
- No → `configure(test_seed_source="source_db_query")`

## Verify

Call `configure(recheck=true)` (no other args). This:

1. Invalidates the cached `schema_manager` and `prereqs` reports for the
   current `(snowflake_connection, snowflake_database)`.
2. Re-runs `ensure_schemas`. `check_validation` now sees
   `testing_data_source` is set and **auto-deploys VALIDATION** via
   `scai test validate --create-schema` if it's missing.
3. Re-runs `ensure_prereqs`. `clone_perms` now sees `testing_data_source`
   is set and actually probes (was `not_applicable` before).

## Parse status lines and route

Look at the lines in the configure response. All `ok` / `not_applicable`
→ done; return to the parent setup skill.

Any failure → surface the verbatim message and **stop**. Don't try to
auto-fix. The user reads the relevant section of
[../migrate-objects/references/testing-framework-perms.md](../migrate-objects/references/testing-framework-perms.md),
applies the GRANT or fixes the connection externally, then says "done" /
"recheck" — call `configure(recheck=true)` and re-parse. Loop until
everything is green.

- `schema_status_validation: error("<msg>")` → surface `<msg>`; common cause is missing `CREATE SCHEMA on DATABASE` or `OWNERSHIP on VALIDATION`. Reference doc covers both.
- `prereq_status_clone_perms: failed("<msg>")` → surface `<msg>`; cause is missing `CREATE DATABASE ON ACCOUNT` (needed for clone-based test isolation). Reference doc has the GRANT.
- `prereq_status_source_connection: failed("<msg>")` → surface and route to the dialect connection skill (`../connection/<dialect>-connection/SKILL.md`).
- Any `error(...)` on either block → surface, suggest `configure(recheck=true)` once if transient-looking, escalate to the user if it persists.

## If the user won't pick a path

A table-and-view-only migration never runs equivalence tests. If the user
says they don't need the testing framework at all, opt out permanently:

```
configure(tasks={"configureTesting": {"enabled": false}})
```

## On completion

Return to the parent setup skill. The resolver will pick the next task,
which depends on the answer to Q1:

- **synthetic** → `generateTestbed`. Synthetic tests need data to run
  against, so the testbed generator (mine → validate → compile →
  generate) is the next step. Tell the user that's coming.
- **source-data** → setup is complete. Test cases come from the source
  database, so there's nothing to generate.
