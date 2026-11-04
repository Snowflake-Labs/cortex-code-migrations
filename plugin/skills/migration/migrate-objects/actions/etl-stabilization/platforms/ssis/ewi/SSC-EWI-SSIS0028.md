# SSC-EWI-SSIS0028 — Excel Source Error-Row Redirection Not Translated

An Excel Source has at least one output column with `errorRowDisposition="RedirectRow"`: in SSIS, a cell that did not convert to the column's type sent its row down the error output. SnowConvert's Excel model reads every row through `excel_source_udf` and wraps typed columns in `TRY_TO_*`, so a bad cell becomes NULL and the row stays in the regular flow. The marker **breaks compilation**. Only the Excel Source emits it; OLE DB and Flat File sources do not.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (once per Excel Source with a redirected column) |
| Common action | Add an error-flag column to the Excel model and split the two branches on it |

## Identification

At the top of the Excel Source's staging model (`stg_*.sql`):

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0028 - SSIS ERROR OUTPUT WITH REDIRECTROW DISPOSITION CANNOT BE DIRECTLY TRANSLATED. USE TRY_TO_* FUNCTIONS WITH ERROR FLAG COLUMNS FOR DEFENSIVE ERROR HANDLING. CREATE SEPARATE ERROR CAPTURE MODELS IF NEEDED. ***/!!!
--Original Excel path: Provider=Microsoft.ACE.OLEDB.16.0;Data Source=C:\data\error_data.xlsx;Extended Properties="Excel 12.0 XML;HDR=YES";
WITH excel_raw_data AS
(
   SELECT data
   FROM TABLE(excel_source_udf('@public.landing_stage/ssis/Package/error_data.xlsx', 'DataSheet', 'YES'))
),
parsed_data AS
(
   SELECT TRY_TO_DOUBLE(data['ID'] :: VARCHAR) AS ID, TRY_TO_DOUBLE(data['Value'] :: VARCHAR) AS Value
   FROM excel_raw_data
)
SELECT * FROM parsed_data
```

In the .dtsx, the redirected columns are the Excel Source's `<outputColumn ... errorRowDisposition="RedirectRow">`; the path starting at its output with `isErrorOut="true"` leads to the error branch. The model at the end of that path carries [SSC-EWI-SSIS0049](SSC-EWI-SSIS0049.md). `truncationRowDisposition` is not checked: a truncation redirect alone does not raise this marker.

## Fix Patterns

### Pattern 1: Error branch exists downstream

The failure test needs the raw cell, which only the Excel model has. Compute it there as a flag column, then filter on it in both branches:

```sql
parsed_data AS
(
   SELECT
      TRY_TO_DOUBLE(data['ID'] :: VARCHAR) AS ID,
      TRY_TO_DOUBLE(data['Value'] :: VARCHAR) AS Value,
      CASE WHEN data['Value'] IS NOT NULL AND TRY_TO_DOUBLE(data['Value'] :: VARCHAR) IS NULL THEN 'Value' END AS ssis_error_column
   FROM excel_raw_data
)
SELECT * FROM parsed_data
```

- Regular downstream model: add `WHERE ssis_error_column IS NULL`.
- Error-branch model (the [SSC-EWI-SSIS0049](SSC-EWI-SSIS0049.md) one): `WHERE ssis_error_column IS NOT NULL`, and resolve that marker too.

Test only the columns marked `RedirectRow`, with the `TRY_` function the model already uses for that column; a truncation redirect is `LENGTH(data['X'] :: VARCHAR) > n`.

### Pattern 2: No error branch reaches a destination

When the error output goes nowhere (or to a Row Count only), filter the bad rows out of the regular flow with the same test, or keep them as NULLs if the destination accepts them and that matches what the business expects. If you cannot tell which, add `-- NEEDS-USER: SSIS redirected rows with bad <col>; now loaded with NULL` and mark needs-user.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker.
- A downstream model that selects explicit columns ignores the extra `ssis_error_column`; one that does `SELECT *` into a destination must drop it (`SELECT * EXCLUDE (ssis_error_column)`).
- Change both branches, or the bad rows land twice (once with NULLs, once in the error table).
- To see what the cells really hold, run `SELECT data FROM TABLE(excel_source_udf('<path>', '<sheet>', 'YES')) LIMIT 10`.
