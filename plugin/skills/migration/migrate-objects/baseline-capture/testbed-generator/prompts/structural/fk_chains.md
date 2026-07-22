# Enrichment prompt — fk_chains (structural pass)

## Role
You infer **undeclared foreign-key residuals**: equi-joins the workload relies on that have no declared FK. Input is the `list-unsolved` rows of kind `fk` and `join_edge` for the workload, already resolved by the miner — **never raw SQL**.

## Output schema (`fk_chains[]`, snake_case, unknown fields rejected)
```json
{ "fk_chains": [ { "child_table": "<SCHEMA.TABLE>", "child_col": "<COL>", "parent_table": "<SCHEMA.TABLE>", "parent_col": "<COL>", "hop_depth": 1, "confidence": 0.9, "implicit_pk": false } ] }
```
`child_table`, `child_col`, `parent_table`, `parent_col` are required. `confidence` is in `[0,1]`; `hop_depth` is `>= 1`.

## Negative constraint (the one rule)
Emit **only the undeclared residual** — a `join_edge` where neither side is already a declared key. A column that already has a declared or inferred FK is skipped, not re-emitted. **Never** emit both directions of the same edge: a bidirectional pair closes a reference cycle and is rejected (`TBD0015`). Peer-attribute joins (e.g. `region_code = region_code` between two children) are *not* FKs — those go to `correlated_groups`.

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
