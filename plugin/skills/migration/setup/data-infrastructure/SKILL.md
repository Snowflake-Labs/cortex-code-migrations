---
name: data-infrastructure-setup
description: Shared infrastructure setup for data migration and data validation — prerequisites, compute pool, worker config, and source database/schema capture.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# Data Infrastructure Setup

## Prerequisite: Support Level Check

Check `support` from the `configure()` response.

If `support` is `basic`, **STOP** — data infrastructure setup is not available for this source dialect. Inform the user and return to the caller.

---

Shared one-time infrastructure configuration used by both **data migration** and **data validation**. This skill is invoked by the parent `setup` skill and only configures shared infrastructure (compute pool + worker config).

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
- Both can be stopped and resumed safely.

## Idempotency

If this sub-skill has already been completed in the current project — i.e., `.scai/settings/cloud-migration.yaml` already has a `compute_pool` value **and** `.scai/settings/DataExchangeWorkerConfig.toml` exists with no remaining `<placeholder>` values — report "Data infrastructure already configured" and return to the caller without re-prompting.

Otherwise, proceed through the steps below.

---

## Prerequisites

Apply to both migration and validation unless noted:

- SPCS enabled on the Snowflake account
- Compute pool created and accessible to the executing role
- Snowflake role has USAGE on the `SNOWCONVERT_AI` database and `DATA_MIGRATION` and `DATA_VALIDATION` schemas
- If the `DATA_MIGRATION_SERVICE` already exists (created by another role), the executing role needs OPERATE and MONITOR privileges on the service. Grant with:
  ```sql
  GRANT OPERATE, MONITOR ON SERVICE SNOWCONVERT_AI.DATA_MIGRATION.DATA_MIGRATION_SERVICE TO ROLE <your_role>;
  GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA SNOWCONVERT_AI.DATA_MIGRATION TO ROLE <your_role>;
  GRANT ALL PRIVILEGES ON ALL PROCEDURES IN SCHEMA SNOWCONVERT_AI.DATA_MIGRATION TO ROLE <your_role>;
  GRANT ALL PRIVILEGES ON ALL STAGES IN SCHEMA SNOWCONVERT_AI.DATA_MIGRATION TO ROLE <your_role>;
  ```
- Source ODBC driver installed (Amazon Redshift or SQL Server)
- Snowflake connection must have a `warehouse` configured in `~/.snowflake/config.toml`. Connections without a warehouse will fail silently during data migration.
- **Validation only:** target tables must already be deployed to Snowflake (run data migration first).

---

## Step 1: Configure Compute Pool

**1a. Verify compute pool is active:**

```sql
SHOW COMPUTE POOLS LIKE '<COMPUTE_POOL>';
```

If state is `SUSPENDED`, resume it and wait for `IDLE` or `ACTIVE`:

```sql
ALTER COMPUTE POOL <COMPUTE_POOL> RESUME;
```

**1b. Save compute pool to MCP config:**

```
configure(compute_pool="<COMPUTE_POOL>")
```

This persists the compute pool to `.scai/settings/cloud-migration.yaml` and auto-generates `.scai/settings/DataExchangeWorkerConfig.toml` if the file does not already exist. `configure` pre-fills as much as it can:

- **Snowflake connection name** from the session config.
- **Source `host`, `port`, `username`, `password`, `database`** from the named scai source connection (`~/.snowflake/snowct/<dialect>.toml`). Anything the scai connection doesn't carry is left as a `<placeholder>` for Step 2.

> The orchestrator SPCS service starts automatically when `migrate_data()` or `validate_data()` is called — no manual service start is required here.

---

## Step 2: Complete Worker Configuration

**First, read `.scai/settings/DataExchangeWorkerConfig.toml`.** If the file exists and contains **no `<placeholder>` tokens**, report "Worker config already complete" and skip the rest of this step — proceed directly to the checklist.

Otherwise:

1. **Show the user the pre-filled values** that came from the scai source connection (`[connections.source.*]` host, port, user, database). Ask them to confirm — and only edit if something is wrong. Do **not** re-prompt for connection values when those fields already have real values from the scai connection.
2. **Fill any remaining `<placeholder>` tokens.** If the scai connection lacked a field (e.g., the TOML had no `port` entry), ask the user for just that field.

> The scai connection's `database` also populates `[connections.source.*].database`. This value **must match** `source.databaseName` in the migration workflow YAML / validation JSON. A mismatch causes the orchestrator to report "table does not exist in the source database." If the user wants to migrate a different database than the one in their scai connection, have them update it here and remember to use the same value in the workflow YAML.

> **Skip** this step for Iceberg migration strategies without a Worker (`catalog_link`, `convert_to_managed`, `copy_files` with `sourceDataStage`). See `./references/worker-config-reference.md` for advanced options.

---

## Checklist

```
- [ ] Snowflake connection has warehouse configured
- [ ] Compute pool active (not suspended)
- [ ] Compute pool saved via configure(compute_pool=...)
- [ ] Worker config has no remaining <placeholder> values — unless pure Iceberg
- [ ] Pre-filled source connection values confirmed with user
```

Return control to the parent `setup` skill and continue with the next setup step.

---

## Reference

- [Worker Config Reference](./references/worker-config-reference.md)
