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
  INSTANCE_FAMILY = CPU_X64_S;
```

> **Defaults:** `CPU_X64_S` is sufficient for the orchestrator. The orchestrator itself is lightweight — it coordinates work but does not process data. `MIN_NODES = 1` and `MAX_NODES = 1` are recommended; the pool scales the number of nodes, not the workers.

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

Return to `../SKILL.md` and save the compute pool name via `configure(compute_pool="<COMPUTE_POOL_NAME>")`.
