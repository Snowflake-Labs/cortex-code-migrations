# Workflow YAML Configuration Reference

> **Field naming:** Use **camelCase** for all workflow YAML keys (for example `targetPartitionSizeMb`, `whereClauseCriteria`, `trackDeletions`). The orchestrator accepts snake_case as a fallback for migration configs, but generated files and this reference use camelCase only.

## Top-Level Properties

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `schemaVersion` | String | No | Semantic version of this config shape (for example `"1"`, `"1.2"`). Omit for current defaults. |
| `tables` | `TableConfiguration[]` | Yes | Tables to migrate |
| `defaultTableConfiguration` | `TableConfiguration` | No | Shared defaults inherited by all tables |
| `affinity` | String | No | Only orchestrator and worker instances with a matching affinity will process this workflow. If the SPCS orchestrator was started with a specific affinity (visible in service logs as `Orchestrator affinity: <value>`), the workflow **must** set the same value or it will be silently skipped. The worker's `[application].affinity` must also match. Omit from all sides for fresh setups. |
| `preflight` | Boolean | No | When `true`, cap each table to one partition and run against a transient `PREFLIGHT_<workflowId>` schema (bounded dry-run). Default `false`. |
| `preflightKeepSchema` | Boolean | No | When `preflight` is `true`, skip cleanup so the transient schema remains for manual inspection. Default `false`. |
| `exportDataGcsBucket` | String | No | BigQuery `export_data` only: GCS bucket name (no `gs://`) that `EXPORT DATA` writes to. `scai data migrate start` copies it into the local worker config as `export_data_gcs_bucket`, replacing any value already there. `extraction.externalStage` must point at the same bucket and prefix. Set with `scai data migrate generate-config --export-data-gcs-bucket <BUCKET>`. |
| `exportDataGcsPrefix` | String | No | BigQuery `export_data` only: path inside `exportDataGcsBucket`, copied into the worker config as `export_data_gcs_prefix`. Set with `--export-data-gcs-prefix <PREFIX>`. |
| `cleanUpTransientResources` | `"never"` \| `"on-success"` \| `"always"` | No | Delete intermediate stage files for this workflow after it finishes (`TASK_RESULTS` and any external stages used by extraction). Default `"on-success"`. Underscores are accepted (`on_success`). Set `"never"` to retain stage files for debugging. When the orchestrator runs in Iceberg metadata mode, the omitted-key default may be `"always"` instead — check your deployment profile if you rely on the default. |
| `intervalHandling` | `"interval"` \| `"varchar"` | No | How PostgreSQL/BigQuery mixed-family interval columns are mapped. Default `"interval"`. Can be overridden per table. |

## Preflight (bounded dry-run)

Set top-level `preflight: true` for a **migration smoke test**: each table runs as a single partition; loads go to transient schema `PREFLIGHT_<workflowId>`, not the configured production target. Optional `preflightKeepSchema: true` retains the schema after the workflow for inspection.

**Not the same as** Preliminary migration type (`whereClauseCriteria` loads to real targets) or `scai data doctor` (infra health checks).

When a customer asks for a dry-run or pipeline test before full migration, offer preflight at Step 2a. Full agent guidance: [Advanced operations reference](../../../../data-infrastructure/references/advanced-operations-reference.md#preflight-workflows-bounded-migration-dry-run).

## Teradata: mixed charsets and `onUntranslatable`

**When:** Teradata extraction fails with **6701** / **5355** (mixed charsets in one row), or the customer asks how to handle **untranslatable** non-Unicode bytes during migration.

**Default:** omit `onUntranslatable` or set `"substitute"` under `defaultTableConfiguration` — untranslatable bytes become **U+FFFD** and migration continues.

**Strict mode:** per-table `"onUntranslatable": "fail"` when any untranslatable byte must abort the partition (Teradata **6706**).

Applies to **`regular`**, worker-side **TPT**, and **`write_nos`** (orchestrator-built `SELECT`; no DEA TOML keys). Detail: `dmvf/docs/data-migration-orchestrator/teradata-charset-extraction.md`.

```yaml
defaultTableConfiguration:
  onUntranslatable: substitute
  extraction:
    strategy: regular   # or write_nos + externalStage
tables:
  - source: { databaseName: ecommerce, tableName: mixed_charset_orders }
    target: { databaseName: TARGET_DB, schemaName: ECOMMERCE_TD, tableName: MIXED_CHARSET_ORDERS }
    columnNamesToPartitionBy: [order_id]
  - source: { databaseName: ecommerce, tableName: strict_audit }
    target: { databaseName: TARGET_DB, schemaName: ECOMMERCE_TD, tableName: STRICT_AUDIT }
    columnNamesToPartitionBy: [id]
    onUntranslatable: fail
```

```yaml
preflight: true
preflightKeepSchema: false
```

## Identity columns and `continueIdentityColumns`

**When:** the customer will insert new rows on Snowflake after cutover into tables whose keys come from a source identity, auto-increment or `serial` column, or asks why a new insert collides with a migrated key.

**Default:** off. Identity values are copied as ordinary data and the target's generator is left alone, so the next generated value can collide with a migrated key.

**Opt in:** `continueIdentityColumns: true` per table, or under `defaultTableConfiguration` for every table. Tables the orchestrator creates get a sequence default on each source identity column. After the final load, a cleanup task restarts each target identity or sequence-default column at `MAX(column) + 1` (empty tables keep their start value). It also covers existing targets, such as tables SnowConvert created with `IDENTITY`. It replaces the column's generator with a `<table>_<column>_IDENTITY_SEQ` sequence, so offer it only when the customer wants it; do not turn it on by default. Native targets only: Iceberg targets and preflight runs are skipped. For incremental sync it runs at the end of every workflow run. Detail: `dmvf/data-migration-orchestrator/README.md` ("Identity columns and sequences").

```yaml
defaultTableConfiguration:
  continueIdentityColumns: true
tables:
  - source: { databaseName: SALES, schemaName: dbo, tableName: Orders }
    target: { databaseName: TARGET_DB, schemaName: DBO, tableName: ORDERS }
    columnNamesToPartitionBy: [OrderId]
  - source: { databaseName: SALES, schemaName: dbo, tableName: AuditLog }
    target: { databaseName: TARGET_DB, schemaName: DBO, tableName: AUDIT_LOG }
    columnNamesToPartitionBy: [Id]
    continueIdentityColumns: false   # leave this table's generator alone
```

## TableConfiguration

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `source` | `SourceTargetIdentifier` | Yes | Source table location |
| `target` | `TargetIdentifier` | Yes | Target table location in Snowflake |
| `columnNamesToPartitionBy` | `String[]` | No | Ordered columns used to partition data during extraction. When omitted or empty, the orchestrator extracts the table as a single unit, or infers a key at preprocessing when the table is large enough. **Not used for Iceberg loading** (see Iceberg section below). |
| `extraction` | `ExtractionStrategy` | No | How data is extracted from source |
| `synchronization` | `SynchronizationStrategy` | No | Incremental sync settings. **Does not apply to Iceberg migrations.** |
| `columnTypeMappings` | `ColumnTypeMapping[]` | No | Type conversions during migration |
| `columnNameMappings` | `ColumnNameMapping[]` | No | Column renaming mappings |
| `primaryKeyColumns` | `String[]` | No | Required for `watermark` sync with `trackModifications`; also used for incremental key tracking |
| `whereClauseCriteria` | String | No | SQL filter appended after `WHERE` in the extraction query (e.g., `"is_deleted = 0"`, `"c_custkey <= 1000"`). **Do not use** `TOP` (SQL Server) or `LIMIT` (Redshift/Oracle) here — they are not valid WHERE clause syntax and cause extraction errors. Teradata: use normal predicates (e.g. `"id <= 1000"`). |
| `targetPartitionSizeMb` | Integer | No | Target partition size in MB. Mutually exclusive with `targetPartitionSizeRows`. Omit both for auto sizing. |
| `targetPartitionSizeRows` | Integer | No | Target partition size in rows. Mutually exclusive with `targetPartitionSizeMb`. Omit both for auto sizing. |
| `loadSegmentation` | Object | No | Post-upload load segmentation — splits a single `COPY INTO` into multiple statements grouped by `targetSegmentSizeMb`. |
| `loading` | Object | No | Loading strategy: `warehouse` (default, `COPY INTO`) or `snowpipe`. |
| `queryModifiers` | Object | No | SQL hints to reduce locking on busy source tables during extraction (see [Query modifiers](#query-modifiers)). |
| `intervalHandling` | `"interval"` \| `"varchar"` | No | Per-table override of top-level `intervalHandling`. |
| `onUntranslatable` | `"substitute"` \| `"fail"` | No | **Teradata only.** How non-Unicode string columns handle untranslatable bytes during extraction. Default `"substitute"`. Set under `defaultTableConfiguration` for a workflow-wide default, or per table to override. Use `"fail"` when untranslatable non-Unicode bytes must abort the partition (Error 6706) instead of substituting U+FFFD. Detail: `dmvf/docs/data-migration-orchestrator/teradata-charset-extraction.md`. |
| `executionTimeoutMinutes` | Integer | No | Wall-clock timeout in minutes for the **Analyze boundaries** DEA task only (orchestrator default is **20** when omitted). Does **not** apply to extraction or load. Use per table for large/slow boundary queries, or under `defaultTableConfiguration` to apply to all tables. |
| `continueIdentityColumns` | Boolean | No | Continue source identity / auto-increment / `serial` generators on the Snowflake target after the final load (default **false**). Per table, or under `defaultTableConfiguration` for all tables. See [Identity columns](#identity-columns-and-continueidentitycolumns). |
| `resetPartitions` | `"disabled"` \| `"enabled"` \| `"enabledWithDedup"` | No | Discard the partitions a previous workflow created for this table and repartition it on the next incremental (`checksum` / `watermark`) run (default **disabled**; `true` / `false` alias `enabled` / `disabled`). Neither value wipes the target; `enabledWithDedup` merges `watermark` tables on the primary key (not supported with Snowpipe or Iceberg). Set it for one run, then remove it. Per table, or under `defaultTableConfiguration`. Detail: `dmvf/data-migration-orchestrator/README.md` ("Resetting partitions"). |

## SourceTargetIdentifier

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `databaseName` | String | Yes | Database name |
| `schemaName` | String | Yes\* | Schema name |
| `tableName` | String | Yes | Table name. Case-sensitive names must be quoted: `"\"MyCaseSensitiveTable\""` |

\* For **Teradata** sources, omit `source.schemaName` — Teradata is `database.table` (no schema layer). Align `databaseName` with `[connections.source.teradata].database` in worker TOML. Snowflake **target** still requires `schemaName`.

## TargetIdentifier

Extends `SourceTargetIdentifier` with optional Iceberg fields.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `databaseName` | String | Yes | Database name |
| `schemaName` | String | Yes | Schema name (always required on Snowflake targets, including Teradata migrations) |
| `tableName` | String | Yes | Table name |
| `tableType` | `"native"` \| `"iceberg"` | No | Target table format. Defaults to `"native"`. **`"iceberg"` is allowed for any source dialect, but only when the source object is fully relational** — never when the source is itself an Iceberg / external table. |
| `icebergConfig` | `IcebergConfig` | When `tableType` is `"iceberg"` | Iceberg-specific configuration (see below) |

## IcebergConfig

> **Scope:** End-to-end Iceberg migration goes **relational source → Snowflake-managed Iceberg** via
> `copy_files` (the source's cloud/server extraction strategy writes Parquet to a stage; Snowflake loads
> it). It is available for every supported source dialect **only when the source object is a fully
> relational table**. **Do not set `tableType: iceberg` when the source is itself an Iceberg / external /
> catalog-backed table — stop instead.** The `catalog_link` / `convert_to_managed` strategies below adopt
> data that is already Iceberg and are therefore **out of scope** under this rule.

Configuration for Iceberg table targets. Required when `tableType` is `"iceberg"`.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `catalog` | String | Yes | Must be `"SNOWFLAKE"` — Snowflake-managed catalog is the only released shape. |
| `icebergSpec` | String | Yes | Iceberg format version. `"v2"` or `"v3"`. `scai data migrate generate-config --iceberg` writes `<ICEBERG_SPEC>`. |
| `storageMode` | String | Yes | `"compatible"` with spec `v2` or `v3`, or `"native"` with spec `v3` only. generate-config writes `<STORAGE_MODE>`. Both the orchestrator and `scai data migrate create-workflow` accept `native` + `v3`. `native` with `v2` is rejected. |
| `loadMode` | String | Yes | `"ADD_FILES_COPY"` or `"FULL_INGEST"`. generate-config writes `<LOAD_MODE>`. |
| `externalVolume` | String | Yes | Name of the Snowflake external volume. Use `"SNOWFLAKE_MANAGED"` for Snowflake-managed storage. |
| `baseLocationPrefix` | String | Required unless `externalVolume` is `"SNOWFLAKE_MANAGED"` | Prefix for the table's `BASE_LOCATION` path. **Must be omitted** when `externalVolume` is `"SNOWFLAKE_MANAGED"`. |
| `migrationStrategy` | `"copy_files"` | No | Omit it (auto-resolves to `copy_files`), or set `"copy_files"` explicitly. `catalog_link` / `convert_to_managed` are not part of the released shape. |

> **Official Iceberg shape — enforced by `scai data migrate create-workflow`.** The CLI gate
> (`IcebergOfficialProfile.ValidateWorkflowConfig`) rejects the workflow before the orchestrator starts
> unless every Iceberg table's effective `icebergConfig` is a released shape: `catalog: SNOWFLAKE`,
> `externalVolume` present, and the `baseLocationPrefix` rule above. `icebergSpec` is `v2` or `v3`
> with `storageMode: compatible`, or `v3` with `storageMode: native`. `loadMode` is `ADD_FILES_COPY`
> or `FULL_INGEST` (`postLoadOptimize` may be set; the orchestrator defaults it per load mode).
> generate-config writes `<ICEBERG_SPEC>`, `<STORAGE_MODE>`, and `<LOAD_MODE>` for the user to fill.
> `catalog`, `icebergSpec`, `storageMode`, and `loadMode` are **required** — an omitted one fails
> (DMVF's own defaults do not count as approval). The orchestrator accepts the same `native` + `v3`
> pair and rejects `native` with spec `v2` or with `externalEngineAccess`. The following keys must be
> **absent**: `sourceDataStage`, `catalogTableName`, `catalogSync`, `externalEngineAccess`.
> `synchronization.strategy` must be `none` or `full-replace` (incremental is not released for Iceberg).
> Set these once on `defaultTableConfiguration.target.icebergConfig`; they are inherited by every table.
>
> **`migrate_data(mode="setup")` writes this block** when `target_table_type=iceberg`: `tableType: iceberg`
> and `icebergConfig` on `defaultTableConfiguration.target` (creating `defaultTableConfiguration` when the
> workflow has none), with `catalog: SNOWFLAKE`. It fills only what the user has decided and leaves the rest
> as generate-config's placeholders:
>
> - `icebergSpec` / `loadMode`: the persisted `iceberg_spec` / `load_mode`; else a valid value already in the
>   YAML; else `<ICEBERG_SPEC>` / `<LOAD_MODE>`.
> - `storageMode`: `compatible` with spec `v2` (the only legal pair); otherwise a `compatible` or `native`
>   already in the YAML; else `<STORAGE_MODE>`.
> - `externalVolume` / `baseLocationPrefix`: the value already in the YAML, else `<EXTERNAL_VOLUME>` /
>   `<BASE_LOCATION_PREFIX>` (no prefix for `SNOWFLAKE_MANAGED`).
>
> Fill every placeholder left (ask the user; a spec or load mode can instead be set with
> `migrate_data(mode="setup", iceberg_spec=..., load_mode=...)`). `migrate_data(mode="run")` refuses a
> workflow whose Iceberg table still has one. A setup re-run re-applies the persisted spec and load mode
> and keeps every other value filled by hand (a `native` storage mode becomes `compatible` once the spec is
> `v2`). `target_table_type=native` removes the block.

### Strategy Auto-Detection

When `migrationStrategy` is omitted, the orchestrator resolves it based on the `catalog` value:

| `catalog` Value | Auto-Detected Strategy |
|-----------------|------------------------|
| Not `"SNOWFLAKE"` (e.g. a Glue integration) | `catalog_link` |
| `"SNOWFLAKE"` | `copy_files` |

> To use `convert_to_managed`, you **must** set `migrationStrategy` explicitly — auto-detection defaults to `catalog_link` for external catalogs.

### IcebergConfig Validation Rules

| Rule | Error When Violated |
|------|---------------------|
| `tableType` must be `"native"` or `"iceberg"` | `ConfigurationError` |
| `icebergConfig` is required when `tableType` is `"iceberg"` | `ConfigurationError` |
| `externalVolume` is required when `catalog` is `"SNOWFLAKE"` | `ConfigurationError` |
| `catalogTableName` is required when `catalog` is not `"SNOWFLAKE"` | `ConfigurationError` |
| `migrationStrategy` must be one of the three valid values | `ValueError` |

### IcebergConfig Inheritance

The `icebergConfig` at the table level is **merged** with `defaultTableConfiguration.target.icebergConfig`. Table-level keys override default keys. Set common values (like `externalVolume`) in the defaults and only specify per-table values (like `catalogTableName`) on each table entry.

### Iceberg Strategy Comparison

| Strategy | Data Movement | DML on Target | Primary Use Case |
|----------|---------------|---------------|------------------|
| `catalog_link` | None (zero-copy) | Read-only | Quick access to existing Iceberg data without copying — **source is already Iceberg → out of scope, do not continue** |
| `convert_to_managed` | None (zero-copy) | Full DML | Take ownership of existing Iceberg data without rewriting files — **source is already Iceberg → out of scope, do not continue** |
| `copy_files` | Server-side binary copy | Full DML | **Supported path:** create a new Snowflake-managed Iceberg table from a **relational** source's staged Parquet files |

## ExtractionStrategy

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `strategy` | `"regular"` \| `"unload"` \| `"write_nos"` \| `"dbms_cloud"` \| `"cet_as"` \| `"export_data"` \| `"cloud_direct"` | Yes | `"regular"` is the default. `"unload"` is Redshift-only, `"write_nos"` Teradata-only, `"dbms_cloud"` Oracle-only, `"export_data"` BigQuery-only; `"cet_as"` is SQL Server and Azure Synapse; `"cloud_direct"` is every dialect except BigQuery. `"tpt"` is accepted as a legacy alias for `"regular"` (TPT is selected from the worker's `tpt_*` fields, not here). Per-dialect setup: [extraction-strategies-reference.md](./extraction-strategies-reference.md) and [`worker-config-reference.md`](../../../../data-infrastructure/references/worker-config-reference.md). |
| `externalStage` | String | Every strategy except `regular` (and its `tpt` alias) | Snowflake external stage (e.g. `MY_DB.MY_SCHEMA.S3_STAGE`), exactly three identifier segments. Omitting it fails workflow parsing, not the run. |

```yaml
extraction:
  strategy: regular

extraction:
  strategy: unload
  externalStage: MY_DB.MY_SCHEMA.S3_EXTERNAL_STAGE

extraction:
  strategy: dbms_cloud
  externalStage: MY_DB.MY_SCHEMA.S3_EXTERNAL_STAGE
```

## SynchronizationStrategy

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `strategy` | `"none"` \| `"full-replace"` \| `"checksum"` \| `"watermark"` | Yes | Sync strategy (default `none`) |
| `checksumExpression` | String | When `strategy` is `checksum` | Source SQL expression used to detect changed partitions (for example `MAX(ORA_ROWSCN)`). Must not contain `;`. |
| `watermarkColumn` | String | When `strategy` is `watermark` | Monotonic column used for incremental filtering |
| `trackModifications` | Boolean | No | When `true` with `watermark`, detect updated rows (requires `primaryKeyColumns`) |
| `trackDeletions` | Boolean | No | When `true` with `watermark`, detect deleted rows (requires `primaryKeyColumns`) |

| Strategy | Description | Best for |
|----------|-------------|----------|
| `none` (default) | Full extraction every run; rows are **appended** to the target | One-time loads, or tables you will not re-migrate without clearing the target first |
| `full-replace` | Like `none`, but each partition's target rows are **deleted before loading** so a re-run overwrites instead of appending | Repeatable full reloads where the whole table (or partition) should be replaced each run, without needing a monotonic/change-tracking column. Works for every supported source dialect (the delete runs on the Snowflake target). |
| `checksum` | Hash all column values per partition; re-extract changed partitions only | Dimension tables without a monotonic column. **Oracle:** built-in partition checksum is supported (`STANDARD_HASH` over normalized columns); optional `checksumExpression` (for example `MAX(ORA_ROWSCN)`) overrides the default hash. Some Oracle types are excluded from the default hash — see checksum type coverage below. |
| `watermark` | Track a monotonic column; sync only rows newer than the last observed value | Fact tables, event logs with a reliable `UPDATED_AT` / ID column |

> **Re-running without incremental sync:** With `strategy: none` (or no `synchronization` block), every migration run extracts and loads **all** matching rows again. Re-running the same workflow against a target that already holds data from a prior run **appends duplicate rows** (or loads more data than expected). Use `full-replace` to have each run delete the target partition before loading (clean overwrite, no duplicates), or `watermark` / `checksum` for repeatable incremental runs. Do **not** `TRUNCATE` or bulk-`DELETE` the target manually without explicit user confirmation — the table may legitimately contain pre-existing or expected rows.

> **Checksum type coverage:** Built-in partition checksums **skip or normalize** some types (SQL Server `text`/`ntext`/`image`; Oracle LOBs/`LONG`/`XMLTYPE`/`VECTOR`; float rounding; spatial WKT; Redshift `HLLSKETCH`). Changes only in those columns may **not** change the checksum — no re-extract on the next run. Custom `checksumExpression` (for example `MAX(ORA_ROWSCN)`) only reflects what that expression measures. See [Advanced operations reference](../../../../data-infrastructure/references/advanced-operations-reference.md#checksum--incremental-sync--types-that-may-not-trigger-re-sync).

```yaml
synchronization:
  strategy: none

synchronization:
  strategy: checksum
  checksumExpression: MAX(ORA_ROWSCN)

synchronization:
  strategy: watermark
  watermarkColumn: UPDATED_AT

synchronization:
  strategy: watermark
  watermarkColumn: UPDATED_AT
  trackModifications: true
  trackDeletions: true
  primaryKeyColumns:
    - CUSTOMER_ID
```

## LoadSegmentation

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `targetSegmentSizeMb` | Integer | Yes | Maximum staged-file group size (MB) per `COPY INTO` statement |

## Loading

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `strategy` | `"warehouse"` \| `"snowpipe"` | No | `warehouse` uses `COPY INTO` (default). `snowpipe` uses Snowpipe auto-ingest. |

## Query modifiers

Reduce locking on busy source tables during extraction. Can be set at the connection layer (worker TOML), workflow default (`defaultTableConfiguration.queryModifiers`), or per table (`tables[].queryModifiers`). Modifiers apply to source queries only — Snowflake target queries never receive them.

| Property | Type | Description |
|----------|------|-------------|
| `objectModifier` | String | Hint applied after the source table in `FROM` (for example ` WITH (NOLOCK)` on SQL Server) |
| `selectModifier` | String | String rendered immediately after `SELECT` in every source query for that table or connection (for example `"/*+ INDEX(t idx_orders_created_at) */"`). Use `"NONE"` to disable (see below). |

```yaml
queryModifiers:
  objectModifier: " WITH (NOLOCK)"
  selectModifier: " /*+ FIRST_ROWS(100) */"
```

### selectModifier

#### Configured value

`selectModifier` is a string literal that DMVF renders immediately after `SELECT` in every source query for that table or connection. The resolver ensures a leading space separator between `SELECT` and the modifier; you do not need to include one in the configured value.

```yaml
# Per-table: apply an Oracle index hint on every extraction SELECT for this table.
# Rendered: SELECT /*+ INDEX(t idx_orders_created_at) */ "COL1", ... FROM "HR"."ORDERS" t ...
tables:
  - source:
      databaseName: ORCL
      schemaName: HR
      tableName: ORDERS
    queryModifiers:
      selectModifier: " /*+ INDEX(t idx_orders_created_at) */"
```

On the DM base-path (extraction, partition-boundary, checksum, watermark probes), DMVF aliases the source table as `t`. Hints referencing the alias should use `t` on this path.

#### Oracle auto-hint

When all three conditions hold, DMVF auto-generates `/*+ PARALLEL(t, N) */` after `SELECT`:

1. The source platform is Oracle.
2. `selectModifier` is not configured at any layer (connection, workflow default, or per-table).
3. The estimated row count yields a computed parallel degree greater than 2.

The degree formula:

```text
N = min(2 ^ max(floor(log10(row_count + 1)) - 6, 0), 16)
```

The hint fires only when the computed degree exceeds 2. In practice this means tables of ~100 million rows or more; smaller tables produce degree 1 or 2, which the resolver treats as "no auto-hint" and renders a plain `SELECT`. When the row-count estimate is unavailable (None) the hint also does not fire.

```yaml
# Oracle source, selectModifier omitted, estimated rows = 120M → degree 4
# Rendered: SELECT /*+ PARALLEL(t, 4) */ "COL1", ... FROM "HR"."ORDERS" t
tables:
  - source:
      databaseName: ORCL
      schemaName: HR
      tableName: ORDERS
    # queryModifiers omitted → Oracle auto-hint fires if row count is large enough
```

Auto-hint fires on every DM source-SELECT path: extraction, checksum probes, watermark probes, and partition-boundary queries. It does not fire on Snowflake-target queries.

#### `"NONE"` opt-out sentinel

Setting `selectModifier: "NONE"` (exact, case-sensitive, upper-case) disables both the configured modifier and the Oracle auto-hint for that table or connection. The rendered `SELECT` has no modifier token.

The sentinel is case-sensitive. `"none"` and `"None"` are **not** opt-outs — they become literal `selectModifier` values rendered into the SQL as-is.

```yaml
# Disable Oracle auto-hint on one table while leaving other tables unrestricted.
tables:
  - source:
      databaseName: ORCL
      schemaName: HR
      tableName: NO_PARALLEL_TABLE
    queryModifiers:
      selectModifier: "NONE"
      # Rendered: SELECT "COL1", ... FROM "HR"."NO_PARALLEL_TABLE" t
```

#### Precedence

The most-specific non-null value wins across the three config layers:

| Layer | Most specific? | Set in |
|-------|----------------|--------|
| `tables[].queryModifiers.selectModifier` | Highest | Workflow YAML per-table |
| `defaultTableConfiguration.queryModifiers.selectModifier` | Middle | Workflow YAML default |
| Connection `query_modifiers.selectModifier` | Lowest | Worker TOML (see [`worker-config-reference.md`](../../../../data-infrastructure/references/worker-config-reference.md)) |

An explicit `null` at a higher-specificity layer falls through to the next layer — it does **not** clear an upstream value. To override a connection-layer or workflow-default `selectModifier` for a specific table, set the per-table `selectModifier` to the desired value (or to `"NONE"` to opt out entirely). Setting it to `null` leaves the upstream value in effect.

```yaml
# Connection layer (worker TOML): selectModifier = " /*+ INDEX(t idx_orders_created_at) */"
# Workflow default: unset (null) → falls through to connection
# Per-table override on ORDERS: "NONE" → opt out for this table only
defaultTableConfiguration:
  queryModifiers:
    selectModifier: null          # falls through; connection-layer value applies to most tables

tables:
  - source:
      databaseName: ORCL
      schemaName: HR
      tableName: ORDERS
    queryModifiers:
      selectModifier: "NONE"      # opts out; plain SELECT for this table
  - source:
      databaseName: ORCL
      schemaName: HR
      tableName: EMPLOYEES
    # queryModifiers omitted → connection-layer hint applies
```

See also: `dmvf/docs/data-migration-orchestrator/features/QueryModifiersAntiLockingSpec.md` §8 for the DMVA parity degree formula.

## Partition sizing and key selection

- **Auto mode:** omit both `targetPartitionSizeMb` and `targetPartitionSizeRows`. The orchestrator picks platform-appropriate defaults.
- **Explicit sizing:** set exactly one of `targetPartitionSizeMb` or `targetPartitionSizeRows`.
- **`columnNamesToPartitionBy`:** optional. Prefer a column (or ordered list) the source can prune on for large tables. When omitted or empty, the orchestrator extracts the table as a single unit, or infers a key at preprocessing when the table is large enough — review `partition_key_findings` from setup. `[]` is not "skip the table"; data still moves as one slice.
- **`executionTimeoutMinutes`:** optional wall-clock limit for **Analyze boundaries** only (default 20). Raise it when NTILE/boundary analysis on large tables exceeds 20 minutes; prefer a cheaper partition key when possible.
- **Deprecated:** do not use legacy `partitionSize: auto` — use the flat `targetPartitionSizeMb` / `targetPartitionSizeRows` fields instead.

### Composite partition keys

`columnNamesToPartitionBy` is an **ordered list**. The orchestrator sorts and splits on the tuple (lexicographic NTILE), so order matters.

- When the leading prune column (sort key, clustered index, partition key, clustering key, …) has too few distinct values for balanced slices, **keep it first** and append the remaining columns of that physical key in catalog order (for example the rest of a Redshift compound sort key, or further Oracle partition-key columns).
- If cardinality is still too low, append a high-cardinality column such as the primary key: `[sale_date, id]`. On Teradata, prefer `[<RANGE_N column>, <PI column>]` when a daily/monthly partitioning column collapses NTILE buckets. On PostgreSQL, prefer `[<partition column>, <pk column>]` when a daily/monthly partition key collapses NTILE buckets.
- Present the candidates to the user before writing the key.
- The Doctor measures cardinality on the **leading** column only, so a low-cardinality warning on that column is expected for a composite key and does not mean the composite is wrong.

### Oracle

Prefer, in order: the table's physical partition key (`ALL_PART_KEY_COLUMNS`, via `query_source` or a `Partition prune:` finding), then an index-organized table (IOT) primary key, then a heap primary key or unique constraint. Leave the field empty to let the orchestrator infer (including `ROWID` only for a one-time full extract with sync `none` on a heap table with no better key). On a low-cardinality partition key, use a composite of the partition key and the PK.

### Teradata

Prefer, in order: the level-1 `RANGE_N(<bare column> BETWEEN ...)` column from `DBC.PartitioningConstraintsV` (via a `Partition prune:` finding or inference), then the primary index (`DBC.IndicesV` types `P` / `Q`). The PI hashes rows onto AMPs — a range filter on the PI does **not** prune; only row partitioning does. Leave the field empty to let the orchestrator infer. Skip expression `RANGE_N` (for example `EXTRACT(...)`) and `CASE_N` as prune columns. On a low-cardinality partitioning date, use a composite `[partitioning column, PI column]`. Verify pruning with `EXPLAIN` on a generated partition predicate — look for `n partitions of`, not an all-AMP scan.

### PostgreSQL

Prefer, in order: the declared partition key (`pg_partitioned_table.partattrs`, bare columns only — skip expression keys), then a valid non-partial minmax/minmax-multi BRIN column whose `pg_stats` shows `abs(correlation) >= 0.9`, `null_frac = 0`, and fresh stats (`n_mod_since_analyze` within 20% of live rows), then the leading column of the `indisclustered` index, then the primary key / unique index. Leave the field empty to let the orchestrator infer. Avoid `ctid`. When BRIN is skipped for missing or weak stats, running `ANALYZE <table>` on the source can re-enable it on the next inference. Verify with `query_source` against `pg_partitioned_table`, `pg_index` / `pg_am`, and `pg_stats`. On a low-cardinality partition date, use a composite `[partition column, pk column]`.

## ColumnTypeMapping

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `sourceType` | String | Yes | Type name in the source system |
| `targetType` | String | Yes | Target type name in Snowflake |

## ColumnNameMapping

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `sourceName` | String | Yes | Column name in source |
| `targetName` | String | Yes | Column name in Snowflake |

---

## Iceberg Workflow Examples

### Example: Catalog Link (Zero-Copy, Read-Only)

```yaml
defaultTableConfiguration:
  columnNamesToPartitionBy:
    - "1"    # Required by CLI validator, not used for Iceberg loading
  source:
    schemaName: iceberg_tpch
    databaseName: ecommerce_db
  target:
    schemaName: public
    databaseName: TARGET_DB
    tableType: iceberg
    icebergConfig:
      catalog: my_glue_catalog_integration
      externalVolume: my_iceberg_ext_vol

tables:
  - source:
      tableName: region
    target:
      tableName: region
      icebergConfig:
        catalogTableName: region    # Bare name — namespace prepended from CATALOG_NAMESPACE
  - source:
      tableName: nation
    target:
      tableName: nation
      icebergConfig:
        catalogTableName: nation    # Bare name — namespace prepended from CATALOG_NAMESPACE
```

Generated DDL (per table):

```sql
CREATE OR REPLACE ICEBERG TABLE TARGET_DB.PUBLIC.region
  CATALOG = 'my_glue_catalog_integration'
  CATALOG_TABLE_NAME = 'iceberg_tpch.region'
  EXTERNAL_VOLUME = 'my_iceberg_ext_vol'
```

### Example: Convert to Managed (Zero-Copy, Full DML)

```yaml
defaultTableConfiguration:
  columnNamesToPartitionBy:
    - "1"    # Required by CLI validator, not used for Iceberg loading
  source:
    schemaName: iceberg_tpch
    databaseName: ecommerce_db
  target:
    schemaName: public
    databaseName: TARGET_DB
    tableType: iceberg
    icebergConfig:
      catalog: my_glue_catalog_integration
      externalVolume: my_iceberg_ext_vol

tables:
  - source:
      tableName: orders
    target:
      tableName: orders
      icebergConfig:
        catalogTableName: orders    # Bare name — namespace prepended automatically
        migrationStrategy: convert_to_managed
```

Generated DDL:

```sql
-- Step 1: Create catalog-linked table
CREATE OR REPLACE ICEBERG TABLE TARGET_DB.PUBLIC.orders
  CATALOG = 'my_glue_catalog_integration'
  CATALOG_TABLE_NAME = 'iceberg_tpch.orders'
  EXTERNAL_VOLUME = 'my_iceberg_ext_vol'

-- Step 2: Convert to Snowflake-managed
ALTER ICEBERG TABLE TARGET_DB.PUBLIC.orders CONVERT TO MANAGED
```

> You **must** set `migrationStrategy: convert_to_managed` explicitly — auto-detection defaults to `catalog_link` for external catalogs.

### Example: Copy Files (Server-Side Binary Copy)

```yaml
defaultTableConfiguration:
  columnNamesToPartitionBy:
    - "1"    # Required by CLI validator, not used for Iceberg loading
  source:
    schemaName: public
    databaseName: analytics_db
  target:
    schemaName: public
    databaseName: TARGET_DB
    tableType: iceberg
    icebergConfig:
      catalog: SNOWFLAKE
      icebergSpec: v2
      storageMode: compatible
      loadMode: ADD_FILES_COPY
      externalVolume: my_iceberg_ext_vol
      baseLocationPrefix: migrations/redshift
  extraction:
    strategy: unload
    externalStage: TARGET_DB.PUBLIC.S3_EXTERNAL_STAGE
  targetPartitionSizeMb: 512

tables:
  - source:
      tableName: customers
    target:
      tableName: customers
```

Generated DDL and DML:

```sql
-- Step 1: Infer schema from Parquet files
SELECT * FROM TABLE(
  INFER_SCHEMA(
    LOCATION => '@TARGET_DB.PUBLIC.ICEBERG_SOURCE_STAGE',
    FILE_FORMAT => 'PARQUET'
  )
);

-- Step 2: Create the Iceberg table
CREATE ICEBERG TABLE TARGET_DB.PUBLIC.customers (col1 NUMBER(38,0), col2 VARCHAR, ...)
  CATALOG = 'SNOWFLAKE'
  EXTERNAL_VOLUME = 'my_iceberg_ext_vol'
  BASE_LOCATION = 'migrations/redshift/TARGET_DB/PUBLIC/customers'

-- Step 3: Binary copy of Parquet files
COPY INTO TARGET_DB.PUBLIC.customers
  FROM '@TARGET_DB.PUBLIC.ICEBERG_SOURCE_STAGE'
  LOAD_MODE = ADD_FILES_COPY
  MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
  PATTERN = '.*\.parquet'
```

### Example: Mixed Strategies (Native + Iceberg in One Workflow)

```yaml
defaultTableConfiguration:
  columnNamesToPartitionBy:
    - "1"    # Required by CLI validator
  source:
    schemaName: public
    databaseName: analytics_db
  target:
    schemaName: public
    databaseName: TARGET_DB
    tableType: iceberg
    icebergConfig:
      catalog: SNOWFLAKE
      icebergSpec: v2
      storageMode: compatible
      loadMode: ADD_FILES_COPY
      externalVolume: my_iceberg_ext_vol
      baseLocationPrefix: migrations/redshift
  targetPartitionSizeMb: 512

tables:
  # copy_files — inherits default icebergConfig (catalog=SNOWFLAKE)
  - source:
      tableName: customers
    target:
      tableName: customers

  # catalog_link — overrides to external catalog
  - source:
      tableName: events
    target:
      tableName: events
      tableType: iceberg
      icebergConfig:
        catalog: my_glue_catalog_integration
        externalVolume: my_iceberg_ext_vol
        catalogTableName: events    # Bare name — namespace prepended from CATALOG_NAMESPACE

  # convert_to_managed — explicit strategy override
  - source:
      tableName: orders
    target:
      tableName: orders
      tableType: iceberg
      icebergConfig:
        catalog: my_glue_catalog_integration
        externalVolume: my_iceberg_ext_vol
        catalogTableName: orders    # Bare name — namespace prepended automatically
        migrationStrategy: convert_to_managed
```

---

## Iceberg Data Type Mapping Reference

DMVF picks the Iceberg column types itself from the effective `icebergConfig`
(`TypeMappingLoader` → `build_iceberg_mappings` in
`dmvf/data-migration-orchestrator/src/data_migration_orchestrator/data_migration_core/type_mappings/iceberg_mappings.py`).
The mapping depends on the **profile**, `(icebergSpec, loadMode)`; `storageMode` is always `compatible`:

- **VARCHAR-temporal profiles**: `ADD_FILES_COPY` (v2 or v3), and `FULL_INGEST` on `v2`. DMVF maps
  temporal and geospatial columns to `VARCHAR`, matching the string footers the extractor writes.
  How the files are loaded still follows the load mode: `ADD_FILES_COPY` registers the staged
  Parquet unchanged, while `FULL_INGEST` (on either spec) loads through the transform COPY and
  rewrites it into new files; on v2 that rewrite keeps the `VARCHAR` targets.
- **`icebergSpec: v3` + `loadMode: FULL_INGEST`**: the transform COPY casts the staged values
  (`TO_TIMESTAMP_*`, `TO_TIME`, `TO_GEOGRAPHY`, `TO_GEOMETRY`), so temporal and geospatial columns keep
  native Iceberg types. FULL_INGEST is accepted only for Redshift `unload`, SQL Server `cet_as` /
  `cloud_direct` / `regular`, and Teradata `write_nos` (or a `sourceDataStage` table on those sources).

### Default Iceberg Target Types by Profile

| Source type family (examples) | VARCHAR-temporal profiles | v3 + `FULL_INGEST` |
|---|---|---|
| Small integers (`SMALLINT`, `INT`, `INTEGER`, `TINYINT`) | `INTEGER` | `INTEGER` |
| Big integers (`BIGINT`, `INT8`) | `BIGINT` | `BIGINT` |
| Floats (Redshift `REAL` / `FLOAT4` / `FLOAT8`, SQL Server `FLOAT` / `REAL`, Teradata `FLOAT`) | `DOUBLE` | `DOUBLE` |
| `DECIMAL(p,s)`, `NUMERIC`, `MONEY` | Native `NUMBER(p,s)` | Native `NUMBER(p,s)` |
| `CHAR` / `VARCHAR` / `NVARCHAR` | `VARCHAR` | `VARCHAR` |
| `BOOLEAN`, `DATE` | Unchanged | Unchanged |
| Redshift / Teradata `TIMESTAMP`, SQL Server `DATETIME` / `DATETIME2` / `SMALLDATETIME` | `VARCHAR` | `TIMESTAMP_NTZ(6)` |
| `TIMESTAMPTZ`, `DATETIMEOFFSET`, `TIMESTAMP WITH TIME ZONE`, Redshift `TIMETZ`, Teradata `TIME WITH TIME ZONE` | `VARCHAR` | `TIMESTAMP_LTZ(6)` (Iceberg has no `TIMESTAMP_TZ`; LTZ keeps the instant) |
| `TIME` | `VARCHAR` | `TIME(6)` |
| `GEOGRAPHY` (Teradata `ST_GEOMETRY` maps here) | `VARCHAR` | `GEOGRAPHY` |
| `GEOMETRY` | `VARCHAR` | `GEOMETRY(4326)`, or `GEOMETRY(n)` for an explicit non-zero SRID |
| Redshift `VARBYTE` / `VARBINARY` | `VARCHAR` | `VARCHAR` |
| SQL Server `BINARY` / `VARBINARY` / `IMAGE`, and `TIMESTAMP` / `ROWVERSION` (a binary row version, not a date) | `BINARY` | `BINARY` |
| Semi-structured (`SUPER`, `VARIANT`, `SQL_VARIANT`, `XML`, `JSON`, `ARRAY`, `OBJECT`), `INTERVAL*` | `VARCHAR` | `VARCHAR` |

Timestamps use scale 6 under v3 `FULL_INGEST`: it covers the full date range (`NTZ(9)` cannot hold years
before 1677).

**Do not add `columnTypeMappings` to flatten temporal or geospatial columns.** A `columnTypeMappings`
entry replaces DMVF's profile default for that source type, so `GEOMETRY → VARCHAR` on a v3
`FULL_INGEST` workflow throws away the native `GEOMETRY` column DMVF would have created. Only override a
type when the user asks for a different target.

### Redshift Iceberg (Glue) → Snowflake Iceberg

| Glue/Iceberg Type | Snowflake Iceberg Type | Notes |
|---|---|---|
| `boolean` | `BOOLEAN` | |
| `int` | `NUMBER(10,0)` | 32-bit integer |
| `bigint` / `long` | `NUMBER(19,0)` | 64-bit integer |
| `float` | `FLOAT` | |
| `double` | `DOUBLE` | |
| `decimal(p,s)` | `DECIMAL(p,s)` | |
| `string` | `VARCHAR` | |
| `binary` | `BINARY` | |
| `date` | `DATE` | |
| `timestamp` | `TIMESTAMP_NTZ` | |
| `timestamptz` | `TIMESTAMP_LTZ` | |
| `list<T>` | Not supported | Flatten or convert to `VARCHAR` (JSON) |
| `map<K,V>` | Not supported | Convert to `VARCHAR` (JSON) |
| `struct<...>` | Not supported | Convert to `VARCHAR` (JSON) |
