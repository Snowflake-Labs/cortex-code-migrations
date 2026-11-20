# SSC-EWI-SSIS0023 — Bulk Insert Format File Not Supported

A Bulk Insert task used a bcp format file (`.fmt` or `.xml`) to describe the file's fields. SnowConvert does not read it: the generated `COPY INTO` has a `FILE_FORMAT` built from the task's own attributes only, and **no column list**, so the file's fields load into the table's first columns in order. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (once per Bulk Insert task with a format file) |
| Common action | Translate the format file into `FILE_FORMAT` options plus a column list |

## Identification

Usually chained with SSC-EWI-SSIS0024 and followed by Bulk Insert FDMs:

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0024 - ... ***/!!!!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0023 - SSIS BULKINSERTTASK FORMAT FILE IS NOT SUPPORTED IN SNOWFLAKE. CREATE EQUIVALENT FILE FORMAT OBJECT MANUALLY BASED ON FORMAT FILE CONTENTS. ***/!!!
--** SSC-FDM-SSIS0012 - ... **
COPY INTO dbo.LargeDataset
FROM '@{STAGE_PLACEHOLDER}'
PATTERN = '.*large_dataset\\.csv.*'
FILE_FORMAT = (TYPE = 'CSV', FIELD_DELIMITER = ',', RECORD_DELIMITER = '\n', SKIP_HEADER = 1, NULL_IF = ('', 'NULL', 'null'), ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE)
ON_ERROR = SKIP_FILE_50;
```

The format file's path is in the task's `FormatFile` connection (a File connection manager). Find the file in the project's source tree.

## Fix Patterns

A non-XML bcp format file has a version line, a field count, then one row per file field:

```
14.0
6
1  SQLCHAR  0  255  ","     4  CLM_NO      SQL_Latin1_General_CP1_CI_AS
...
6  SQLCHAR  0  255  "\r\n"  9  LOSS_DESC   SQL_Latin1_General_CP1_CI_AS
```

Columns: file field order, host data type, prefix length, host length, terminator, **server column order**, server column name, collation.

| Format file | Snowflake |
|---|---|
| terminator of fields 1 … n-1 | `FIELD_DELIMITER` |
| terminator of the last field | `RECORD_DELIMITER` (`"\r\n"` → `'\r\n'`) |
| `SQLCHAR` / `SQLNCHAR` host types | `TYPE = CSV` (`SQLNCHAR` files are UTF-16: `ENCODING = 'UTF16LE'`) |
| server column order and name | the `COPY INTO t (col, ...)` column list, in file-field order |
| server column order `0` | skip that field: leave its `$n` out of the transformation |
| task `CodePage` 1252 | `ENCODING = 'WINDOWS1252'` |
| task `FirstRow` *n* | `SKIP_HEADER = n - 1` |
| host length, prefix length, collation | no equivalent (use `TRUNCATECOLUMNS = TRUE` only if the source truncated) |

```sql
-- After: six file fields into server columns 4..9; the table's first three columns are not in the file
COPY INTO raw.CLM_Claim (CLM_NO, POL_NO, LOSS_DT, REPORTED_DT, STAT, LOSS_DESC)
FROM (SELECT $1, $2, $3, $4, $5, $6 FROM @public.landing_stage/history/claims/)
PATTERN = '.*/CLM_HIST_[^/]*[.]csv'   -- the loop's CLM_HIST_*.csv; see SSC-EWI-SSIS0024 Pattern 2
FILE_FORMAT = (TYPE = CSV, FIELD_DELIMITER = ',', RECORD_DELIMITER = '\r\n', SKIP_HEADER = 1,
               ENCODING = 'WINDOWS1252', NULL_IF = ('', 'NULL', 'null'))
ON_ERROR = SKIP_FILE_10;
```

Columns left out of the list take their `DEFAULT` or NULL. A column the source filled afterwards (a file name stamped by the next task) can be filled in the same `COPY` with `METADATA$FILENAME` / `METADATA$FILE_ROW_NUMBER`.

An XML format file (`<BCPFORMAT>`) carries the same facts: `<FIELD TERMINATOR=...>` in `<RECORD>`, `<COLUMN SOURCE=... NAME=...>` in `<ROW>`.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker.
- Check the generated `FIELD_DELIMITER` against the package: SSIS stores some terminators by name (`Comma`, `Semicolon`, `Tab`, `VerticalBar`). A `FIELD_DELIMITER = 'Comma'` must become `','`.
- A named `CREATE FILE FORMAT` is worth it only when several loads share the format; an inline `FILE_FORMAT = (...)` is fine otherwise.
- The stage still has to be resolved: see [SSC-EWI-SSIS0024](SSC-EWI-SSIS0024.md).
