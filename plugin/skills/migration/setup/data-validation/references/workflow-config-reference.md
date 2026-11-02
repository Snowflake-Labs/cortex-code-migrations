# Validation Workflow YAML Configuration Reference

`validate_data(mode="setup")` writes a YAML file with this shape to `artifacts/data_validation/workflows/<hash>.yaml`. The agent edits the file between `mode="setup"` and `mode="run"` for per-table overrides.

> **Field naming:** Prefer **camelCase** for all workflow YAML keys (for example `validationConfiguration`, `sourceWhereClause`, `useSnowpipeForResults`, `indexColumnList`) — that is what `validate_data(mode="setup")` generates and what this reference documents.
>
> **Where-clause and index-column aliases:** The orchestrator accepts alternate spellings for backward compatibility. Use camelCase in agent edits; snake_case and legacy names still parse.
>
> | Concept | Preferred (YAML) | Also accepted |
> |---------|------------------|---------------|
> | Source row filter | `sourceWhereClause` | `whereClause` (legacy), `source_where_clause`, `where_clause` |
> | Target row filter | `targetWhereClause` | `target_where_clause` |
> | L3 index columns (source) | `indexColumnList` | `index_column_list` |
> | L3 index columns (target) | `targetIndexColumnList` | `target_index_column_list` |
>
> Set **both** `sourceWhereClause` and `targetWhereClause` when limiting compared rows — filtering one side only compares different subsets. Do **not** supply both `sourceWhereClause` and legacy `whereClause` on the same table (rejected at load time). If both camelCase and snake_case appear for index columns, **camelCase wins**.

## Top-level properties

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `sourcePlatform` | String | (required) | Source dialect id (for example `sqlserver`, `redshift`, `oracle`, `teradata`, `postgresql`, `snowflake`) |
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
| `useSnowpipeForResults` | Boolean | `true` | Ingest L2/L3 CSV results via Snowpipe (default). Set `false` for per-partition `COPY INTO`. |
| `cleanUpTransientResources` | `"never"` \| `"on-success"` \| `"always"` | `"on-success"` | Delete intermediate DV `TASK_RESULTS` stage files for this workflow after it finishes. Underscores are accepted (`on_success`). Set `"never"` to retain stage files for debugging. |
| `targetPartitionSizeRows` | Integer | No | Global partition row target (mutually exclusive with `targetPartitionSizeMb`) |
| `targetPartitionSizeMb` | Integer | No | Global partition size target in MB |
| `validationCustomTypes` | Object | `{}` | Source datatype normalizations for L1 |
| `validationCustomMetrics` | Object | `{}` | L2 metric overrides: per-datatype **or** per source column (see [Custom L2 metrics](#custom-l2-metrics-validationcustommetrics)) |
| `validationCustomNormalizations` | Object | `{}` | Per-platform L2/L3 normalization SQL |
| `acceptedTransformations` | Array | No | Global accepted source→target value differences (L3) |
| `validationCustomNormalizationRules` | Array | No | Granular L3 normalization expression overrides |
| `validationCustomTypeRules` | Array | No | Per-column cross-type mappings for L1 |
| `queryModifiers` | Object | No | SQL hints for source queries (see migration reference). DV Jinja templates alias the source table as `src` or `rw` (not `t`), so check the template context before writing a hint that references the alias. |
| `intervalHandling` | `"interval"` \| `"varchar"` | `"interval"` | Interval column mapping mode |

\*At least one entry is required across `tables`, `views`, and `objects`.

For `sourcePlatform: snowflake`, validation runs in warehouse and does not use
DEW. Leave `affinity` unset and fill the template's source and target fully
qualified names before running.

## `validationConfiguration` (global or per-table)

| Field | Type | Default (scai `generate-config`) | Description |
|-------|------|----------------------------------|-------------|
| `schemaValidation` | Boolean | `true` | L1 — compare column definitions. **Never `false`**, under either spelling (`schema_validation` is rejected identically): scai rejects the whole config (`CDV0004`), because L2 metrics and hybrid L3 both read L1's column metadata. There is no row-only run — accept a known type difference with `validationCustomTypeRules` / `acceptedTransformations` instead |
| `metricsValidation` | Boolean | `false` | L2 — compare aggregate statistics (opt-in) |
| `rowValidation` | Boolean | `true` | L3 — row-level comparison |
| `rowValidationMode` | String | `hybrid` | Only `hybrid` is supported (`row`/`cell` are rejected) |
| `continueOnFailure` | Boolean | `true` | Continue validating remaining tables on failure |
| `maxFailedRowsNumber` | Integer | No | Stop L3 after N mismatch rows per partition / early-stop threshold |
| `excludeMetrics` | Boolean | No | `true` drops the `avg` / `sum` / `stddev` L2 metrics on both source and target (the orchestrator's default is `false`) |
| `includeCountDistinct` | Boolean | No | `true` adds the `count_distinct` L2 metric on both source and target (default `false`; the most expensive L2 metric on large tables). See [L2 `count_distinct`](#l2-count_distinct-opt-in-includecountdistinct) |
| `includeLobColumnsInRowValidation` | Boolean | `false` | `true` makes L3 hash and compare source LOB columns (Oracle `CLOB` / `NCLOB` / `BLOB`, SQL Server `TEXT` / `NTEXT` / `IMAGE`, …). L3 leaves them out by default; L1 and L2 still check them. See [L3 LOB columns](#l3-lob-columns-opt-in-includelobcolumnsinrowvalidation) |
| `applyMetricColumnModifier` | Boolean | No | Toggles the `% 2097143` overflow guard on L2 `avg` / `sum` / `stddev`, on both source and target (the orchestrator's default is `true`). `false` aggregates full values, which can overflow on large `BIGINT` / `DECIMAL` sums |
| `maxColumnsPerMetricsBatch` | Integer | No | Split L2 metrics queries by column count |
| `maxColumnsPerCellBatch` | Integer | No | Per-table: split L3 cell drill-down batch size |
| `earlyStoppingForRowHashing` | Boolean | No | Hybrid L3 row-hash phase may stop early |
| `earlyStoppingForCellByCellComparison` | Boolean | No | Hybrid L3 cell drill-down may stop early |
| `earlyStopCheckIntervalMinutes` | Integer | No | Minutes between early-stop poll ticks |
| `earlyStopCheckIntervalSeconds` | Integer | No | Seconds between ticks (mutually exclusive with minutes) |
| `acceptedTransformations` | Array | No | Accepted source→target value differences at this level |
| `textComparisonMode` | String | No | Text comparison mode for L3 |
| `extraction` | Object | `regular` (omit) | L3 signature **transport** for non-Snowflake sources. See [L3 pushdown extract](./l3-pushdown-extraction.md). |
| `extraction.strategy` | String | `regular` | `regular` \| `unload` \| `write_nos` \| `dbms_cloud` \| `cet_as` \| `export_data` \| `cloud_direct`. Must be supported for `sourcePlatform`. Snowflake sources ignore this (in-warehouse L3). |
| `extraction.externalStage` | String | No | Snowflake external stage FQN. **Required** for every strategy except `regular`. |
| `validationCustomNormalizationRules` | Array | No | Granular L3 normalization overrides |
| `validationCustomTypeRules` | Array | No | Per-column L1 type mapping overrides |

For user-facing explanations of each level, see [Validation levels reference](../../../validate-objects/actions/references/validation-levels-reference.md).

The four bool toggles can be set via setup-mode params (`schema_validation=true` only, `metrics_validation=`, `row_validation=`, `continue_on_failure=`). They apply to that call's workflow only and are never saved: pass them again on each setup that needs them. Incremental mode uses `validation_type=` / `sync_strategy=` (persisted as the project's defaults in `plugin.yml`) and patches `defaultTableConfiguration.synchronization.strategy`. Other fields (`watermarkColumn`, `checksumExpression`, `maxFailedRowsNumber`, …) require an in-place YAML edit.

## L2 `count_distinct` (opt-in, `includeCountDistinct`)

L2 skips the `count_distinct` metric unless `includeCountDistinct` is `true`. It is off by default because it is the most expensive L2 metric on large tables (one SQL Server batch: 26.4 s with it, 1.4 s without). The other L2 metrics (`min`, `max`, `avg`, `sum`, `stddev`, `count_null`, …) are unaffected, and L3 still compares every value.

**Where it goes.** In the workflow file itself: the YAML that `validate_data(mode="setup")` writes to `artifacts/data_validation/workflows/<hash>.yaml`, or the JSON/YAML file passed to `create-data-validation-workflow`. It is read when the workflow is created and stored with each table's configuration in the metadata database, so it needs no image rebuild, account setting or Snowflake object. Change it in the file and create a new workflow. A running or finished workflow keeps the value it was created with.

**Turn it on for every table:**

```yaml
validationConfiguration:
  metricsValidation: true
  includeCountDistinct: true
```

**Turn it on for one table only:**

```yaml
tables:
  - fullyQualifiedName: db.dbo.orders
    validationConfiguration:
      includeCountDistinct: true
```

**Turn it on everywhere except one table:**

```yaml
validationConfiguration:
  includeCountDistinct: true
tables:
  - fullyQualifiedName: db.dbo.big_fact
    validationConfiguration:
      includeCountDistinct: false
  - fullyQualifiedName: db.dbo.orders   # inherits true
```

**Turn it off:** remove the key, or set it to `false`. Removing it from every level gives the default (off).

**Precedence (most specific wins):**

1. `tables[].validationConfiguration.includeCountDistinct`, or the same key under `defaultTableConfiguration.validationConfiguration`.
2. `tables[].includeCountDistinct` (key directly on the table entry), or `defaultTableConfiguration.includeCountDistinct`. A table entry beats `defaultTableConfiguration` at the same level.
3. Global `validationConfiguration.includeCountDistinct`.
4. Default: `false`.

| Global `validationConfiguration` | `defaultTableConfiguration` | Table entry | Result for that table |
|---|---|---|---|
| — | — | — | off |
| `true` | — | — | on |
| `false` / — | — | `includeCountDistinct: true` | on |
| `true` | — | `includeCountDistinct: false` | off |
| `true` | — | `validationConfiguration.includeCountDistinct: false` | off |
| — | — | `includeCountDistinct: true` + `validationConfiguration.includeCountDistinct: false` | off (the `validationConfiguration` key wins) |
| `false` | `includeCountDistinct: true` | — | on |
| `true` | `includeCountDistinct: false` | — | off |
| — | `includeCountDistinct: true` | `includeCountDistinct: false` | off |
| — | `validationConfiguration.includeCountDistinct: true` | `includeCountDistinct: false` | **on**: a `validationConfiguration` key beats a key set directly on the entry, even from `defaultTableConfiguration`. Use `validationConfiguration.includeCountDistinct: false` on the table instead |

To avoid the last case, set the flag in `validationConfiguration` blocks only.

**Rules that hold for every permutation:**

- Source and target always get the same value, so both compute `count_distinct` or neither does.
- With the flag off, a `validationCustomMetrics` entry for `count_distinct` is skipped too. With it on, the custom entry replaces the default query as usual.
- `excludeMetrics` (drops `avg` / `sum` / `stddev`) and `includeCountDistinct` are independent. `excludeMetrics: true` + `includeCountDistinct: true` gives `min`, `max`, `count_null`, `count_distinct` and the type-specific counts.
- `metricsValidation: false` turns off all of L2, so `includeCountDistinct` has no effect.
- snake_case `include_count_distinct` is accepted everywhere camelCase is.

## L3 LOB columns (opt-in, `includeLobColumnsInRowValidation`)

L3 (the row hash and the cell drill-down) leaves source LOB columns out unless `includeLobColumnsInRowValidation` is `true`. Hashing a LOB in every row is slow, and on some sources it is not possible (DB2 `HEX(BLOB)`). L1 still compares these columns' definitions and L2 their metrics. scai `generate-config` leaves the key out, which means `false`: add it as `true` to opt in.

**Which columns count as LOBs** (by the source column's base type):

| `sourcePlatform` | Left out of L3 by default |
|---|---|
| Oracle | `CLOB`, `NCLOB`, `BLOB` |
| SQL Server | `TEXT`, `NTEXT`, `IMAGE` (not `VARCHAR(MAX)`, `NVARCHAR(MAX)` or `VARBINARY(MAX)`, which L3 compares) |
| Teradata | `CLOB`, `BLOB` |
| DB2 | `CLOB`, `DBCLOB`, `NCLOB`, `BLOB` |
| Other sources, Snowflake included | none: the key has no effect |

- A LOB column named in the table's `indexColumnList` is never left out, since L3 needs it to align rows.
- A left-out column is dropped on both sides, the way a `columnSelectionList` exclusion drops a column. L3 records no result for it, so it can neither pass nor fail L3. The worker logs `skips source LOB columns <names>; set include_lob_columns_in_row_validation to hash them` for each table it applies to.
- **Oracle:** L3 hashes LOBs with `DBMS_CRYPTO`. Opting a table's LOBs in needs `GRANT EXECUTE ON DBMS_CRYPTO` to the validation user. `scai data doctor` checks the grant when a table in the workflow needs it.

**Where it goes.** As for `includeCountDistinct`: in the workflow file, read when the workflow is created. Change it and create a new workflow; a running or finished workflow keeps the value it was created with.

**Compare LOBs on every table:**

```yaml
validationConfiguration:
  rowValidation: true
  includeLobColumnsInRowValidation: true
```

**Compare LOBs on one table only:**

```yaml
tables:
  - fullyQualifiedName: db.app.documents
    validationConfiguration:
      includeLobColumnsInRowValidation: true
```

**Precedence (most specific wins):**

1. `tables[].validationConfiguration.includeLobColumnsInRowValidation`.
2. `defaultTableConfiguration.validationConfiguration.includeLobColumnsInRowValidation`.
3. Global `validationConfiguration.includeLobColumnsInRowValidation`.
4. Default: `false`.

Unlike `includeCountDistinct`, the key goes only in a `validationConfiguration` block. It is not a key of a table entry or of `defaultTableConfiguration` itself, and the orchestrator rejects an unknown key on a table entry. `rowValidation: false` turns off all of L3, so the key then has no effect. snake_case `include_lob_columns_in_row_validation` is accepted everywhere camelCase is.

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
| `sourceWhereClause` | Filter **source** rows. Legacy alias: `whereClause`. Snake_case: `source_where_clause`, `where_clause`. **Set together with `targetWhereClause`.** Do not set both `sourceWhereClause` and `whereClause` on the same entry. |
| `targetWhereClause` | Filter **target** rows. Snake_case alias: `target_where_clause`. Pairs with `sourceWhereClause`. |
| `columnSelectionList` | Columns to include (or exclude) |
| `useColumnSelectionAsExcludeList` | When `true`, `columnSelectionList` is an exclusion list |
| `columnMappings` | `{"source_col": "TARGET_COL"}` for renamed columns |
| `indexColumnList` | Row-identity columns for L3. Snake_case alias: `index_column_list`. |
| `targetIndexColumnList` | Target-side index columns when different. Snake_case alias: `target_index_column_list`. |
| `columnNamesToPartitionBy` | Partition columns for large-table validation. The first column should be one the source can prune on (sort key, clustered index, Teradata level-1 RANGE_N column, partition key, Oracle IOT primary key, Snowflake / BigQuery clustering key, or BigQuery partition column / `_PARTITIONTIME`). A Teradata primary index does not prune range scans — prefer the RANGE_N column when present, or a composite `[partitioning column, PI column]` when the date is low-cardinality. BigQuery `_PARTITIONTIME` needs `columnMappings` in DV (it is not in the target schema). When omitted, a key is inferred for tables (never for views); an object that needs more than one partition with no key fails with an error naming `columnNamesToPartitionBy`. An explicit `[]` turns partitioning off (no inference, one partition whatever the size): never write it, here or in `defaultTableConfiguration`, unless the user explicitly asks for a single partition and accepts the performance cost. |
| `targetPartitionSizeRows` / `targetPartitionSizeMb` | Per-table partition sizing (mutually exclusive) |
| `validationConfiguration` | Per-object override of validation toggles |
| `synchronization` | Opt into **incremental validation** (or override `defaultTableConfiguration`) |
| `acceptedTransformations` | Per-object accepted transformations |
| `validationCustomTypes` / `validationCustomMetrics` / `validationCustomNormalizations` | Per-object custom template overrides |
| `queryModifiers` | Per-object SQL hints |
| `intervalHandling` | Per-object interval mapping override |

Physical Snowflake target names (table, schema, and column identifiers) resolve from catalog metadata, not from an operator flag. Spell stored case in `targetName` / `targetDatabase` / `targetSchema` when overriding location; do not emit `isCaseSensitive` or `is_case_sensitive` (unknown keys are rejected).

## Incremental validation (`synchronization`)

By default every run fully re-validates the table. Adding a `synchronization` block opts a table into **incremental validation**: on later runs the orchestrator compares each partition against the prior run's baseline and re-validates only the partitions that changed.

In the plugin, choose mode/sync via `progress_setup(mode="data_validation")`, then pass `validation_type` / `sync_strategy` to `validate_data(mode="setup")`. Setup persists those in `plugin.yml` and patches `defaultTableConfiguration.synchronization.strategy` into the generated YAML. The agent still edits `watermarkColumn` (watermark) and partition columns when needed — see `edit_hints`.

Like data migration, you can set shared defaults once via top-level `defaultTableConfiguration` (including `synchronization`). Each table/view inherits those defaults and per-table fields override them: nested objects (`synchronization`, `queryModifiers`, `validationConfiguration`, `icebergConfig`) merge key by key, while lists, `columnMappings` and scalars are replaced whole. `targetPartitionSizeRows` / `targetPartitionSizeMb` are one setting (a table that sets either takes neither from the defaults), and so are `columnSelectionList` / `useColumnSelectionAsExcludeList`. Full rules: the orchestrator README's *defaultTableConfiguration merging (Data Validation)* section.

**Prerequisite:** at least one prior full validation of the table must have completed — that run records the baselines the incremental run diffs against. The first run with `synchronization` set still validates everything (establishing the baseline); subsequent runs are incremental. Requires the table to be partitioned (`columnNamesToPartitionBy`). Unchanged incremental runs may show CLI status **Not validated** (skipped) rather than Valid/Failed.

> **Advanced use case:** When a customer asks to re-run validation without scanning every partition, confirm incremental mode + sync strategy at setup and configure `synchronization` here. Full agent guidance: [Advanced operations reference](../../../data-infrastructure/references/advanced-operations-reference.md#incremental-data-validation).

| Field | Type | Description |
|-------|------|-------------|
| `strategy` | String | `watermark`, `checksum`, or `none` |
| `watermarkColumn` | String | Column whose max value marks the high-water mark. **Required** when `strategy: watermark`. |
| `trackModifications` | Boolean | Watermark only — also reconcile rows modified (not just newly inserted) since the last run. |
| `checksumExpression` | String | Checksum only — optional SQL aggregate per partition to detect change. Must not contain `;`. **Oracle:** built-in incremental checksum is supported; use this field to override with a cheaper probe (for example `MAX(ORA_ROWSCN)`). |

> **Oracle:** `checksum` incremental validation is supported (same as other platforms). Default partition probes hash normalized columns; some types are excluded from the hash — see checksum detection limits below and [Advanced operations reference](../../../data-infrastructure/references/advanced-operations-reference.md#checksum--incremental-sync--types-that-may-not-trigger-re-sync).

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

> **Checksum detection limits:** Default partition checksums **exclude or normalize** some column types (for example SQL Server legacy `text`/`ntext`/`image`, Oracle LOBs, float rounding, spatial WKT). A change confined to those columns may **not** trigger incremental re-validation. Custom `checksumExpression` overrides the built-in hash. See [Advanced operations reference](../../../data-infrastructure/references/advanced-operations-reference.md#checksum--incremental-sync--types-that-may-not-trigger-re-sync).

## Custom normalization (L3)

Advanced **Data Validation** feature — SQL applied before L3 row-hash and cell compare. **Not** DM `columnTypeMappings` (extraction/load only).

| Field | Level | Purpose |
|-------|-------|---------|
| `validationCustomNormalizationRules` | root / `validationConfiguration` / per-table | **Preferred** — `column`, `columnPattern`, `dataType`/`sourceDataType`, or `targetDataType` + `sourceExpression` / `targetExpression` (`{{ col_name }}` placeholder). Each expression matches that side's own catalog type. `targetDataType: "*"` applies `targetExpression` to the type the datatype mapping produces for `sourceDataType`. A `dataType` rule with both expressions and no `targetDataType` is that star. Quote the star in YAML. |
| `validationCustomNormalizations` | root / per-table | Legacy datatype-keyed normalization lists |
| `validationCustomTypes` | root / per-table | L1 source datatype → target type mappings |
| `validationCustomTypeRules` | root / per-table | Per-column L1 cross-type overrides |

**Requirements:** hybrid L3 needs `schemaValidation: true`. Use `acceptedTransformations` for known source→target value pairs; use normalization **rules** for shared expressions on both sides.

```yaml
validationCustomNormalizationRules:
  - column: NOTES
    sourceExpression: 'TRIM(CAST("{{ col_name }}" AS VARCHAR(4000)))'
    targetExpression: 'TRIM(TO_VARCHAR("{{ col_name }}"))'
  - columnPattern: '^GEO_'
    sourceExpression: 'ST_AsText("{{ col_name }}")'
    targetExpression: 'TO_VARCHAR("{{ col_name }}")'
```

When a customer asks about formatting drift, Teradata PERIOD cast strings, or case-only diffs, load [Advanced operations reference](../../../data-infrastructure/references/advanced-operations-reference.md#custom-normalization-data-validation-l3).

## L3 result codes (hybrid mode)

After L3 completes, partition results use standard codes:

| Code | Meaning |
|------|---------|
| `VALID` | No mismatches detected |
| `INVALID` | Row-level mismatches found |
| `POSSIBLE_MISMATCH` | Early stopping triggered before full comparison — treat as needing review, not automatic pass |

## Custom L2 metrics (`validationCustomMetrics`)

Top-level (or rarely per-object) overrides for **metrics validation (L2)** only. Does **not** change L1 schema or L3 row identity.

Each entry under `source` / `target` uses **exactly one** of:

| Selector | Scope | Notes |
|----------|-------|-------|
| `datatype` | Every column of that type | Optional `replaceAll: true` replaces the built-in metric set for that type |
| `column` | One source column | Value is `{table.fullyQualifiedName}.{columnName}` matching the table entry’s FQN + source column name. **`source` list only** — the orchestrator maps the override to the target column (via `columnMappings` when names differ). Do **not** put the PK in `columnSelectionList` with exclude mode to skip L2; that rejects index columns and would drop L3 |

Metric list entries:

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Metric id (`avg`, `min`, `max`, `sum`, `count_distinct`, …) |
| `metricQuery` | No | SQL expression. **Omit or leave empty to remove** that metric for the selector |
| `metricReturnDatatype` | No | Expected return type when defining/replacing a metric |
| `metricColumnModifier` | No | Optional wrapper applied to the column before the metric |

**Common ask — skip useless aggregations on a VARCHAR / text primary key** (e.g. length-based `avg` on an order id) while keeping the key in L1 and L3:

```yaml
validationConfiguration:
  metricsValidation: true   # must be on for L2 overrides to matter
validationCustomMetrics:
  source:
    - column: public.orders.order_id
      metrics:
        - name: avg
        # omit metricQuery → remove avg for this column only
    # Or remove every VARCHAR aggregation on the PK:
    # - column: public.orders.order_id
    #   metrics:
    #     - name: min
    #     - name: max
    #     - name: avg
    #     - name: count_empty
    #     - name: count_distinct
    #     - name: count_null
  target: []
```

Datatype-scoped override (unchanged):

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

Apply these edits **before** `validate_data(mode="run")` when the user asks to skip L2 metrics on specific columns. Prefer column-scoped removals over turning off `metricsValidation` for the whole workflow when they still want L2 on other columns.

## Advanced

| Field | Level | Description |
|-------|-------|-------------|
| `defaultTableConfiguration` | top-level | Shared defaults for every `tables[]` / `views[]` entry (DM parity); nested objects merge key by key, lists and scalars are replaced |
| `affinity` | top-level | Routes the workflow's tasks to workers with a matching label; the orchestrator stays without an affinity and claims every workflow. See [Affinity Reference](../../../data-infrastructure/references/affinity-reference.md) |
| `cleanUpTransientResources` | top-level | Delete intermediate DV stage files after the workflow finishes (`never` / `on-success` / `always`; default `on-success`) |
| `views` | top-level | Array of view validation entries (same schema as `tables`) |

> View validation is handled separately from table validation — see the migrate-objects view validation flow.

## How `defaultTableConfiguration` is resolved

`scai data validate create-workflow` and `scai data doctor --config` copy `defaultTableConfiguration` into each `tables[]` / `views[]` / `objects[]` entry by the orchestrator's rules. The workflow scai submits and the configuration doctor checks (for example, whether an entry runs row validation) match the configuration the run uses.

- **Nested objects merge key by key:** `synchronization`, `queryModifiers`, `validationConfiguration` (and its `extraction`), `icebergConfig`. The entry's keys win and the default's other keys are kept.
- **Lists, maps and scalars are replaced whole.** A key the entry leaves out, or sets to `null`, inherits the default.
- **Partition size is one setting.** An entry that sets `targetPartitionSizeRows` or `targetPartitionSizeMb` takes neither from the defaults. `earlyStopCheckIntervalMinutes` / `earlyStopCheckIntervalSeconds` inside `validationConfiguration` follow the same rule.
- **Column selection is one setting.** An entry that sets `columnSelectionList` or `useColumnSelectionAsExcludeList`, even to `null`, takes neither from the defaults. A key it leaves out or sets to `null` reads as `[]` (no selection, every column) or `false` (the list is an include list).
- **`tableType: native`**, on the entry or inherited, drops an inherited `icebergConfig`.

```yaml
defaultTableConfiguration:
  useColumnSelectionAsExcludeList: true
  columnSelectionList: [AUDIT_TS]
  validationConfiguration:
    rowValidation: true
tables:
  - fullyQualifiedName: db.dbo.orders       # excludes AUDIT_TS; row validation on
  - fullyQualifiedName: db.dbo.customers
    columnSelectionList: [ID, NAME]         # validates only ID and NAME (include list)
    validationConfiguration:
      metricsValidation: false              # row validation still on
  - fullyQualifiedName: db.dbo.events
    useColumnSelectionAsExcludeList: true
    columnSelectionList: [PAYLOAD]          # excludes PAYLOAD only, not AUDIT_TS
```

**Changes from earlier scai releases.** No key was added, renamed or removed, and scai rejects nothing it accepted before. Earlier releases resolved these cases differently:

- **Column selection.** Earlier releases resolved `columnSelectionList` and `useColumnSelectionAsExcludeList` each on its own, and a `null` on the entry inherited the default. Three cases now validate different columns; under the default above (`[AUDIT_TS]`, exclude):
  - An entry that sets only `columnSelectionList` (or sets `useColumnSelectionAsExcludeList: null` beside it) kept the default's `true`, so its list was an exclude list. It is now an include list (`customers` above).
  - An entry that sets only `useColumnSelectionAsExcludeList` kept the default's list: with `false` it validated only `AUDIT_TS`. Its list is now `[]`, so it validates every column.
  - An entry that sets one key to `null` and leaves the other out inherited both of the default's values. It now reads as `[]` / `false` and validates every column.

  To keep a selection, set both keys on the entry, as `events` does above.
- **An entry that sets part of `queryModifiers`, `validationConfiguration` or `icebergConfig`** replaced the default's block whole, so the entry lost the default's other keys: under an entry that sets only `metricsValidation`, a default `rowValidation: true` was dropped, and doctor did not check row validation. Such an entry now also inherits the default's early-stop interval when it sets neither. One that sets one interval still takes neither of the default's: that was already so, because the whole block was replaced, and the pair rule keeps it so under the key-by-key merge.
- **An entry that sets one partition size** (`targetPartitionSizeRows` or `targetPartitionSizeMb`) also carried the default's other one. Now only the entry's own value applies. This changes partition sizes, not which rows pass.
- **`partitionByDate`** under `defaultTableConfiguration` was dropped from every entry. It is now inherited.

## Source platform

Generated validation workflows include `sourcePlatform` from the project dialect:

| Project source | `sourcePlatform` |
|----------------|------------------|
| SQL Server | `sqlserver` |
| Redshift | `redshift` |
| Oracle | `oracle` |
| Teradata | `teradata` |
| PostgreSQL | `postgresql` |

Setup stamps the top-level `affinity` with the project-default label; it routes work to workers carrying the same label.

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
| Limit validation to a subset of rows | `sourceWhereClause` + `targetWhereClause` (both sides; snake_case aliases accepted) |
| Skip expensive L2 on wide tables | Disable `metricsValidation`, split it with `maxColumnsPerMetricsBatch`, or drop the `avg` / `sum` / `stddev` aggregates with `excludeMetrics: true` |
| Keep metrics off (default / user said off) | Leave `metricsValidation: false` — **Full** mode does not mean enable L2 |
| Skip L2 aggregations on one column (e.g. VARCHAR PK) without dropping L1/L3 | Top-level `validationCustomMetrics.source` with `column: {table.fullyQualifiedName}.{columnName}` and metric `name`s with **no** `metricQuery` — see [Custom L2 metrics](#custom-l2-metrics-validationcustommetrics). Do **not** exclude the index/PK via `columnSelectionList` |
| Exclude columns from L3 row compare (timestamp / audit drift) | Per table: `useColumnSelectionAsExcludeList: true` and `columnSelectionList: [created_at]` (or `CREATED_AT`, `updated_at`, …). Common for SQL Server `DATETIME2` → Snowflake `TIMESTAMP_*` precision or write-time drift. |
| Whitelist known formatting differences | `acceptedTransformations` |
| Reduce source locking | `queryModifiers` on table or worker TOML |
| Faster L3 on huge tables | `earlyStoppingForRowHashing`, `maxFailedRowsNumber` |
| Rename columns between source and target | `columnMappings`, `indexColumnList`, `targetIndexColumnList` |
| Incremental watermark column | `defaultTableConfiguration.synchronization.watermarkColumn` (or per-table) |
| Views vs tables in one workflow | Use `objects[]` or separate `views[]` section |

Example — exclude `created_at` from row compare for one table:

```yaml
tables:
  - name: customers
    schemaName: dbo
    databaseName: eval_setup
    useColumnSelectionAsExcludeList: true
    columnSelectionList:
      - created_at
    indexColumnList:
      - id
```

Apply user-requested excludes **before** `validate_data(mode="run")`. Do not wait for a failed row compare to add them when the user already asked.

For task-level debugging when validation stalls or finishes with incomplete tables, see [Task model reference](../../../validate-objects/actions/references/task-model-reference.md) and [Troubleshooting reference](../../../validate-objects/actions/references/troubleshooting-reference.md).
