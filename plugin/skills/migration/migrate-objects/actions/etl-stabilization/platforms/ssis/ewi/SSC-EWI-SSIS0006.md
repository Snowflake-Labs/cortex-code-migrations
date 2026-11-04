# SSC-EWI-SSIS0006 — Execute Package Task Parameter Bindings Not Converted

An Execute Package task passes parent variables to the child package's parameters (`<ParameterAssignment>`), but the child is started with `EXECUTE TASK` ([SSC-EWI-SSIS0005](SSC-EWI-SSIS0005.md)), and SnowConvert passes no values with it. The child runs with its default parameter values. The marker **breaks compilation**. A child converted to a procedure gets the values through `CALL public.<child>(:inherited_vars)` and never has this marker.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Once per Execute Package task with parameter assignments whose child is a task graph |
| Common action | Pass the values as a run-time config: `EXECUTE TASK ... USING CONFIG` |

## Identification

First in the chain, before the async marker:

```sql
---- Start block 'Package\LocalExecutePackageTaskWithParams'
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0006 - SSIS EXECUTE PACKAGE TASK VARIABLE BINDINGS WERE NOT CONVERTED. ***/!!!!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0005 - SSIS EXECUTE PACKAGE TASK WAS CONVERTED TO A SNOWFLAKE EXECUTE TASK STATEMENT THAT RUNS ASYNCHRONOUSLY. ***/!!!
EXECUTE TASK public.employee_names;
```

The bindings are in the parent `.dtsx`:

```xml
<ExecutePackageTask>
  <UseProjectReference>True</UseProjectReference>
  <PackageName>employee_names.dtsx</PackageName>
  <ParameterAssignment>
    <ParameterName>NewParameterName</ParameterName>
    <BindedVariableOrParameterName>System::MachineName</BindedVariableOrParameterName>
  </ParameterAssignment>
</ExecutePackageTask>
```

The child's root task (`CREATE OR REPLACE TASK public.employee_names`) has a `CONFIG = $${ "package": {...}, "project": {...} }$$`. Its body loads that config into `public.control_variables` (`ClearVariables`, then `InitVariablesFromConfig`), and the child's tasks read the variables from there. Find the child parameter's key in that `CONFIG`; package parameters are named `Package_<ParameterName>`.

## Fix Patterns

### Pattern 1: Override the child's config for this run

`EXECUTE TASK <root> USING CONFIG = '<json>'` merges the JSON into the root task's `CONFIG` for that one run, so the child's root task loads the passed values. Copy each entry's `type` and `is_parameter` from the child's `CONFIG`. A value that comes from a parent variable means the statement has to be built at run time:

```sql
-- After (in the parent task; the parent reads its own variables as SnowConvert does, with GetControlVariableUDF)
LET child_config VARCHAR := OBJECT_CONSTRUCT('package', OBJECT_CONSTRUCT(
   'Package_BatchID', OBJECT_CONSTRUCT(
      'value', public.GetControlVariableUDF('User_BatchID', 'ops_master_nightly'),
      'type', 'NUMBER',
      'is_parameter', TRUE)))::VARCHAR;
EXECUTE IMMEDIATE 'EXECUTE TASK public.load_claims USING CONFIG = ''' || REPLACE(:child_config, '''', '''''') || '''';
```

For a binding to a system variable (`System::MachineName` above), use the replacement in [SSC-EWI-SSIS0046](SSC-EWI-SSIS0046.md) or a literal.

### Pattern 2: The child exists as a procedure

When the output has `CREATE OR REPLACE PROCEDURE public.<child>(p_inherited_vars VARCHAR DEFAULT null)`, use the shape SnowConvert generates for reusable packages:

```sql
LET inherited_vars VARCHAR := OBJECT_CONSTRUCT('Package_BatchID', public.GetControlVariableUDF('User_BatchID', 'ops_master_nightly'))::VARCHAR;
CALL public.load_claims(:inherited_vars);
```

`public.ApplyInheritedVariables` updates only the `control_variables` rows whose `variable_name` matches a key exactly. Use the child's variable name as the key (`Package_BatchID`), not the bare `ParameterName`.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker, then resolve [SSC-EWI-SSIS0005](SSC-EWI-SSIS0005.md).
- `USING CONFIG` applies to that run only; scheduled runs go back to the task's `CONFIG`. If the child graph is already running, Snowflake runs the configured run after the current one. If several callers issue it before then, only the last config is used.
- Bindings pass values from parent to child only; SSIS has no way for the child to write a parent variable through them.
