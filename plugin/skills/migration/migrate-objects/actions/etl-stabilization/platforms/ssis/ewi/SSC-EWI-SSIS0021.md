# SSC-EWI-SSIS0021 — Bulk Insert LastRow Not Supported

A Bulk Insert task had `LastRow` set: SQL Server loaded only file rows `FirstRow` through `LastRow`. `COPY INTO` has no row limit, and its transformation `SELECT` takes no `WHERE`. SnowConvert turned `FirstRow` into `SKIP_HEADER = FirstRow - 1` and dropped `LastRow`, so the generated `COPY` loads every row to the end of the file. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Rare (once per Bulk Insert task with a positive LastRow) |
| Common action | Copy the file with `METADATA$FILE_ROW_NUMBER` into a temporary table, then `INSERT` the row range |

## Identification

Chained with the other Bulk Insert EWIs:

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0024 - ... ***/!!!!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0021 - SSIS BULKINSERTTASK LASTROW OPTION IS NOT SUPPORTED IN SNOWFLAKE. USE TEMPORARY TABLE WITH ROW_NUMBER AND LIMIT/OFFSET TO SELECT SPECIFIC ROW RANGE. ***/!!!!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0023 - ... ***/!!!
--** SSC-FDM-SSIS0011 - ... **
COPY INTO dbo.LargeDataset
FROM '@{STAGE_PLACEHOLDER}'
PATTERN = '.*large_dataset\\.csv.*'
FILE_FORMAT = (TYPE = 'CSV', FIELD_DELIMITER = ',', RECORD_DELIMITER = '\n', SKIP_HEADER = 1, NULL_IF = ('', 'NULL', 'null'), ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE)
ON_ERROR = SKIP_FILE_50;
```

The marker does not show the value: read `BulkInsertTask:LastRow` and `BulkInsertTask:FirstRow` in the `.dtsx`. Both count file rows from 1, header included.

## Fix Patterns

### Pattern 1: Copy the file into a temporary table and keep the row range

Ignore the marker's `ROW_NUMBER` / `LIMIT` advice: a file has no row order a query can rely on. `METADATA$FILE_ROW_NUMBER` is the record's position in its file. Copy the one file, with that number, into a temporary table of `VARCHAR` columns, then filter while inserting. `SKIP_HEADER = 0` keeps the numbers equal to `FirstRow` / `LastRow`, and the `VARCHAR` columns let the header row load:

```sql
-- Task body: FirstRow = 2, LastRow = 50000
CREATE OR REPLACE TEMPORARY TABLE large_dataset_rows (ID VARCHAR, Name VARCHAR, Amount VARCHAR, file_row NUMBER);
COPY INTO large_dataset_rows
FROM (SELECT $1, $2, $3, METADATA$FILE_ROW_NUMBER FROM @public.landing_stage/large/)
FILES = ('large_dataset.csv')
FILE_FORMAT = (TYPE = CSV FIELD_DELIMITER = ',' RECORD_DELIMITER = '\n' SKIP_HEADER = 0 NULL_IF = ('', 'NULL', 'null'));
INSERT INTO dbo.LargeDataset (ID, Name, Amount)
SELECT ID::NUMBER(38, 0), Name, Amount::NUMBER(18, 2)   -- the target's column types
FROM large_dataset_rows
WHERE file_row BETWEEN 2 AND 50000;
```

`FILES` names the one file SSIS loaded, and nothing else: a `PATTERN` such as `'.*large_dataset[.]csv'` also loads `old_large_dataset.csv`, and would apply the row range to it too.

### Pattern 2: Also a format file

With [SSC-EWI-SSIS0023](SSC-EWI-SSIS0023.md), build the `FILE_FORMAT` options and the `$n` column list from the format file, then apply Pattern 1.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker; the stage marker [SSC-EWI-SSIS0024](SSC-EWI-SSIS0024.md) still applies.
- The casts run in the `INSERT`, which has no `ON_ERROR`: one bad value fails the statement, like `ON_ERROR = ABORT_STATEMENT`. If the task tolerated errors ([SSC-FDM-SSIS0011](SSC-FDM-SSIS0011.md)), use `TRY_TO_NUMBER` / `TRY_TO_DATE` on the columns that can be bad, and say so in a comment.
- A temporary table starts with no load history, so the `COPY` loads the file on every run, as `BULK INSERT` did.
- A target table with a `CHECK` constraint cannot be loaded with `COPY` at all; the `INSERT` from the temporary table works. See [SSC-FDM-SSIS0016](SSC-FDM-SSIS0016.md).
- Keep the `LastRow` value as it is. If it looks like a test cap left in a production package (a round number on a full load), keep it and add a `-- NEEDS-USER:` question.
