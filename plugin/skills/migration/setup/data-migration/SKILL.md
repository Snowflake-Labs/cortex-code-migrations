---
name: data-migration-setup
description: One-time setup for data migration into Snowflake — choose approach, generate configs, register with MCP.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# Data Migration Setup

One-time configuration for migrating data from a source database into Snowflake via the **scai CLI**.

> **Supported sources**: SQL Server, Redshift
> **Supported targets**: Native tables (default), Iceberg tables

## Architecture

```
┌──────────────────┐     ┌──────────────────────────────────────┐
│  Customer Env     │     │         Snowflake Account             │
│  ┌─────────────┐ │     │  ┌────────────────────────────────┐  │
│  │  Worker(s)   │─┼─────┤  │  Orchestrator (SPCS)            │  │
│  └──────┬──────┘ │     │  │  → manages tasks, COPY INTO     │  │
│         │ reads   │     │  └────────────────────────────────┘  │
│  ┌─────────────┐ │     │  ┌────────────────────────────────┐  │
│  │Source System │ │     │  │  Target Tables                  │  │
│  └─────────────┘ │     │  └────────────────────────────────┘  │
└──────────────────┘     └──────────────────────────────────────┘
```

- **Orchestrator** runs on SPCS (requires a compute pool). Breaks workflows into tasks and runs `COPY INTO`.
- **Worker** runs locally. Reads from source, uploads to Snowflake stage. Not needed for most Iceberg strategies.
- Both can be stopped and resumed safely.

**Prerequisites:**

- SPCS enabled on the Snowflake account
- Compute pool created and accessible to the executing role
- Snowflake role has USAGE on the `SNOWCONVERT_AI` database and `DATA_MIGRATION` schema (or can create them)
- If the `DATA_MIGRATION_SERVICE` already exists (created by another role), the executing role needs OPERATE and MONITOR privileges on the service. Grant with:
  ```sql
  GRANT OPERATE, MONITOR ON SERVICE SNOWCONVERT_AI.DATA_MIGRATION.DATA_MIGRATION_SERVICE TO ROLE <your_role>;
  GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA SNOWCONVERT_AI.DATA_MIGRATION TO ROLE <your_role>;
  GRANT ALL PRIVILEGES ON ALL PROCEDURES IN SCHEMA SNOWCONVERT_AI.DATA_MIGRATION TO ROLE <your_role>;
  GRANT ALL PRIVILEGES ON ALL STAGES IN SCHEMA SNOWCONVERT_AI.DATA_MIGRATION TO ROLE <your_role>;
  ```
- Source ODBC driver installed (Amazon Redshift or SQL Server)
- Snowflake connection must have a `warehouse` configured in `~/.snowflake/config.toml`. Connections without a warehouse will fail silently during data migration.

---

## Step 1: Choose Migration Approach

### 1.A — Migration Type

Ask the user:

> 1. **Preliminary** — Subset of rows to verify setup. Sets `whereClauseCriteria` to a valid WHERE predicate for your source platform, sync = `none`.
>    - **SQL Server**: Filter on a key column (e.g., `"id <= 1000"`)
>    - **Redshift**: Filter on a key column (e.g., `"id <= 1000"`)
>    - **Important**: `whereClauseCriteria` is injected after `WHERE` in the extraction query. `TOP` (SQL Server) and `LIMIT` (Redshift) are **not valid** inside a WHERE clause and will cause a syntax error.
> 2. **Incremental** — Only new/changed data. Ask: **Checksum** (partition hashing) or **Watermark** (monotonic column)?
> 3. **Full** — All rows, one-time load. Sync = `none`.

### 1.B — Extraction Strategy

Only for **Redshift** (default `regular`):

> 1. **Regular** — Direct ODBC read.
> 2. **UNLOAD** — Redshift writes to S3, loaded via External Stage.

### 1.C — Target Table Type

> 1. **Native (default)** — Standard Snowflake tables.
> 2. **Iceberg** — See `./references/iceberg-setup-reference.md` for strategy selection and prerequisite setup.

### 1.D — Confirm

```
Migration approach:
  Type:        Preliminary | Incremental | Full
  Sync:        none | checksum | watermark
  Extraction:  regular | unload
  Target:      native | iceberg
```

---

## Step 2: Configure Compute Pool

**2a. Verify compute pool is active:**

```sql
SHOW COMPUTE POOLS LIKE '<COMPUTE_POOL>';
```

If state is `SUSPENDED`, resume it and wait for `IDLE` or `ACTIVE`:

```sql
ALTER COMPUTE POOL <COMPUTE_POOL> RESUME;
```

**2b. Save compute pool to MCP config:**

```
configure(compute_pool="<COMPUTE_POOL>")
```

This persists the compute pool to `.scai/settings/cloud-migration.yaml` and auto-generates `.scai/settings/WorkerConfig.toml` with placeholders if the file does not already exist. The Snowflake connection name is pre-filled from the session config.

> The orchestrator SPCS service starts automatically when `migrate_data()` is called — no manual setup or service verification is needed here.

---

## Step 3: Edit Worker Configuration

Edit the generated `.scai/settings/WorkerConfig.toml` to fill in source connection details.

**Explicitly ask the user for:**
1. **Source database name** — do NOT infer from the scai connection. This value goes into `[connections.source.*].database` AND must match `source.databaseName` in the workflow YAML (Step 4). A mismatch causes the orchestrator to report "table does not exist in the source database."
2. **Source schema name** — needed for `source.schemaName` in the workflow YAML (Step 4). Do not assume `public` or `dbo`.
3. **Source host, port, credentials** — fill in the remaining `<placeholder>` values.

> **Skip** for Iceberg strategies without a Worker (`catalog_link`, `convert_to_managed`, `copy_files` with `sourceDataStage`). See `./references/worker-config-reference.md` for advanced options.

---

## Step 4: Create Workflow Configuration

### Option A — Auto-generate

```bash
mkdir -p .scai/settings
scai data generate-cloud-migration-config -o .scai/settings/workflow-config.yaml
```

Edit to match the approach from Step 1 (sync strategy, extraction, etc.).

### Option B — Create manually

Minimal native example:

```yaml
defaultTableConfiguration:
  columnNamesToPartitionBy:
    - <partition_col>
  synchronization:
    strategy: <none|checksum|watermark>
  extraction:
    strategy: <regular|unload>

tables:
  - source:
      databaseName: <src_db>
      schemaName: <src_schema>
      tableName: <table>
    target:
      databaseName: <tgt_db>
      schemaName: <tgt_schema>
      tableName: <TABLE>
```

> `columnNamesToPartitionBy` is **required** by the CLI validator for all configs.

For **Iceberg** workflows, see `./references/workflow-config-reference.md`.

Save to `.scai/settings/workflow-config.yaml`.

> **Affinity matching** — If the orchestrator logs show "Found 0 pending workflows," the service likely has a baked-in affinity that doesn't match. See [Troubleshooting Reference](./references/troubleshooting-reference.md) for diagnosis and fix.

---

## Step 5: Create Target Database

```sql
CREATE DATABASE IF NOT EXISTS <target_db>;
CREATE SCHEMA IF NOT EXISTS <target_db>.<target_schema>;
```

This completes the setup. During the migrate-objects phase, the `migrate_data()` MCP tool will automatically detect the configs at `.scai/settings/` and use cloud migration. **Do not run `scai data cloud-migrate` or `scai data start-cloud-worker` directly** — `migrate_data()` handles orchestrator and worker lifecycle internally.

---

## Checklist

```
- [ ] Snowflake connection has warehouse configured
- [ ] Migration approach selected
- [ ] Compute pool active (not suspended)
- [ ] Compute pool saved via configure(compute_pool=...)
- [ ] Worker config edited with source connection details — unless pure Iceberg
- [ ] Source database name explicitly confirmed with user
- [ ] Workflow config created (.scai/settings/workflow-config.yaml)
- [ ] Target database and schema exist
- [ ] Iceberg prerequisites validated — if applicable
```

Return control to the parent skill.

---

## Reference

- [Worker Config Reference](./references/worker-config-reference.md)
- [Workflow Config Reference](./references/workflow-config-reference.md)
- [Iceberg Setup Reference](./references/iceberg-setup-reference.md)
- [Troubleshooting Reference](./references/troubleshooting-reference.md)
