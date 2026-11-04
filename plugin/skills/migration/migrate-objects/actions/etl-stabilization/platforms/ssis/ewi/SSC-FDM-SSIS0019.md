# SSC-FDM-SSIS0019 — Excel File Must Be Staged

Older SnowConvert output for an Excel Source: a reminder that the workbook has to be uploaded to a Snowflake stage before the model that reads it through `excel_source_udf` runs. The current engine does **not** emit this FDM: an Excel model now reads a literal path under the project's landing stage (`@public.landing_stage/ssis/<Package>/<file>`), listed in the ingestion manifest that lands the file. Expect it only in output from an older conversion. The FDM is informational.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Rare (not emitted by the current engine) |
| Common action | Check that the quoted stage path exists and holds the workbook |

## Identification

Look for the marker:
```
--** SSC-FDM-SSIS0019 - SNOWFLAKE REQUIRES EXCEL FILES TO BE STAGED BEFORE PROCESSING. THE GENERATED CODE REFERENCES STAGE FILE PATH '@excel_source_stage/claims.xlsx'. USE PUT COMMAND, SNOWSQL, SNOWSIGHT, OR OPENFLOW FOR FILE INGESTION. **
```

It sits above the Excel read (`TABLE(excel_source_udf(<path>, '<sheet>', '<YES|NO>'))`), usually with [SSC-EWI-SSIS0031](SSC-EWI-SSIS0031.md) for the variable that holds the path.

## Fix Patterns

### Pattern 1: No change

The path is a stage that exists and the workbook is landed there: leave the comment.

### Pattern 2: The quoted path is a placeholder stage

`@excel_source_stage/...` was a default nobody created. Change the path (or the variable behind it, see SSC-EWI-SSIS0031) to the stage the file lands in, e.g. `@public.landing_stage/ssis/<Package>/claims.xlsx`. If no stage receives the file, add `-- NEEDS-USER: stage <file>` and mark needs-user.

## Key Points

- Do **NOT** remove the FDM comment.
- `PUT` runs from a client (SnowSQL, Snowflake CLI, a driver), never inside a task or procedure.
- The `EXCEL_SOURCE_UDF` setup script (`etl_configuration/functions/EXCEL_SOURCE_UDF.sql`) must be run before the model; it creates `public.EXCEL_SOURCE_UDF`.
- Stage setup: see [SSC-EWI-SSIS0024](SSC-EWI-SSIS0024.md).
