---
name: data-infrastructure-setup
description: Shared infrastructure setup for data migration and data validation — prerequisites, compute pool, worker config, and source database/schema capture.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# Data Infrastructure Setup

## Overview — Tell the User

Before starting any configuration, tell the user verbatim:

> Snowflake's Data Migration and Validation Framework is a fault-tolerant, scalable system for Snowflake Migrations. It uses a two-component architecture: an **Orchestrator** that runs inside your Snowflake account (on Snowpark Container Services) and breaks migration work into parallel tasks, and one or more **Workers** that run in an environment of your choice, connect and read data from your source system, and upload it to your Snowflake account.

> You make **two independent placement choices** in Step 0: where the **orchestrator** runs — **local** (on your machine, no compute pool — simplest) or **SPCS** (on a Snowpark Container Services compute pool — scalable) — and where each **worker** runs (usually **your machine**, since it reads your source; optionally other VMs, SPCS, or Kubernetes). The two don't have to match; nothing about compute pools matters until you put the orchestrator on SPCS.

> **You are in full control of what gets migrated and how.** You decide which tables to include, how they are partitioned for extraction, whether to use incremental synchronization or full loads, and how many workers run in parallel. You can filter rows, remap column names and types, and stop or resume the process at any point without losing progress. Nothing runs until you review and approve the configuration.
>
> **The same infrastructure is used for validation.** You choose what level of validation to run: **schema validation**, **metrics validation**, and **row-level validation**.

> **Always use the official tooling for data movement and validation.** Route table migration through `migrate_data` and validation through `validate_data`. Do not suggest ad-hoc extract/copy/compare scripts — the DMVF orchestrator and workers handle partitioning, loading, and multi-level validation.

> **Supported sources**: SQL Server, Redshift, Oracle, Teradata, PostgreSQL
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
- **Worker** runs locally. Reads from the source and uploads to a Snowflake stage (migration) or streams rows for comparison (validation). Not needed for most Iceberg migration strategies.
- **The orchestrator + worker are shared, brought up ONCE, and reused across every `migrate_data` / `validate_data` dispatch** (migrate → validate → revalidate all run against the same infrastructure). Bring it up with `data_infrastructure(mode="up")` and tear it down with `data_infrastructure(mode="down")` (local) or [./teardown/SKILL.md](./teardown/SKILL.md) (SPCS). Dispatch does **not** start or resume infrastructure — if it is not up, `migrate_data` / `validate_data` return a `remediation` pointing back to `data_infrastructure(mode="up")`.
- **Whenever infrastructure starts**, tell the user that idle infrastructure can accrue Snowflake credits until teardown — the `data_infrastructure(mode="up")` response includes a `cost_reminder` field to relay.

## The `data_infrastructure` tool

Use the `data_infrastructure` tool (modes `up` / `down` / `status`) to manage the shared orchestrator + worker lifecycle — **pass `compute_pool` to run the orchestrator on SPCS, omit it for local**; `start_worker=false` skips the local worker (Iceberg / externally-managed workers). Call `up` once before dispatching migrations/validations. See the tool's own description for the full parameter list — don't restate it here.

## Idempotency

If this sub-skill has already been completed in the current project — i.e., the project's `.scai/config/dew_configuration.toml` (path relative to the SCAI project root) exists with no remaining `<placeholder>` values — tell the user verbatim: "Data infrastructure already configured — running `scai data doctor` to confirm nothing has drifted." This runs live checks against Snowflake and the source, so say it out loud rather than running silently. Then run [Level 1 Data Doctor](./references/data-doctor-reference.md#level-1-infrastructure-no-workflow-yaml) (iterate until `result.hasFailures` is `false`) and return to the caller without re-prompting.

Otherwise, proceed through the steps below.


---

## Step 0 — Confirm intent, then choose where to run (ask FIRST)

Do this **before** gathering any compute pool, role, or warehouse details — those only matter once the placements in 0.b/0.c are chosen. Do not dive into cloud specifics until the user has answered 0.a, 0.b, and 0.c.

### 0.a — Do you actually need data infrastructure?

The orchestrator + worker exist **only** to migrate or validate table **data**. Deploying tables/views and testing objects (schema/code) does **not** need them. Ask:

> Are you going to migrate or validate table **data**? (Just deploying objects and testing them does **not** need this — tell me and I'll skip it.)

- **No / not now** → call `progress_setup(mode="setup", skip="setupDataInfrastructure")` and return to the caller. Set nothing up.
- **Yes** → continue to 0.b.

### 0.b — Where should the orchestrator run?

The orchestrator runs inside your Snowflake account, breaking work into tasks and issuing `COPY INTO` / validation queries. This is the **only** choice that decides whether you need a compute pool — it is **independent** of where the worker runs (0.c).

| Orchestrator | What it means | Choose when |
|--------------|---------------|-------------|
| **Local** | Runs on your machine — **no compute pool** | Simplest; small tables, dev/PoC, or an account that can't use SPCS. Runs only while your session is up. |
| **SPCS** | Runs on a Snowpark Container Services **compute pool** | Scalable + fault-tolerant, lives in your Snowflake account, survives your local session. Large/production migrations. Needs a compute pool. |

Ask:

> Where should the data-migration **orchestrator** run — **local** (simplest, no compute pool) or **SPCS** (scalable, needs a compute pool)?

| Answer | Next step |
|--------|-----------|
| **Local** | **Skip Question 0** (no compute pool). Bring it up later with `data_infrastructure(mode="up")` (omit `compute_pool`). |
| **SPCS** | Set up the compute pool in **Question 0**; bring it up with `data_infrastructure(mode="up", compute_pool="<POOL>")`. |

### 0.c — Where should each worker run?

The worker reads from your **source** system and moves the data, so it **usually runs on your machine** (or wherever can reach the source) — independent of the orchestrator's placement in 0.b. Ask this **once**; the Worker setup step (Question 3) only acts on the answer and does **not** re-ask:

> How will you run the Data Exchange **Worker(s)** — a **single worker on this machine** (default), **multiple workers on separate VMs/servers**, on **Snowpark Container Services (SPCS)**, or on **Kubernetes**? (Some Iceberg strategies need **no** worker at all — say so and I'll set `start_worker=false`.)

Record the answer; it selects the worker sub-skill in **Question 3**.

## Worker Deployment Decisions

Having chosen placement in Step 0, gather the remaining Snowflake-side details **in order**. Question 0 is **SPCS-only** — skip it entirely on the local path.

### Question 0: Compute pool SPCS

If the user chose **local** in Step 0.b, **do not ask Question 0** — continue from **Question 1**.

Ask the user:

> The Orchestrator needs a compute pool to run inside your Snowpark Container Services. Do you already have a compute pool, or will you need to set one up?

| Answer | Action |
|--------|--------|
| **I have one** | Verify it is active (see below), then save it and continue to Question 1. |
| **I need to set one up** | Route to → `./compute-pool-setup/SKILL.md` — guide the user through creating and configuring a compute pool. After that skill completes, return here and run the steps below. |

**Bring the shared infrastructure up on this pool:**

```
data_infrastructure(mode="up", compute_pool="<COMPUTE_POOL>")
```

> The pool is persisted, so later `up` calls (and `migrate_data`/`validate_data` after them) reuse it without re-passing it. Omit `compute_pool` to run a local orchestrator instead.

### Question 1: Snowflake role and privileges

Ask the user:

> What Snowflake role will you use for the migration? The Orchestrator needs a role with USAGE on the `SNOWCONVERT_AI` database and its `DATA_MIGRATION` and `DATA_VALIDATION` schemas.

| Situation | Action |
|-----------|--------|
| **Role has the required privileges** | Continue to Question 2. |
| **Role needs grants** | Run the grants below on behalf of the user (or show them to run with an admin role), then continue. |
| **DATA_MIGRATION_SERVICE already exists (created by another role)** | The executing role also needs OPERATE and MONITOR on the service. Run the extended grants below, then continue. |

**Standard grants:**

```sql
GRANT USAGE ON DATABASE SNOWCONVERT_AI TO ROLE <your_role>;
GRANT USAGE ON SCHEMA SNOWCONVERT_AI.DATA_MIGRATION TO ROLE <your_role>;
GRANT USAGE ON SCHEMA SNOWCONVERT_AI.DATA_VALIDATION TO ROLE <your_role>;
```

**Extended grants (when the service was created by another role):**

```sql
GRANT OPERATE, MONITOR ON SERVICE SNOWCONVERT_AI.DATA_MIGRATION.DATA_MIGRATION_SERVICE TO ROLE <your_role>;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA SNOWCONVERT_AI.DATA_MIGRATION TO ROLE <your_role>;
GRANT ALL PRIVILEGES ON ALL PROCEDURES IN SCHEMA SNOWCONVERT_AI.DATA_MIGRATION TO ROLE <your_role>;
GRANT ALL PRIVILEGES ON ALL STAGES IN SCHEMA SNOWCONVERT_AI.DATA_MIGRATION TO ROLE <your_role>;
```

### Question 2: Snowflake warehouse

Ask the user:

> Which Snowflake warehouse should be used for data migration and validation? The Orchestrator uses this warehouse to execute `COPY INTO` statements and run validation queries. Your Snowflake connection must have a warehouse configured — without one, data migration will fail silently.

| Situation | Action |
|-----------|--------|
| **User provides a warehouse name** | Verify the warehouse exists and the role from Question 1 has USAGE on it. Confirm that `~/.snowflake/config.toml` has `warehouse = "<WAREHOUSE>"` under the active connection. If not, help the user add it. Continue to Question 3. |
| **User is unsure** | Run `SHOW WAREHOUSES;` to list available warehouses and help them pick one. For large migrations, recommend a dedicated warehouse to avoid contention with other workloads. |

### Question 3: Worker setup

**Do not ask where the worker runs again** — that was decided in **Step 0.c**. Route to the matching sub-skill; it handles install/start and returns control here:

| Step 0.c answer | Sub-skill |
|-----------------|-----------|
| **Single worker on this machine** | → `./worker-local-setup/SKILL.md` — install and start on one host |
| **Multiple workers on separate VMs/servers** | → `./worker-distributed-setup/SKILL.md` — affinity config + per-host copy instructions |
| **Snowpark Container Services (SPCS)** | → `./worker-spcs/SKILL.md` — image selection, Snowflake Secrets, CREATE SERVICE |
| **Kubernetes (external cluster)** | → `./worker-k8s-external/SKILL.md` — image selection, Kubernetes Secrets, Deployment manifest |
| **No worker (Iceberg)** | none — set `start_worker=false` on `data_infrastructure(mode="up")` |

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
- [ ] Worker config complete (no <placeholder> values) — unless pure Iceberg
- [ ] Level 1 scai data doctor — no Fail checks
```

---

Return control to the calling skill.

---

## Reference

- [Data Doctor reference](./references/data-doctor-reference.md)
- [Worker Config Reference](./references/worker-config-reference.md)
- [Teardown (cost-saving suspend)](./teardown/SKILL.md)
