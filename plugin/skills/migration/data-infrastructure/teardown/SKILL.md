---
name: data-infrastructure-teardown
description: Cost-saving teardown for shared data infrastructure — verify no in-flight workflows, suspend the SPCS orchestrator and compute pool, and stop the local worker. Invoked after every migrate_data() / validate_data() cycle and at end-of-migration.
parent_skill: data-infrastructure-setup
license: Proprietary. See License-Skills for complete terms
---

# Data Infrastructure Teardown

Suspend the SPCS orchestrator and compute pool, and stop the local worker, after a wave's data work has completed. The next call to `migrate_data()` or `validate_data()` automatically resumes the service (per `../SKILL.md`), so suspending between waves is safe.

> **Why this exists:** while the `DATA_MIGRATION_SERVICE` is running it consumes compute pool seconds, and the local worker keeps polling the warehouse every `task_fetch_interval` seconds — both accrue cost even when no real work is happening.

## When to Invoke

| Trigger | Invocation |
|---------|------------|
| After `migrate_data()` reaches `completed` for a wave | Caller prompts the user (default Yes) before loading this skill |
| After `validate_data()` reaches `completed` for a wave | Caller prompts the user (default Yes) before loading this skill |
| End of full migration (no more waves) | Caller invokes this skill unconditionally |

---

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

- `migrate_data_status(job_id=<latest>)` — must be `completed` or `failed`.
- `validate_data_status(job_id=<latest>)` — must be `completed` or `failed`.

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

Otherwise continue to Step 2.

---

## Step 2: Suspend the SPCS Orchestrator Service

The orchestrator service is the dominant cost driver — it pins the compute pool active. Suspend it first using the CLI:

```bash
scai data orchestrator stop
```

Then poll status until it reports `SUSPENDED`. **Poll every 15 s for up to 3 minutes (12 polls).** If the service has not reached `SUSPENDED` after 12 polls, surface the last CLI output and stop — do not proceed to Step 3 while the orchestrator may still be running.

```bash
scai data orchestrator status
```

The CLI returns `{"status": "SUSPENDING"}` for ~60-90s before settling at `{"status": "SUSPENDED"}`.

> **Why not raw SQL?** `scai data orchestrator stop` wraps `ALTER SERVICE … SUSPEND` and uses the connection / role / warehouse from the active project, so it works without the caller hard-coding the service name. Use raw `ALTER SERVICE SNOWCONVERT_AI.DATA_MIGRATION.DATA_MIGRATION_SERVICE SUSPEND` only if the CLI is unavailable or the agent needs to inspect SPCS state directly.

---

## Step 3: Suspend the Compute Pool

With the service suspended, the pool will eventually auto-suspend per its `AUTO_SUSPEND_SECS`. Suspending explicitly is faster and free of risk:

```sql
ALTER COMPUTE POOL <COMPUTE_POOL> SUSPEND;
SHOW COMPUTE POOLS LIKE '<COMPUTE_POOL>';
```

`<COMPUTE_POOL>` is the value persisted by `configure(compute_pool=...)` — read from `.scai/settings/cloud-migration.yaml`.

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

The local worker polls the warehouse every `task_fetch_interval` seconds (see `../references/worker-config-reference.md`). Each poll wakes the warehouse and accrues credits — even with the orchestrator suspended.

Tell the user:

> Stop the local worker so the warehouse can auto-suspend.
> - Find the terminal running `scai data worker start --local` and press `Ctrl+C`.
> - If the worker was launched in the background, kill it: `pkill -f "scai data.*worker.*start"` (macOS / Linux) or end the process in Task Manager (Windows).

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

Run these once per project — they make all future suspend cycles tighter. Skip any value that's already low enough.

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

No manual resume needed. Calling `migrate_data()` or `validate_data()` again starts the service automatically (per `../SKILL.md` Step 1). Expect a 30-60s warm-up on the first job after suspend before the orchestrator picks up tasks.

If you want to resume eagerly without scheduling work (e.g. to shave the warm-up off the first job), use the CLI:

```bash
scai data orchestrator start    # SPCS orchestrator
scai data worker start          # SPCS DEW worker, if used
```

The local worker (4b) is **not** auto-restarted — re-launch it before the next migration wave:

```bash
scai data worker start --local
```

---

## Checklist

```
- [ ] No in-flight workflows in TASK_QUEUE
- [ ] Orchestrator service suspended (`scai data orchestrator status` reports SUSPENDED)
- [ ] Compute pool suspended (or AUTO_SUSPEND_SECS <= 60)
- [ ] DEW worker service suspended (if applicable) or local worker process stopped
- [ ] Warehouse AUTO_SUSPEND <= 60s (one-time)
```

Return control to the caller.
