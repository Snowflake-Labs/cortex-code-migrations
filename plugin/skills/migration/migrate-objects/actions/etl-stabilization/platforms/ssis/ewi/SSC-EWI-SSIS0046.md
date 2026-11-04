# SSC-EWI-SSIS0046 — SSIS System Variable Not Supported

A `System::` variable has no automatic Snowflake equivalent, so SnowConvert left it as `:System_<Name>`, which is never declared. The marker **breaks compilation**. It shows up most in event-handler procedures (`OnError`, `OnPostExecute`) that log `ErrorDescription`, `SourceName` and `StartTime`.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Moderate (once per unmapped system variable reference) |
| Common action | Replace with the equivalent below, or pass the value in as an argument |

SnowConvert already maps `UserName` → `CURRENT_USER()`, `PackageName` → `SYSTEM$TASK_RUNTIME_INFO('CURRENT_ROOT_TASK_NAME')`, `PackageID` → `SYSTEM$TASK_RUNTIME_INFO('CURRENT_ROOT_TASK_UUID')` and `ExecutionInstanceGUID` → `SYSTEM$TASK_RUNTIME_INFO('CURRENT_TASK_GRAPH_RUN_GROUP_ID')`.

## Identification

```sql
INSERT INTO etl_results.package_system_variables (username, packagename, packageid, starttime, executioninstanceguid)
VALUES (CURRENT_USER(), SYSTEM$TASK_RUNTIME_INFO('CURRENT_ROOT_TASK_NAME'), SYSTEM$TASK_RUNTIME_INFO('CURRENT_ROOT_TASK_UUID'),
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0046 - THE SSIS SYSTEM VARIABLE 'StartTime' DOES NOT HAVE A DIRECT EQUIVALENT IN SNOWFLAKE TASK GRAPHS AND CANNOT BE AUTOMATICALLY CONVERTED. ***/!!!
:System_StartTime, SYSTEM$TASK_RUNTIME_INFO('CURRENT_TASK_GRAPH_RUN_GROUP_ID'));
```

## Fix Patterns

| System variable | Snowflake |
|---|---|
| `StartTime` | the root task's start: `TO_TIMESTAMP_LTZ(SYSTEM$TASK_RUNTIME_INFO('CURRENT_TASK_GRAPH_ORIGINAL_SCHEDULED_TIMESTAMP'))` (the scheduled time, a string); or capture `CURRENT_TIMESTAMP()` in the root task and publish it as a control variable |
| `ContainerStartTime` | `CURRENT_TIMESTAMP()` at the start of the block |
| `TaskName`, `SourceName` | the task's name as a literal (it is in the `---- Start block '...'` comment), or `SYSTEM$TASK_RUNTIME_INFO('CURRENT_TASK_NAME')` inside a task body |
| `ErrorDescription` | `SQLERRM` |
| `ErrorCode` | `SQLCODE` (Snowflake's numbers, not SSIS's) |
| `MachineName` | no equivalent: a literal or NULL, and note it |
| `VersionMajor`, `VersionBuild`, `CreationDate`, `CreatorName` | the package's design-time values, as literals |

`SYSTEM$TASK_RUNTIME_INFO` errors outside a task run. `SQLERRM` and `SQLCODE` are only set inside `EXCEPTION WHEN OTHER THEN`.

### Pattern 1: An event-handler procedure

The handler is a separate procedure ([SSC-FDM-SSIS0006](SSC-FDM-SSIS0006.md)) and is called from the failing task's exception block, so the error context exists only at the caller. Give the handler parameters and pass the values in:

```sql
-- Handler
CREATE OR REPLACE PROCEDURE public.ops_master_nightly_onerror_handler(SOURCE_NAME VARCHAR, ERROR_DESCRIPTION VARCHAR, ERROR_CODE NUMBER)
...
   INSERT INTO etl.ErrorLog (SourceName, ErrorDescription, ErrorCode, PackageName)
   VALUES (:SOURCE_NAME, :ERROR_DESCRIPTION, :ERROR_CODE, SYSTEM$TASK_RUNTIME_INFO('CURRENT_ROOT_TASK_NAME'));

-- Caller, in the task body
EXCEPTION
   WHEN OTHER THEN
      LET err_msg VARCHAR := SQLERRM;
      LET err_code NUMBER := SQLCODE;
      CALL public.ops_master_nightly_onerror_handler('SQL Load Claims', :err_msg, :err_code);
      RAISE;
```

### Pattern 2: A task body

Replace `:System_<Name>` with the expression from the table and remove the marker.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker.
- Re-raise after logging (`RAISE;`) when the SSIS package failed on error; logging alone swallows the failure.
- `HOST_NAME()` in the same statement has no Snowflake equivalent either: a literal or NULL.
- An expression variable that reads a system variable (`YEAR(@[System::StartTime])`) needs the same replacement where the variable is computed.
