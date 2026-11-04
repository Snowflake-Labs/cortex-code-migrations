# SSC-EWI-SSIS0029 — Excel Source Query Parameters Not Translated

An Excel Source has a non-empty `ParameterMapping`: its SQL command had `?` placeholders bound to SSIS variables. SnowConvert does not translate the command (see [SSC-EWI-SSIS0033](SSC-EWI-SSIS0033.md)), so the parameters are dropped and the model reads the whole sheet through `excel_source_udf`. The marker **breaks compilation**. Only the Excel Source emits it.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (once per parameterized Excel Source) |
| Common action | Re-apply the query's filter in the model with `{{ var('...') }}` in place of each `?` |

## Identification

At the top of the Excel Source's staging model, usually next to SSC-EWI-SSIS0033:

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0029 - SSIS PARAMETERMAPPING PROPERTY '<ParameterMapping value>' REQUIRES CONVERSION TO DBT VARS OR JINJA TEMPLATING. REPLACE SSIS PARAMETERS WITH DBT VARS AND PASS VALUES AT RUNTIME USING --VARS. ***/!!!
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0033 - EXCEL SOURCE USES SQL COMMAND ACCESS MODE WITH QUERY: 'SELECT * FROM [Claims$] WHERE Region = ?'. ... ***/!!!
--Original Excel path: Provider=Microsoft.ACE.OLEDB.16.0;Data Source=...;Extended Properties="Excel 12.0 XML;HDR=YES";
WITH excel_raw_data AS ( SELECT data FROM TABLE(excel_source_udf('@public.landing_stage/ssis/<Package>/<file>.xlsx', '<sheet>', 'YES')) ),
parsed_data AS ( SELECT ... FROM excel_raw_data )
SELECT * FROM parsed_data
```

The quoted value is the component's `ParameterMapping` property: one `"Parameter0:Input",{GUID};` entry per `?`, in order. Each GUID is a variable's `DTS:DTSID` in the package's `<DTS:Variables>` (or a project/package parameter); its `DTS:ObjectName` and namespace give the name.

## Fix Patterns

### Pattern 1: Filter on a variable

Map each `?` (in order) to its variable and apply it after `parsed_data`, as a dbt var:

```sql
parsed_data AS ( SELECT data['Region'] :: VARCHAR AS Region, TRY_TO_DOUBLE(data['Amount'] :: VARCHAR) AS Amount FROM excel_raw_data ),
filtered AS ( SELECT * FROM parsed_data WHERE Region = '{{ var("User_Region") }}' )
SELECT * FROM filtered
```

Name the var the way the other models of this dbt project do (`User_Region`, or with a scope prefix such as `Load_Claims_User_Region` in a consolidated project). The orchestration passes control variables to `EXECUTE DBT PROJECT` as `--vars` built by `public.BuildDbtVarsJsonUDF('<scope>')`; check the variable is among that scope's control variables, and add it there if not. Quote string vars; leave numeric ones bare.

### Pattern 2: Value unknown at conversion time

If the variable is set at run time by something not converted (a Script Task, a caller), give the var a default so `dbt build` still compiles, `{{ var("User_Region", "WEST") }}`, add `-- NEEDS-USER: confirm how User_Region is supplied`, and mark needs-user.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker; resolve SSC-EWI-SSIS0033 for the rest of the query at the same time.
- `var()` with no default fails at compile time when the var is not passed.
- Jet SQL compares text case-insensitively; Snowflake does not. Use `UPPER(Region) = UPPER('...')` when the source data's case varies.
