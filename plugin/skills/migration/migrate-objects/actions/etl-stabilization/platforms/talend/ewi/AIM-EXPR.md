# AIM-EXPR — a column's value derivation was not carried through

An `EXPR` finding is narrow: the element and its column set are fine, but how a particular column's
value is computed did not make it into the representation
(`reason: not-carried-into-representation`).

Full codes carry a per-instance digest (`AIM-EXPR-542a49f76777`). This guide covers the family.

## Where the expression lives

| Component | Where |
|-----------|-------|
| `tMap` | `nodeData/outputTables/mapperTableEntries/@expression`, output name in `@name` |
| `tFilterRow` | the condition rows in `elementParameter` — the predicate, not a column value |
| `tAggregateRow` | the aggregate operation in `elementParameter` |
| `t*Input`/`t*Output` | the `QUERY`/`TABLE` `elementParameter` — no row-level expression, just column selection |

## Translating Talend's Java routine calls

`tMap` expressions are Java, not SQL. The mechanical differences (see `tool-guide.md` for the
full table):

| Talend Java | Snowflake |
|-------------|-----------|
| `row1.Field` | `"field"` or bare identifier |
| `"literal"` | `'literal'` (single quotes) |
| `a == null ? b : a` | `COALESCE(a, b)` |
| `StringHandling.UPCASE(x)` | `UPPER(x)` |
| `TalendDate.getCurrentDate()` | `CURRENT_DATE()` |
| `TalendDate.parseDate(fmt, x)` | `TRY_TO_DATE(x, fmt)` |
| Java string `+` | `||` |

Two that cause silent wrong answers rather than errors:

- **String concatenation.** Java `+` concatenates strings. Snowflake's `+` on two string literals
  that look numeric coerces to numeric (`'1' + '2'` returns `3`, not `'12'`), so a missed `||`
  conversion does not always error — it silently returns the wrong type or value. Use `||`.
- **Declared type.** `mapperTableEntries/@type` (e.g. `id_String`, `id_Integer`, `id_Date`) states
  the intended output type. A conversion that drops the corresponding cast produces a column whose
  declared type in `metadata` disagrees with what actually landed in Snowflake, and the difference
  only shows up in the data.

## Fixing

Translate from `@expression` in the source `tMap`, keeping the output column name from `@name` and
the cast implied by `@type`. Verify against the component's own `nodeData`/`elementParameter`
configuration rather than against neighbouring generated SQL.
