# SSC-FDM-SSIS0025 — Variable Must Hold a Snowflake Stage Path

A File System Task reads its source or destination from a variable that is not the Foreach loop's current file. SnowConvert spliced the variable into the stage command as it is, so the command works only if the variable's value is a stage path (`@db.schema.stage/path/`). In SSIS it held a file-system path (`\\server\share\...`, `C:\...`).

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Moderate (once per File System Task with a variable path) |
| Common action | Rewrite the variable's value or expression to produce a stage path |

## Identification

Look for the marker:
```
--** SSC-FDM-SSIS0025 - THE VARIABLE(S) VALUE(S) MUST CONTAIN A VALID SNOWFLAKE STAGE PATH. **
```

Above a `REMOVE` or an `EXECUTE IMMEDIATE 'COPY FILES ...'`:

```sql
--** SSC-FDM-SSIS0025 - THE VARIABLE(S) VALUE(S) MUST CONTAIN A VALID SNOWFLAKE STAGE PATH. **
EXECUTE IMMEDIATE 'COPY FILES INTO ''' || REPLACE(:User_DestFilePath, '''', '''''') || ''' FROM ''' || REPLACE(:User_SourceFilePath, '''', '''''') || '''';
```

Variables with an expression are expanded inline, followed by `/*Expanded Variable: @[User::X]*/`.

## Fix Patterns

### Pattern 1: A variable with a fixed value

Change where the variable is declared (its `GetControlVariableUDF` default or the control-variable setup) from the UNC path to the stage path that folder maps to. Keep the trailing `/` for a folder.

### Pattern 2: A variable built by an expression

Rewrite the expression to build a stage path. A project parameter that held the share root (`$Project::FileRoot` = `\\fs01\share`) becomes the stage root:

```sql
-- SSIS: @[$Project::FileRoot] + "\out\" + <yyyymm of DATEADD("mm", -@[$Package::ArchiveMonths], GETDATE())>
LET User_ExpiredOutboundFolder VARCHAR :=
   '@public.landing_stage/out/' || TO_CHAR(DATEADD(month, -:Package_ArchiveMonths, CURRENT_DATE()), 'YYYYMM') || '/';
```

### Pattern 3: The command takes the path directly

`REMOVE`, `LIST`, `COPY FILES` and `COPY INTO` take a bound scalar variable (`REMOVE :User_TempFolder;`) when its value is already a full stage reference starting with `@`. A value without the `@` (`'stg/archive/'`) fails with `invalid URL prefix found in: ...`. So when the generated code passes a variable straight to the command, keep it and fix the variable's value (Patterns 1 and 2). Build the statement as a string only for a cursor row field, which does not bind, or for a path assembled in the statement:

```sql
EXECUTE IMMEDIATE 'REMOVE ''' || REPLACE(:User_TempFolder || :User_FileName, '''', '''''') || '''';
```

`REMOVE` deletes every file whose path starts with the text: end a folder's path in `/` ([SSC-FDM-SSIS0028](SSC-FDM-SSIS0028.md)), and for a single file run both checks in [SSC-EWI-SSIS0044](SSC-EWI-SSIS0044.md) Pattern 1 (the `LIST` names the file itself, and the copy copied it) first, or `report.csv` also removes `report.csv.bak`.


## Key Points

- Do **NOT** remove the FDM comment.
- Which stage a share maps to is an environment fact. When the project has no stage for that share yet, write the stage path you expect and mark as needs-user.
- Backslashes from the SSIS path never belong in a stage path; use `/`.
