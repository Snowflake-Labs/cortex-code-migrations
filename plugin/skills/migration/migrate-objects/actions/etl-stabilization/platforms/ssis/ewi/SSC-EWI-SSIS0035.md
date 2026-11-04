# SSC-EWI-SSIS0035 — Header Row Delimiter Is Not a Newline

The Flat File connection skips header rows (`DTS:HeaderRowsToSkip` ≥ 1) that end in a `DTS:HeaderRowDelimiter` other than CRLF, LF or CR. SnowConvert generated the full staging model and put `SKIP_HEADER = <HeaderRowsToSkip>` in its `FILE FORMAT`, but Snowflake's `SKIP_HEADER` counts newline-terminated lines, not rows ending in that delimiter. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (once per Flat File Source on such a connection) |
| Common action | Set `SKIP_HEADER` to the number of physical lines the header takes |

## Identification

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0035 - FLAT FILE HEADER ROW DELIMITER IS NOT A NEWLINE CHARACTER. THIS IS NOT SUPPORTED. ***/!!!
SELECT
   $1 :: VARCHAR(50) AS col_a,
   $2 :: VARCHAR(50) AS col_b
FROM
   @public.landing_stage/ssis/TestPackage/MyFlatFile/input.csv (FILE_FORMAT => 'TestPackage_Data_Flow_Task_Flat_File_Source')
WHERE
   METADATA$FILE_ROW_NUMBER > 1
```

The format, with its `SKIP_HEADER`, is in `etl_configuration/file_formats/file_formats.sql` under the name in `FILE_FORMAT => '...'`. In the connection: `DTS:HeaderRowDelimiter="_x003B_"` (`;`), `DTS:HeaderRowsToSkip="2"`. The `WHERE` drops the column-name row and `DTS:DataRowsToSkip`, which use the row delimiter and are not affected.

## Fix Patterns

Look at a sample file's first lines before choosing.

### Pattern 1: The header ends at a line break

For example, one banner line `RUN;2024-06-30;BATCH 17;` followed by a newline, with `HeaderRowsToSkip = 3`. Count the physical lines the header occupies and set that, then remove the marker:

```sql
CREATE FILE FORMAT IF NOT EXISTS TestPackage_Data_Flow_Task_Flat_File_Source
TYPE = 'CSV'
FIELD_DELIMITER = ','
SKIP_HEADER = 1          -- was 3: three ';'-terminated header rows on one physical line
EMPTY_FIELD_AS_NULL = TRUE;
```

### Pattern 2: The data starts on the same line as the header

`SKIP_HEADER` cannot skip part of a line. If the header and the first data row share a line, the file needs a pre-processing step (in the land process, or a Snowpark/Python procedure that rewrites the file into the stage). Add `-- NEEDS-USER: header of <file> ends mid-line; files need pre-processing before load` and mark as needs-user.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker.
- The format is created `IF NOT EXISTS`: in an account where it is already deployed, a changed `SKIP_HEADER` takes effect only after a `CREATE OR REPLACE FILE FORMAT` or `ALTER FILE FORMAT ... SET SKIP_HEADER = n`.
- A header line that contains the field delimiter or quotes is still skipped whole; nothing else in the format needs to change.
- Other connection settings SnowConvert could not carry over: [SSC-EWI-SSIS0036](SSC-EWI-SSIS0036.md).
