# SSC-EWI-SSIS0031 — Excel Stage File Path Variable Needs Mapping

Older SnowConvert output for an Excel Source: the orchestration defined a CONFIG variable holding the workbook's stage path, with a default built from the SSIS file name, and the Excel model read the workbook from that variable. The current engine does **not** emit this marker: an Excel model now calls `excel_source_udf` with a literal path under the project's landing stage (`@public.landing_stage/ssis/<Package>/<file>`), and no such variable is created. Expect it only in output from an older conversion. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Rare (not emitted by the current engine) |
| Common action | Point the variable's value at the staged workbook (or bind the literal path) and remove the marker |

## Identification

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0031 - THE GENERATED ORCHESTRATION DEFINES CONFIG VARIABLE '<prefix>_stage_file_path' (STAGE FILE PATH) WITH DEFAULT VALUE FROM THE ORIGINAL SSIS PACKAGE. UPDATE THIS VARIABLE IN THE TASK CONFIG SECTION TO POINT TO YOUR SNOWFLAKE STAGE AND EXCEL FILE PATH (E.G., @MY_STAGE/FILE.XLSX) BEFORE EXECUTION. ***/!!!
```

The variable is named `<package>_<data flow>_<component>_stage_file_path`; its default is `@excel_source_stage/<file>.xlsx`, a stage nobody created. The Excel read passes it as the first argument: `excel_source_udf(GetControlVariableUDF('<prefix>_stage_file_path', :scope), '<sheet>', 'YES')` in a script, or a `{{ var('...') }}` in a dbt model. Usually next to [SSC-FDM-SSIS0019](SSC-FDM-SSIS0019.md).

## Fix Patterns

### Pattern 1: The project has a landing stage

Set the variable's default (in the CONFIG section / control-variable setup) to where the file actually lands, the same layout the current engine binds:

```sql
'@public.landing_stage/ssis/<Package>/claims.xlsx'
```

Or replace the variable read in the call with that literal; then the CONFIG variable is unused and can go.

### Pattern 2: No stage holds the workbook

Use the stage path you expect, add `-- NEEDS-USER: stage <file> (from <original Windows path>) at <path>`, and mark needs-user. Files are loaded with `PUT` from a client, Snowsight upload, or an external stage; `PUT` cannot run inside a task.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker.
- The path must include the file name and extension: the UDF picks `.xls` / `.xlsb` / `.xlsx` parsing from it.
- The owner of `EXCEL_SOURCE_UDF` needs read access on the stage (`READ` on an internal stage, `USAGE` on an external one).
- Stage setup itself: see [SSC-EWI-SSIS0024](SSC-EWI-SSIS0024.md).
