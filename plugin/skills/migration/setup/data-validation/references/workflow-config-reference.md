# Validation Workflow YAML Configuration Reference

`validate_data(mode="setup")` writes a YAML file with this shape to `artifacts/data_validation/workflows/<hash>.yaml`. The agent edits the file between `mode="setup"` and `mode="run"` for per-table overrides.

> **Field naming:** Use **camelCase** for all workflow YAML keys (for example `validationConfiguration`, `sourceWhereClause`, `useSnowpipeForResults`). The orchestrator accepts snake_case as a fallback.

## Top-level properties

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `sourcePlatform` | String | (required) | Source dialect id (for example `sqlserver`, `redshift`, `oracle`, `teradata`, `postgresql`) |
| `targetPlatform` | String | `Snowflake` | Target platform |
| `targetDatabase` | String | No | Default target database for tables without explicit target |
| `validationConfiguration` | Object | See below | Global validation level toggles |
| `comparisonConfiguration` | Object | No | Numeric tolerance and type-mapping file |
| `databaseMappings` | Object | No | `{"source_db": "TARGET_DB"}` when names differ |
| `schemaMappings` | Object | No | `{"source_schema": "TARGET_SCHEMA"}` when names differ |
| `tables` | Array | Yes* | Table entries (legacy section; still supported) |
| `views` | Array | No | View entries (same schema as `tables`) |
| `objects` | Array | No | Unified table/view entries — additive with `tables`/`views` |
| `affinity` | String | No | Routes work to workers with matching affinity |
| `useSnowflakeCompute` | Boolean | `false` | Run validation compute on Snowflake instead of the worker |
| `useSnowpipeForResults` | Boolean | `true` | Ingest L2/L3 CSV results via Snowpipe (default). Set `false` for per-partition `COPY INTO`. |
| `cleanUpTransientResources` | `"never"` \| `"on-success"` \| `"always"` | `"never"` | Delete intermediate DV `TASK_RESULTS` stage files for this workflow after it finishes. Underscores are accepted (`on_success`). |
| `targetPartitionSizeRows` | Integer | No | Global partition row target (mutually exclusive with `targetPartitionSizeMb`) |
| `targetPartitionSizeMb` | Integer | No | Global partition size target in MB |
| `validationCustomTypes` | Object | `{}` | Source datatype normalizations for L1 |
| `validationCustomMetrics` | Object | `{}` | Per-platform custom L2 metric overrides |
| `validationCustomNormalizations` | Object | `{}` | Per-platform L2/L3 normalization SQL |
| `acceptedTransformations` | Array | No | Global accepted source→target value differences (L3) |
| `validationCustomNormalizationRules` | Array | No | Granular L3 normalization expression overrides |
| `validationCustomTypeRules` | Array | No | Per-column cross-type mappings for L1 |
| `queryModifiers` | Object | No | SQL hints for source queries (see migration reference) |
| `intervalHandling` | `"interval"` \| `"varchar"` | `"interval"` | Interval column mapping mode |

\*At least one entry is required across `tables`, `views`, and `objects`.

## `validationConfiguration` (global or per-table)

| Field | Type | Default (scai `generate-config`) | Description |
|-------|------|----------------------------------|-------------|
| `schemaValidation` | Boolean | `true` | L1 — compare column definitions |
| `metricsValidation` | Boolean | `false` | L2 — compare aggregate statistics (opt-in) |
| `rowValidation` | Boolean | `true` | L3 — row-level comparison |
| `rowValidationMode` | String | `hybrid` | Only `hybrid` is supported (`row`/`cell` are rejected) |
| `continueOnFailure` | Boolean | `true` | Continue validating remaining tables on failure |
| `maxFailedRowsNumber` | Integer | No | Stop L3 after N mismatch rows per partition / early-stop threshold |
| `excludeMetrics` | Boolean | No | Skip L2 metrics for matching tables |
| `applyMetricColumnModifier` | Boolean | No | Apply metric column modifiers from templates |
| `maxColumnsPerMetricsBatch` | Integer | No | Split L2 metrics queries by column count |
| `maxColumnsPerCellBatch` | Integer | No | Per-table: split L3 cell drill-down batch size |
| `earlyStoppingForRowHashing` | Boolean | No | Hybrid L3 row-hash phase may stop early |
| `earlyStoppingForCellByCellComparison` | Boolean | No | Hybrid L3 cell drill-down may stop early |
| `earlyStopCheckIntervalMinutes` | Integer | No | Minutes between early-stop poll ticks |
| `earlyStopCheckIntervalSeconds` | Integer | No | Seconds between ticks (mutually exclusive with minutes) |
| `acceptedTransformations` | Array | No | Accepted source→target value differences at this level |
| `textComparisonMode` | String | No | Text comparison mode for L3 |
| `validationCustomNormalizationRules` | Array | No | Granular L3 normalization overrides |
| `validationCustomTypeRules` | Array | No | Per-column L1 type mapping overrides |

For user-facing explanations of each level, see [Validation levels reference](../../../validate-objects/actions/references/validation-levels-reference.md).

The four bool toggles can be set via setup-mode params (`schema_validation=`, `metrics_validation=`, `row_validation=`, `continue_on_failure=`) and persist as session defaults under `data_validation_*` in `plugin.yml`. Incremental mode uses `validation_type=` / `sync_strategy=` (also persisted) and patches `defaultTableConfiguration.synchronization.strategy`. Other fields (`watermarkColumn`, `checksumExpression`, `maxFailedRowsNumber`, …) require an in-place YAML edit.

## `comparisonConfiguration`

| Field | Type | Description |
|-------|------|-------------|
| `tolerance` | Float | Numeric comparison tolerance (for example `0.001`) |
| `typeMappingFilePath` | String | Path to custom type mapping file |

## `acceptedTransformations` entry

| Field | Type | Description |
|-------|------|-------------|
| `column` | String | Exact column name (mutually exclusive with `columnPattern`) |
| `columnPattern` | String | Regex column selector |
| `sourceValue` | String | Expected source-side value |
| `targetValue` | String | Expected target-side value |

## Per-table / per-object entry (`tables[]`, `views[]`, or `objects[]`)

| Field | Description |
|-------|-------------|
| `fullyQualifiedName` | Source object FQN used as the workflow key |
| `objectType` | `TABLE` or `VIEW` when known. When omitted, resolved at runtime via dialect detection. |
| `targetName` | Override target table name |
| `targetDatabase` / `targetSchema` | Override target location |
| `sourceWhereClause` | Filter **source** rows. Alias: `whereClause`. **Set together with `targetWhereClause`.** |
| `targetWhereClause` | Filter **target** rows. Pairs with `sourceWhereClause`. |
| `columnSelectionList` | Columns to include (or exclude) |
| `useColumnSelectionAsExcludeList` | When `true`, `columnSelectionList` is an exclusion list |
| `columnMappings` | `{"source_col": "TARGET_COL"}` for renamed columns |
| `indexColumnList` | Row-identity columns for L3 |
| `targetIndexColumnList` | Target-side index columns when different |
| `columnNamesToPartitionBy` | Partition columns for large-table validation |
| `targetPartitionSizeRows` / `targetPartitionSizeMb` | Per-table partition sizing (mutually exclusive) |
| `isCaseSensitive` | Case-sensitive identifier comparison for this object |
| `validationConfiguration` | Per-object override of validation toggles |
| `synchronization` | Opt into **incremental validation** (or override `defaultTableConfiguration`) |
| `acceptedTransformations` | Per-object accepted transformations |
| `validationCustomTypes` / `validationCustomMetrics` / `validationCustomNormalizations` | Per-object custom template overrides |
| `queryModifiers` | Per-object SQL hints |
| `intervalHandling` | Per-object interval mapping override |

## Incremental validation (`synchronization`)

By default every run fully re-validates the table. Adding a `synchronization` block opts a table into **incremental validation**: on later runs the orchestrator compares each partition against the prior run's baseline and re-validates only the partitions that changed.

In the plugin, choose mode/sync via `progress_setup(mode="data_validation")`, then pass `validation_type` / `sync_strategy` to `validate_data(mode="setup")`. Setup persists those in `plugin.yml` and patches `defaultTableConfiguration.synchronization.strategy` into the generated YAML. The agent still edits `watermarkColumn` (watermark) and partition columns when needed — see `edit_hints`.

Like data migration, you can set shared defaults once via top-level `defaultTableConfiguration` (including `synchronization`). Each table/view inherits those defaults; per-table fields override, and nested `synchronization` is deep-merged field-by-field.

**Prerequisite:** at least one prior full validation of the table must have completed — that run records the baselines the incremental run diffs against. The first run with `synchronization` set still validates everything (establishing the baseline); subsequent runs are incremental. Requires the table to be partitioned (`columnNamesToPartitionBy`). Unchanged incremental runs may show CLI status **Not validated** (skipped) rather than Valid/Failed.

| Field | Type | Description |
|-------|------|-------------|
| `strategy` | String | `watermark`, `checksum`, or `none` |
| `watermarkColumn` | String | Column whose max value marks the high-water mark. **Required** when `strategy: watermark`. |
| `trackModifications` | Boolean | Watermark only — also reconcile rows modified (not just newly inserted) since the last run. |
| `checksumExpression` | String | Checksum only — optional SQL aggregate per partition to detect change. Must not contain `;`. |

Global defaults + per-table override (camelCase YAML):

```yaml
sourcePlatform: sqlserver
targetDatabase: MY_DB
defaultTableConfiguration:
  columnNamesToPartitionBy:
    - ID
  synchronization:
    strategy: checksum
tables:
  - fullyQualifiedName: db.schema.customers
    # inherits checksum + partition column
  - fullyQualifiedName: db.schema.orders
    columnNamesToPartitionBy:
      - ORDER_ID
    synchronization:
      strategy: watermark
      watermarkColumn: UPDATED_AT
  - fullyQualifiedName: db.schema.lookup_codes
    synchronization:
      strategy: none
    # explicit full validation despite global checksum default
```

Per-table watermark example:

```yaml
tables:
  - fullyQualifiedName: db.schema.customers
    columnNamesToPartitionBy:
      - CUSTOMERID
    synchronization:
      strategy: watermark
      watermarkColumn: SIGNATURE
      trackModifications: true
```

Checksum example:

```yaml
tables:
  - fullyQualifiedName: db.schema.orders
    columnNamesToPartitionBy:
      - ORDER_ID
    synchronization:
      strategy: checksum
      checksumExpression: "SUM(AMOUNT)"
```

## L3 result codes (hybrid mode)

After L3 completes, partition results use standard codes:

| Code | Meaning |
|------|---------|
| `VALID` | No mismatches detected |
| `INVALID` | Row-level mismatches found |
| `POSSIBLE_MISMATCH` | Early stopping triggered before full comparison — treat as needing review, not automatic pass |

## Custom template shapes

Under `validationCustomMetrics`:

```yaml
validationCustomMetrics:
  source:
    - datatype: INTEGER
      replaceAll: false
      metrics:
        - name: sum
          metricQuery: 'SUM("{{ col_name }}")'
          metricReturnDatatype: NUMBER
          metricColumnModifier: 'TRIM("{{ col_name }}")'
  target: []
```

## Advanced

| Field | Level | Description |
|-------|-------|-------------|
| `defaultTableConfiguration` | top-level | Shared defaults for every `tables[]` / `views[]` entry (DM parity); `synchronization` deep-merges |
| `affinity` | top-level | Affinity group — orchestrator only picks up matching workflows |
| `cleanUpTransientResources` | top-level | Delete intermediate DV stage files after the workflow finishes (`never` / `on-success` / `always`) |
| `views` | top-level | Array of view validation entries (same schema as `tables`) |

> View validation is handled separately from table validation — see the migrate-objects view validation flow.

## Source platform

Generated validation workflows include `sourcePlatform` from the project dialect:

| Project source | `sourcePlatform` |
|----------------|------------------|
| SQL Server | `sqlserver` |
| Redshift | `redshift` |
| Oracle | `oracle` |
| Teradata | `teradata` |
| PostgreSQL | `postgresql` |

Optional top-level `affinity: <dialect>` routes work to workers with matching affinity.

## Oracle identifiers

Oracle table FQNs may use quoted identifiers when names are case-sensitive:

```yaml
sourcePlatform: oracle
tables:
  - fullyQualifiedName: '"TEST_SCHEMA"."EMPLOYEES"'
    targetDatabase: TARGET_DB
    targetSchema: PUBLIC
```

Align `source.databaseName` (when present) with the Oracle **service name** in worker TOML.

## Teradata identifiers

Teradata uses **database.table** naming — omit source `schemaName` (there is no schema layer). Align `databaseName` with `[connections.source.teradata].database` in worker TOML. Teradata L3 requires the `HASH_MD5` UDF in that database. Snowflake target identifiers still require `schemaName`.

## Common edit scenarios

| Scenario | Fields to edit |
|----------|----------------|
| Limit validation to a subset of rows | `sourceWhereClause` + `targetWhereClause` (both sides) |
| Skip expensive L2 on wide tables | `excludeMetrics: true` or disable `metricsValidation` |
| Whitelist known formatting differences | `acceptedTransformations` |
| Reduce source locking | `queryModifiers` on table or worker TOML |
| Faster L3 on huge tables | `earlyStoppingForRowHashing`, `maxFailedRowsNumber` |
| Rename columns between source and target | `columnMappings`, `indexColumnList`, `targetIndexColumnList` |
| Incremental watermark column | `defaultTableConfiguration.synchronization.watermarkColumn` (or per-table) |
| Views vs tables in one workflow | Use `objects[]` or separate `views[]` section |

For task-level debugging when validation stalls or finishes with incomplete tables, see [Task model reference](../../../migrate-objects/actions/data-migration/references/task-model-reference.md) and [Troubleshooting reference](../../../migrate-objects/actions/data-migration/references/troubleshooting-reference.md).
