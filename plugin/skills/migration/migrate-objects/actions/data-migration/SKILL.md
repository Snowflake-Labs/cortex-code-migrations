---
name: data-migration-setup
description: One-time setup for data migration into Snowflake — choose approach, generate workflow config, create target database.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# Data Migration Setup

One-time configuration for migrating data from a source database into Snowflake via the **scai CLI**.

> **Supported sources**: SQL Server, Redshift, Oracle, Teradata, PostgreSQL
> **Supported targets**: Native tables (default), Iceberg tables

## Prerequisite

Load `../../../data-infrastructure/SKILL.md` first. It handles shared prerequisites, compute pool registration, and worker config (source host/port/credentials, source database, source schema). Return here after it completes.

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

Show the proposed `where` to the user and get confirmation before continuing.

### 1.B — Migration approach (state machine)

Migration type, sync strategy, extraction strategy, and target table type are
driven by the **`data-migration-setup` state machine**. Call
`progress_setup(mode="data_migration")` in a loop until `completed` is true —
follow each response's `next_prompt` (persist answers with `configure`) the same
way as project setup in `setup/SKILL.md`.

For **Preliminary** migrations, after YAML generation (Step 2a), add
`whereClauseCriteria` per table with a valid WHERE predicate; see
`./references/workflow-config-reference.md`.

### 1.C — Confirm

```
Migration approach:
  Tables (where): <registry filter or "all in scope">
  Type:           <from machine>
  Sync:           <from machine, or none for preliminary/full>
  Extraction:     <from machine, or regular default>
  Target:         <from machine>
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

- `where` is forwarded to `scai data migrate generate-config --where` as a
  **table-selection filter** (registry syntax). It controls which tables show
  up in the generated `tables:` list. Row-level filtering for the Preliminary
  type is a separate YAML edit (`whereClauseCriteria`) applied in Step 2a.
- The tool writes the YAML to `artifacts/data_migration/workflows/<hash>.yaml`.
  Same `where` always maps to the same file. **Re-running setup reuses the
  existing file** (preserves your edits). Pass `force_regenerate=true` only
  when you intentionally want a fresh file from scai (previous file copied to
  `.yaml.bak`).
- On first generation, the MCP server fills missing `source.databaseName` (from
  the scai source connection), `target.databaseName` (from
  `configure(snowflake_database=...)`), and Oracle `columnNamesToPartitionBy`
  (`ROWID`) when the CLI left them empty.

### Step 2a: Read, edit, and confirm

1. Read `workflow_path`.
2. Apply each entry in `edit_hints`. Refer to `./references/workflow-config-reference.md`
   for field-level details.
3. **For Preliminary type**: add `whereClauseCriteria: "<row predicate>"` to
   each table (or to `defaultTableConfiguration` for a shared filter). This
   is the row-level filter and is unrelated to the table-selection `where`.
4. Fill in any remaining per-table fields. **`columnNamesToPartitionBy` must
   have at least one column** for native tables (empty `[]` finishes the
   workflow without moving data). SQL Server / Redshift need an explicit PK or
   partition column — Oracle defaults to `ROWID` on first generate —
   PostgreSQL should use a monotonic integer PK (e.g. `id BIGINT`) or a
   timestamp column; avoid `ctid` (unstable across vacuum). If no suitable
   column exists, omit the field for a single-partition full extract.
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

This completes the **setup** phase. Start migration via
`migrate_data(mode="run", workflow_path=<path>)`. That runs, in order:

1. `scai data orchestrator setup --compute-pool ...`
2. `scai data worker start --local .scai/settings/DataExchangeWorkerConfig.toml` (when config exists)
3. `scai data migrate create-workflow --config <path> --start-service --compute-pool ...`

Track progress with `migration_status(mode="data_migration")`.

**Do not** use `scai data migrate start` for cloud/SPCS workflows — it follows a
different path and may accept YAML the orchestrator rejects.

**Removed commands (do not use):** `cloud-migrate`, `start-cloud-worker`, etc.
Use the `migrate_data` MCP tool or `scai data migrate create-workflow` / `scai data worker start`.

---

## Checklist

Shared infrastructure checklist is owned by `../../../data-infrastructure/SKILL.md`. Migration-specific items:

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
