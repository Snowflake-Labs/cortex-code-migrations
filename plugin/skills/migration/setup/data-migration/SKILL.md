---
name: data-migration-setup
description: One-time setup for data migration into Snowflake — choose approach, generate workflow config, create target database.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# Data Migration Setup

One-time configuration for migrating data from a source database into Snowflake via the **scai CLI**.

> **Supported sources**: SQL Server, Redshift
> **Supported targets**: Native tables (default), Iceberg tables

## Prerequisite

Load `../data-infrastructure/SKILL.md` first. It handles shared prerequisites, compute pool registration, and worker config (source host/port/credentials, source database, source schema). Return here after it completes.

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

## Step 2: Create Workflow Configuration

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

## Step 3: Create Target Database

```sql
CREATE DATABASE IF NOT EXISTS <target_db>;
CREATE SCHEMA IF NOT EXISTS <target_db>.<target_schema>;
```

This completes the setup. During the migrate-objects phase, the `migrate_data()` MCP tool will automatically detect the configs at `.scai/settings/` and use cloud migration. **Do not run `scai data cloud-migrate` or `scai data start-cloud-worker` directly** — `migrate_data()` handles orchestrator and worker lifecycle internally.

---

## Checklist

Shared infrastructure checklist is owned by `../data-infrastructure/SKILL.md`. Migration-specific items:

```
- [ ] Migration approach selected
- [ ] Workflow config created (.scai/settings/workflow-config.yaml)
- [ ] Target database and schema exist
- [ ] Iceberg prerequisites validated — if applicable
```

Return control to the parent skill.

---

## Reference

- [Workflow Config Reference](./references/workflow-config-reference.md)
- [Iceberg Setup Reference](./references/iceberg-setup-reference.md)
- [Troubleshooting Reference](./references/troubleshooting-reference.md)
