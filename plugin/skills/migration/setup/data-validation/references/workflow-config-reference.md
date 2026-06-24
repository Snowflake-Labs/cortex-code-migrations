# Validation Workflow YAML Configuration Reference

`validate_data(mode="setup")` writes a YAML file with this shape to `artifacts/data_validation/workflows/<hash>.yaml`. The agent edits the file between `mode="setup"` and `mode="run"` for per-table overrides.

## Top-level `validation_configuration`

| Field                    | Type   | Default | Description                                     |
| ------------------------ | ------ | ------- | ----------------------------------------------- |
| `schema_validation`      | bool   | true    | Compare column definitions                      |
| `metrics_validation`     | bool   | true    | Compare aggregate statistics                    |
| `row_validation`         | bool   | false   | Row-by-row comparison (expensive)               |
| `row_validation_mode`    | string | null    | Mode for row validation                         |
| `continue_on_failure`    | bool   | true    | Continue validating remaining tables on failure |
| `max_failed_rows_number` | int    | null    | Stop row validation after N mismatches          |

The four bool fields can be set directly via setup-mode params (`schema_validation=`, `metrics_validation=`, `row_validation=`, `continue_on_failure=`) and persist as session defaults under `data_validation_*` in `plugin.yml`. The other two fields require an in-place edit.

## Optional `comparison_configuration`

| Field                    | Type   | Description                                |
| ------------------------ | ------ | ------------------------------------------ |
| `tolerance`              | float  | Numeric comparison tolerance (e.g., 0.001) |
| `type_mapping_file_path` | string | Path to custom type mapping file           |

## Optional mappings (when source/target names differ)

| Field               | Type | Description                          |
| ------------------- | ---- | ------------------------------------ |
| `database_mappings` | dict | `{"source_db": "TARGET_DB"}`         |
| `schema_mappings`   | dict | `{"source_schema": "TARGET_SCHEMA"}` |

## Per-table overrides (each entry in `tables[]`)

| Field                                  | Description                                             |
| -------------------------------------- | ------------------------------------------------------- |
| `where_clause`                         | Filter source rows for validation                       |
| `target_where_clause`                  | Filter target rows for validation                       |
| `column_selection_list`                | Columns to include (or exclude)                         |
| `use_column_selection_as_exclude_list` | If true, `column_selection_list` is an exclusion list   |
| `column_mappings`                      | `{"source_col": "TARGET_COL"}` for renamed columns      |
| `index_column_list`                    | Columns to use as row identity for row-level validation |
| `target_index_column_list`             | Target-side index columns (if different)                |
| `partition_column`                     | Column to partition large table validation              |
| `validation_configuration`             | Per-table override of validation checks                 |

## Advanced

| Field      | Level     | Description                                                    |
| ---------- | --------- | -------------------------------------------------------------- |
| `affinity` | top-level | Affinity group — orchestrator only picks up matching workflows |
| `views`    | top-level | Array of view validation entries (same schema as `tables`)     |

> View validation is handled separately from table validation — see the migrate-objects view validation flow.

## Source platform

Generated validation workflows include `sourcePlatform` from the project dialect (lowercase orchestrator id):

| Project source | `sourcePlatform` |
|----------------|------------------|
| SQL Server | `sqlserver` |
| Redshift | `redshift` |
| Oracle | `oracle` |
| Teradata | `teradata` |
| PostgreSQL | `postgresql` |

Optional top-level `affinity: <dialect>` routes work to workers with matching affinity (e.g. `affinity: teradata`).

## Oracle identifiers

Oracle table FQNs in `tables[]` may use quoted identifiers when names are case-sensitive or reserved:

```yaml
sourcePlatform: oracle
tables:
  - source:
      databaseName: ORCL
      schemaName: TEST_SCHEMA
      name: EMPLOYEES
      fullyQualifiedName: '"TEST_SCHEMA"."EMPLOYEES"'
```

Align `source.databaseName` with the Oracle **service name** used in the worker TOML `database` field.

## Teradata identifiers

Teradata uses **database** as the schema-level container (two-part names: `database.table`). Table FQNs in `tables[]` use `databaseName` and `tableName`; `schemaName` is typically the same as `databaseName` or omitted per orchestrator conventions.

Align `source.databaseName` with the Teradata **database name** in worker TOML `[connections.source.teradata].database` (from `--database` / `database` in `~/.snowflake/snowct/teradata.toml`).
