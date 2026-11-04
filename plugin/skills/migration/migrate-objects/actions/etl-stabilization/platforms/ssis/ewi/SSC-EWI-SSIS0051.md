# SSC-EWI-SSIS0051 — Fixed-Width Column Layout Incomplete

A `FixedWidth` Flat File connection has a column with no usable width: neither `DTS:ColumnWidth` nor `DTS:MaximumWidth` is a positive number (numeric columns usually carry `MaximumWidth="0"`), or the connection lists no columns at all. SnowConvert slices fixed-width lines by summing the widths before each column, so one missing width leaves every later start unknown. It generated a placeholder model that selects `null` for every output column, with no `FROM` and no `FILE FORMAT`. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (once per Flat File Source on such a connection) |
| Common action | Find the missing widths and write the `SUBSTR` read; needs-user if no layout exists |

## Identification

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0051 - ... WAS UNABLE TO RESOLVE THE FIXED-WIDTH COLUMN LAYOUT. ONE OR MORE COLUMNS HAVE NO COLUMN WIDTH. ***/!!!
SELECT
   null AS col_a,
   null AS col_b
```

Check each `DTS:FlatFileColumn` in the connection (package `DTS:ConnectionManagers` or `.conmgr`) for `DTS:ColumnWidth`. SnowConvert uses `ColumnWidth` first and falls back to `MaximumWidth`.

## Fix Patterns

### Pattern 1: The widths can be found

Sources, best first: the same connection in another package or `.conmgr` copy; the file's record-layout spec; a sample file (count the characters of each field, padding included). Then write what SnowConvert writes for a complete fixed-width layout:

```sql
-- etl_configuration/file_formats/file_formats.sql
CREATE FILE FORMAT IF NOT EXISTS LoadPolicies_Data_Flow_Task_Policy_Source
TYPE = 'CSV'
FIELD_DELIMITER = NONE
ENCODING = 'WINDOWS1252'
EMPTY_FIELD_AS_NULL = TRUE;

-- models/staging/stg_flat_file__policy_source.sql   (widths: POL_NO 12, PREMIUM 9, EFF_DT 8)
SELECT
   SUBSTR($1, 1, 12) :: VARCHAR(12) AS POL_NO,
   SUBSTR($1, 13, 9) :: NUMERIC(9, 2) AS PREMIUM,
   SUBSTR($1, 22, 8) :: VARCHAR(8) AS EFF_DT
FROM
   @public.landing_stage/ssis/LoadPolicies/PolicyFile/ (FILE_FORMAT => 'LoadPolicies_Data_Flow_Task_Policy_Source')
WHERE
   METADATA$FILENAME = 'ssis/LoadPolicies/PolicyFile/policies.dat'
   AND METADATA$FILE_ROW_NUMBER > 1
```

`SUBSTR` starts are 1-based: start of column *n* = 1 + the widths of columns 1 … *n*-1. Keep the placeholder's column names and order. Read the folder and name the file in the `METADATA$FILENAME` equality, not at the end of the `FROM` path: a stage path is a prefix, so `.../policies.dat` also reads `policies.dat.bak` ([SSC-EWI-SSIS0025](SSC-EWI-SSIS0025.md), Pattern 1). Keep the `METADATA$FILE_ROW_NUMBER` filter only when `DTS:ColumnNamesInFirstDataRow` is true (add `DTS:DataRowsToSkip` to the number); `DTS:HeaderRowsToSkip` becomes `SKIP_HEADER`.

### Pattern 2: No layout anywhere

Leave the placeholder, add `-- NEEDS-USER: column widths of <connection> (<file>) are missing from the package; provide the record layout` and mark as needs-user.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker, never by deleting it alone: the placeholder would load one row of NULLs.
- Check the total: the widths must add up to the record length of a sample line (without the row delimiter). An off-by-one shifts every later column.
- An implied decimal (`000012345` meaning `123.45`) needs `SUBSTR(...) :: NUMBER / 100`, not a plain cast; check how the SSIS data flow treated it.
- `RaggedRight` and other formats are [SSC-EWI-SSIS0034](SSC-EWI-SSIS0034.md).
