# Enrichment prompt — derivation (value pass)

## Role
Each `list-unsolved` `calendar_column` row names a column (`table`, `column`) that no mined derivation computes, of a
table a routine reads at the run date. Its run-date column is `columns[0].column`; `detail` gives its type, facets,
CHECK and semantic type; `source_evidence` and `left` / `op` / `right` carry a filter on it not applied automatically.
State the column as an expression of the run-date column, in `column_enrichments[].derivation`.

## Output schema (`column_enrichments[].derivation`)
```json
{ "column_enrichments": [ { "table": "<SCHEMA.TABLE>", "column": "<COL>", "derivation": { "from_column": "<RUN_DATE_COL>", "expression": { "kind": "fn", "fn": "<function>", "args": [ { "kind": "column", "column": "<RUN_DATE_COL>" } ] } }, "source_evidence": "<...>" } ] }
```
`table`, `column` and `derivation` are required. `from_column` is the run-date column. `expression` is a tree of:

| Node | Shape |
|---|---|
| column | `{"kind": "column", "column": "<from_column>"}`: the only column the tree reads, as often as it needs |
| literal | `{"kind": "literal", "literal": "<text>"}`: a number, date part or format pattern, always a string |
| type | `{"kind": "type", "type": "<type>"}`: only as the second argument of `cast` |
| function | `{"kind": "fn", "fn": "<function>", "args": [<node>, …]}` |
| operator | `{"kind": "operator", "fn": "<operator>", "args": [<node>, …]}` |

## Vocabulary
Use only these names; translate the routine's own spelling, and write a `CASE` as nested `iif`. If a piece of the
expression has no name here, leave the row unanswered.

| Function | Arguments | Result |
|---|---|---|
| `year` / `month` / `day` | value | The integer part |
| `date_part` | part, value | The integer part. `weekday` counts Sunday = 1; `week` starts weeks on Sunday, week 1 holds January 1 |
| `date_name` | part, value | The English month or weekday name; any other part as decimal text |
| `date_add` | part, number, value | Adds number × part; adding months clamps to the month's last day |
| `date_diff` | part, start, end | The part boundaries crossed from start to end; week boundaries fall on Sunday |
| `last_day` | value[, months] | The month's last day, after adding months |
| `format_date` | value, pattern | The date as text in the pattern, English names |
| `cast` | value, type | Text in invariant culture; `fixed_text(n)` pads or truncates to n; decimal to integer truncates |
| `left` / `right` | text, n | The first / last n characters |
| `substring` | text, start, length | Start is 1-based; a start below 1 shortens the length |
| `concat` | values… | The values joined; a null counts as empty. The default way to join text |
| `concat_ws` | separator, values… | The non-null values joined by the separator |
| `upper` / `lower` | text | Invariant culture |
| `trim` / `ltrim` / `rtrim` | text | Removes spaces (U+0020) only |
| `replace` / `replace_ci` | text, find, with | Ordinal; case-sensitive / case-insensitive |
| `coalesce` | values… | The first non-null |
| `nullif` | a, b | Null when a = b, else a |
| `iif` | condition, a, b | a when the condition holds; b when it is false or null |
| `floor` / `ceiling` / `abs` | number | Rounded down / rounded up / non-negative |
| `round` | number, digits | Half away from zero |

- **Operators:** `add`, `subtract`, `multiply`, `negate`; `divide` (exact), `integer_divide` (truncating), `modulo`
  (sign of the dividend); `concat_strict` (joins text, a null gives null; prefer the `concat` function); `eq`, `ne`,
  `lt`, `le`, `gt`, `ge` (a null gives null); `and`, `or`, `not` (three-valued).
- **Date parts:** `year`, `quarter`, `month`, `day_of_year`, `day`, `week`, `iso_week`, `weekday`, `hour`, `minute`, `second`.
- **Pattern tokens:** `yyyy` `yy` `MMMM` `MMM` `MM` `M` `dddd` `ddd` `dd` `d` `HH` `mm` `ss` `fff`. Any other character
  is literal; quote text in `'…'`.
- **Types:** `text`, `text(n)`, `fixed_text(n)`, `integer`, `decimal(p,s)`, `float`, `date`, `datetime`, `time`, `boolean`.

Node shapes for three common parts, over a run-date column `CAL_DATE`:
- month name: `{"kind": "fn", "fn": "date_name", "args": [{"kind": "literal", "literal": "month"}, {"kind": "column", "column": "CAL_DATE"}]}`
- `yyyyMM` key: `{"kind": "fn", "fn": "format_date", "args": [{"kind": "column", "column": "CAL_DATE"}, {"kind": "literal", "literal": "yyyyMM"}]}`
- four-character year: `{"kind": "fn", "fn": "cast", "args": [{"kind": "fn", "fn": "year", "args": [{"kind": "column", "column": "CAL_DATE"}]}, {"kind": "type", "type": "text(4)"}]}`

## Negative constraint (the one rule)
**Answer only a column that is a function of the run-date column under a convention the workload states.** A calendar
part of the date always is: its year, quarter, month or day, their names, a `yyyyMM` key, a period's first or last
day. A fiscal year's start month, a week's first day or a period's numbering is one only when the workload states it:
the row's own filter (`left` / `op` / `right`), a routine that computes the column, or a loader of the table. Never
choose a convention yourself. Leave every other row unanswered, such as a key, a flag a routine sets, or a value that
depends on more than the date; `generate` then warns about that column.

## What `propose-enrichments` does with it
It evaluates the expression on the run date and checks the value against the column's type, width and CHECK. A name
outside the vocabulary, a column other than `from_column`, or a value the column cannot hold is rejected (`TBD0014`)
with a diagnostic naming it. Fix that piece and propose again, or drop the entry.

## Work it out before you emit
Reason in prose first, then emit the fragment as your final output — deciding and formatting in the same pass is
where accuracy is lost. Per entry, name the `calendar_column` row that backs it and the code that states its
convention, and say what you considered and dropped. Keep that reasoning out of the fragment: it carries only the
emitted type's own fields, and unknown fields are rejected.

## Examples
A routine reads `SALES.CALENDAR` at `CAL_DATE = <today>` and filters `FISCAL_YEAR_NBR` on the year of today, plus
one from July on: the fiscal year runs July to June and is named by the year it ends.

<!-- example:accept -->
```json
{ "column_enrichments": [ { "table": "SALES.CALENDAR", "column": "FISCAL_YEAR_NBR", "derivation": { "from_column": "CAL_DATE", "expression": { "kind": "fn", "fn": "iif", "args": [ { "kind": "operator", "fn": "ge", "args": [ { "kind": "fn", "fn": "month", "args": [ { "kind": "column", "column": "CAL_DATE" } ] }, { "kind": "literal", "literal": "7" } ] }, { "kind": "operator", "fn": "add", "args": [ { "kind": "fn", "fn": "year", "args": [ { "kind": "column", "column": "CAL_DATE" } ] }, { "kind": "literal", "literal": "1" } ] }, { "kind": "fn", "fn": "year", "args": [ { "kind": "column", "column": "CAL_DATE" } ] } ] } }, "source_evidence": "PROC:load_budget predicates[2]" } ] }
```

An expression that also reads the table's `FISCAL_OFFSET` is rejected, because it reads more than `from_column`:

<!-- example:reject TBD0014 -->
```json
{ "column_enrichments": [ { "table": "SALES.CALENDAR", "column": "FISCAL_YEAR_NBR", "derivation": { "from_column": "CAL_DATE", "expression": { "kind": "operator", "fn": "add", "args": [ { "kind": "fn", "fn": "year", "args": [ { "kind": "column", "column": "CAL_DATE" } ] }, { "kind": "column", "column": "FISCAL_OFFSET" } ] } } } ] }
```

Leave `FISCAL_YEAR_NBR` unanswered when no filter on it and no routine computing it says when the fiscal year starts:
`year` plus one from July is then a guess.
