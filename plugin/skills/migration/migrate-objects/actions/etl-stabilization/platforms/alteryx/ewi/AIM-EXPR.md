# AIM-EXPR — a column's value derivation was not carried through

An `EXPR` finding is narrow: the element and its column set are fine, but how a particular column's
value is computed did not make it into the representation
(`reason: not-carried-into-representation`).

Full codes carry a per-instance digest (`AIM-EXPR-542a49f76777`). This guide covers the family.

## Where the expression lives

| Tool | Where |
|------|-------|
| `Formula` | `FormulaField/@expression`, output name in `@field` |
| `Filter` | `<Expression>` — the predicate, not a column value |
| `Summarize` | `SummarizeField/@action` — the aggregate |
| `AlteryxSelect` | no expression; projection and rename only |

## Translating Alteryx formula syntax

Alteryx formulas are not SQL. The mechanical differences:

| Alteryx | Snowflake |
|---------|-----------|
| `[Field]` | `"Field"` or bare identifier |
| `"literal"` | `'literal'` (single quotes) |
| `IF c THEN a ELSE b ENDIF` | `CASE WHEN c THEN a ELSE b END` |
| `IIF(c, a, b)` | `IFF(c, a, b)` |
| `Left([F], n)` | `LEFT("F", n)` |
| `DateTimeNow()` | `CURRENT_TIMESTAMP()` |
| `ToNumber([F])` | `TRY_CAST("F" AS NUMBER)` |
| `IsNull([F])` | `"F" IS NULL` |
| `+` on strings | `||` |

Two that cause silent wrong answers rather than errors:

- **String concatenation.** `+` concatenates strings in Alteryx. In Snowflake `+` on strings coerces
  to numeric, so `'a' + 'b'` errors and `'1' + '2'` returns `3`, not `'12'`. Use `||`.
- **Declared type.** `FormulaField/@type` and `@size` state the intended output type. A formula
  declared `V_String(10)` truncates; one converted without the cast does not, and the difference only
  shows up in the data.

## Fixing

Translate from `@expression` in the source, keeping the output column name from `@field` and the cast
implied by `@type`. Verify against the tool configuration rather than against neighbouring generated
SQL.
