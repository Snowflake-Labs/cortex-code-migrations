---
name: data-infrastructure-setup
description: Shared infrastructure setup for data migration and data validation — prerequisites, compute pool, worker config, and source database/schema capture.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# Data Infrastructure Setup

`<metadata_database>` below is `.scai/config/plugin.yml` `metadata_database` (`SNOWCONVERT_AI` unless
overridden): this project's workflows, tasks and results live there, and `SNOWCONVERT_AI` may hold another
project's.

## Overview — Tell the User

Before starting any configuration, tell the user verbatim:

> Snowflake's Data Migration and Validation Framework is a fault-tolerant, scalable system for Snowflake Migrations. It uses a two-component architecture: an **Orchestrator** that runs inside your Snowflake account (on Snowpark Container Services) and breaks migration work into parallel tasks, and one or more **Workers** that run in an environment of your choice, connect and read data from your source system, and upload it to your Snowflake account.

> You make **two independent placement choices** in Step 0: where the **orchestrator** runs — **SPCS** (on a Snowpark Container Services compute pool in the customer Snowflake account — **recommended** for real migrations) or **local** (on this machine, no compute pool — laptop / PoC only) — and where each **worker** runs — **SPCS** (**recommended** whenever the source is reachable from the Snowflake account), **your machine**, other VMs, or Kubernetes. The two don't have to match; nothing about compute pools matters until you put the orchestrator or a worker on SPCS. Ask first, **recommend SPCS** for each when they have not chosen, and wait for confirmation. Do not start infrastructure until they confirm.

> **You are in full control of what gets migrated and how.** You decide which tables to include, how they are partitioned for extraction, whether to use incremental synchronization or full loads, and how many workers run in parallel. You can filter rows, remap column names and types, and stop or resume the process at any point without losing progress. Nothing runs until you review and approve the configuration.
>
> **The same infrastructure is used for validation.** You choose what level of validation to run: **schema validation**, **metrics validation**, and **row-level validation**.

> **Metadata storage mode (trial accounts):** On Snowflake accounts **without Hybrid Table** support, the orchestrator falls back to standard/`TRANSIENT` metadata tables automatically. That path preserves correctness but **reduces task-queue throughput under contention** and effectively **limits how many workers you should run in parallel** — start with fewer workers and scale up carefully. This is **not** the same as L3 “hybrid” row validation. See [Metadata storage mode reference](./references/metadata-storage-mode-reference.md).

> **Always use the official tooling for data movement and validation.** Route table migration through `migrate_data` and validation through `validate_data`. Do not suggest ad-hoc extract/copy/compare scripts — the DMVF orchestrator and workers handle partitioning, loading, and multi-level validation.

> **Supported sources**: SQL Server, Azure Synapse, Redshift, Oracle, Teradata, PostgreSQL, BigQuery, Snowflake (validation only)
> **Supported target**: Snowflake

## Architecture

```
┌──────────────────┐     ┌──────────────────────────────────────┐
│  Customer Env     │     │         Snowflake Account             │
│  ┌─────────────┐ │     │  ┌────────────────────────────────┐  │
│  │  Worker(s)   │─┼─────┤  │  Orchestrator (SPCS)            │  │
│  └──────┬──────┘ │     │  │  → migration + validation tasks │  │
│         │ reads   │     │  └────────────────────────────────┘  │
│  ┌─────────────┐ │     │  ┌────────────────────────────────┐  │
│  │Source System │ │     │  │  Target Tables                  │  │
│  └─────────────┘ │     │  └────────────────────────────────┘  │
└──────────────────┘     └──────────────────────────────────────┘
```

- **Orchestrator** runs on SPCS (requires a compute pool) or locally. Handles migration workflows (break into tasks, `COPY INTO`) and validation workflows (schema/metrics/row comparison).
- **Worker** runs on SPCS (recommended when the source is reachable from Snowflake), on this machine, on other VMs, or on Kubernetes. Reads from the source and uploads to a Snowflake stage (migration) or streams rows for comparison (validation). Not needed for most Iceberg migration strategies.
- **Snowflake-to-Snowflake validation runs in warehouse.** It uses the
  orchestrator but no Data Exchange Worker. Do not generate worker config,
  ask for worker placement, or start a worker for a Snowflake source project.
- **The orchestrator + worker are shared, brought up ONCE, and reused across every `migrate_data` / `validate_data` dispatch** (migrate → validate → revalidate all run against the same infrastructure). Bring it up with `data_infrastructure(mode="up")` and tear it down with `data_infrastructure(mode="down")` (local) or [./teardown/SKILL.md](./teardown/SKILL.md) (SPCS). Dispatch does **not** start or resume infrastructure — if it is not up, `migrate_data` / `validate_data` return a `remediation` pointing back to `data_infrastructure(mode="up")`.
- **Whenever infrastructure starts**, tell the user that idle infrastructure can accrue Snowflake credits until teardown — the `data_infrastructure(mode="up")` response includes a `cost_reminder` field to relay.
- **An open question is not a pause.** Before the session waits on the user with no wave running (a confirmation, an EWI decision, an overnight gap), offer `data_infrastructure(mode="down")`; resume with `mode="up"`. See [Waiting on the user](./teardown/SKILL.md#waiting-on-the-user), and the one-time cost settings (pool `MIN_NODES = 1`, idle SPCS suspend, warehouse auto-suspend, rule-engine Cortex Search lag) in teardown Step 3.

## The `data_infrastructure` tool

Use the `data_infrastructure` tool (modes `up` / `down` / `status`) to manage the shared orchestrator + worker lifecycle — **pass `compute_pool` to run the orchestrator on SPCS, omit it for local**; `start_worker=false` skips the local worker (Iceberg / externally-managed workers). Call `up` once before dispatching migrations/validations. See the tool's own description for the full parameter list — don't restate it here.

## Idempotency

**One project setting, not one choice per action.** The orchestrator/worker
placement selected in Step 0 is shared by migration and validation and remains
in effect until the user explicitly asks to change it. Do not re-ask local vs
SPCS when validation begins, and do not ask a per-object subagent to start,
stop, repair, or reconfigure infrastructure. Subagents only dispatch against
the setup already in place; if infrastructure is unavailable, they return the
remediation to the main agent.

If the user explicitly asks to change placement or a persisted data strategy,
the **main agent** owns that setup change. Re-enter this skill for placement or
worker changes, and load [`../setup/data-strategy/SKILL.md`](../setup/data-strategy/SKILL.md)
for migration/validation strategy changes. Complete the change once, persist
it, bring infrastructure up as needed, and only then resume per-object
dispatch.

If this sub-skill has already been completed in the current project — i.e.,
the project has a recorded orchestrator placement, or (for worker-based
sources) `.scai/config/dew_configuration.toml` exists with no remaining
`<placeholder>` values — the infrastructure is **configured**, but that does
not mean it is **running**. Completion is durable; "up" is ephemeral.

**Budget check before `up` (SPCS or hybrid):** read the placement in `.scai/config/plugin.yml` first. When `data_orchestrator_placement: spcs`, or an SPCS worker runs on the `compute_pool` saved in `.scai/settings/cloud-migration.yaml`, run `SELECT SYSTEM$SHOW_BUDGETS_FOR_RESOURCE('COMPUTE_POOL', '<COMPUTE_POOL>');` and the same with `'WAREHOUSE'` for the migration warehouse (`warehouse` under the active connection in `~/.snowflake/config.toml`, not the session's). If either returns `[]`, or the pool's budget is the guardrail's `DMV_<POOL_ID>_BUDGET` but the warehouse is not in it (the migration warehouse changed), load [`./budget-guardrail/SKILL.md`](./budget-guardrail/SKILL.md) before `up`; it still asks before running anything, and a decline means telling the user no spend cap is in place and continue to `up`. If both list the guardrail's `DMV_<POOL_ID>_BUDGET`, that does not prove its stop can run: a stop procedure replaced without re-granting USAGE, or a partial run that linked both objects but never added the action, lists the same budget. Load [`./budget-guardrail/SKILL.md`](./budget-guardrail/SKILL.md) before `up` for its read-only Step 2 inspection and Step 6 read-back. Name the budget and continue only when one action is set and `CONFIRM_CUSTOM_ACTIONS_ACCESS` returns `IS_VALID = TRUE`; otherwise the guardrail says the cap is not working and offers its repair, run only after a yes, or a decline. If both list a budget other than `DMV_<POOL_ID>_BUDGET`, it is managed elsewhere: name it and continue.

Tell the user verbatim: "Data infrastructure already configured — bringing the shared orchestrator + worker back up (this also runs `scai data doctor` to confirm nothing has drifted)." Say it out loud rather than acting silently, because this runs live checks against Snowflake and the source. Then call `up` with the arguments that **preserve the project's recorded placement**. `up` does not read the recorded placement back: it resolves placement from its own arguments (an omitted `compute_pool` reuses the saved pool; an omitted `start_worker` starts a local worker for non-Snowflake sources) and records the result. So first read `data_orchestrator_placement` and `data_worker_placement` from `.scai/config/plugin.yml`, then:

| Recorded placement | Call |
|--------------------|------|
| `data_orchestrator_placement: spcs` | omit `compute_pool` (reuses the saved pool) |
| `data_orchestrator_placement: local` | pass `compute_pool=""`, even if a pool is saved (an SPCS worker's pool would otherwise move the orchestrator onto SPCS) |
| `data_worker_placement: local` | omit `start_worker` |
| `data_worker_placement: none` (SPCS worker, Iceberg / externally-managed, or a Snowflake source) | pass `start_worker=false` |

For example, a local orchestrator with an SPCS worker resumes with `data_infrastructure(mode="up", compute_pool="", start_worker=false)`; an SPCS orchestrator with a local worker with a bare `data_infrastructure(mode="up")`. If the placement is not recorded, ask Step 0 instead of guessing. `up` generates and applies the selected worker configuration, runs the [Level 1 Data Doctor](./references/data-doctor-reference.md#level-1-infrastructure-no-workflow-yaml) gate (iterate until it stops reporting `doctor_failures`), and only then starts/resumes the orchestrator and (unless this project runs no local worker) the worker; relay its `cost_reminder`. **Also state the placement it resolved** — the response carries the placement it just recorded: `orchestrator_placement` (`local` = on this machine, no compute pool; `spcs` = SPCS compute pool) and `worker_placement` (`local` = a worker on this machine; `none` = no local worker: an SPCS worker, Iceberg / externally-managed, or a Snowflake source). Check it matches what `plugin.yml` recorded before the call; if it does not, the arguments were wrong, so re-run `up` with the right ones rather than relaying the change. If `orchestrator_placement` is `local` and they meant SPCS, they can switch by re-running with `compute_pool="<POOL>"`. Return to the caller without re-prompting. Only run a bare Level 1 Data Doctor instead when you specifically need a config-drift check *without* bringing infrastructure up.

Otherwise, proceed through the steps below.


---

## Step 0 — Choose where to run (ask FIRST)

Call `configure()` and read `data_orchestrator_placement` /
`data_worker_placement`. When AIM already collected these via
`progress_setup` `next_prompt`, **do not re-ask** — use the persisted
values and skip 0.b / 0.c.

The user has already confirmed they want data infrastructure (answered by
the `enableDataMigration` prompt node in the setup state machine). Now gather
placement choices **before** any compute pool, role, or warehouse details.

**Ask on one card.** None of orchestrator placement (0.b), worker placement
(0.c), the role (Question 1), or the warehouse (Question 2) depends on another
answer, so ask every one of them still unanswered in **one**
`ask_user_question` call — up to four questions, recommended option first.
Only the SPCS compute pool (Question 0) waits, because it exists only once
the orchestrator answer is SPCS. Then act on the answers in the order below.

### 0.b — Where should the orchestrator run?

The orchestrator runs inside your Snowflake account, breaking work into tasks and issuing `COPY INTO` / validation queries. An SPCS orchestrator needs a compute pool, and so does an SPCS worker (0.c): you need one when **either** runs on SPCS. The two choices are **independent**, so a local orchestrator does not by itself mean no pool.

**Ask before any `data_infrastructure(mode="up")`.** Do not silently bring infrastructure up, and do not treat a coin-flip menu as a recommendation.

Do **not** add a third menu option such as “let’s chat / I need clarification” and then treat that as permission to pick **local**. If they defer, stay in Step 0.b: recommend **SPCS** in your own words and ask them to confirm **SPCS** vs **explicit local**. Do not proceed with local because they “left it to you.”

| Orchestrator | What it means | Recommend when |
|--------------|---------------|----------------|
| **SPCS** | Runs on a Snowpark Container Services **compute pool** in the Snowflake account | **Default recommendation** for a real customer migration: scalable, fault-tolerant, survives the local session. |
| **Local** | Runs on this machine — **no compute pool** | Only when they **explicitly** want a laptop / PoC / session-bound run, or the account cannot use SPCS. Do not frame this as the simplest default. |

Ask, then **state the recommendation in your own words** before they pick:

> For a real customer Snowflake account I recommend **SPCS** (orchestrator on a compute pool in the account). Local is for a laptop proof-of-concept or when SPCS is not available. Do you want SPCS, or do you explicitly want local?

If they are undecided or say they do not know: **recommend SPCS again** and wait for confirmation. Do not pick for them, and do not start `up` until they confirm.

**Never recommend local because the current source looks small, is an eval fixture, has few tables, or is "only reachable from this host."** Workload size is not a placement signal, and reaching the source is the worker's job, not the orchestrator's (0.c). Treat this as a customer Snowflake account unless they **explicitly** ask for a laptop / PoC / local-only run. Do not say "for this project I still recommend local" after recommending SPCS for production.

**Missing Microsoft ODBC (or any local worker driver) does not change orchestrator placement.** Do not switch to a local orchestrator, and do not stop the whole skill, because a local worker cannot start yet. Keep **SPCS** for the orchestrator. If the worker cannot start, call `data_infrastructure(mode="up", compute_pool="<POOL>", start_worker=false)` after they confirm SPCS and the pool, relay the ODBC/install gap, and stop before migrate/validate.

| Answer | Next step |
|--------|-----------|
| **SPCS** (or they accept the SPCS recommendation) | Call `configure(needs_compute_pools=true)` so the response lists the accessible pools, then resolve the pool in **Question 0**. Bring it up with `data_infrastructure(mode="up", compute_pool="<POOL>")`. |
| **Local** (they explicitly chose laptop / PoC / cannot use SPCS) | The orchestrator needs no compute pool, but do not decide Question 0 yet: ask 0.c first. Skip Question 0 only when the worker is not on SPCS either; an SPCS worker still needs one. Bring the orchestrator up later with `data_infrastructure(mode="up", compute_pool="")` (an explicitly empty pool selects local). |

### 0.c — Where should each worker run?

For a Snowflake source project, skip this question and record
`start_worker=false`. Continue to Question 1 after resolving the orchestrator
placement. `data_infrastructure(mode="up")` also enforces this server-side.

The worker reads from your **source** system and moves the data, so it must run somewhere that can **reach the source** — independent of the orchestrator's placement in 0.b. Ask this **once**; the Worker setup step (Question 3) only acts on the answer and does **not** re-ask.

| Worker | What it means | Recommend when |
|--------|---------------|----------------|
| **SPCS** | The Data Exchange Worker runs as an SPCS service on a **compute pool** in the Snowflake account | **Default recommendation** for a real customer migration whenever the source is reachable from Snowflake (a cloud-hosted database, or a host the account can reach through a network rule / external access integration): no worker to install or keep running on this machine, SPCS restarts stopped instances, it scales by instance count, and it survives the local session. |
| **This machine** | A single worker on this host | The source is reachable **only** from the customer network (on-prem behind a firewall Snowflake cannot get through, or `localhost`), they **explicitly** want a laptop / PoC run, or the account cannot use SPCS. |
| **Separate VMs/servers** | Several workers, each on a host that can reach the source | The source is reachable only from the customer network and one host is not enough throughput. |
| **Kubernetes** | Workers on the customer's existing cluster | They already run workloads on Kubernetes and want the workers there. |

Ask, then **state the recommendation in your own words** before they pick:

> For a real customer migration I recommend running the **worker on SPCS** as well: there is no worker to install or keep running on this machine, and Snowflake restarts it if it stops. It needs your Snowflake account to be able to reach the source database. If the source is reachable only from inside your network, the worker runs on **this machine**, on **separate VMs/servers**, or on **Kubernetes** instead. Where do you want the worker(s)? (Some Iceberg strategies need **no** worker at all — say so and I'll set `start_worker=false`.)

If they are unsure whether Snowflake can reach the source, ask where the source is hosted: cloud-hosted or reachable through their firewall → recommend **SPCS**; on-prem with no path in from Snowflake → recommend **this machine** (or VMs for more throughput). Do not recommend a local worker just because the orchestrator is local or the workload is small, and do not pick for them.

An SPCS worker needs a compute pool, so choosing it means **Question 0** runs even when the orchestrator is local; the orchestrator and worker can share the same pool.

Record the answer; it selects the worker sub-skill in **Question 3**.

## Worker Deployment Decisions

Having chosen placement in Step 0, gather the remaining Snowflake-side details **in order**. Question 0 is **SPCS-only** — skip it entirely when neither the orchestrator (0.b) nor the worker (0.c) runs on SPCS.

### Question 0: Compute pool SPCS

If the user chose **local** in Step 0.b **and** a worker that is not on SPCS in Step 0.c, **do not ask Question 0** — continue from **Question 1**.

The orchestrator and the worker on SPCS need a compute pool. **Always ask** whether the user already has one or needs to create one — but first surface the pools their role can already reach, so they pick from a short list instead of recalling a name. Call `configure(needs_compute_pools=true)`; its response carries an `existing_compute_pools:` line listing them as `NAME (state)` (the compute-pool analogue of the `existing_connections:` line from `needs_source_connection`).

Then ask, presenting those pools as a short list (name + `state`):

> The Orchestrator and an SPCS worker need a compute pool to run on SPCS. Here are the pools your role can access:
> `<NAME — state>` (one per line)
> Do you already have one to use, or do you need to create one?

Handle the `existing_compute_pools:` value:

- **Pools listed** → present them and let the user pick, or create a new one.
- **`none`** → the role sees no pool; say so and go straight to the create path.
- **`(unavailable: …)`** → couldn't reach Snowflake; tell the user, then fall back to asking them to name an existing pool or create one.

| Answer | Action |
|--------|--------|
| **Use an existing pool** | Confirm its `state` (from the list) is **ACTIVE** or **IDLE**. If `SUSPENDED`, run `ALTER COMPUTE POOL <POOL> RESUME;` and re-check; if `STARTING`, wait a moment and re-check. Then save it and continue to Question 1. |
| **Create a new one** | Route to → `./compute-pool-setup/SKILL.md` — guide the user through creating and configuring a compute pool. After that skill completes, return here and run the steps below. |

**Budget guardrail, before the first `up`:** a resolved pool means the orchestrator or a worker runs on SPCS (SPCS + SPCS, or either hybrid split), so the guardrail runs now. First settle the migration warehouse: ask **Question 2** now and make sure `~/.snowflake/config.toml` names it under the active connection; when you reach Question 2 later, confirm that answer instead of asking again. Then load [`./budget-guardrail/SKILL.md`](./budget-guardrail/SKILL.md) for that warehouse and this pool. It proposes a budget that stops the warehouse and this pool at a spend threshold and runs nothing without the user's yes; on a decline, tell them no spend cap is in place and continue. Fully local (Question 0 skipped) skips it.

**Bring the shared infrastructure up on this pool:**

```
data_infrastructure(mode="up", compute_pool="<COMPUTE_POOL>")
```

> The pool is persisted, so later `up` calls (and `migrate_data`/`validate_data` after them) reuse it without re-passing it. Omitting `compute_pool` therefore does **not** mean local: it reuses the project's saved pool when there is one. To run a local orchestrator, pass an explicitly empty pool: `compute_pool=""`.

**SPCS worker (0.c):** pass `start_worker=false` on every `up`, since no local worker runs; the worker sub-skill deploys it on the pool with `scai data worker setup --compute-pool <COMPUTE_POOL>`. With a **local** orchestrator, do **not** pass the worker's pool to `up` (that moves the orchestrator onto SPCS) and do not omit `compute_pool` (that reuses any saved pool): call `data_infrastructure(mode="up", compute_pool="", start_worker=false)`.

**Existing `DATA_MIGRATION_SERVICE` (account-wide, one service):** `up` **resumes** that service in place. You **cannot** `ALTER` it onto another compute pool. If `up` targets pool A but the service already sits on pool B (or another role owns it):

1. **Stop and ask.** Explain it is account-wide, who owns it, and which pool it is on. Do **not** `DROP SERVICE` (or `data_infrastructure(mode="down", drop=true)`) silently.
2. Default path when another role created it: Question 1 extended grants (`OPERATE` / `MONITOR`) and keep the existing service. Persist the user's **requested** pool on the project, but do not move the live service.
3. `DROP` + recreate on the user's pool **only** after they explicitly confirm they own that service and accept that every other project on the account loses the old one. Quote the service name and the other pool in the question.

### Question 1: Snowflake role and privileges

Ask the user:

> What Snowflake role will you use for the migration? The Orchestrator needs a role with USAGE on the `<metadata_database>` database and its `DATA_MIGRATION` and `DATA_VALIDATION` schemas.

| Situation | Action |
|-----------|--------|
| **Role has the required privileges** | Continue to Question 2. |
| **Role needs grants** | Run the grants below on behalf of the user (or show them to run with an admin role), then continue. |
| **DATA_MIGRATION_SERVICE already exists (created by another role)** | The executing role also needs OPERATE and MONITOR on the service. Run the extended grants below, then continue. **Do not DROP it** to pin a different compute pool unless the user confirmed step 3 above. |

**Standard grants:**

```sql
GRANT USAGE ON DATABASE <metadata_database> TO ROLE <your_role>;
GRANT USAGE ON SCHEMA <metadata_database>.DATA_MIGRATION TO ROLE <your_role>;
GRANT USAGE ON SCHEMA <metadata_database>.DATA_VALIDATION TO ROLE <your_role>;
```

**Extended grants (when the service was created by another role):**

```sql
GRANT OPERATE, MONITOR ON SERVICE <metadata_database>.DATA_MIGRATION.DATA_MIGRATION_SERVICE TO ROLE <your_role>;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA <metadata_database>.DATA_MIGRATION TO ROLE <your_role>;
GRANT ALL PRIVILEGES ON ALL PROCEDURES IN SCHEMA <metadata_database>.DATA_MIGRATION TO ROLE <your_role>;
GRANT ALL PRIVILEGES ON ALL STAGES IN SCHEMA <metadata_database>.DATA_MIGRATION TO ROLE <your_role>;
```

### Question 2: Snowflake warehouse

Ask the user:

> Which Snowflake warehouse should be used for data migration and validation? The Orchestrator uses this warehouse to execute `COPY INTO` statements and run validation queries. Your Snowflake connection must have a warehouse configured — without one, data migration will fail silently.

| Situation | Action |
|-----------|--------|
| **User provides a warehouse name** | Verify the warehouse exists and the role from Question 1 has USAGE on it. Confirm that `~/.snowflake/config.toml` has `warehouse = "<WAREHOUSE>"` under the active connection. If not, help the user add it. Continue to Question 3. |
| **User is unsure** | Run `SHOW WAREHOUSES;` to list available warehouses and help them pick one. For large migrations, recommend a dedicated warehouse to avoid contention with other workloads. |

**SPCS or hybrid:** the warehouse was settled in Question 0, before the budget guardrail ran. If the user now picks a different warehouse, or `config.toml` names another one, the guardrail still caps the old one: load [`./budget-guardrail/SKILL.md`](./budget-guardrail/SKILL.md) again before the next `up`, and it moves the cap to the new warehouse after the user's yes.

### Question 3: Worker setup

Skip Question 3 for a Snowflake source project. Call
`data_infrastructure(mode="up", start_worker=false, ...)` and continue to Data
Doctor; no DEW configuration file is expected.

**Do not ask where the worker runs again** — that was decided in **Step 0.c**. Route to the matching sub-skill; it handles install/start and returns control here:

| Step 0.c answer | Sub-skill |
|-----------------|-----------|
| **Single worker on this machine** | → `./worker-local-setup/SKILL.md` — install and start on one host |
| **Multiple workers on separate VMs/servers** | → `./worker-distributed-setup/SKILL.md` — affinity config + per-host copy instructions |
| **Snowpark Container Services (SPCS)** | → `./worker-spcs/SKILL.md` — image selection, Snowflake Secrets, CREATE SERVICE; then `data_infrastructure(mode="up", start_worker=false, ...)`, since no local worker runs |
| **Kubernetes (external cluster)** | → `./worker-k8s-external/SKILL.md` — image selection, Kubernetes Secrets, Deployment manifest |
| **No worker (Iceberg or Snowflake-to-Snowflake validation)** | none — set `start_worker=false` on `data_infrastructure(mode="up")` |

**Stop here for worker deployment** — the routed sub-skill handles install/start, then **returns control here**. After it returns (or on the no-worker path), run the Data Doctor section below before returning to the caller.

---

## Data Doctor (Level 1)

This is the **single place** Level 1 Data Doctor runs — after **any** worker deployment path (local, distributed, SPCS, Kubernetes) returns control here. The worker sub-skills do not run it themselves.

Run [Level 1 Data Doctor](./references/data-doctor-reference.md#level-1-infrastructure-no-workflow-yaml). **Do not** start migration or validation setup until `result.hasFailures` is `false`. Iterate with the user on failures and warnings using each check's `suggestion`; you do not need to fix everything automatically.

---

## Checklist

```
- [ ] Compute pool passed to `data_infrastructure(mode="up", compute_pool=...)` — when using SPCS orchestrator
- [ ] Snowflake role has DATA_MIGRATION / DATA_VALIDATION usage (and service grants if needed)
- [ ] Warehouse configured on the Snowflake connection
- [ ] Worker config complete (no <placeholder> values) — unless pure Iceberg or Snowflake-to-Snowflake validation
- [ ] Level 1 scai data doctor — no Fail checks
```

---

Return control to the calling skill.

---

## Advanced operations (when the customer asks)

These are **optional** — not part of default setup. Load [Advanced operations reference](./references/advanced-operations-reference.md) when the user mentions:

| Topic | Trigger phrases | Summary |
|-------|-----------------|---------|
| **Rate limiting** | Source overloaded, throttle extractions/loads, pause one workflow | SQL rules in `DATA_MIGRATION.RATE_LIMIT`; soft cap on worker task pulls |
| **Preflight migration** | Dry-run, smoke test pipeline, test before full load | `preflight: true` in DM YAML → transient `PREFLIGHT_<id>` schema (not doctor, not Preliminary) |
| **Incremental validation** | Re-validate only changed partitions, ongoing DV | `synchronization` + watermark/checksum in DV YAML; baseline run required first |
| **Re-validation** | Retry failed validation partitions | `validate_data(mode="revalidate", workflow_name=…)` after parent workflow finishes |
| **Custom L3 normalization** | Formatting drift, case/spatial/period compare | `validationCustomNormalizationRules` in DV YAML — not DM `columnTypeMappings` |
| **Checksum blind spots** | Incremental sync missed a column change | Some types excluded/rounded from checksum — see advanced ref |
| **Non-hybrid metadata (trial)** | Trial account, HYBRID TABLE unsupported, slow pulls with many workers | Standard/`TRANSIENT` fallback — limit workers; see metadata storage mode ref |

Do not suggest ad-hoc throttling via polling env vars. Rate limits are metadata SQL, not workflow YAML fields.

---

## Reference

- [Metadata storage mode reference](./references/metadata-storage-mode-reference.md) — Hybrid vs standard metadata (trial fallback, worker scaling)
- [Advanced operations reference](./references/advanced-operations-reference.md) — rate limiting, preflight, incremental DV, revalidate
- [Data Doctor reference](./references/data-doctor-reference.md)
- [Worker Config Reference](./references/worker-config-reference.md)
- [Affinity Reference](./references/affinity-reference.md) — routing workers to workflows (multi-worker / multi-source)
- [Teardown (cost-saving suspend)](./teardown/SKILL.md)
