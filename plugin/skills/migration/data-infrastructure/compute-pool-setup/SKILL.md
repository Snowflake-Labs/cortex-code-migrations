---
name: compute-pool-setup
description: Guide the user through creating and configuring a Snowpark Container Services compute pool for the migration orchestrator.
parent_skill: data-infrastructure-setup
license: Proprietary. See License-Skills for complete terms
---

# Compute Pool Setup

Create a compute pool for the migration orchestrator to run inside Snowpark Container Services.

## Step 1 — Choose a Name

Ask the user:

> What name would you like for the compute pool? (e.g., `MIGRATION_COMPUTE_POOL`)

## Step 2 — Create the Compute Pool

Run the following SQL, substituting the user's chosen name:

```sql
CREATE COMPUTE POOL <COMPUTE_POOL_NAME>
  MIN_NODES = 1
  MAX_NODES = 1
  INSTANCE_FAMILY = CPU_X64_S
  AUTO_SUSPEND_SECS = 60;
```

> **Defaults:** `CPU_X64_S` is sufficient for the orchestrator. The orchestrator itself is lightweight — it coordinates work but does not process data. `MIN_NODES = 1` and `MAX_NODES = 1` are recommended; the pool scales the number of nodes, not the workers.
>
> **`AUTO_SUSPEND_SECS = 60`** lets the pool go cold ~60s after the orchestrator service suspends, so an idle pool stops billing even if teardown is never run. It stays active while the service is running, and `data_infrastructure(mode="up")` resumes it before the next wave (a ~30–60s warm-up). Raise it if your migration waves run back-to-back and the warm-up is disruptive.

### Sizing a pool that also runs SPCS workers

The values above are for an orchestrator-only pool. When the Data Exchange Worker also runs on SPCS
([worker-spcs](../worker-spcs/SKILL.md)) in the same pool, size it from the worker's CPU request, and keep
the minimum at one node:

- **Instance family:** the worker spec requests `cpu: 6`, which needs `CPU_X64_M` (6 vCPU per node). A
  `CPU_X64_S` pool cannot schedule it.
- **Node count:** with `cpu: 6`, each worker replica fills a node and the orchestrator needs one more. With a
  smaller request (`cpu: 0.5`–`2`), the orchestrator and two or three workers share one or two nodes.
- **Recommend `MIN_NODES = 1`, `MAX_NODES = 2`–`3`, `AUTO_SUSPEND_SECS = 60`**, with 2–3 worker replicas and
  `MAX_PARALLEL_TASKS = 4`. The source system, not the pool, limits throughput: a pool wider than the source can
  feed adds cost, not speed.
- **Never recommend a large fixed minimum** (for example `MIN_NODES = 10`). Every node in `MIN_NODES` bills
  whenever the pool is resumed, including while the agent waits on a confirmation. For a wave that needs more
  source concurrency, raise only `MAX_NODES` and the worker's `MAX_INSTANCES` for that wave, then lower them
  again.

Nothing in the product sizes the pool from table row counts. Tell the user these numbers as a starting point
and let them decide.

## Step 3 — Verify the Pool Is Active

Run:

```sql
DESCRIBE COMPUTE POOL <COMPUTE_POOL_NAME>;
```

Check that the `state` column is **ACTIVE** or **IDLE**. If the state is `STARTING`, wait a moment and re-check — pools typically become active within a minute.

If the state is `SUSPENDED`, run:

```sql
ALTER COMPUTE POOL <COMPUTE_POOL_NAME> RESUME;
```

Then re-verify.

## Step 4 — Grant USAGE to the Migration Role

The role that will run the migration needs USAGE on the compute pool:

```sql
GRANT USAGE ON COMPUTE POOL <COMPUTE_POOL_NAME> TO ROLE <MIGRATION_ROLE>;
```

## Done

Return to `../SKILL.md`; the compute pool name is passed to `data_infrastructure(mode="up", compute_pool="<COMPUTE_POOL_NAME>")` when bringing the shared infrastructure up (it is persisted for reuse).
