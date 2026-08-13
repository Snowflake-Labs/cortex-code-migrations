---
name: data-infrastructure-teardown
description: Cost-saving teardown for shared data infrastructure — verify no in-flight workflows, stop/suspend orchestrator and worker (SPCS or local, as configured), and suspend the compute pool when applicable. Invoked after every migrate_data() / validate_data() cycle and at end-of-migration.
parent_skill: data-infrastructure-setup
license: Proprietary. See License-Skills for complete terms
---

# Data Infrastructure Teardown

Tear down only what this project actually provisioned: **SPCS orchestrator + compute pool**, **local orchestrator process**, **SPCS DEW worker**, and/or **local worker process**. Nothing auto-resumes on the next dispatch — `migrate_data()` / `validate_data()` are pure dispatch and assume the infrastructure is already up. To run another wave after teardown, bring it back explicitly with `data_infrastructure(mode="up")` (per `../SKILL.md`).

> **Why this exists:** an SPCS `DATA_MIGRATION_SERVICE` consumes compute pool seconds; a local orchestrator or local worker polling `TASK_QUEUE` wakes the warehouse on every interval — all accrue cost when idle.

## When to Invoke

| Trigger | Invocation |
|---------|------------|
| After `migrate_data()` reaches `completed` or `failed` for a wave | Caller prompts the user (default Yes) before loading this skill |
| After `validate_data()` reaches `completed` or `failed` for a wave | Caller prompts the user (default Yes) before loading this skill |
| End of full migration (no more waves) | Caller invokes this skill unconditionally |

**Skip entirely** when the project never configured data infrastructure (no `compute_pool` and no local orchestrator/worker was started).

---

## Which steps apply

Determine from infrastructure setup and `configure()` / `.scai/settings/cloud-migration.yaml`:

| Component | Signal | Teardown steps |
|-----------|--------|----------------|
| SPCS orchestrator | `compute_pool` configured | **Step 2a**, **Step 3** |
| Local orchestrator | No `compute_pool`; user chose local orchestrator in setup | **Step 2b** |
| SPCS DEW worker | `scai data worker setup` / `worker-spcs` completed | **Step 4a** (`scai data worker stop`; DMG0024 → no SPCS worker) |
| Local worker | `worker-local-setup` or `scai data worker start --local` | **Step 4b** |

Run **Step 1** always when any orchestrator/worker was used. Skip rows that do not apply — do not suspend a compute pool or SPCS service that was never provisioned.

## Privilege Prerequisites

Before running any step, ensure the active role has the following privileges. The role that ran `scai data orchestrator setup` is granted these automatically; if a different role is performing teardown (e.g. `ACCOUNTADMIN` cleaning up after the project owner), grant them explicitly:

```sql
GRANT SELECT ON ALL TABLES IN SCHEMA SNOWCONVERT_AI.DATA_MIGRATION TO ROLE <your_role>;
GRANT MONITOR, OPERATE ON SERVICE SNOWCONVERT_AI.DATA_MIGRATION.DATA_MIGRATION_SERVICE TO ROLE <your_role>;
-- If the DEW worker service is in use:
GRANT MONITOR, OPERATE ON SERVICE SNOWCONVERT_AI.DATA_MIGRATION.DATA_EXCHANGE_WORKER_SERVICE TO ROLE <your_role>;
```

If Step 1 or `scai data orchestrator stop` fails with an insufficient-privileges error, apply the grants above and retry from the failed step.

---

## Step 1: Verify No In-Flight Workflows

Do **not** suspend mid-job. Check the most recently observed job(s) first:

- `job_status()` — every job must report `terminal: true`.

Then probe the orchestrator's queue directly:

```sql
SELECT WORKFLOW_ID, STATUS, COUNT(*) AS N
FROM SNOWCONVERT_AI.DATA_MIGRATION.TASK_QUEUE
WHERE STATUS NOT IN ('completed', 'failed', 'cancelled')
GROUP BY WORKFLOW_ID, STATUS
ORDER BY WORKFLOW_ID;
```

If any rows return, **abort teardown** and report to the user:

> Teardown skipped — workflow `<id>` still has `<N>` `<status>` task(s). Wait for completion (or cancel via the troubleshooting reference) before suspending.

Otherwise continue to Step 2 (or Step 4 only if no orchestrator was ever started).

---

## Step 2: Stop the orchestrator

### 2a. SPCS orchestrator — when `compute_pool` is configured

**Skip 2a and Step 3** when there is no `compute_pool` (local orchestrator path).

The orchestrator service is the dominant SPCS cost driver — it pins the compute pool active. Suspend it first:

```bash
scai data orchestrator stop
```

Then poll status until it reports `SUSPENDED`. **Poll every 15 s for up to 3 minutes (12 polls).** If the service has not reached `SUSPENDED` after 12 polls, surface the last CLI output and stop — do not proceed to Step 3 while the orchestrator may still be running.

```bash
scai data orchestrator status
```

The CLI returns `{"status": "SUSPENDING"}` for ~60-90s before settling at `{"status": "SUSPENDED"}`.

> **Why not raw SQL?** `scai data orchestrator stop` wraps `ALTER SERVICE … SUSPEND` and uses the connection / role / warehouse from the active project. Use raw `ALTER SERVICE SNOWCONVERT_AI.DATA_MIGRATION.DATA_MIGRATION_SERVICE SUSPEND` only if the CLI is unavailable.

### 2b. Local orchestrator — when no `compute_pool` / user chose local orchestrator in setup

**Skip 2a and Step 3.** The local orchestrator runs as a **foreground process** (`scai data orchestrator start --local`). `scai data orchestrator stop --local` is **advisory only** — it does not kill a running process.

Tell the user:

> Stop the local orchestrator so it stops polling Snowflake.
> - Find the terminal running `scai data orchestrator start --local` and press `Ctrl+C`.
> - If it was launched in the background, end that process (Task Manager / `pkill` as appropriate).

---

## Step 3: Suspend the compute pool (SPCS only)

**Skip Step 3** when there is no `compute_pool`.

```sql
ALTER COMPUTE POOL <COMPUTE_POOL> SUSPEND;
SHOW COMPUTE POOLS LIKE '<COMPUTE_POOL>';
```

`<COMPUTE_POOL>` is the value persisted by `data_infrastructure(mode="up", compute_pool=...)` — read from `.scai/settings/cloud-migration.yaml`.

The pool's `STATE` should report `SUSPENDED` (or `STOPPING` for a few seconds, then `SUSPENDED`).

---

## Step 4: Stop the Worker

There are two worker variants and at most one is in use per project:

### 4a. SPCS Data Exchange Worker (DEW) service — if `scai data worker setup` was used

If the worker runs as a Snowpark Container Services service, suspend it via the CLI:

```bash
scai data worker stop
scai data worker status
```

`stop` suspends the `DATA_EXCHANGE_WORKER_SERVICE` (default; pass `--drop` to remove permanently). `status` is the inverse of `setup`. If no DEW service exists, `scai data worker stop` returns error code `DMG0024` ("Service `SNOWCONVERT_AI.DATA_MIGRATION.DATA_EXCHANGE_WORKER_SERVICE` does not exist") — that's the signal you have no SPCS worker and should fall through to 4b.

### 4b. Local worker process — if launched with `scai data worker start --local`

The local worker polls the warehouse every `task_fetch_interval` seconds (see `../references/worker-config-reference.md`). Each poll wakes the warehouse and accrues credits — even with the SPCS orchestrator suspended.

When the worker was started by **`migrate_data()` / `validate_data()`** through the MCP server, it **stops automatically when the MCP session ends**. Teardown 4b still applies when the user chose **No, keep running** on a prior wave, when the worker was started manually, or when you need to stop it before the session ends.

When the worker was started by **`migrate_data()` / `validate_data()`** through the MCP server, it is **stopped automatically when the MCP session ends** (stdio or HTTP server task exit). Teardown step 4b still applies when the user chose **No, keep running** on a prior wave, when the worker was started manually, or when you need to stop it before the session ends.

Tell the user:

> Stop the local worker so the warehouse can auto-suspend.
> - If you are ending the Coco/MCP session, the worker started by `migrate_data` / `validate_data` will stop on exit — no manual kill needed unless you started the worker outside MCP.
> - Otherwise find the terminal running `scai data worker start --local` and press `Ctrl+C`.
> - If the worker was launched in the background outside MCP, kill it: `pkill -f "scai data.*worker.*start"` (macOS / Linux) or end the process in Task Manager (Windows).

Verify polling has stopped:

```sql
SELECT QUERY_ID, USER_NAME, WAREHOUSE_NAME, START_TIME, LEFT(QUERY_TEXT, 120) AS QUERY_TEXT
FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY_BY_USER(USER_NAME => CURRENT_USER(), RESULT_LIMIT => 20))
WHERE QUERY_TEXT ILIKE '%TASK_QUEUE%'
ORDER BY START_TIME DESC;
```

Within `task_fetch_interval` seconds (default 30s) the worker's `TASK_QUEUE` queries should stop appearing. If they keep appearing, the worker process is still running.

---

## Step 5: Cost-Hygiene Recommendations (Idempotent)

Run these once per project — they make future suspend cycles tighter. **Skip compute-pool items** when no `compute_pool` is configured.

**Compute pool auto-suspend** — drop to ~60s so the pool unblocks even if Step 3 is skipped:

```sql
ALTER COMPUTE POOL <COMPUTE_POOL> SET AUTO_SUSPEND_SECS = 60;
```

**Warehouse auto-suspend** — verify the warehouse used by the Snowflake connection auto-suspends quickly:

```sql
SHOW PARAMETERS LIKE 'AUTO_SUSPEND' IN WAREHOUSE <WAREHOUSE>;
-- If value > 60:
ALTER WAREHOUSE <WAREHOUSE> SET AUTO_SUSPEND = 60;
```

Both changes are persistent and safe to apply outside this teardown.

---

## Resuming for the Next Wave

Nothing auto-resumes on the next dispatch. Bring the shared infrastructure back up **once** with `data_infrastructure(mode="up")` before the next `migrate_data` / `validate_data` — it resumes the SPCS orchestrator (expect a 30–60s warm-up after suspend) or starts a persistent local orchestrator, plus the worker, depending on whether a `compute_pool` is configured.

`data_infrastructure(mode="up")` wraps these underlying commands; run them directly only when debugging outside the tool:

```bash
# SPCS
scai data orchestrator start
scai data worker start          # SPCS DEW worker, if used
# Local
scai data orchestrator start --local
scai data worker start --local
```

---

## Checklist

```
- [ ] No in-flight workflows in TASK_QUEUE (Step 1)
- [ ] SPCS orchestrator suspended (2a), or local orchestrator process stopped (2b), or N/A
- [ ] Compute pool suspended when SPCS orchestrator was used (Step 3), or N/A
- [ ] DEW worker service suspended (4a) or local worker process stopped (4b), or N/A
- [ ] Warehouse AUTO_SUSPEND <= 60s (one-time, Step 5)
```

Return control to the caller.
