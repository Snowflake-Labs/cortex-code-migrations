# SSC-EWI-SSIS0026 — Property Expression Not Supported

A task or connection manager has a property expression for a property SnowConvert does not translate. The marker names the property: `PROPERTY EXPRESSION 'Disable' IS NOT SUPPORTED.` When it is inline, it **breaks compilation**. Some cases are only recorded in the issues report, with no marker in the code.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) when inline; report-only for a connection `ConnectionString` |
| Breaks compilation? | **Yes**, when inline |
| Frequency | Low |
| Common action | `Disable`: wrap the body in `IF`. Connection properties: check the generated path or model |

## Identification

On a task, the marker is the first statement of the task body:

```sql
BEGIN
   CALL public.SetRunContext();
   !!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0026 - PROPERTY EXPRESSION 'Disable' IS NOT SUPPORTED. ***/!!!
   LET User_message VARCHAR := public.GetControlVariableUDF('User_message', 'disabled_property_expression') :: VARCHAR;
   LET User_ShouldDisable BOOLEAN := public.GetControlVariableUDF('User_ShouldDisable', 'disabled_property_expression') :: BOOLEAN;
   ---- Start block 'Package\dynamic_disabled_expression'
   User_message := UPPER(:User_message || 'message');
```

For a Flat File source connection, an inline marker lands in the dbt model for any property other than `ConnectionString`. A `ConnectionString` expression appears only in the issues report.

## Fix Patterns

### Pattern 1: `Disable` expression on a task

The task ran only when the expression was false. Keep the body and guard it:

```sql
-- After
BEGIN
   CALL public.SetRunContext();
   LET User_message VARCHAR := public.GetControlVariableUDF('User_message', 'disabled_property_expression') :: VARCHAR;
   LET User_ShouldDisable BOOLEAN := public.GetControlVariableUDF('User_ShouldDisable', 'disabled_property_expression') :: BOOLEAN;
   IF (NOT :User_ShouldDisable) THEN
      ---- Start block 'Package\dynamic_disabled_expression'
      User_message := UPPER(:User_message || 'message');
      ---- End block 'Package\dynamic_disabled_expression'
   END IF;
```

The expression is in the package (`<DTS:PropertyExpression DTS:Name="Disable">`). Translate it as an SSIS expression ([SSC-EWI-SSIS0002](SSC-EWI-SSIS0002.md)) when it is more than one Boolean variable.

### Pattern 2: `ConnectionString` on a Flat File or Excel source inside a Foreach loop

The expression points the connection at the loop's current file (`@[User::CurrentFile]`). Check that the generated model or task reads the loop's current stage path, not the design-time sample file named in the connection. If it reads the sample file, change it to the loop's path; if the model cannot take a per-file path, load all files with one `PATTERN` instead and note it.

### Pattern 3: Another connection property (`ColumnDelimiter`, `HeaderRowsToSkip`, `CodePage`)

Evaluate the expression. A constant (or a project parameter) becomes the matching `FILE_FORMAT` option in the model. A value that changes per run cannot be expressed in a static `FILE_FORMAT`: mark as needs-user with the expression quoted.

## Key Points

- **Must** remove an inline `!!!RESOLVE EWI!!!` marker.
- A report-only entry still needs checking: the code compiles but may read the wrong file.
- A task disabled outright (`DTS:Disabled="True"`, no expression) is [SSC-FDM-SSIS0029](SSC-FDM-SSIS0029.md), not this.
