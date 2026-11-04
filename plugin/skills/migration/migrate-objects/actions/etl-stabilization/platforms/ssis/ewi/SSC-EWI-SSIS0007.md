# SSC-EWI-SSIS0007 — Property Expressions Not Converted

An SSIS executable (a Foreach loop's enumerator, an Execute Package task, a Data Flow task, or an Execute SQL task property other than `SqlStatementSource`) had property expressions, and SnowConvert dropped them: the converted statement uses the property's design-time value. The `!!!RESOLVE EWI!!!` marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Moderate (once per executable with expressions; most often a Foreach File `Directory`) |
| Common action | Evaluate the expression; keep the design-time value when it is constant, otherwise build the statement from the variable |

## Identification

```
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0007 - SSIS EXECUTABLE CONTAINS PROPERTY EXPRESSIONS that were not converted. ***/!!!
```

Typical placement, on the `LIST` that feeds a Foreach File loop:

```sql
---- Start block 'Package\Process Files'
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0007 - SSIS EXECUTABLE CONTAINS PROPERTY EXPRESSIONS that were not converted. ***/!!!
LIST @public.landing_stage/ssis/ForEachFallbackLoad/c/landing/sales PATTERN = '.*/.*\.csv';
LET foreachfallbackload_process_files_cursor CURSOR
FOR
   SELECT REGEXP_SUBSTR($1, '[^/]+$') AS FILE_VALUE, ...
   FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
```

The expression itself is not in the output. Read it from the package: the executable's `<DTS:PropertyExpression DTS:Name="...">` elements (for a Foreach loop, also the enumerator's).

## Fix Patterns

### Pattern 1: The expression is constant per environment (most common)

`@[$Project::FileRoot] + "\\in\\bordereaux"` changes only between environments, not between runs. The design-time path the engine used is the same folder. Check that the stage prefix in the `LIST` is where those files land in Snowflake, fix it if not, and remove the marker.

```sql
-- After
LIST @public.landing_stage/in/bordereaux/ PATTERN = '.*[.]csv';
```

Write the dot as `[.]` (or `\\.`): in a single-quoted literal a lone backslash is consumed by the string, so the generated `'.*\.csv'` does not reach the regex as an escaped dot.

### Pattern 2: The expression changes per run

When the value depends on a variable set earlier in the run and the path is assembled from it, build the statement as a string. `LIST`, `COPY` and `REMOVE` bind a scalar variable only when it holds the whole stage reference (`LIST :User_DropPath` with a value starting with `@`), not a piece of the path:

```sql
-- After
EXECUTE IMMEDIATE 'LIST @public.landing_stage/' || :User_DropFolder || '/ PATTERN = ''.*\\.pdf''';
LET process_files_cursor CURSOR FOR
   SELECT REGEXP_SUBSTR($1, '[^/]+$') AS FILE_VALUE, ...
   FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
```

### Pattern 3: Another property

- **Execute Package task** (`PackageName`, `Connection`): the called package is fixed in the converted graph. If the expression picks among packages at run time, rebuild the call as `IF`/`CASE` over the candidates, or mark as needs-user.
- **Data Flow task** (`[Component].[SqlCommand]` and similar): the dbt model was built from the design-time query. If the expression only changes environment-level values, remove the marker; if it changes the query per run, mark as needs-user with the expression quoted.
- **Execute SQL task** (`TimeOut`, `Connection`, `BypassPrepare`): usually irrelevant in Snowflake. Remove the marker and note what was dropped.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker line.
- Quote the original expression in a `--` comment above the statement, so the next reader sees what was decided.
- A Foreach loop's file path also involves [SSC-FDM-SSIS0025](SSC-FDM-SSIS0025.md) and [SSC-EWI-SSIS0014](SSC-EWI-SSIS0014.md) when the folder still needs a stage.
