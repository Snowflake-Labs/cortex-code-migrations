# SSC-FDM-SSIS0027 — Cache Transform Duplicate-Key Check Not Enforced

An SSIS Cache Transform with `TreatDuplicateKeysAsError = true` fails the data flow when two rows share the cache's index columns. SnowConvert turns every Cache Transform into a passthrough `SELECT` of its columns, so duplicates pass through and nothing fails. The FDM is informational.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Low (once per Cache Transform with the option on) |
| Common action | Add a dbt `unique` test on the cache key |

## Identification

```sql
--** SSC-FDM-SSIS0027 - SSIS CACHE TRANSFORM WITH TREATDUPLICATEKEYSASERROR=TRUE ENFORCES DUPLICATE KEY VALIDATION AT RUNTIME. IN THE DBT TRANSLATION, THIS VALIDATION IS NOT ENFORCED AND DUPLICATE ROWS WILL PASS THROUGH UNCHANGED. THE TRANSLATED SQL WORKS CORRECTLY AS A PASSTHROUGH. IF DUPLICATE KEY VALIDATION IS REQUIRED FOR DATA QUALITY, CONSIDER ADDING A DBT TEST OR UNIQUE CONSTRAINT. **
SELECT
   name,
   salary
FROM
   {{ ref('stg_raw__ole_db_source') }}
```

The model is `int_<cache transform name>.sql`. The key columns are not in the generated SQL: they are the columns of the Cache connection manager (`DTS:CreationName="CACHE"`) with a non-zero `IndexPosition`, in the `.dtsx` or a project `.conmgr`.

## Fix Patterns

### Pattern 1: Add a unique test (most common)

```yaml
# models/intermediate/schema.yml
models:
  - name: int_cache_transform_duplicate_check
    tests:
      - dbt_utils.unique_combination_of_columns:   # several index columns
          combination_of_columns: ['name']
    columns:
      - name: name
        tests:
          - unique                                # single index column
```

`dbt build` then fails on duplicates, as the package did. Use `dbt_utils.unique_combination_of_columns` only if `dbt_utils` is already in `packages.yml`; otherwise write a singular test (`SELECT key, COUNT(*) FROM {{ ref('...') }} GROUP BY key HAVING COUNT(*) > 1`).

### Pattern 2: The duplicates are expected and must be resolved

When the cache's readers (Lookups) need one row per key and the data is known to repeat, dedup explicitly instead of failing: `QUALIFY ROW_NUMBER() OVER (PARTITION BY name ORDER BY <deciding column>) = 1`. Only do this when the package owner confirms it; otherwise use Pattern 1.

## Key Points

- Do **NOT** remove the FDM comment.
- A Snowflake `UNIQUE` constraint is not enforced, so it does not replace the test.
- A Lookup that reads this cache matches every duplicate in SQL (a join returns several rows) where SSIS returned one. The test above also protects that join.
