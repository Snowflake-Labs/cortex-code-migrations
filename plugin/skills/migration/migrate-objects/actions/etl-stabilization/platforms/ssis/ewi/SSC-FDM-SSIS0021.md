# SSC-FDM-SSIS0021 — Pivot PassThroughUnmatchedPivotKeys Not Reproduced

An SSIS Pivot has `PassThroughUnmatchedPivotKeys = true`: a row whose pivot key matches no output column's `PivotKeyValue` does not fail the component. The converted SQL builds one `MAX(CASE WHEN <pivot key> = '<value>' THEN <value> END)` per declared output, so an unmatched row contributes no value anywhere and nothing reports it. The FDM is informational.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Low (once per Pivot with the option on) |
| Common action | No code change; surface the unmatched keys if the package reported them |

## Identification

```
--** SSC-FDM-SSIS0021 - SSIS PIVOT WITH PASSTHROUGHUNMATCHEDPIVOTKEYS ENABLED PASSES UNMATCHED PIVOT KEY ROWS TO A SEPARATE OUTPUT. THE CONVERTED SQL PRODUCES NULL VALUES FOR UNMATCHED PIVOT KEYS INSTEAD. **
```

In a dbt model it sits at the top of the pivot model, above [SSC-FDM-SSIS0022](SSC-FDM-SSIS0022.md):

```sql
--** SSC-FDM-SSIS0021 - SSIS PIVOT WITH PASSTHROUGHUNMATCHEDPIVOTKEYS ENABLED ... **
--** SSC-FDM-SSIS0022 - THE SSIS PIVOT TRANSFORMATION ASSUMES INPUT DATA IS SORTED BY THE SET KEY COLUMN. ... **
WITH source_data AS
( SELECT CustomerName, Product, Quantity FROM {{ ref('stg_raw__source') }} )
SELECT
   CustomerName,
   MAX(CASE WHEN Product = 'Bike' THEN Quantity END) AS Bike
FROM source_data
GROUP BY CustomerName
```

With `SsisToSnowflakeScripting` it sits above the `cte_pivot AS (...)` CTE of the data-flow procedure. There, a Pivot *without* the option fails the run on an unmatched key (`TO_NUMBER(CONCAT('SSIS Pivot invalid key: ', ...))`); with the option that check is left out, and the duplicate-key check (`ssis_pivot_pair_count`) stays.

Source facts: the Pivot component's `PassThroughUnmatchedPivotKeys` property, and each output column's `PivotKeyValue` in the `.dtsx`.

## Fix Patterns

### Pattern 1: No change (most common)

Nothing downstream used the unmatched rows. Leave the comment.

### Pattern 2: The run should report unmatched keys

SSIS logged the unmatched values after the data flow. To keep that visibility, add a warning test on the pivot key in the model that feeds the pivot:

```yaml
# models/.../schema.yml
models:
  - name: stg_raw__source
    columns:
      - name: Product
        tests:
          - accepted_values:
              values: ['Bike', 'Helmet']   # every PivotKeyValue of the Pivot
              config:
                severity: warn
```

### Pattern 3: A set key whose rows are all unmatched

`GROUP BY <set key>` still returns a row for it, with every pivoted column NULL. If the target must not get such rows, filter them out: `HAVING COUNT(CASE WHEN Product IN ('Bike', 'Helmet') THEN 1 END) > 0`.

## Key Points

- Do **NOT** remove the FDM comment.
- Compare the pivot key with the right type: `PivotKeyValue` is text in the package even when the key column is numeric (see [SSC-FDM-SSIS0022](SSC-FDM-SSIS0022.md)). An unmatched-looking key is often a type or case mismatch (`'bike'` vs `'Bike'`), not a new value.
- If a path in the `.dtsx` leaves the Pivot's error output, that branch is not converted: see [SSC-EWI-SSIS0049](SSC-EWI-SSIS0049.md).
