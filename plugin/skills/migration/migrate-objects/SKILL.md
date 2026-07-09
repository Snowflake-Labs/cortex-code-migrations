---
name: migrate-objects
description: Deploy and validate all object types (tables, views, functions, procedures) in dependency order. Triggers: deploy objects, migrate objects, deploy tables, deploy views, migrate functions, migrate procedures.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# Migrate Objects

## Prerequisite: Support Level Check

Check `support` from the `configure()` response.

If `support` is `basic`, load [BASIC_SUPPORT.md](BASIC_SUPPORT.md) and **STOP**. Do not continue with the steps below.

## On Entry **IMPORTANT DO NOT SKIP**

Tell the user:
> **Phase 2: Migrate Objects.** Setup is complete. Now we'll deploy your objects to Snowflake according to your wave plan (if you created one in assessments). Each object goes through a deploy-test-fix loop.

## Step 1: Configure Session

Call `configure()` to retrieve the current configuration.

Check the returned values for `snowflake_connection`, `source_connection`, and `snowflake_database`:

- **All three set** → confirm them with the user (e.g. "Using snowflake_connection=X, source_connection=Y, deploying to database Z. Correct?"). If the user wants changes, call `configure` with the updated values.
- **Any missing** → ask the user for the missing values, then call `configure` with all of them.

Once a `snowflake_connection` and `snowflake_database` are set, the same `configure()` response includes status lines (`schema_status_*`, `prereq_status_*`). **Ignore them in Step 1** — they are checked in Step 2.d/2.e after the user opts into testing. The one exception:

- `schema_status_validation: database_missing` → tell the user the configured database does not exist, ask before creating; if confirmed, run `CREATE DATABASE <snowflake_database>;` then call `configure(recheck=true)` to refresh. Do **not** auto-create — the name may be a typo.

## Step 2: Configure Testing Framework

`configure()` carries the user's testing preference in `testing_data_source`. On entry:

- **Already set** → returning user. Skip 2.a (sell), 2.b (Q1), 2.c (Q2). Show a one-line recap and run 2.d to confirm the environment is still ready in this session:
  >  Continuing in **source-data mode** with `<test_seed_source>` (`<execution_log_path>` if logs). Say "change testing path" to switch.

  If `testing_data_source == "synthetic"`:
  >  Continuing in **synthetic-data mode**. Say "change testing path" to switch.

  If the user says "change testing path", fall through to 2.a–2.c with the existing values cleared (re-ask Q1, then Q2 if applicable).

- **Not set** → first-time visit. Run 2.a through 2.d in order.

### 2.a — Sell block (first-time only)

Show the user this block verbatim:

> **Now we'll configure the testing framework.** This makes sure your migrated procedures and functions on Snowflake produce the same output as the originals on your source database. A quick orientation before we pick how to run it:
>
> - **It's an automated comparison.** For each procedure, the framework runs it on your source DB *and* on Snowflake, then compares the two results. Anything that doesn't match shows up as a failure you can drill into.
> - **Your source DB is the reference.** Whatever your source procedure produces is treated as the "correct" answer; the goal is to make Snowflake match.
> - **It handles the hard cases.** Procedures that return multiple result sets, that use OUTPUT/INOUT parameters, or that modify tables (DML) are all covered — for DML, table changes are compared, not just return values.
> - **Tests are isolated.** Each test runs against a fresh clone of your data on the Snowflake side; the source side uses snapshot or transactional isolation. Tests can't pollute each other or your real data.
> - **Results are saved in Snowflake.** Expected outputs from your source DB are captured once and stored in Snowflake, so the framework can compare against them repeatedly while you iterate on a fix — no need to re-query the source. Test outcomes are also stored in Snowflake, ready to review or share later.
> - **Multi-dialect.** Works for SQL Server, Oracle, Redshift, PostgreSQL, and Teradata source databases.

### 2.b — Q1: synthetic-data or source-data

Show the two-path framing, then ask:

> **Two testing paths, picked once per project:**
>
> **Source-data tests** — when your source DB has representative production-like data. Test cases come from real values (either query logs or queries against the source).
>
> **Synthetic-data tests** — when source data isn't representative or you want isolated logic tests. The agent analyzes each proc's branches and generates seed data + assertions from scratch.
>
> Does your source DB have representative production-like data?
> - **A) Yes** → source-data path
> - **B) No** → synthetic-data path

Persist the answer **without** `recheck=true` yet — we batch the recheck for 2.d.

- A → `configure(testing_data_source="source_database")`
- B → `configure(testing_data_source="synthetic")`

### 2.c — Q2: query logs (source-data only)

If the user picked synthetic, skip this section.

Ask:

> **Optional:** do you have query logs (CSV) capturing real proc invocations from your source DB?
> - **Yes** → provide the path; the seeder will populate `test_cases:` automatically from real call sites for procs that appear in the log.
> - **No** → the seeder will scaffold stubs; AI fills them later by querying the source DB.

Persist via `configure(...)` (still no `recheck=true`):

- Yes → `configure(test_seed_source="logs", execution_log_path="<path>")`
- No → `configure(test_seed_source="source_db_query")`

### 2.d — Verify environment

Call `configure(recheck=true)` (no other args). This:

1. Invalidates the cached `schema_manager` and `prereqs` reports for the current `(snowflake_connection, snowflake_database)`.
2. Re-runs `ensure_schemas`. `check_validation` now sees `testing_data_source` is set and **auto-deploys VALIDATION** via `scai test validate --create-schema` if it's missing.
3. Re-runs `ensure_prereqs`. `clone_perms` now sees `testing_data_source` is set and actually probes (was `not_applicable` before).

### 2.e — Parse status lines and route

Look at the lines in the configure response. All `ok` / `not_applicable` → continue to Step 3.

Any failure → surface the verbatim message and **stop**. Don't try to auto-fix. The user reads the relevant section of [references/testing-framework-perms.md](references/testing-framework-perms.md), applies the GRANT or fixes the connection externally, then says "done" / "recheck" — the agent calls `configure(recheck=true)` and re-parses. Loop until everything is green.

- `schema_status_validation: error("<msg>")` → surface `<msg>`; common cause is missing `CREATE SCHEMA on DATABASE` or `OWNERSHIP on VALIDATION`. Reference doc covers both.
- `prereq_status_clone_perms: failed("<msg>")` → surface `<msg>`; cause is missing `CREATE DATABASE ON ACCOUNT` (needed for clone-based test isolation). Reference doc has the GRANT.
- `prereq_status_source_connection: failed("<msg>")` → surface and route to the dialect connection skill (`../connection/<dialect>-connection/SKILL.md`).
- Any `error(...)` on either block → surface, suggest `configure(recheck=true)` once if transient-looking, escalate to the user if it persists.

## Step 3: Object Loop

**IMPORTANT** Ask the user to `/compact` between work units to free up context. **IMPORTANT**

### 3a. Pull status

> **Entry call — always.** Whenever you enter this skill, you must **first** call `migration_status(mode="my_objects_summary")`.

Cache the response — it drives the render in 3b and the drill-down `id`s in 3c.

If `groups` is empty, `blocked_groups` is empty, and `errored_count` and `done_count` are both 0, the user has no active claims. Tell them so and go to Step 3c → **"User picked `claimObjects`"** to pick up new work.

### 3b. Render

> **Finish before claiming new work.** Done objects sitting unmerged keep your branch ahead of `main`, which forces every teammate to rebase against stale state (or worse, duplicate the work you've already finished). Whenever `done_count > 0`, you must steer the user toward `finishObjects` before offering any new claims.

Show **only** the following status lines, all derived from the cached summary response. Skip any line whose count is zero or whose group is empty — do not write "(no errored bucket)" or "(none)" placeholders, and do not mention buckets that don't apply.

> **Use `group.user_label` verbatim.** Every group entry carries a server-controlled `user_label` (e.g. `"Generate test cases from source database"`). Render it exactly as returned. **Do not paraphrase, shorten, or substitute the camelCase `group.task` identifier** — those identifiers (`seedSourceDb`, `captureBaseline`, `extractRules`, ...) are opaque to end users and must not appear in your output.

- One line per `group`: `<group.count> <group.object_type>s ready: <group.user_label>`.
- One line per `blocked_groups` entry: `<count> <object_type>s blocked at "<blocked_group.user_label>" (waiting on dependencies)` — only if `blocked_groups` is non-empty. Don't list individual deps here; that comes from the drill-down in 3c.
- `<done_count> objects ready to finish (merge)` — only if `done_count > 0`.
- `<errored_count> objects errored` — only if `errored_count > 0`.

Then ask the user to pick a next action. **Only list actions you are actually offering** — never include an absent option just to acknowledge it. Build the action menu like this:

1. One numbered item per task group, labelled `<group.user_label> for the <group.count> <group.object_type>(s)` — e.g. `Deploy to Snowflake for the 5 tables`, `Generate test cases from source database for the 1 function`. Use `group.user_label` verbatim.
2. One numbered item per `blocked_groups` entry, labelled `Resolve blocked <object_type>s waiting on "<blocked_group.user_label>" (see deps)` — only if `blocked_groups` is non-empty.
3. `finishObjects` — only if `done_count > 0`.
4. `claimObjects` — only if `done_count == 0` (when `done_count > 0`, omit this entirely; the user must merge first). The exception: if the user *explicitly overrides* on a later turn ("I know, claim anyway", "skip the merge for now"), proceed to claim and flag the unmerged done objects in your reply.
5. The errored bucket — only if `errored_count > 0`.

**Wait for the user's response — do not proceed to 3c until they choose.**

### 3c. Dispatch

**User picked a task group** → take the matching `group.id` from the cached summary and call:

```
migration_status(mode="my_objects_details", group=<group.id>)
```

When `object_type == "etl"`, the group is an ETL stabilization batch — load [migrate-etl/SKILL.md](migrate-etl/SKILL.md) and follow it. SQL object types (`table`, `view`, `procedure`, `function`, `bteq`) follow the loop already described by `instructions` (BTEQ scripts skip deploy).

VERY IMPORTANT: **Wait for user input before acting.** Once the user confirms which objects to operate on, follow the `instructions` field on the response.

**User picked `claimObjects`** → load [actions/claim_objects.md](actions/claim_objects.md).

**User picked `finishObjects`** → load [actions/finish_objects.md](actions/finish_objects.md).

**User picked a blocked group** → call `migration_status(mode="my_objects_details", group="<blocked_id>")`.

> **Differentiate "missing" deps from "not-yet-completed" deps.** Walk every `objects[i].blocked_on[]` entry and look at `reason`:
>
> - `reason == "missing"` → the dep is **not in the project at all** (the resolver also classifies orphan deps with no registry entry as missing). Present a per-object resolution menu:
>
>   1. **Register the missing dep** — extract DDL from the source database (or import a local SQL file) and add it to the project. Load `../register-code-units/SKILL.md` for the matching dep `object_type`. After registration completes, re-run the blocked group; the dep should now resolve.
>   2. **Stub the missing dep in Snowflake** — create a placeholder object (empty table / no-op procedure / view returning the right column shape) so the dependent unit can deploy. Use this when the source isn't available but the shape is known. Capture what was stubbed in `extensions.notes` on the registry entry so the team has a record.
>   3. **Mark this object out of scope** — when the dependent shouldn't migrate at all because its missing dep is genuinely deprecated. Run `update_registry(field="inScope", status="false", objects="<object_id>")`.
>   4. **Bypass the precondition** — only when the user has already mitigated the dep externally (e.g. it lives in another database that's already in Snowflake) and wants to proceed without registering. Use `transition_status(status="bypass", task="<blocking_task>", where="id IN ('<object_id>')")`. This is logged and reversible.
>
>   **Wait for the user to pick one option per object** before acting. Do not auto-pick — "missing" usually surfaces a real data-modeling decision the user needs to make.
>
> - any other `reason` (e.g. `"deploy not completed"`, `"migrateData not completed"`) → the dep exists in the project but its prerequisite task hasn't finished yet. No prompt needed; the dep will resolve itself once the user finishes the upstream group. Tell the user which upstream group is blocking and offer to switch to it.

**User picked the errored bucket** → call `migration_status(mode="my_objects_details", group="errored")` to fetch `ErroredObject` entries and present them. **Wait for the user to pick which errored object(s) to address** before attempting any resolution; resolution depends on each `task`/`reason`.

### Resolving errored async tasks (`migrateData`, `validateData`, `runTests`)

When the errored task is a long-running async one and the failure is
**transient** (Snowflake connection drop, source timeout, cancelled
run), don't try to fix anything — just retry. After confirming with
the user, call:

```
transition_status(status="reset", task="<errored task>", where="id IN ('<id1>', '<id2>')")
```

This clears the registry stamp behind the task so the next walk
re-emits the task as Pending. The agent (or user) re-runs the task
the same way as before. For non-transient failures (schema drift,
missing target tables, etc.) the agent should diagnose and fix the
root cause first; reset is only for "try again now that the
environment is healthy."

`reset` is also useful when the user manually fixed something
out-of-band and wants the resolver to re-evaluate — for example,
they corrected a column type in Snowflake and want `validateData` to
re-run.

### After `migrateData` (data migration run)

When the current task is **`migrateData`** and you call `migrate_data(mode="run")` (from FSM instructions or this skill), you **must** complete poll and report before marking work done:

1. Load [actions/data-migration/SKILL.md](actions/data-migration/SKILL.md) **Steps 5–7** if you have not already (poll with `migrate_data_status()`, present the error-first migration report, offer teardown).
2. Do not return to the object loop or claim the next task until the user has seen the summary.

### After `validateData` (data validation run)

When the current task is **`validateData`** and you call `validate_data(mode="run")` (from FSM instructions or the validate-objects skill), you **must** complete poll and report before marking work done:

1. Load [../validate-objects/actions/validate_tables.md](../validate-objects/actions/validate_tables.md) **Steps 4–6** if you have not already (poll with `validate_data_status()`, present the error-first validation report, offer teardown).
2. Do not return to the object loop or claim the next task until the user has seen the summary.

## Step 4: Report

Call `migration_status()` and present a completion summary to the user:
> **Wave `<N>` complete.** `<deployed_count>` objects deployed, `<tested_count>` tested and passing, `<failed_count>` still failing. `<data_migrated_count>` tables with data migrated.

If all waves are done:
> **Migration complete.** All objects have been deployed to Snowflake and validated.

When all waves are done **and** any wave used data migration or data validation (i.e. SPCS infrastructure was provisioned), unconditionally load [../data-infrastructure/teardown/SKILL.md](../data-infrastructure/teardown/SKILL.md) to suspend the orchestrator + compute pool and prompt the user to stop the local worker. Skip this if the project never configured a `compute_pool` (no SPCS infrastructure was used).

If the wave is complete, the next `configure()` call will auto-advance to the next wave.
