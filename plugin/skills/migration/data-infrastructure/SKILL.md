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

> If your Snowflake account **cannot** use Snowpark Container Services or you **are not** using a compute pool for the orchestrator, you can run the **Orchestrator** and **Workers** **locally**.

> **You are in full control of what gets migrated and how.** You decide which tables to include, how they are partitioned for extraction, whether to use incremental synchronization or full loads, and how many workers run in parallel. You can filter rows, remap column names and types, and stop or resume the process at any point without losing progress. Nothing runs until you review and approve the configuration.
>
> **The same infrastructure is used for validation.** You choose what level of validation to run: **schema validation**, **metrics validation**, and **row-level validation**.

> **Supported sources**: SQL Server, Redshift
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

- **Orchestrator** runs on SPCS (requires a compute pool). Handles migration workflows (break into tasks, `COPY INTO`) and validation workflows (schema/metrics/row comparison).
- **Worker** runs locally. Reads from the source and uploads to a Snowflake stage (migration) or streams rows for comparison (validation). Not needed for most Iceberg migration strategies.
- Both can be stopped and resumed safely. The next `migrate_data()` / `validate_data()` call auto-resumes the SPCS service. To suspend everything between waves and minimise idle SPCS / warehouse cost, use [./teardown/SKILL.md](./teardown/SKILL.md).

## Idempotency

If this sub-skill has already been completed in the current project — i.e., `.scai/settings/cloud-migration.yaml` already has a `compute_pool` value **and** `.scai/settings/DataExchangeWorkerConfig.toml` exists with no remaining `<placeholder>` values — report "Data infrastructure already configured" and return to the caller without re-prompting.

Otherwise, proceed through the steps below.


---

## Worker Deployment Decisions

After the overview, walk the user through the following questions **in order**. Each answer determines the next step.

### Preflight: Orchestrator placement (before compute pool)

Ask the user:

> **Orchestrator:** Can this Snowflake account run the migration **orchestrator** on **Snowpark Container Services** using a **compute pool**? (If **no** — account cannot use SPCS, or you will **not** use a compute pool / SPCS for the orchestrator — use the **local orchestrator** path and **skip Question 0**.)

| Situation | Next step |
|-----------|-----------|
| **Yes** — SPCS + compute pool for the orchestrator | Continue to **Question 0** (compute pool). |
| **No** — local orchestrator | **Skip Question 0** (no compute pool setup for orchestrator placement). The data orchestrator will run locally (Python must be available; the CLI prepares the orchestrator environment). Continue to **Question 1**. |

### Question 0: Compute pool SPCS

If the user chose **local orchestrator** in the preflight, **do not ask Question 0** — continue from **Question 1**.

Ask the user:

> The Orchestrator needs a compute pool to run inside your Snowpark Container Services. Do you already have a compute pool, or will you need to set one up?

| Answer | Action |
|--------|--------|
| **I have one** | Verify it is active (see below), then save it and continue to Question 1. |
| **I need to set one up** | Route to → `./compute-pool-setup/SKILL.md` — guide the user through creating and configuring a compute pool. After that skill completes, return here and run the steps below. |

**Save compute pool to MCP config:**

```
configure(compute_pool="<COMPUTE_POOL>")
```

> The orchestrator SPCS service starts automatically when we start migrating or validating data later on.

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

### Question 3: Worker deployment

Ask the user:

> How will you run the Data Exchange Worker?

| Answer | Route |
|--------|-------|
| **Single worker on one machine** | → `./worker-local-setup/SKILL.md` — handles install and start on one host |
| **Multiple workers on separate VMs or servers** | → `./worker-distributed-setup/SKILL.md` — handles affinity config and per-host copy instructions |
| **Snowpark Container Services (SPCS)** | → `./worker-spcs/SKILL.md` — handles image selection, Snowflake Secrets, and CREATE SERVICE |
| **Kubernetes on an external cluster** | → `./worker-k8s-external/SKILL.md` — handles image selection, Kubernetes Secrets, and Deployment manifest |

**Stop here** — do not continue; the routed skill handles the rest.


---

Return control to the calling skill.

---

## Reference

- [Worker Config Reference](./references/worker-config-reference.md)
- [Teardown (cost-saving suspend)](./teardown/SKILL.md)
