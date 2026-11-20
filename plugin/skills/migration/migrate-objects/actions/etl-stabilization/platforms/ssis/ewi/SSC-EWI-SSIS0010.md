# SSC-EWI-SSIS0010 — Table Model Already Defined

Two destinations in one data flow write the same table. SnowConvert normally merges them into one model with `UNION ALL` (the `SSC-FDM-0137` comment). This marker means the merge could not happen: the table was already claimed by an earlier destination that left no model to merge into. In the current engine that happens when the earlier destination's translation failed after it claimed the table, which usually shows as [SSC-EWI-SSIS0009](SSC-EWI-SSIS0009.md). This destination's model was written on its own, with the same table, so dbt finds two models for one relation. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Rare |
| Common action | Fix the first writer, then merge both writers into one model with `UNION ALL` |

## Identification

`{0}` is the destination's table name (or the model name when the table name is empty):

```sql
{{ config(
    alias='SharedTarget'
) }}
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0010 - A model associated with table 'SharedTarget' is already defined. ***/!!!
WITH source_data AS
( ... )
SELECT
   sd.CustomerID AS CustomerID,
   ...
FROM
   source_data AS sd
```

Find the other model with the same `alias` (or the same file name when there is no alias) in the same data flow's `models/` folder.

## Fix Patterns

### Pattern 1: Merge into one model

Resolve the other writer first. Then keep one model for the table, in the shape SnowConvert generates when it merges writers itself:

```sql
-- After: one model; delete the duplicate model file
{{ config(
    alias='SharedTarget'
) }}
--** SSC-FDM-0137 - MULTIPLE WRITERS TO THE SAME TARGET ARE COMBINED WITH UNION ALL IN A SINGLE QUERY. ... **
WITH source_1 AS
( SELECT CustomerID, OrderAmount FROM {{ ref('int_multicast') }} ),
source_2 AS
( SELECT CustomerID, OrderAmount FROM {{ ref('int_lookup_no_match') }} )
SELECT sd.CustomerID AS CustomerID, sd.OrderAmount AS OrderAmount FROM source_1 AS sd
UNION ALL
SELECT sd.CustomerID AS CustomerID, sd.OrderAmount AS OrderAmount FROM source_2 AS sd
```

Both legs need the same columns in the same order; write `NULL AS <col>` for a column one destination did not map. Carry over the `config` of both models (`materialized`, `pre_hook`/`post_hook`) into the one that remains.

### Pattern 2: The writes must stay separate

When one destination truncates or deletes before loading, or the second one updates rows the first one inserted, `UNION ALL` changes the result. Say so in a `-- NEEDS-USER:` comment and mark as needs-user.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker; and also the duplicate model, or dbt fails on two models for the same relation.
- Remove the deleted model's name from any `ref()` and selector that used it.
- `UNION ALL` does not keep the order in which SSIS wrote the rows, and a table keeps no row order anyway. A consumer that needs an order has to sort.
- SnowConvert tracks which tables are claimed separately for each Data Flow task, so writers in different data flows never get this marker.
