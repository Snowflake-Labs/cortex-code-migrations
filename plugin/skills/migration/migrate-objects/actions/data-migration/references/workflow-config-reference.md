# Workflow YAML Configuration Reference

## Top-Level Properties

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `tables` | `TableConfiguration[]` | Yes | Tables to migrate |
| `defaultTableConfiguration` | `TableConfiguration` | No | Shared defaults inherited by all tables |
| `affinity` | String | No | Only orchestrator and worker instances with a matching affinity will process this workflow. If the SPCS orchestrator was started with a specific affinity (visible in service logs as `Orchestrator affinity: <value>`), the workflow **must** set the same value or it will be silently skipped. The worker's `[application].affinity` must also match. Omit from all sides for fresh setups. |

## TableConfiguration

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `source` | `SourceTargetIdentifier` | Yes | Source table location |
| `target` | `TargetIdentifier` | Yes | Target table location in Snowflake |
| `columnNamesToPartitionBy` | `String[]` | Yes (native) | Columns used to partition data during extraction. **Not used for Iceberg loading** (see Iceberg section below). |
| `extraction` | `ExtractionStrategy` | No | How data is extracted from source |
| `synchronization` | `SynchronizationStrategy` | No | Incremental sync settings. **Does not apply to Iceberg migrations.** |
| `columnTypeMappings` | `ColumnTypeMapping[]` | No | Type conversions during migration |
| `columnNameMappings` | `ColumnNameMapping[]` | No | Column renaming mappings |
| `primaryKeyColumns` | `String[]` | No | Required for `watermark` sync with `trackModifications` |
| `whereClauseCriteria` | String | No | SQL filter appended after `WHERE` in the extraction query (e.g., `"is_deleted = 0"`, `"c_custkey <= 1000"`). **Do not use** `TOP` (SQL Server) or `LIMIT` (Redshift) here — they are not valid WHERE clause syntax and cause extraction errors. |

## SourceTargetIdentifier

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `databaseName` | String | Yes | Database name |
| `schemaName` | String | Yes | Schema name |
| `tableName` | String | Yes | Table name. Case-sensitive names must be quoted: `"\"MyCaseSensitiveTable\""` |

## TargetIdentifier

Extends `SourceTargetIdentifier` with optional Iceberg fields.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `databaseName` | String | Yes | Database name |
| `schemaName` | String | Yes | Schema name |
| `tableName` | String | Yes | Table name |
| `tableType` | `"native"` \| `"iceberg"` | No | Target table format. Defaults to `"native"`. Set to `"iceberg"` to create an Iceberg table. |
| `icebergConfig` | `IcebergConfig` | When `tableType` is `"iceberg"` | Iceberg-specific configuration (see below) |

## IcebergConfig

Configuration for Iceberg table targets. Required when `tableType` is `"iceberg"`.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `catalog` | String | No | `"SNOWFLAKE"` (default) for Snowflake-managed Iceberg, or the name of a catalog integration (e.g. a Glue integration) |
| `externalVolume` | String | When `catalog` is `"SNOWFLAKE"` | Name of the Snowflake external volume |
| `baseLocationPrefix` | String | No | Prefix for the table's `BASE_LOCATION` path. Only applies when `catalog` is `"SNOWFLAKE"`. |
| `catalogTableName` | String | When `catalog` is not `"SNOWFLAKE"` | Table name in the external catalog. **If the catalog integration has `CATALOG_NAMESPACE` set, use the bare table name only** (e.g., `"customer"`). The namespace is prepended automatically. Using `"namespace.table"` will cause a double-prefix error. |
| `catalogSync` | String | No | Catalog integration name to sync Snowflake-managed metadata back to (for dual-engine access) |
| `sourceDataStage` | String | No | Stage path (must start with `@`) pointing to existing Parquet files. Only applies when `catalog` is `"SNOWFLAKE"`. |
| `migrationStrategy` | `"catalog_link"` \| `"convert_to_managed"` \| `"copy_files"` | No | Iceberg migration strategy. Auto-detected when omitted (see below). |

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
| `catalog_link` | None (zero-copy) | Read-only | Quick access to existing Iceberg data without copying |
| `convert_to_managed` | None (zero-copy) | Full DML | Take ownership of existing Iceberg data without rewriting files |
| `copy_files` | Server-side binary copy | Full DML | Create a new Snowflake-managed Iceberg table from staged Parquet files |

## ExtractionStrategy

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `strategy` | `"regular"` \| `"unload"` | Yes | `"regular"` is the default. `"unload"` is Redshift-only. |
| `externalStage` | String | UNLOAD only | Snowflake external stage (e.g. `MY_DB.MY_SCHEMA.S3_STAGE`) |

```yaml
extraction:
  strategy: regular

extraction:
  strategy: unload
  externalStage: MY_DB.MY_SCHEMA.S3_EXTERNAL_STAGE
```

## SynchronizationStrategy

| Strategy | Description | Best for |
|----------|-------------|----------|
| `none` (default) | Full extraction every run | Small tables or unpredictable changes |
| `checksum` | Hash all column values per partition; re-extract changed partitions only | Dimension tables without a monotonic column |
| `watermark` | Track a monotonic column; sync only rows newer than the last observed value | Fact tables, event logs with a reliable `UPDATED_AT` / ID column |

```yaml
synchronization:
  strategy: none

synchronization:
  strategy: checksum

synchronization:
  strategy: watermark
  watermarkColumn: UPDATED_AT

synchronization:
  strategy: watermark
  watermarkColumn: UPDATED_AT
  trackModifications: true
```

> **Note**: Watermark cannot currently track deletions.

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
      externalVolume: my_iceberg_ext_vol
      baseLocationPrefix: migrations/redshift
      sourceDataStage: "@TARGET_DB.PUBLIC.ICEBERG_SOURCE_STAGE"
  extraction:
    strategy: unload
    externalStage: TARGET_DB.PUBLIC.S3_EXTERNAL_STAGE
  partitionSize: auto

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
      externalVolume: my_iceberg_ext_vol
      baseLocationPrefix: migrations/redshift
      sourceDataStage: "@TARGET_DB.PUBLIC.ICEBERG_SOURCE_STAGE"
  partitionSize: auto

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

### Redshift Native → Snowflake Iceberg

| Redshift Native Type | Parquet Type (UNLOAD) | Snowflake Iceberg Type |
|---|---|---|
| `SMALLINT` | `INT32` | `INT` |
| `INTEGER` | `INT32` | `INT` |
| `BIGINT` | `INT64` | `LONG` |
| `DECIMAL(p,s)` | `FIXED_LEN_BYTE_ARRAY` | `DECIMAL(p,s)` |
| `REAL` | `FLOAT` | `FLOAT` |
| `DOUBLE PRECISION` | `DOUBLE` | `DOUBLE` |
| `BOOLEAN` | `BOOLEAN` | `BOOLEAN` |
| `CHAR(n)` | `BYTE_ARRAY (UTF8)` | `STRING` |
| `VARCHAR(n)` | `BYTE_ARRAY (UTF8)` | `STRING` |
| `DATE` | `INT32 (DATE)` | `DATE` |
| `TIMESTAMP` | `INT96` or `INT64` | `TIMESTAMP_NTZ` |
| `TIMESTAMPTZ` | `INT96` or `INT64` | `TIMESTAMP_LTZ` |
| `TIME` | N/A (cast to VARCHAR) | `STRING` |
| `VARBYTE` | N/A (cast via TO_HEX) | `STRING` |
| `GEOMETRY` | N/A (cast via ST_AsText) | `STRING` |
| `SUPER` | `BYTE_ARRAY (UTF8)` | `STRING` |

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

### Supported Iceberg Column Types

| Type | Notes |
|---|---|
| `BOOLEAN` | |
| `INT` | 32-bit integer |
| `LONG` | 64-bit integer |
| `FLOAT` | Single precision |
| `DOUBLE` | Double precision |
| `DECIMAL(p,s)` | Exact numeric |
| `DATE` | Date only |
| `TIME` | Time only |
| `TIMESTAMP_NTZ` | Timestamp without timezone |
| `TIMESTAMP_LTZ` | Timestamp with timezone |
| `STRING` / `VARCHAR` | Variable-length text |
| `BINARY` | Variable-length binary |
| `FIXED(n)` | Fixed-length binary |

### Unsupported Types in Iceberg Tables

The following Snowflake types are **not supported** in Iceberg tables and must be mapped to `STRING`/`VARCHAR` using `columnTypeMappings`:

- `VARIANT`
- `OBJECT`
- `ARRAY`
- `GEOGRAPHY`
- `GEOMETRY`

```yaml
columnTypeMappings:
  - sourceType: SUPER
    targetType: VARCHAR
  - sourceType: GEOMETRY
    targetType: VARCHAR
  - sourceType: VARIANT
    targetType: VARCHAR
```
