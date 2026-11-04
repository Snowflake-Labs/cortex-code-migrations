# SSC-EWI-SSIS0030 — Excel Source Uses a Project-Level Connection Manager

The Excel Source's connection points at a project-level connection manager (its `connectionManagerID` contains `Project.ConnectionManagers`), defined in a `.conmgr` file rather than in the .dtsx. The workbook's file name and `HDR` setting live in that file's `ConnectionString`. When the `.conmgr` was not part of the conversion input, the generated `excel_source_udf` call falls back to `excel_file.xlsx` and `'YES'`. The marker **breaks compilation**. Only the Excel Source emits it.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (once per Excel Source on a project connection) |
| Common action | Check the UDF call's file name and header flag against the `.conmgr`, fix them, remove the marker |

## Identification

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0030 - CONNECTION MANAGER 'Project.ConnectionManagers[Excel Claims]' IS DEFINED AT PROJECT LEVEL (IN .CONMGR FILE), NOT IN THE .DTSX PACKAGE. LOCATE THE CORRESPONDING .CONMGR FILE AND EXTRACT CONNECTIONSTRING FOR EXCEL FILE PATH AND HDR SETTING. ***/!!!
WITH excel_raw_data AS
(
   SELECT data
   FROM TABLE(excel_source_udf('@public.landing_stage/ssis/<Package>/excel_file.xlsx', 'Sheet1', 'YES'))
),
...
```

The `.conmgr` is in the SSIS project folder, named after the manager (`Excel Claims.conmgr`). Its `DTS:ConnectionManager/DTS:ObjectData/DTS:ConnectionManager` element has `DTS:ConnectionString="Provider=Microsoft.ACE.OLEDB.12.0;Data Source=\\fs01\share\claims.xlsx;Extended Properties=&quot;Excel 12.0 XML;HDR=NO&quot;;"`.

If the `.conmgr` *was* in the input, the manager resolves: the model then has a `--Original Excel path: <connection string>` line and the real file name in the call, and only the check below is left.

## Fix Patterns

### Pattern 1: Placeholder file name

Take the file name from `Data Source` (the last path segment) and the header flag from `HDR=YES|NO` (default `YES`), and put them in the call. The stage folder stays `@public.landing_stage/ssis/<Package>/`, the same path the ingestion manifest lands the file in:

```sql
FROM TABLE(excel_source_udf('@public.landing_stage/ssis/<Package>/claims.xlsx', 'Claims', 'NO'))
```

With `HDR=NO` the UDF names the columns `F1`, `F2`, ...; change the `data['...']` keys in `parsed_data` to match.

### Pattern 2: `.conmgr` not available

If no `.conmgr` for the manager is in the project, write the file name you expect, add `-- NEEDS-USER: real workbook name and HDR for project connection 'Excel Claims'`, and mark needs-user.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker.
- The marker fires on the `connectionManagerID` text alone, so it also appears when the manager did resolve. Check the call; do not change a correct one.
- A project connection referenced as `connectionManagerID="{GUID}:external"` does not raise this marker but can still leave `excel_file.xlsx` in the call: check for that placeholder in every Excel model.
- A `ConnectionString` property expression on the manager is not applied to the call either (it is only reported, as [SSC-EWI-SSIS0026](SSC-EWI-SSIS0026.md)); rebuild the file name from the expression, with a `{{ var('...') }}` for any variable part.
- The sheet argument comes from the component's `OpenRowset` (`Sheet1` when empty); confirm it against the workbook.
