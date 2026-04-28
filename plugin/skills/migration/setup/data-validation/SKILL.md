---
name: data-validation-setup
description: One-time setup for cloud data validation — choose validation scope, generate JSON config, verify orchestrator service.
parent_skill: migration
---

# Cloud Data Validation Setup

One-time configuration for validating migrated data between a source database and Snowflake using the **Cloud Data Validation** feature via the **scai CLI**.

> **Supported sources**: SQL Server, Redshift
> **Supported target**: Snowflake

## Prerequisite

Load `../data-infrastructure/SKILL.md` first. It handles shared prerequisites, compute pool registration, and worker config (source host/port/credentials, source database, source schema). Return here after it completes.

> Validation additionally requires that target tables are already deployed to Snowflake (run data migration first).

---

## Step 1: Choose Validation Scope

### 1.A — Tables to Validate

Ask the user:

> 1. **All deployed tables** — Validate every table in the registry that has been deployed.
> 2. **Specific schema** — Filter by source schema (e.g., `"source.schema = 'dbo'"`).
> 3. **Specific wave** — Filter by planning wave (e.g., `"planning.wave = 'wave_1'"`).
> 4. **Custom filter** — Any valid `--where` expression.

### 1.B — Validation Types

Ask the user which checks to enable:

> 1. **Schema validation** (default: enabled) — Compare column names, data types, nullability between source and target.
> 2. **Metrics validation** (default: enabled) — Compare row counts, null counts, min/max/sum aggregates per column.
> 3. **Row-level validation** (default: disabled) — Row-by-row comparison. Expensive for large tables; requires index columns.

### 1.C — Failure Handling

> Continue on failure? (default: yes)
>
> - **Yes** — Validate all tables even if some fail. Report failures at the end.
> - **No** — Stop on first table failure.

### 1.D — Confirm

```
Validation scope:
  Filter:     all | schema=<X> | wave=<X> | custom
  Schema:     enabled | disabled
  Metrics:    enabled | disabled
  Row-level:  enabled | disabled
  On failure: continue | stop
```

---

## Step 2: Generate Validation Config

### Option A — Auto-generate from registry

```bash
scai data generate-cloud-validation-config -o .scai/settings/data-validation-config.json
```

With a filter:

```bash
scai data generate-cloud-validation-config --where "source.schema = 'dbo'" -o .scai/settings/data-validation-config.json
```

This reads the Code Unit Registry and produces a JSON config with all matching tables.

### Option B — Create manually

Minimal example:

```json
{
  "source_platform": "SqlServer",
  "target_platform": "Snowflake",
  "validation_configuration": {
    "schema_validation": true,
    "metrics_validation": true,
    "row_validation": false,
    "continue_on_failure": true
  },
  "tables": [
    {
      "fully_qualified_name": "mydb.dbo.customers",
      "target_database": "TARGET_DB",
      "target_schema": "DBO",
      "target_name": "CUSTOMERS"
    }
  ]
}
```

> `source_platform` must be `"SqlServer"` or `"Redshift"`. Each table requires `fully_qualified_name`.

Save to `.scai/settings/data-validation-config.json`.

---

## Step 3: Customize Validation Configuration

Edit the generated JSON to match the choices from Step 1. Key fields:

**Top-level `validation_configuration`:**

| Field                    | Type   | Default | Description                                     |
| ------------------------ | ------ | ------- | ----------------------------------------------- |
| `schema_validation`      | bool   | true    | Compare column definitions                      |
| `metrics_validation`     | bool   | true    | Compare aggregate statistics                    |
| `row_validation`         | bool   | false   | Row-by-row comparison (expensive)               |
| `row_validation_mode`    | string | null    | Mode for row validation                         |
| `continue_on_failure`    | bool   | true    | Continue validating remaining tables on failure |
| `max_failed_rows_number` | int    | null    | Stop row validation after N mismatches          |

**Optional `comparison_configuration`:**

| Field                    | Type   | Description                                |
| ------------------------ | ------ | ------------------------------------------ |
| `tolerance`              | float  | Numeric comparison tolerance (e.g., 0.001) |
| `type_mapping_file_path` | string | Path to custom type mapping file           |

**Optional mappings (when source/target names differ):**

| Field               | Type | Description                          |
| ------------------- | ---- | ------------------------------------ |
| `database_mappings` | dict | `{"source_db": "TARGET_DB"}`         |
| `schema_mappings`   | dict | `{"source_schema": "TARGET_SCHEMA"}` |

**Per-table overrides (on each entry in `tables[]`):**

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

**Advanced:**

| Field     | Level     | Description                                                    |
| --------- | --------- | -------------------------------------------------------------- |
| `affinity` | top-level | Affinity group — orchestrator only picks up matching workflows |
| `views`   | top-level | Array of view validation entries (same schema as `tables`)     |

---

## Step 4: Verify Orchestrator Service

After the shared infrastructure step has registered the compute pool, confirm the orchestrator service started:

```sql
SELECT SYSTEM$GET_SERVICE_STATUS('SNOWCONVERT_AI.DATA_MIGRATION.DATA_MIGRATION_SERVICE');
```

If it returns `[]` (suspended/not started), resume it manually:

```sql
ALTER SERVICE SNOWCONVERT_AI.DATA_MIGRATION.DATA_MIGRATION_SERVICE RESUME;
```

Wait 30-60s and re-check until status shows `READY`.

This completes the setup. During the validate-objects phase, the `validate_data()` MCP tool will automatically detect the config at `.scai/settings/data-validation-config.json` and use cloud validation. **Do not run `scai data cloud-validate` directly** — `validate_data()` handles service and worker lifecycle internally.

---

## Checklist

Shared infrastructure checklist is owned by `../data-infrastructure/SKILL.md`. Validation-specific items:

```
- [ ] Validation scope selected (tables, checks, failure handling)
- [ ] Validation config created (.scai/settings/data-validation-config.json)
- [ ] Validation types configured (schema/metrics/row)
- [ ] Data Validation Service running (READY)
```

Return control to the parent skill.
