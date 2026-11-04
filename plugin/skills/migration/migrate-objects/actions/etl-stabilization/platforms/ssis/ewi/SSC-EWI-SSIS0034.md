# SSC-EWI-SSIS0034 — Flat File Format Not Supported

The Flat File connection's `DTS:Format` is neither `Delimited` nor `FixedWidth` (in practice `RaggedRight`, or `Mixed`). SnowConvert reads only those two, so it generated a placeholder model that selects `null` for every output column, with no `FROM` and no `FILE FORMAT`. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (once per Flat File Source on such a connection) |
| Common action | Read each line whole and slice it with `SUBSTR`, as SnowConvert does for fixed-width files |

## Identification

`{0}` is the format as written in the connection manager:

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0034 - FLAT FILE FORMAT 'RaggedRight' IS NOT SUPPORTED. ***/!!!
SELECT
   null AS col_a,
   null AS col_b
```

The layout is in the connection's `DTS:FlatFileColumns`: per column `DTS:ColumnType` (`FixedWidth` or `Delimited`), `DTS:ColumnWidth`, `DTS:ColumnDelimiter`, `DTS:DataType`. In a ragged-right file every column is fixed-width except the last, which runs to the row delimiter.

## Fix Patterns

### Pattern 1: RaggedRight

Add a format with no field delimiter to `etl_configuration/file_formats/file_formats.sql`, named as SnowConvert names it (`<Package>_<Data Flow path>_<Source>`), and slice `$1`. Starts are 1-based, each one the sum of the widths before it; the last column takes the rest of the line:

```sql
CREATE FILE FORMAT IF NOT EXISTS LoadClaims_Data_Flow_Task_Claims_Source
TYPE = 'CSV'
FIELD_DELIMITER = NONE
ENCODING = 'WINDOWS1252'
EMPTY_FIELD_AS_NULL = TRUE;
```

```sql
-- ColumnWidth: CLM_NO 10, LOSS_DT 8, STAT 2, then LOSS_DESC (delimited, last)
SELECT
   SUBSTR($1, 1, 10) :: VARCHAR(10) AS CLM_NO,
   TO_DATE(SUBSTR($1, 11, 8), 'YYYYMMDD') AS LOSS_DT,
   SUBSTR($1, 19, 2) :: VARCHAR(2) AS STAT,
   SUBSTR($1, 21) :: VARCHAR(500) AS LOSS_DESC
FROM
   @public.landing_stage/ssis/LoadClaims/ClaimsFile/ (FILE_FORMAT => 'LoadClaims_Data_Flow_Task_Claims_Source')
WHERE
   METADATA$FILENAME = 'ssis/LoadClaims/ClaimsFile/claims.txt'
   AND METADATA$FILE_ROW_NUMBER > 1
```

Keep the placeholder's column names and order. Take the land path from another converted source on the same connection, or build `ssis/<Package>/<Connection>/<file name of ConnectionString>`. Read the folder and name the file in the `METADATA$FILENAME` equality, not at the end of the `FROM` path: a stage path is a prefix, so `.../claims.txt` also reads `claims.txt.bak` ([SSC-EWI-SSIS0025](SSC-EWI-SSIS0025.md), Pattern 1). `WHERE METADATA$FILE_ROW_NUMBER > n` drops the column-name row (`DTS:ColumnNamesInFirstDataRow`) plus `DTS:DataRowsToSkip`; `DTS:HeaderRowsToSkip` becomes `SKIP_HEADER`.

### Pattern 2: Mixed (some columns delimited mid-row)

Slice the fixed-width columns with `SUBSTR` and take each delimited one with `REGEXP_SUBSTR` from where it starts, e.g. `REGEXP_SUBSTR(SUBSTR($1, 21), '^[^|]*')` for a `|`-terminated column. If the positions cannot be derived from the connection, add `-- NEEDS-USER: record layout of <file>` and mark as needs-user.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker, never by deleting it alone: the placeholder would load one row of NULLs.
- `ColumnWidth` counts characters, so `SUBSTR` offsets are right for any `ENCODING`.
- `SUBSTR` keeps padding: add `TRIM(...)` where the SSIS output was later trimmed, or where a numeric cast would choke on spaces.
- A `FixedWidth` connection with missing widths is [SSC-EWI-SSIS0051](SSC-EWI-SSIS0051.md); code page and locale issues are [SSC-EWI-SSIS0036](SSC-EWI-SSIS0036.md).
