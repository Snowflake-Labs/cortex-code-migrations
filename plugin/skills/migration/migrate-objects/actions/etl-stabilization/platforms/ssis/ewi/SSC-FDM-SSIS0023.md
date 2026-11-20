# SSC-FDM-SSIS0023 — Circular Variable Reference in an SSIS Expression

SnowConvert inlines a variable that has an expression (`EvaluateAsExpression = True`) by translating that expression in place. When the chain of expressions comes back to a variable it is already expanding (`A` uses `A`, or `A` uses `B` uses `A`), it stops and puts the type's default value there instead: `0` for numbers, `''` for strings, `FALSE` for booleans, `'1900-01-01'` / `'1900-01-01 00:00:00'` for dates and timestamps, `TO_BINARY('')` for binary, `NULL` otherwise. The code runs, but with a made-up value.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Rare (once per cycle hit) |
| Common action | Replace the default with the variable's real run-time value |

## Identification

```
--** SSC-FDM-SSIS0023 - CIRCULAR REFERENCE DETECTED WHEN EXPANDING VARIABLE '@[User::VarA]'. THE DEFAULT VALUE FOR TYPE 'NUMBER' HAS BEEN USED INSTEAD. **
```

It precedes the expression that holds the default, in a dbt model column (Derived Column, Conditional Split) or in orchestration SQL (Expression task, Execute SQL). Each expanded variable is wrapped in parentheses and tagged:

```sql
-- VarA = @[User::VarA] + 1
(0 + 1) /*Expanded Variable: @[User::VarA]*/
-- VarA = @[User::VarB] + 1, VarB = @[User::VarA] + 2
((0 + 2) /*Expanded Variable: @[User::VarB]*/ + 1) /*Expanded Variable: @[User::VarA]*/
```

The `0` (or `''`, `FALSE`, ...) is where the cycle was cut. Find the variables in the `.dtsx`: `<DTS:Variable DTS:EvaluateAsExpression="True" DTS:Expression="..." DTS:ObjectName="VarA" DTS:Namespace="User">`.

## Fix Patterns

### Pattern 1: One link of the cycle is really a stored value

Usually one variable in the cycle gets its value elsewhere at run time (a Script Task, an Execute SQL result set, a For Loop `AssignExpression`, a parameter or configuration), and its expression is only a design-time leftover. Replace the default with a reference to that variable's value, as other variables are read in the same file (see [SSC-EWI-SSIS0002](SSC-EWI-SSIS0002.md)):

```sql
-- Before (dbt model)
--** SSC-FDM-SSIS0023 - CIRCULAR REFERENCE DETECTED WHEN EXPANDING VARIABLE '@[User::BatchNo]'. THE DEFAULT VALUE FOR TYPE 'NUMBER' HAS BEEN USED INSTEAD. **
(0 + 1) /*Expanded Variable: @[User::BatchNo]*/ AS NextBatchNo,

-- After
--** SSC-FDM-SSIS0023 - ... **
({{ var('User_BatchNo') }} + 1) /*Expanded Variable: @[User::BatchNo]*/ AS NextBatchNo,
```

In a task body, use `:User_BatchNo`. Check that the variable is declared in the `CONFIG` block and that whatever set it in SSIS sets it in the converted orchestration.

### Pattern 2: The value cannot be determined

If nothing in the package sets any variable of the cycle, the package itself could not compute it. Keep the default, add `-- NEEDS-USER: variable <name> has a circular expression in the package; confirm its run-time value`, and mark as needs-user.

## Key Points

- Do **NOT** remove the FDM comment.
- A default of `0`, `''` or `'1900-01-01'` in a filter (`WHERE LoadDate > '1900-01-01'`) silently changes which rows load: check every use, not only the one with the comment.
- System variables inside the cycle need their own mapping: see [SSC-EWI-SSIS0046](SSC-EWI-SSIS0046.md).
