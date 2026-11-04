# SSC-EWI-SSIS0020 — Bulk Insert Native Data File Not Supported

A Bulk Insert task had `DataFileType` set to `Native` or `WideNative`: the file is in bcp native format, SQL Server's binary layout. Snowflake cannot read it. SnowConvert still generated its usual `COPY INTO ... FILE_FORMAT = (TYPE = 'CSV', ...)` with the default terminators, which cannot parse the file. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Rare (once per Bulk Insert task with a native data file) |
| Common action | Replace the file hop with a table read, or have the file re-exported as text; usually needs-user |

## Identification

Chained after [SSC-EWI-SSIS0024](SSC-EWI-SSIS0024.md). A native task sets no terminators, so [SSC-FDM-SSIS0017](SSC-FDM-SSIS0017.md) and [SSC-FDM-SSIS0018](SSC-FDM-SSIS0018.md) come with it:

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0024 - ... ***/!!!!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0020 - SSIS BULKINSERTTASK NATIVE OR WIDENATIVE DATA FILE TYPE IS NOT SUPPORTED IN SNOWFLAKE. EXPORT SOURCE DATA TO CSV FORMAT BEFORE MIGRATION. ***/!!!
--** SSC-FDM-SSIS0013 - ... **
--** SSC-FDM-SSIS0017 - FIELD TERMINATOR NOT SPECIFIED IN DTSX. USING SSIS DEFAULT VALUE ','. VERIFY THIS MATCHES YOUR DATA FILE FORMAT. **
--** SSC-FDM-SSIS0018 - ROW TERMINATOR NOT SPECIFIED IN DTSX. USING SSIS DEFAULT VALUE '\r\n'. VERIFY THIS MATCHES YOUR DATA FILE FORMAT. **
COPY INTO dbo.BinaryData
FROM '@{STAGE_PLACEHOLDER}'
PATTERN = '.*binary_data\\.dat.*'
FILE_FORMAT = (TYPE = 'CSV', FIELD_DELIMITER = ',', RECORD_DELIMITER = '\r\n', SKIP_HEADER = 0, NULL_IF = ('', 'NULL', 'null'), ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE)
ON_ERROR = SKIP_FILE_10;
```

In the `.dtsx`: `BulkInsertTask:DataFileType="DTSBulkInsert_DataFileType_Native"` (or `_WideNative`). Native files are almost always written by `bcp <table> out <file> -n` (or `-N`): look for an Execute Process task or a SQL Agent step that runs `bcp`, to learn which table the file comes from.

## Fix Patterns

### Pattern 1: The exported table is also in Snowflake

A native file is a SQL Server-to-SQL Server copy. When the table `bcp` exported was migrated too, drop the file and copy the table directly:

```sql
-- Was: bcp Sales.dbo.BinaryData out binary_data.dat -n, then Bulk Insert into dbo.BinaryData
INSERT INTO dbo.BinaryData
SELECT * FROM sales.dbo.BinaryData;
```

List the columns when the two tables do not match one to one. Remove the export step (or note it as no longer needed).

### Pattern 2: The file comes from outside

Snowflake has no reader for bcp native files, so whoever produces the file must export text instead (`bcp ... out -c -t "|" -r "\n"`, or a CSV or Parquet export). Write the `COPY` for the format you ask for, and say so:

```sql
-- NEEDS-USER: dbo.BinaryData was loaded from a bcp native file, which Snowflake cannot read.
-- Re-export it as text (bcp -c -t "|" -r "\n") to @public.landing_stage/binary_data/binary_data.txt.
COPY INTO dbo.BinaryData
FROM @public.landing_stage/binary_data/
FILES = ('binary_data.txt')
FILE_FORMAT = (TYPE = CSV, FIELD_DELIMITER = '|', RECORD_DELIMITER = '\n', SKIP_HEADER = 0)
ON_ERROR = ABORT_STATEMENT;
```

`FILES` names the one file exactly; a `PATTERN` such as `'.*binary_data[.]txt'` also loads `old_binary_data.txt`. Mark as needs-user.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker; the stage marker [SSC-EWI-SSIS0024](SSC-EWI-SSIS0024.md) still applies to Pattern 2.
- The generated `FIELD_DELIMITER = ','` and `RECORD_DELIMITER = '\r\n'` are placeholders here, not facts about the file: set them to the new export's.
- A `-w` (Unicode text) export is UTF-16: add `ENCODING = 'UTF16LE'`. The same holds for a `WideChar` task, which gets no marker.
- `TYPE = PARQUET` with `MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE` is the simplest load if the producer can write Parquet.
