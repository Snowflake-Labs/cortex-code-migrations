# SSC-EWI-SSIS0032 — Excel Source Sheet or Query From a Variable

The Excel Source used access mode 1 (Table name from variable: `OpenRowsetVariable`) or 3 (SQL command from variable: `SqlCommandVariable`). SnowConvert does not read the variable: the model calls `excel_source_udf` with the component's static `OpenRowset` value as the sheet (`Sheet1` when it is empty) and reads the whole sheet. The marker **breaks compilation**. Only the Excel Source emits it.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (once per Excel Source in a variable access mode) |
| Common action | Pass the sheet as a dbt var (mode 1), or rebuild the variable's query as CTEs (mode 3) |

## Identification

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0032 - EXCEL SOURCE ACCESS MODE Table from Variable (1) USES SSIS VARIABLE 'User::SheetName' TO RESOLVE THE SHEET NAME OR SQL QUERY AT RUNTIME. VARIABLE-BASED ACCESS MODES ARE NOT TRANSLATED. THE GENERATED MODEL READS THE FULL SHEET USING THE STATIC OPENROWSET VALUE. MANUALLY ADD THE DYNAMIC SHEET/QUERY LOGIC USING DBT VARS. ***/!!!
WITH excel_raw_data AS
(
   SELECT data
   FROM TABLE(excel_source_udf('@public.landing_stage/ssis/<Package>/claims.xlsx', 'Sheet1', 'YES'))
),
...
```

The mode text is `Table from Variable (1)` or `SQL Command from Variable (3)`. Find the variable in the package's `<DTS:Variables>` (its `DTS:VariableValue`, or `DTS:Expression` when `DTS:EvaluateAsExpression="True"`), and find what sets it at run time (a Foreach loop's variable mapping, an Execute SQL result set, a Script Task).

## Fix Patterns

### Pattern 1: Mode 1, one sheet per run

Pass the sheet name as a var. The UDF strips a trailing `$`, so `Claims$` works as it is:

```sql
FROM TABLE(excel_source_udf('@public.landing_stage/ssis/<Package>/claims.xlsx', '{{ var("User_SheetName", "Claims$") }}', 'YES'))
```

Name the var like the project's other `{{ var(...) }}` references and check the orchestration passes it (the `--vars` built by `public.BuildDbtVarsJsonUDF`). A value stored with quotes (`'Claims$'`) must lose them.

### Pattern 2: Mode 1 inside a loop over a fixed set of sheets

When a Foreach loop sets the variable to each sheet in turn and the sheets have the same layout, read them all in one model:

```sql
WITH excel_raw_data AS
(
   SELECT data, 'Q1' AS sheet_name FROM TABLE(excel_source_udf('@public.landing_stage/ssis/<Package>/claims.xlsx', 'Q1', 'YES'))
   UNION ALL
   SELECT data, 'Q2' FROM TABLE(excel_source_udf('@public.landing_stage/ssis/<Package>/claims.xlsx', 'Q2', 'YES'))
),
```

If the sheet list is only known at run time (a Foreach ADO.NET Schema Rowset enumerator over the workbook), add `-- NEEDS-USER: list of sheets read by <loop>` and mark needs-user.

### Pattern 3: Mode 3, the query is in the variable

Take the query from the variable's value or expression and apply it as in [SSC-EWI-SSIS0033](SSC-EWI-SSIS0033.md): set the sheet argument to the query's `FROM [Sheet$]`, then add the `WHERE` / `GROUP BY` as CTEs; parts the expression built from other variables become `{{ var('...') }}`.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker.
- A wrong sheet name fails at run time inside the UDF (the workbook has no such sheet), not at compile time.
- A range is `Sheet!A1:D100` for the UDF; an SSIS `Sheet$A1:D100` must be rewritten.
