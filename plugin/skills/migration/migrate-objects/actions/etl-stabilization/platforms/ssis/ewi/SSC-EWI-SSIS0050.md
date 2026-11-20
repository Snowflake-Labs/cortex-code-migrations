# SSC-EWI-SSIS0050 — Unbound `?` Parameter Marker

An Execute SQL task's SQL has more positional `?` markers than the task has positional parameter bindings. SnowConvert replaced the `?`s it could with the bound variables, in order, and left the rest as a literal `?`, which is not valid Snowflake SQL. The marker **breaks compilation**. Named `@x` markers without a binding are left alone and not flagged, since they may be T-SQL local variables.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low to moderate (logging and audit tasks that pass `System::` values) |
| Common action | Replace each remaining `?` with the variable SSIS bound to it |

## Identification

The marker is on the task's **first** statement, even when the `?` is further down. Search the whole block for `?`. It often comes with [SSC-EWI-SSIS0011](SSC-EWI-SSIS0011.md):

```sql
---- Start block 'Package\Execute SQL Task 3'
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0050 - THE PARAMETER MARKER '?' HAS NO MATCHING PARAMETER BINDING AND WAS LEFT UNRESOLVED. MAP THE PARAMETER IN THE EXECUTE SQL TASK OR REPLACE THE MARKER MANUALLY. ***/!!!!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0011 - ... ***/!!!
DECLARE
   TABLE_NAME VARCHAR(100) := ?;
   SSIS_PACKAGE_NAME VARCHAR(100) := ?;
   SSIS_TASK_NAME VARCHAR(100) := ?;
```

The bindings are in the task: `<SQLTask:ParameterBinding SQLTask:ParameterName="0" SQLTask:DtsVariableName="User::LogMsg" SQLTask:ParameterDirection="Input" ... />`. OLE DB numbers them from `0`, ODBC from `1`. A binding whose `ParameterName` starts with `@` is a named binding and never fills a `?`.

## Fix Patterns

### Pattern 1: Bindings exist, but fewer or named differently

Map the `?`s in source order to the bindings sorted by `ParameterName` (`0`, `1`, ...). SnowConvert consumes positional bindings in sequence, not by `ParameterName`, so also check the `?`s it already replaced:

```sql
-- After
DELETE FROM dbo.StaleRows WHERE Id = :User_StaleId;
```

A task-body variable has to be declared in that block, as SnowConvert does for the variables it binds: `LET User_StaleId NUMBER := public.GetControlVariableUDF('User_StaleId', '<package>') :: NUMBER;`. Copy the scope from another `GetControlVariableUDF` call in the file.

### Pattern 2: `System::` values in a logging header

`DECLARE @SSIS_Package_Name varchar(100) = ?` blocks are usually bound to `System::PackageName`, `System::TaskName`, `System::UserName`:

```sql
-- After
DECLARE
   TABLE_NAME VARCHAR(100) := :User_TableName;
   SSIS_PACKAGE_NAME VARCHAR(100) := SYSTEM$TASK_RUNTIME_INFO('CURRENT_ROOT_TASK_NAME');
   SSIS_TASK_NAME VARCHAR(100) := 'Execute SQL Task 3';
   USER_EXECUTING_SSIS VARCHAR(100) := CURRENT_USER();
```

See [SSC-EWI-SSIS0046](SSC-EWI-SSIS0046.md) for the other system variables.

### Pattern 3: Stored procedure call

`EXEC dbo.usp_X ?, ?` becomes `CALL dbo.usp_X(:User_A, :User_B);` (see [SSC-EWI-SSIS0003](SSC-EWI-SSIS0003.md) for the `EXEC` rewrite). For a binding with `ParameterDirection="Output"`, read the procedure's return value: `SELECT $1 INTO :User_A FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));`, then publish it with `public.UpdateControlVariable`.

### Pattern 4: The task has no bindings at all

With no bindings, an OLE DB task fails at run time in SSIS ("No value given for one or more required parameters"). The task was unused, or its bindings were set elsewhere. Add `-- NEEDS-USER: '?' in <task> has no binding in the package; which value was intended?` and mark as needs-user.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker, and leave no literal `?` in the block.
- Only static SQL gets this marker. SQL read from a variable or built from an expression is run with `EXECUTE IMMEDIATE ... USING (...)`, where `?` is valid.
- Fix the rest of the chained markers ([SSC-EWI-SSIS0011](SSC-EWI-SSIS0011.md) for the result binding) in the same block.
