# SSC-FDM-SSIS0020 — Legacy .xls / .xlsb Workbook

The Excel Source's file name ends in `.xls` or `.xlsb`. `excel_source_udf` picks its reader from the file extension: `xlrd` for `.xls`, `pyxlsb` for `.xlsb`, `openpyxl` otherwise. The two legacy readers return dates as Excel serial numbers and numbers as floats, so the generated `TRY_TO_DATE` / `TRY_TO_TIMESTAMP` columns can come back NULL or wrong. The FDM is informational.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Low (once per Excel Source on an .xls/.xlsb file) |
| Common action | Convert date columns from the serial number; check text columns that hold numeric codes |

## Identification

Look for the marker:
```
--** SSC-FDM-SSIS0020 - LEGACY .XLS OR BINARY .XLSB FILE 'legacy_data.xls' MAY HAVE MINOR DIFFERENCES IN DATE/NUMBER HANDLING COMPARED TO .XLSX. THE UDF AUTO-DETECTS FORMAT FROM FILENAME. FOR DATE COLUMNS, CONSIDER USING DATEADD SERIAL CONVERSION PATTERN. **
```

At the top of the Excel staging model:

```sql
--** SSC-FDM-SSIS0020 - LEGACY .XLS OR BINARY .XLSB FILE 'legacy_data.xls' ... **
--Original Excel path: Provider=Microsoft.Jet.OLEDB.4.0;Data Source=C:\data\legacy_data.xls;Extended Properties="Excel 8.0;HDR=YES";
WITH excel_raw_data AS
(
   SELECT data
   FROM TABLE(excel_source_udf('@public.landing_stage/ssis/Package/legacy_data.xls', 'Sheet1', 'YES'))
),
parsed_data AS
(
   SELECT data['Name'] :: VARCHAR AS Name, TRY_TO_DOUBLE(data['Amount'] :: VARCHAR) AS Amount
   FROM excel_raw_data
)
SELECT * FROM parsed_data
```

Check what the cells hold before changing anything: `SELECT data FROM TABLE(excel_source_udf('<path>', '<sheet>', 'YES')) LIMIT 10`.

## Fix Patterns

### Pattern 1: No date columns (most common)

Numbers and text read the same as from `.xlsx` for typed numeric columns. Leave the comment.

### Pattern 2: Date and time columns

A date cell arrives as days since 1899-12-30 (`45292.0` is 2024-01-01); the fraction is the time of day.

```sql
-- Before
TRY_TO_DATE(data['LossDate'] :: VARCHAR) AS LossDate,
TRY_TO_TIMESTAMP(data['ReportedAt'] :: VARCHAR) AS ReportedAt
-- After
DATEADD(day, FLOOR(TRY_TO_DOUBLE(data['LossDate'] :: VARCHAR)), '1899-12-30'::DATE) AS LossDate,
DATEADD(second, ROUND(TRY_TO_DOUBLE(data['ReportedAt'] :: VARCHAR) * 86400), '1899-12-30'::TIMESTAMP_NTZ) AS ReportedAt
```

If the same column can also hold dates typed as text, keep both: `COALESCE(TRY_TO_DATE(data['X'] :: VARCHAR), DATEADD(day, FLOOR(TRY_TO_DOUBLE(data['X'] :: VARCHAR)), '1899-12-30'::DATE))`. A workbook saved with the 1904 date system (old Mac files) counts from `1904-01-01`.

### Pattern 3: Text columns holding numeric codes

A cell typed as a number (`1001`) comes back as a float. If a `VARCHAR` column shows `1001.0`, convert it: `TO_VARCHAR(TRY_TO_NUMBER(data['PolicyNo'] :: VARCHAR, 38, 0)) AS PolicyNo`. Leading zeros are already gone in the workbook when the cell is numeric.

## Key Points

- Do **NOT** remove the FDM comment.
- The reader is chosen from the staged file's extension (after stripping `.gz` / `.bz2` / `.zst`); renaming an `.xls` to `.xlsx` on the stage breaks the read.
- With `HDR=NO` the columns are `F1`, `F2`, ...; with `HDR=YES` a numeric header cell in a legacy file becomes a key like `2024.0`.
