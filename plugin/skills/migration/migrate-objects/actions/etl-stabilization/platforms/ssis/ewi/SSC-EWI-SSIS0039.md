# SSC-EWI-SSIS0039 — Fuzzy Lookup Exact Join Columns Not Supported

The Fuzzy Lookup has exact join columns (`JoinType = 1`): SSIS matches only reference rows that are equal on those columns and fuzzy-scores within them. SnowConvert leaves them out. The model still does `input_data CROSS JOIN lookup_reference`, so a row can match a reference row with a different exact key. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (once per Fuzzy Lookup with an exact join column) |
| Common action | Turn the `CROSS JOIN` into a join on the exact columns |

## Identification

Last in the stack at the top of the `int_<component>` model:

```sql
--** SSC-FDM-SSIS0024 - ... **
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0039 - THE SSIS FUZZYLOOKUP TRANSFORMATION HAS EXACT JOIN COLUMNS (JOINTYPE=1). EXACT JOIN PRE-FILTERING IS NOT YET IMPLEMENTED — THE GENERATED SQL USES A FULL CROSS JOIN INSTEAD. ***/!!!
WITH lookup_reference AS ( ... ),
input_data AS ( ... )
SELECT ...
FROM
   input_data
   CROSS JOIN lookup_reference
WHERE
   JAROWINKLER_SIMILARITY(input_data.CompanyName, lookup_reference.CompanyName) / 100.0 >= 0.3
```

The exact columns are the `Fuzzy Lookup Input` columns with `<property name="JoinType">1</property>`. Their `JoinToReferenceColumn` names the reference column.

## Fix Patterns

### Pattern 1: Exact and fuzzy columns together

```sql
-- Before
FROM
   input_data
   CROSS JOIN lookup_reference
WHERE
   JAROWINKLER_SIMILARITY(input_data.CompanyName, lookup_reference.CompanyName) / 100.0 >= 0.3

-- After
FROM
   input_data
   JOIN lookup_reference
     ON input_data.Country = lookup_reference.Country
WHERE
   JAROWINKLER_SIMILARITY(input_data.CompanyName, lookup_reference.CompanyName) / 100.0 >= 0.3
```

To keep unmatched rows (what SSIS does), use `LEFT JOIN ... ON <exact columns> AND <similarity> >= <MinSimilarity>` as in [SSC-FDM-SSIS0024](SSC-FDM-SSIS0024.md). The exact columns also make that join much cheaper.

### Pattern 2: Every join column is exact

With no fuzzy column, the generated `_Similarity` is the literal `0`, the `WHERE` is `TRUE` and the `QUALIFY` orders by `NULL`, so each input row gets an arbitrary reference row. This is a plain lookup. Use `LEFT JOIN lookup_reference ON <exact columns>` with `QUALIFY ROW_NUMBER() OVER (PARTITION BY <input key> ORDER BY <reference key>) <= <MaxOutputMatchesPerInput>`, and set `_Similarity` and `_Confidence` to `1` for matched rows and `0` for unmatched ones.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker.
- Make sure the exact reference columns are selected in the `lookup_reference` CTE and the `stg_raw__<component>` staging model.
- `=` never matches NULL keys. Use `EQUAL_NULL(a, b)` only if NULL keys in the reference should match NULL inputs.
- Compare the column types. A numeric input against a text reference column needs an explicit cast on one side.
- With two or more fuzzy columns as well, apply [SSC-EWI-SSIS0038](SSC-EWI-SSIS0038.md).
