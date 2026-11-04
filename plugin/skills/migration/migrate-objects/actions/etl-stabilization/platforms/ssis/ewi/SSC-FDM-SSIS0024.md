# SSC-FDM-SSIS0024 — Fuzzy Lookup Approximated with JAROWINKLER_SIMILARITY

Every Fuzzy Lookup becomes an `int_<component>` model: `input_data CROSS JOIN lookup_reference`, scored with `JAROWINKLER_SIMILARITY(...) / 100.0` on the first fuzzy join column, filtered at the component's `MinSimilarity`, and cut to `MaxOutputMatchesPerInput` rows per input row with `QUALIFY ROW_NUMBER()`. A staging model `stg_raw__<component>` reads the reference table from `source('raw', '<table>')`. SSIS scores token-based matches. It also keeps every input row: a row with no match comes out with `_Similarity = 0` and NULL reference columns. The converted SQL drops such rows. The FDM is informational, but the dropped rows change the row count.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Once per Fuzzy Lookup component |
| Common action | Switch to `LEFT JOIN` so unmatched rows are kept, then check scores against SSIS output |

## Identification

```sql
--** SSC-FDM-SSIS0024 - THE SSIS FUZZYLOOKUP TRANSFORMATION USES A TOKEN-BASED SIMILARITY ALGORITHM. ... UNMATCHED INPUT ROWS ARE EXCLUDED — SSIS PRESERVES ALL INPUT ROWS WITH SIMILARITY=0 AND NULL REFERENCE COLUMNS. **
WITH lookup_reference AS
( SELECT RefID , CompanyName , Industry FROM {{ ref('stg_raw__fuzzy_lookup') }} ),
input_data AS
( SELECT InputID InputID, CompanyName CompanyName, City City FROM {{ ref('stg_raw__ole_db_source') }} )
SELECT
   input_data.CompanyName,
   lookup_reference.CompanyName RefCompanyName,
   lookup_reference.Industry,
   JAROWINKLER_SIMILARITY(input_data.CompanyName, lookup_reference.CompanyName) / 100.0 AS _Similarity,
   JAROWINKLER_SIMILARITY(input_data.CompanyName, lookup_reference.CompanyName) / 100.0 AS _Confidence,
   JAROWINKLER_SIMILARITY(input_data.CompanyName, lookup_reference.CompanyName) / 100.0 AS _Similarity_CompanyName
FROM
   input_data
   CROSS JOIN lookup_reference
WHERE
   JAROWINKLER_SIMILARITY(input_data.CompanyName, lookup_reference.CompanyName) / 100.0 >= 0.3
QUALIFY
   ROW_NUMBER() OVER (
   PARTITION BY input_data.InputID, input_data.CompanyName, input_data.City
   ORDER BY JAROWINKLER_SIMILARITY(input_data.CompanyName, lookup_reference.CompanyName) DESC) <= 1
```

In the `.dtsx` (`componentClassID="Microsoft.FuzzyLookup"`): `MinSimilarity`, `MaxOutputMatchesPerInput` and `ReferenceTableName` are component properties. Each input column has `JoinToReferenceColumn` and `JoinType` (`2` fuzzy, `1` exact). Each output column has `ColumnType` (`0` pass-through, `1` `_Similarity`, `2` `_Confidence`, `3` `_Similarity_<col>`) and `CopyFromReferenceColumn`.

## Fix Patterns

### Pattern 1: Keep unmatched rows (when anything downstream counts or routes them)

SSIS packages often follow the lookup with a Conditional Split on `_Similarity`, which needs the low-score rows. Move the filter into a `LEFT JOIN` condition, give each input row its own key, and default the scores to 0:

```sql
input_data AS
( SELECT SEQ8() AS _row_id, InputID, CompanyName, City FROM {{ ref('stg_raw__ole_db_source') }} )
SELECT
   input_data.CompanyName,
   lookup_reference.CompanyName RefCompanyName,
   lookup_reference.Industry,
   COALESCE(JAROWINKLER_SIMILARITY(input_data.CompanyName, lookup_reference.CompanyName) / 100.0, 0) AS _Similarity,
   COALESCE(JAROWINKLER_SIMILARITY(input_data.CompanyName, lookup_reference.CompanyName) / 100.0, 0) AS _Confidence,
   COALESCE(JAROWINKLER_SIMILARITY(input_data.CompanyName, lookup_reference.CompanyName) / 100.0, 0) AS _Similarity_CompanyName
FROM
   input_data
   LEFT JOIN lookup_reference
     ON JAROWINKLER_SIMILARITY(input_data.CompanyName, lookup_reference.CompanyName) / 100.0 >= 0.3
QUALIFY
   ROW_NUMBER() OVER (PARTITION BY input_data._row_id
                      ORDER BY JAROWINKLER_SIMILARITY(input_data.CompanyName, lookup_reference.CompanyName) DESC, lookup_reference.RefID) <= 1
```

`_row_id` also fixes a second loss. The generated `PARTITION BY` lists every input column, so two identical input rows share a partition and only one survives. SSIS keeps both. The reference key added to the `ORDER BY` makes ties deterministic.

### Pattern 2: Scores differ from SSIS

`JAROWINKLER_SIMILARITY` is character-based and case-insensitive (SSIS's default `FuzzyComparisonFlags = 1` also ignores case). It favours common prefixes, and it scores reordered words ("Smith John" vs "John Smith") low where SSIS's tokens match. If the package's `MinSimilarity` was tuned on SSIS scores, compare a sample of the two outputs and adjust the threshold. Write `-- NEEDS-USER:` and mark as needs-user when the business must accept the new threshold. For reordered words, score tokens instead: split both sides with `STRTOK_SPLIT_TO_TABLE(col, ' ,.;')` and compare the token sets (shared tokens / all distinct tokens). `EDITDISTANCE` is the other built-in.

### Pattern 3: Large inputs

The model compares every input row with every reference row. Narrow the join with an exact column ([SSC-EWI-SSIS0039](SSC-EWI-SSIS0039.md)) or a blocking key such as `SOUNDEX(input) = SOUNDEX(reference)` or the same first letter, and say in a comment that the blocking key can lose matches SSIS found.

## Key Points

- Do **NOT** remove the FDM comment.
- `_Confidence` is the same number as `_Similarity`. Nothing in Snowflake computes SSIS's confidence, so any split on `_Confidence` uses that score.
- With several fuzzy columns, every score uses the first column only: [SSC-EWI-SSIS0038](SSC-EWI-SSIS0038.md). An empty `lookup_reference` select list is [SSC-EWI-SSIS0052](SSC-EWI-SSIS0052.md).
- The component's `Delimiters` and per-column `MinSimilarity` are not used by the converted SQL.
