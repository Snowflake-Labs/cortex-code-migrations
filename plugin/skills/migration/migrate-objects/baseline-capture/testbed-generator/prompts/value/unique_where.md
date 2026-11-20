# Enrichment prompt — unique_where (value pass)

## Role
You declare a **filtered uniqueness**: at most one row per key carries a flag value — one current salary per
employee, one open order per customer. Emit it when a routine reads **one row per key behind a flag predicate**:
a scalar assignment (`SELECT @x = col FROM t WHERE key = @k AND IsCurrent = 1`) or a scalar subquery
(`= (SELECT col FROM t WHERE key = … AND IsCurrent = 1)`) with no `ORDER BY` / `TOP 1` picking among rows. The
source engine silently takes one of several matches; Snowflake's scalar subquery fails on them, so the
generated data must hold at most one.

## Output schema (`unique_where[]`)
```json
{ "unique_where": [ { "table": "<SCHEMA.TABLE>", "columns": ["<KEY_COL>"], "where": { "column": "<FLAG_COL>", "value": "<v>" }, "source_evidence": "<...>" } ] }
```
`table`, `columns` and `where` required. `columns` are the key the read filters on (`= @k`), `where.value` is the
flag literal as a string (`"1"` for a `BIT`, `"Y"` for a `CHAR(1)` flag).

## Negative constraint (the one rule)
`where.column` must be an ordinary column: not one of `columns`, and not a primary-key, unique or foreign-key
column — `generate` moves extra rows off the flag value, and it never moves a key. Such an entry is rejected
(`TBD0014`).

## What `generate` does with it
Of the rows sharing a key that carry the flag value, it keeps one (a row a branch value pinned, else the first)
and moves every other to another value of the flag column: the opposite boolean, another enum value, the next
number its domain allows, or null. No row is dropped. It warns when the flag column has no other value it may hold.

## Work it out before you emit
Reason in prose first, then emit the fragment as your final output — deciding and formatting in the same
pass is where accuracy is lost. Per candidate, name the routine and the single-row read that backs it, and say
what you considered and dropped. Keep that reasoning out of the fragment: it carries only the emitted type's own
fields, and unknown fields are rejected.

## Examples
A routine reads `SELECT @Amount = AMOUNT FROM SALES.ORDERS WHERE CUST_ID = @Cust AND ORDER_STATUS = 'N'` — at most
one open order per customer:

<!-- example:accept -->
```json
{ "unique_where": [ { "table": "SALES.ORDERS", "columns": ["CUST_ID"], "where": { "column": "ORDER_STATUS", "value": "N" }, "source_evidence": "GetOpenOrderAmount: SELECT @Amount = AMOUNT ... AND ORDER_STATUS = 'N'" } ] }
```

`CUST_ID` is the foreign key the read filters on, not a flag; it cannot be the `where` column:

<!-- example:reject TBD0014 -->
```json
{ "unique_where": [ { "table": "SALES.ORDERS", "columns": ["ORDER_ID"], "where": { "column": "CUST_ID", "value": "1" } } ] }
```
