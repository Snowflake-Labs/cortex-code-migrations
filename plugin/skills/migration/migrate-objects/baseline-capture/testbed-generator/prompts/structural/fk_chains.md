# Enrichment prompt — fk_chains (structural pass)

## Role
You infer **undeclared foreign-key residuals**: equi-joins the active table/workload relies on that have no declared FK. Input is the active CLI-scoped `list-unsolved` rows of kind `fk` and `join_edge`, already resolved by the miner — **never raw SQL**.

## Output schema (`fk_chains[]`, snake_case, unknown fields rejected)
```json
{ "fk_chains": [ { "child_table": "<SCHEMA.TABLE>", "child_col": "<COL>", "parent_table": "<SCHEMA.TABLE>", "parent_col": "<COL>", "hop_depth": 1, "confidence": 0.9, "implicit_pk": false } ] }
```
`child_table`, `child_col`, `parent_table`, `parent_col` are required. `confidence` is in `[0,1]`; `hop_depth` is `>= 1`.

A row with an empty `table` or `column` had its identifiers withheld because one join side is a query-local alias (a CTE or derived table) with no table behind it — its `detail` names the side. The four required names cannot be recovered from such a row, so **skip it**: naming the alias anyway rejects the whole document (`TBD0014`) and discards every other entry in it.

For a `join_edge`, take the parent table from its typed `right_table` field
(unsolved JSON schema v3). Do not parse `detail` to rediscover the right-hand
table.

## Negative constraint (the one rule)
Emit **only the undeclared residual**: a `join_edge` with no declared or inferred FK whose parent column is a key of the parent table, meaning its primary key or a unique column. A column that already has a declared or inferred FK is skipped, not re-emitted. **Never** emit both directions of the same edge: a bidirectional pair closes a reference cycle and is rejected (`TBD0015`). Peer-attribute joins (e.g. `region_code = region_code` between two children, or a country code shared by two fact tables) are *not* FKs. Those go to `correlated_groups`. An FK onto a parent column outside the parent's key rejects the whole document (`TBD0014`). Set `implicit_pk` only when that column is genuinely unique in the source.

## Work it out before you emit
Per candidate, name the `list-unsolved` row that backs it and why it
holds, and say what you considered and dropped. Keep that reasoning out of the fragment: it carries only
the emitted type's own fields, and unknown fields are rejected.

## Examples
`SALES.ORDERS.REP_ID` is joined to `SALES.SALES_REP.REP_ID` in `CLASSIFY_ORDER` with no declared FK — the canonical residual:

<!-- example:accept -->
```json
{ "fk_chains": [ { "child_table": "SALES.ORDERS", "child_col": "REP_ID", "parent_table": "SALES.SALES_REP", "parent_col": "REP_ID", "hop_depth": 1, "confidence": 0.9 } ] }
```

Do **not** reverse an existing edge. `SALES.ORDER_LINE.ORDER_ID` already references `SALES.ORDERS.ORDER_ID`; emitting the reverse closes a cycle:

<!-- example:reject TBD0015 -->
```json
{ "fk_chains": [ { "child_table": "SALES.ORDERS", "child_col": "ORDER_ID", "parent_table": "SALES.ORDER_LINE", "parent_col": "ORDER_ID", "hop_depth": 1, "confidence": 0.9 } ] }
```

Do **not** turn a peer join into an FK. `SALES.CUSTOMER.STATUS` is joined to `SALES.ORDERS.ORDER_STATUS`, a status code that many orders share. The key of `SALES.ORDERS` is `ORDER_ID`, so the edge is rejected. Emit it under `correlated_groups` instead:

<!-- example:reject TBD0014 -->
```json
{ "fk_chains": [ { "child_table": "SALES.CUSTOMER", "child_col": "STATUS", "parent_table": "SALES.ORDERS", "parent_col": "ORDER_STATUS", "hop_depth": 1, "confidence": 0.8 } ] }
```

Do **not** substitute an alias for the table it stands for. `MonthlySales` is a CTE name, so the workload has no such table and the whole document is rejected:

<!-- example:reject TBD0014 -->
```json
{ "fk_chains": [ { "child_table": "SALES.ORDERS", "child_col": "REP_ID", "parent_table": "MonthlySales", "parent_col": "REP_ID", "hop_depth": 1, "confidence": 0.9 } ] }
```
