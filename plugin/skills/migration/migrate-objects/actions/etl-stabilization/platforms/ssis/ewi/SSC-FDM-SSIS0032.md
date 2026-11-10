# SSC-FDM-SSIS0032 — Destination Converted to a Dynamic Table

The package fully replaced this OLE DB Destination on every run: a `TRUNCATE TABLE` or an unfiltered `DELETE`, then one data flow that reloads it. Because the user converted with `--materialize-as-dynamic-table`, SnowConvert materialized the mart as a Snowflake Dynamic Table over the converted data-flow query instead of `incremental`, and removed the emptying statement from the orchestration (`SSC-FDM-SSIS0033`).

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment in the mart model |
| Breaks compilation? | **No** |
| Frequency | Once per promoted destination; only with `--materialize-as-dynamic-table` |
| Common action | Confirm nothing else writes the table; otherwise revert the mart to `incremental` |

## Identification

The mart's config and the marker:

```sql
{{ config(
    materialized='dynamic_table',
    refresh_mode='AUTO',
    tags=['Data_Flow_Task'],
    alias='SsisEmployeeStaging'
) }}
--** SSC-FDM-SSIS0032 - Destination 'dbo.SsisEmployeeStaging' has a direct reset/load pair and no other statically known writer in this package, so it was converted to a Dynamic Table over the converted data-flow query. Verify that procedures, scripts, unresolved event handlers, and other packages do not write this table. Identity values, column defaults, constraints, and triggers of the original SQL Server table are not reproduced. **
```

## Decision Tree

1. **Does anything outside this package write the table?** Search the converted workload (`snowflake/`) for `TRUNCATE`, `DELETE`, `INSERT`, `UPDATE`, or `MERGE` against the table name, including other packages' orchestration, procedures, and scripts. The engine only checks the package it converts.
   - **Yes:** those writes fail on a Dynamic Table. Revert this mart (Fix Pattern 1).
   - **No:** keep the Dynamic Table (Fix Pattern 2).
2. **Did the original table rely on an identity column, column defaults, constraints, or triggers?** A Dynamic Table has none of them. If downstream code depends on one, revert the mart (Fix Pattern 1).

## Fix Patterns

### Pattern 1: Revert to an incremental mart

Remove `materialized` and `refresh_mode`, and keep every other config key, so the mart inherits the project's `marts` default again (`incremental`), exactly as a conversion without the flag writes it:

```sql
{{ config(
    tags=['Data_Flow_Task'],
    alias='SsisEmployeeStaging'
) }}
```

Then restore the emptying statement in the orchestration, in place of the matching `SSC-FDM-SSIS0033` note (Decision Tree step 2 there). An incremental mart appends, so without it every run duplicates the rows.

If the Dynamic Table was already built in Snowflake, drop it with `DROP DYNAMIC TABLE` before the next `dbt run`, so dbt creates the incremental table in its place.

### Pattern 2: Keep the Dynamic Table

No code change. dbt refreshes the table each time the project runs. Running it needs dbt-snowflake 1.11.5 or later and a warehouse in `profiles.yml`. `refresh_mode='AUTO'` refreshes incrementally when it can, which needs change tracking on the source tables; their owner may have to enable it.

## Key Points

- Never `TRUNCATE`, `INSERT`, `UPDATE`, or `MERGE` into a Dynamic Table, in fixes or in test setup. Seed its source tables instead; the next `dbt run` refreshes it.
- To rebuild it from scratch, use `uv run --project {SKILL_DIR}/dbt-runtime dbt run --full-refresh --project-dir <DBT_PROJECT_PATH> --profiles-dir ~/.dbt` or `DROP DYNAMIC TABLE`; `DROP TABLE` does not drop a Dynamic Table.
- Do **NOT** remove the FDM comment.
