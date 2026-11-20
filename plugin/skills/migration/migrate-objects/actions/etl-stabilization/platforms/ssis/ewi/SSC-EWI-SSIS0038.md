# SSC-EWI-SSIS0038 — Fuzzy Lookup Multi-Column Matching Not Supported

The Fuzzy Lookup has more than one fuzzy join column (`JoinType = 2`). SnowConvert scores only the first one. `_Similarity`, `_Confidence`, the `WHERE` threshold, the `QUALIFY` order and **every** `_Similarity_<col>` output use `JAROWINKLER_SIMILARITY` on that first column, and the other fuzzy columns take no part in the match. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (once per Fuzzy Lookup with two or more fuzzy columns) |
| Common action | Score each fuzzy column, combine the scores into `_Similarity`, filter and rank on the combined score |

## Identification

At the top of the `int_<component>` model, after [SSC-FDM-SSIS0024](SSC-FDM-SSIS0024.md):

```sql
--** SSC-FDM-SSIS0024 - ... **
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0038 - THE SSIS FUZZYLOOKUP TRANSFORMATION HAS MULTIPLE FUZZY JOIN COLUMNS. ONLY THE FIRST FUZZY COLUMN IS USED FOR SIMILARITY SCORING. MULTI-COLUMN AVERAGING IS NOT YET IMPLEMENTED. ***/!!!
WITH lookup_reference AS ( ... ),
input_data AS ( ... )
SELECT
   ...
   JAROWINKLER_SIMILARITY(input_data.CompanyName, lookup_reference.CompanyName) / 100.0 AS _Similarity_CompanyName,
   JAROWINKLER_SIMILARITY(input_data.CompanyName, lookup_reference.CompanyName) / 100.0 AS _Similarity_City
```

The fuzzy columns are the `Fuzzy Lookup Input` columns whose `JoinType` is `2`, each with its `JoinToReferenceColumn`. Each one can have its own `MinSimilarity` property, which is a per-column floor. Check that every reference column is in the `lookup_reference` CTE.

## Fix Patterns

### Pattern 1: Average the per-column scores

SSIS combines the column scores into one `_Similarity` with its own weighting, which Microsoft does not publish. The average is the closest simple equivalent. Compute the scores once in a CTE, then filter and rank on them:

```sql
scored AS
(
   SELECT
      input_data.*,
      lookup_reference.Industry,
      JAROWINKLER_SIMILARITY(input_data.CompanyName, lookup_reference.CompanyName) / 100.0 AS _Similarity_CompanyName,
      JAROWINKLER_SIMILARITY(input_data.City, lookup_reference.City) / 100.0 AS _Similarity_City
   FROM input_data CROSS JOIN lookup_reference
)
SELECT
   CompanyName, Industry,
   (_Similarity_CompanyName + _Similarity_City) / 2 AS _Similarity,
   (_Similarity_CompanyName + _Similarity_City) / 2 AS _Confidence,
   _Similarity_CompanyName,
   _Similarity_City
FROM scored
WHERE (_Similarity_CompanyName + _Similarity_City) / 2 >= 0.3   -- component MinSimilarity
  AND _Similarity_City >= 0.5                                    -- column MinSimilarity, only where it is > 0
QUALIFY ROW_NUMBER() OVER (PARTITION BY <input key columns>
                           ORDER BY _Similarity_CompanyName + _Similarity_City DESC) <= 1
```

Keep the output column list and order the generated model had. Watch for reference columns whose names clash with input columns in `input_data.*`: alias them as the generated model did (`RefCompanyName`). If the package must keep unmatched rows, combine this with the `LEFT JOIN` pattern in [SSC-FDM-SSIS0024](SSC-FDM-SSIS0024.md).

### Pattern 2: One column dominates

When the package's output shows that one column decides the match (a name, with the city only as a tie-break), weight it: `0.7 * _Similarity_CompanyName + 0.3 * _Similarity_City`. Say in a comment that the weights are a choice. Ask the user with `-- NEEDS-USER:` when no SSIS output is available to calibrate against.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker.
- Each `_Similarity_<col>` must score its own column. The generated ones all score the first fuzzy column.
- A row with a NULL fuzzy column gets a NULL score, and the `WHERE` drops it. Wrap each score in `COALESCE(..., 0)` if SSIS kept the row.
- Exact join columns in the same lookup are a separate marker: [SSC-EWI-SSIS0039](SSC-EWI-SSIS0039.md).
