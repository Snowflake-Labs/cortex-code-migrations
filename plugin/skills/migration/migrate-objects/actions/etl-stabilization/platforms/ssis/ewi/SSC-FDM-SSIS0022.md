# SSC-FDM-SSIS0022 — Pivot Assumes Sorted Input

An SSIS Pivot became `MAX(CASE WHEN <pivot key> = '<value>' THEN <value column> END) ... GROUP BY <set key>`. SSIS Pivot reads its input in set-key order and starts a new output row each time the set key changes; it also fails on a duplicate pivot key within a set. `GROUP BY` needs no order, makes exactly one row per set key, and takes the `MAX` of duplicates silently.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Low (once per Pivot component) |
| Common action | Check the input for duplicates and the pivot-key comparison type; add ORDER BY only where a consumer needs it |

## Identification

Look for the marker:
```
--** SSC-FDM-SSIS0022 - THE SSIS PIVOT TRANSFORMATION ASSUMES INPUT DATA IS SORTED BY THE SET KEY COLUMN. THE CONVERTED SQL USES GROUP BY WHICH DOES NOT REQUIRE OR PRESERVE SORT ORDER. VERIFY THAT DOWNSTREAM CONSUMERS DO NOT DEPEND ON SORTED OUTPUT. **
```

At the top of the pivot's dbt model:

```sql
--** SSC-FDM-SSIS0022 - THE SSIS PIVOT TRANSFORMATION ASSUMES INPUT DATA IS SORTED BY THE SET KEY COLUMN. ... **
WITH source_data AS
( SELECT CustomerName, Product, Quantity FROM {{ ref('stg_raw__source') }} )
SELECT
   CustomerName,
   MAX(CASE WHEN Product = 'Bike' THEN Quantity END) AS Bike,
   MAX(CASE WHEN Product = 'Helmet' THEN Quantity END) AS Helmet
FROM source_data
GROUP BY CustomerName
```

## Fix Patterns

### Pattern 1: No change (most common)

The input was sorted by a Sort component upstream and the output feeds a table: the `GROUP BY` result is the same. Leave the comment.

### Pattern 2: Duplicates within a set

If the input can hold two rows with the same set key and pivot key (SSIS would have failed the package), `MAX` hides it. Aggregate first when the source summed them, or add a dbt `unique` test on `(set key, pivot key)` in the input model so the case surfaces.

### Pattern 3: Pivot key compared with the wrong type

The `PivotKeyValue` is text in the package (`12`, `24`, ...). When the pivot-key column is numeric, compare it as a number: `MAX(CASE WHEN DevelopmentAge = 12 THEN PaidToDate END) AS PaidToDate012`.

### Pattern 4: A consumer depends on order

Add `ORDER BY <set key>` in the consumer (a file export, a `LISTAGG`), not in the pivot model; table order is not kept.


## Key Points

- Do **NOT** remove the FDM comment.
- A Script Component upstream of the pivot ([SSC-EWI-SSIS0001](SSC-EWI-SSIS0001.md)) often computes the pivot key or a running total; rebuild it with window functions (`SUM(x) OVER (PARTITION BY ... ORDER BY ...)`) before checking the pivot.
