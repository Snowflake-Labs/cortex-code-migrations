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

Load `../../../setup/data-infrastructure/SKILL.md` first. It handles shared prerequisites, compute pool registration, and worker config (source host/port/credentials, source database, source schema). Return here after it completes.

---

## Step 1: Choose Migration Approach

### 1.A — Pick Tables to Migrate (`where`)

The `where` parameter is a **registry filter that selects which tables go into
the generated workflow**. Same syntax as `scai code deploy --where` (e.g.
`source.objectType = 'table' AND source.schema = 'sales'`,
`source.canonicalName IN ('dbo.customers', 'dbo.orders')`).

Decide the value in this order:

1. **You already know the tables.** If the parent skill or the current wave has
   already identified the tables, construct the `where` from that. For a wave's batch,
   the batch's `where` filter is typically reusable verbatim.
2. **Otherwise, ask the user.** Suggest options like "all tables in schema X"
   (`source.schema = 'X'`), "specific tables"
   (`source.canonicalName IN (...)`), or "all tables in scope" (omit `where`).
3. **If you're unsure of the registry filter syntax**, run `scai code where`
   to see the available columns and operators for this project, then
   construct the filter from the listed columns (`source.objectType`,
   `source.schema`, `source.canonicalName`, etc.).

Show the proposed `where` to the user and get confirmation before generating.

### 1.B — Migration Type (controls per-table sync + row scope)

Once tables are chosen, decide what happens *inside* each table:

> 1. **Preliminary** — Subset of rows to verify setup. After YAML generation,
>    add `whereClauseCriteria` to each table with a valid WHERE predicate for
>    your source platform; sync = `none`.
>    - **SQL Server**: Filter on a key column (e.g., `"id <= 1000"`)
>    - **Redshift**: Filter on a key column (e.g., `"id <= 1000"`)
>    - **Important**: `whereClauseCriteria` is injected after `WHERE` in the
>      extraction query. `TOP` (SQL Server) and `LIMIT` (Redshift) are **not
>      valid** inside a WHERE clause and will cause a syntax error.
>    - This is **separate from** the table-selection `where` in 1.A.
>      `whereClauseCriteria` is a YAML edit applied to each table after the
>      file is generated.
> 2. **Incremental** — Only new/changed data. Ask: **Checksum** (partition
>    hashing) or **Watermark** (monotonic column)?
> 3. **Full** — All rows, one-time load. Sync = `none`. No
>    `whereClauseCriteria`.

### 1.C — Extraction Strategy

Only for **Redshift** (default `regular`):

> 1. **Regular** — Direct ODBC read.
> 2. **UNLOAD** — Redshift writes to S3, loaded via External Stage.

### 1.D — Target Table Type

> 1. **Native (default)** — Standard Snowflake tables.
> 2. **Iceberg** — See `./references/iceberg-setup-reference.md` for strategy selection and prerequisite setup.

### 1.E — Confirm

```
Migration approach:
  Tables (where): <registry filter or "all in scope">
  Type:           Preliminary | Incremental | Full
  Sync:           none | checksum | watermark
  Extraction:     regular | unload
  Target:         native | iceberg
```

---

## Step 2: Generate the Workflow YAML

Workflow YAML generation is owned by the `migrate_data` MCP tool.

Translate the user's choices from Step 1 into the call:

```
migrate_data(
  mode="setup",
  where=<table-selection filter from 1.A, or omit to include all tables in scope>,
  migration_type="preliminary" | "incremental" | "full",
  sync_strategy="none" | "checksum" | "watermark",
  extraction_strategy="regular" | "unload",
  target_table_type="native" | "iceberg",
)
```

Notes:

- `where` is forwarded to `scai data generate-cloud-migration-config --where`
  as a **table-selection filter** (registry syntax). It controls which tables
  show up in the generated `tables:` list. Row-level filtering for the
  Preliminary type is a separate YAML edit (`whereClauseCriteria`) applied in
  Step 2a.
- The tool writes the generated YAML to
  `artifacts/data_migration/workflows/<hash>.yaml`, where `<hash>` is derived
  from `where`. Same `where` always maps to the same file; distinct table
  selections produce distinct files. If the file already exists, the tool
  reuses it — no overwrite.

### Step 2a: Read, edit, and confirm

1. Read `workflow_path`.
2. Apply each entry in `edit_hints`. Refer to `./references/workflow-config-reference.md`
   for field-level details.
3. **For Preliminary type**: add `whereClauseCriteria: "<row predicate>"` to
   each table (or to `defaultTableConfiguration` for a shared filter). This
   is the row-level filter and is unrelated to the table-selection `where`.
4. Fill in any missing per-table fields (`columnNamesToPartitionBy` is
   **required** by the CLI validator for native tables; `target.databaseName`
   / `schemaName` / `tableName` if not auto-populated).
5. For **Iceberg** workflows, also follow `./references/iceberg-setup-reference.md`.
6. Show the final YAML to the user and get explicit confirmation before running.

> `columnNamesToPartitionBy` is **required** by the CLI validator for all configs.

> **Affinity matching** — If the orchestrator logs show "Found 0 pending workflows," the service likely has a baked-in affinity that doesn't match. See [Troubleshooting Reference](./references/troubleshooting-reference.md) for diagnosis and fix.

---

## Step 3: Create Target Database

```sql
CREATE DATABASE IF NOT EXISTS <target_db>;
CREATE SCHEMA IF NOT EXISTS <target_db>.<target_schema>;
```

This completes the **setup** phase. The actual migration is started later by the
migrate-objects skill via `migrate_data(mode="run", workflow_path=<path>)`,
which handles the orchestrator and worker lifecycle internally. Track progress
with `migration_status(mode="data_migration")`. **Do not run `scai data cloud-migrate`
or `scai data start-cloud-worker` directly.**

---

## Checklist

Shared infrastructure checklist is owned by `../../../setup/data-infrastructure/SKILL.md`. Migration-specific items:

```
- [ ] Migration approach selected
- [ ] Workflow YAML generated via migrate_data(mode="setup", ...) and edited
- [ ] User confirmed the final workflow YAML
- [ ] Target database and schema exist
- [ ] Iceberg prerequisites validated — if applicable
```

Return control to the parent skill.

---

## Reference

- [Workflow Config Reference](./references/workflow-config-reference.md)
- [Iceberg Setup Reference](./references/iceberg-setup-reference.md)
- [Troubleshooting Reference](./references/troubleshooting-reference.md)
- [Teardown (cost-saving suspend)](../../../data-infrastructure/teardown/SKILL.md)
