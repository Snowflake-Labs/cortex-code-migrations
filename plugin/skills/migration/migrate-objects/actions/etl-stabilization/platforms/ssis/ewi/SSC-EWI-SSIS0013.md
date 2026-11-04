# SSC-EWI-SSIS0013 — SqlStatementSource Expression Has Unsupported Patterns

An Execute SQL task builds its SQL from a property expression or an expression variable, and SnowConvert converts only literals, variable references, `+` and parentheses. This expression uses something else (a function such as `REPLACE`, a cast such as `(DT_WSTR,20)`, a variable that is itself only another variable), so the task body is **empty**: the design-time SQL is left as `---- ` comments. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (once per dynamic-SQL Execute SQL task) |
| Common action | Rebuild the string with `\|\|` and run it with `EXECUTE IMMEDIATE` |

## Identification

```sql
---- Start block 'Package\Use Current File'
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0013 - PROPERTY EXPRESSION FOR SQLSTATEMENTSOURCE CONTAINS UNSUPPORTED PATTERNS. ONLY SINGLE VARIABLE REFERENCES OR SIMPLE STRING CONCATENATION WITH LITERALS AND VARIABLE REFERENCES IS SUPPORTED. ***/!!!
---- SELECT 'unused'
 ;
---- End block 'Package\Use Current File'
```

The `---- ` lines are the SQL as it was at design time: a reference, not the statement that runs. The expression is in the package, on the task (`<DTS:PropertyExpression DTS:Name="SqlStatementSource">`) or on the variable it reads (`DTS:EvaluateAsExpression="True"`, `DTS:Expression="..."`).

## Fix Patterns

### Pattern 1: Rebuild the expression

Translate the SSIS expression into a Snowflake Scripting string, in the shape SnowConvert uses when it can:

| SSIS expression | Snowflake Scripting |
|---|---|
| `"text" + @[User::X]` | `'text' \|\| :User_X` |
| `(DT_WSTR,20)@[User::BatchID]` | `:User_BatchID::VARCHAR` |
| `REPLACE(@[User::S], "a", "b")` | `REPLACE(:User_S, 'a', 'b')` |
| `"\n"` | `'\n'` |
| a `"` inside the string | `"` (no escape); a `'` becomes `''` |

Then translate the **T-SQL inside the string** to Snowflake, as for any converted statement: `GETDATE()` → `CURRENT_TIMESTAMP()`, `CAST(GETDATE() AS date)` → `CURRENT_DATE()`, `SYSUTCDATETIME()` → `SYSDATE()`, drop `WITH (HOLDLOCK)` and `WITH (NOLOCK)`, and map three-part names (`Claims.dbo.T`) to their target names.

```sql
-- After
LET dynamic_sql STRING := 'INSERT INTO STAGING.' || :User_TargetTable || ' (BatchID, ' || :User_InsertList || ') '
   || 'SELECT ' || :User_BatchID::VARCHAR || ', ' || :User_SelectList
   || ' FROM ' || REPLACE(:User_SourceFrom, 'JOIN ', 'JOIN CLAIMS.')
   || ' WHERE ModifiedAt >= DATEADD(day, -' || :User_LookbackDays::VARCHAR || ', CURRENT_DATE())';
EXECUTE IMMEDIATE :dynamic_sql;
```

### Pattern 2: The values come from a Foreach Item loop

When the variables are set by a Foreach Item enumerator over a fixed list, the statement can be static per item: unroll the loop into one statement per item, or loop over the list with `FOR rec IN (SELECT ... FROM VALUES (...)) DO ... END FOR;`. Static statements are easier to test than generated ones.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker and the empty `;` statement.
- Keep the `---- ` design-time lines as comments if they help the reader; they never run.
- Test the generated string: run it once with the variables' default values before wiring it into the graph.
- When the expression is too involved to translate with confidence, quote it and mark as needs-user.
