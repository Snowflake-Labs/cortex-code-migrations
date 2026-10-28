---
name: data-infrastructure-teardown
description: Cost-saving teardown for shared data infrastructure — verify no in-flight workflows, then call data_infrastructure(mode="down") to stop/suspend orchestrator and worker (SPCS or local, as configured). The compute pool auto-suspends. Invoked after every migrate_data() / validate_data() cycle and at end-of-migration.
parent_skill: data-infrastructure-setup
license: Proprietary. See License-Skills for complete terms
---

# Data Infrastructure Teardown

`<metadata_database>` below is `.scai/config/plugin.yml` `metadata_database` (`SNOWCONVERT_AI` unless
overridden): this project's workflows, tasks and results live there, and `SNOWCONVERT_AI` may hold another
project's.

`data_infrastructure(mode="down")` does the teardown for **both** placements in one call:

- **Local** — reaps the orchestrator + worker processes this MCP session started.
- **SPCS** — when a `compute_pool` is configured for the project, it also suspends the SPCS orchestrator
  service and the Data Exchange Worker. An SPCS worker is suspended even when the orchestrator ran
  locally (`execution: local` with `worker: suspended_spcs`). The compute pool then **auto-suspends** on its own
  (`AUTO_SUSPEND_SECS`), so there is no separate pool step. Pass `drop=true` to remove the DEW service
  permanently instead of suspending it.

So teardown is normally just: **call `data_infrastructure(mode="down")`**. Everything below is the
in-flight check to do first, plus the few cases the tool cannot cover on its own. Nothing auto-resumes —
bring it back with `data_infrastructure(mode="up")` before the next wave (per `../SKILL.md`).

> **Why this exists:** an SPCS `DATA_MIGRATION_SERVICE` consumes compute pool seconds; a local
> orchestrator or local worker polling `TASK_QUEUE` wakes the warehouse on every interval — all accrue
> cost when idle.

## When to Invoke

| Trigger | Invocation |
|---------|------------|
| After `migrate_data()` reaches `completed` or `failed` for a wave | Caller prompts the user (default Yes) before loading this skill |
| After `validate_data()` reaches `completed` or `failed` for a wave | Caller prompts the user (default Yes) before loading this skill |
| End of full migration (no more waves) | Caller invokes this skill unconditionally |
| The session is about to wait on the user with no wave running: an open confirmation (extraction or sync strategy, workflow YAML, worker `CREATE SERVICE`, EWI decision), or the user is leaving for the night | Offer it before asking the question (default Yes). See [Waiting on the user](#waiting-on-the-user) |

**Skip entirely** when the project never configured data infrastructure (no `compute_pool` and no local
orchestrator/worker was started).

### Waiting on the user

An agent confirmation is not a pause. While the session waits on the user, the SPCS orchestrator and worker keep
running, keep polling `TASK_QUEUE` (the worker every ~5s, the orchestrator every 10–20s), and keep the warehouse and
every resumed pool node billing. Idle shutdown does not help while a workflow is still pending or running, and after
an idle hour it only stops the services if the orchestrator spec has the suspend variables (see Step 3).

So, when the session stops on a question with no wave in flight, and always before an overnight or unattended gap:

1. Run the in-flight check in Step 1. If a wave is still loading, leave it running (or abort it on purpose with
   `force=true`).
2. Otherwise offer `data_infrastructure(mode="down")`, and resume with `data_infrastructure(mode="up")` when the
   user comes back.
3. For an unattended overnight run, get every confirmation first (extraction strategy, explicit `sync_strategy`,
   approved workflow YAML) and only then dispatch, so the load never sits at a prompt with the pool resumed.

---

## Step 1: Verify no in-flight workflows

`data_infrastructure(mode="down")` already **refuses** while a migrate/validate job it can see is running
(it reads the project's relay ledger) — so a plain `down` is safe by default. But that ledger only covers
jobs dispatched from **this project on this machine**. Before tearing down shared SPCS infrastructure that
**another machine** might be using, confirm the queue is quiet directly:

- `job_status()` — every job you know about must report `terminal: true`.
- Then probe the orchestrator's queue (SPCS, cross-machine):

```sql
SELECT WORKFLOW_ID, STATUS, COUNT(*) AS N
FROM <metadata_database>.DATA_MIGRATION.TASK_QUEUE
WHERE STATUS NOT IN ('completed', 'failed', 'cancelled')
GROUP BY WORKFLOW_ID, STATUS
ORDER BY WORKFLOW_ID;
```

If any rows return, **abort teardown** and report:

> Teardown skipped — workflow `<id>` still has `<N>` `<status>` task(s). Wait for completion (or cancel via the troubleshooting reference) before suspending.

If a job is running only on this machine and you intend to stop it anyway, pass
`data_infrastructure(mode="down", force=true)`.

---

## Step 2: Tear down

Call the tool:

```
data_infrastructure(mode="down")                # suspend (resumable) — the default
data_infrastructure(mode="down", drop=true)     # SPCS: also permanently drop the DEW service
```

The response reports `execution` (`local` | `cloud`) and the `orchestrator` / `worker` actions
(`stopped_local` | `suspended_spcs` | `dropped` | `stop_failed`). Relay it to the user. On SPCS the
compute pool auto-suspends shortly after the service stops — no pool call needed.

If the payload reports a `partial` status with `spcs_errors`, read the error to decide what it means:
- An **insufficient-privileges** failure on the `ALTER SERVICE … SUSPEND` the tool runs through scai —
  grant the privileges below and re-run `data_infrastructure(mode="down")`.
- A **"service … does not exist"** failure on `worker stop` — this project has no SPCS DEW worker (Iceberg,
  a local worker, or `start_worker=false` at `up`); nothing to suspend, so it is safe to ignore.

### Privilege prerequisites (SPCS)

The tool suspends the SPCS service via `scai`, using the project's connection/role. The role that ran
`scai data orchestrator setup` holds these already; a **different** teardown role (e.g. `ACCOUNTADMIN`
cleaning up after the owner) needs them granted explicitly:

```sql
GRANT MONITOR, OPERATE ON SERVICE <metadata_database>.DATA_MIGRATION.DATA_MIGRATION_SERVICE TO ROLE <your_role>;
-- If the DEW worker service is in use:
GRANT MONITOR, OPERATE ON SERVICE <metadata_database>.DATA_MIGRATION.DATA_EXCHANGE_WORKER_SERVICE TO ROLE <your_role>;
```

### Local orchestrator started outside MCP (the tool can't reap it)

`data_infrastructure(mode="down")` reaps the local orchestrator/worker **this MCP session** spawned. A
local orchestrator the user launched themselves is not the tool's to kill. Tell the user:

> Stop the local orchestrator so it stops polling Snowflake:
> - Started with `scai data orchestrator start --local --detach`: run `scai data orchestrator stop --local`
>   with the same connection.
> - Running in a terminal (`scai data orchestrator start --local`): press `Ctrl+C` there.

The same applies to a local **worker** started outside MCP: `scai data worker stop --local [CONFIG_FILE]`
stops one started with `scai data worker start --local` (foreground or `--detach`) on that config, and
`Ctrl+C` stops a foreground one in its terminal.

---

## Step 3: Cost-hygiene recommendations (idempotent, optional)

Run these once per project — they make future suspend cycles tighter. **Skip compute-pool items** when no
`compute_pool` is configured.

```sql
-- Compute pool auto-suspend — the pool unblocks quickly after the service stops:
ALTER COMPUTE POOL <COMPUTE_POOL> SET AUTO_SUSPEND_SECS = 60;

-- Warehouse auto-suspend — verify the connection's warehouse suspends quickly:
SHOW PARAMETERS LIKE 'AUTO_SUSPEND' IN WAREHOUSE <WAREHOUSE>;
-- If value > 60:
ALTER WAREHOUSE <WAREHOUSE> SET AUTO_SUSPEND = 60;
```

`<COMPUTE_POOL>` is the value persisted by `data_infrastructure(mode="up", compute_pool=...)` — read from
`.scai/settings/cloud-migration.yaml`. Both changes are persistent and safe to apply outside teardown.

Auto-suspend only helps once the services stop. For a cap that stops the warehouse and the pool even when
nobody runs teardown, offer [`../budget-guardrail/SKILL.md`](../budget-guardrail/SKILL.md) if the project has no budget yet.

Keep the warehouse at the size the bulk loads need (Medium for billion-row tables). A warehouse that never
suspends is a polling problem, not a sizing one: downsizing stretches the load without cutting the credits
for the same bytes, and a larger or multi-cluster warehouse does not speed up a pool the source cannot feed.

**Compute pool shape (SPCS workers):** if the pool's `MIN_NODES` is more than 1, suggest lowering it. Suspend
the services first (Step 2), wait until `DESCRIBE COMPUTE POOL` shows `IDLE` or `SUSPENDED`, then:

```sql
ALTER SERVICE <metadata_database>.DATA_MIGRATION.DATA_EXCHANGE_WORKER_SERVICE SET MIN_INSTANCES = 2 MAX_INSTANCES = 3;
ALTER COMPUTE POOL <COMPUTE_POOL> SET MIN_NODES = 1 MAX_NODES = 3 AUTO_SUSPEND_SECS = 60;
```

Sizing reasoning is in [Sizing a pool that also runs SPCS workers](../compute-pool-setup/SKILL.md#sizing-a-pool-that-also-runs-spcs-workers).

**Make idle shutdown suspend SPCS, not just exit:** the processes exit after 60 idle minutes
(`DM_IDLE_SHUTDOWN_MINUTES`), but SPCS restarts a container whose service has `MIN_INSTANCES >= 1`, so the pool
stays up unless the service is suspended.

- **Worker (DEA):** when running in SPCS it suspends its own service after inserting `WORKER_SHUTDOWN`, using
  `SNOWFLAKE_SERVICE_NAME` / `SNOWFLAKE_DATABASE` / `SNOWFLAKE_SCHEMA`. The service owner role must be able to
  `ALTER SERVICE … SUSPEND`. If suspend fails, the worker stays up and retries (it does not exit into a restart
  loop). Confirm with a `WORKER_SHUTDOWN` row and, on failure, a `SPCS_IDLE_SUSPEND` row with
  `SOURCE_COMPONENT = 'dea'`.
- **Orchestrator:** also suspends services when its container has
  `DM_SPCS_SUSPEND_AGENT_SERVICE` (worker FQN) and/or `DM_SPCS_SUSPEND_ORCHESTRATOR_SERVICE` (falls back to
  `SNOWFLAKE_SERVICE_NAME`). `scai` sets the worker name on the orchestrator spec. For older specs missing those
  vars: `DESCRIBE SERVICE <metadata_database>.DATA_MIGRATION.DATA_MIGRATION_SERVICE`, copy the spec, add the
  env vars under the container's `env:`, and apply with `ALTER SERVICE … FROM SPECIFICATION $$ … $$` while the
  service is suspended — show the edited spec and wait for confirmation first.

After the next idle hour, confirm it worked:

```sql
SELECT EVENT_TYPE, SOURCE_COMPONENT, CREATION_TIME, PAYLOAD
FROM <metadata_database>.DATA_MIGRATION.SYSTEM_EVENT
WHERE EVENT_TYPE IN ('SHUTDOWN_BY_IDLE', 'WORKER_SHUTDOWN', 'SPCS_IDLE_SUSPEND')
ORDER BY CREATION_TIME DESC
LIMIT 20;
```

`SHUTDOWN_BY_IDLE` alone means the process exited but the services were not suspended. `SPCS_IDLE_SUSPEND` with a
success outcome means they were.

**Rule-engine Cortex Search (not DMVF):** `RULE_ENGINE.RULE_SEARCH` and `RULE_ENGINE.CODE_SEARCH` refresh on their
`TARGET_LAG` whether or not a migration runs, and `data_infrastructure(mode="down")` does not touch them. Current
builds create them at `TARGET_LAG = '7 days'` and suspend `CODE_SEARCH` indexing, but `CREATE … IF NOT EXISTS`
leaves an older install on its old lag (for example `1 minute`, about 1,440 refreshes a day per service). If
`SHOW CORTEX SEARCH SERVICES IN DATABASE <db>` shows a shorter lag, suggest, in each database that has a
`RULE_ENGINE` schema:

```sql
ALTER CORTEX SEARCH SERVICE IF EXISTS <db>.RULE_ENGINE.RULE_SEARCH SET TARGET_LAG = '7 days';
ALTER CORTEX SEARCH SERVICE IF EXISTS <db>.RULE_ENGINE.CODE_SEARCH SET TARGET_LAG = '7 days';
ALTER CORTEX SEARCH SERVICE IF EXISTS <db>.RULE_ENGINE.CODE_SEARCH SUSPEND INDEXING;
```

Do not move them back to a short lag. After a rule change, one `ALTER CORTEX SEARCH SERVICE … REFRESH` picks it up.

---

## Resuming for the next wave

Nothing auto-resumes on the next dispatch. Bring the shared infrastructure back up **once** with
`data_infrastructure(mode="up")` before the next `migrate_data` / `validate_data` — it resumes the SPCS
orchestrator (expect a 30–60s warm-up after suspend) or starts a persistent local orchestrator, plus the
worker, depending on whether a `compute_pool` is configured.

---

## Checklist

```
- [ ] No in-flight workflows — job_status() terminal + TASK_QUEUE quiet (Step 1)
- [ ] data_infrastructure(mode="down") called; response relayed (Step 2)
- [ ] Local orchestrator/worker started outside MCP stopped by the user, or N/A
- [ ] Warehouse AUTO_SUSPEND <= 60s (one-time, Step 3), or N/A
- [ ] Compute pool `MIN_NODES = 1`, idle-suspend env vars on the orchestrator spec, Cortex Search lag 7 days (one-time, Step 3), or N/A
```

Return control to the caller.
</content>
