# Enrichment prompt — anti_join_tables (structural pass)

## Role
You declare that a table needs a **fraction of rows whose FK deliberately does not match**, so anti-join / `NOT EXISTS` / `LEFT JOIN … IS NULL` branches return rows. Input: `list-unsolved` anti-join `branch_predicate` rows and the table's FKs. Never raw SQL.

## Output schema (`anti_join_tables[]`)
```json
{ "anti_join_tables": [ { "table": "<SCHEMA.TABLE>", "fk_column": "<FK_COLUMN>", "anti_join_fraction": 0.1 } ] }
```
All fields required. `anti_join_fraction` is in `[0,1]`.

## Negative constraint (the one rule)
`fk_column` must be a child column of an **FK the table already has** (declared in DDL, or inferred from the workload's joins and listed in the table's `foreign_keys`), single-column or composite, **or of one you infer in the same batch** — an anti-join needs a parent reference to deliberately miss. For a composite FK, name any one member: the whole tuple misses. A column in no FK is rejected (`TBD0014`). (`anti_join_tables` is applied after `fk_chains`, so an FK you infer in the same envelope counts.)

## Work it out before you emit
Reason in prose first, then emit the fragment as your final output — deciding and formatting in the same
pass is where accuracy is lost. Per candidate, name the `list-unsolved` row that backs it and why it
holds, and say what you considered and dropped. Keep that reasoning out of the fragment: it carries only
the emitted type's own fields, and unknown fields are rejected.

## Examples
`SALES.ORDERS.CUST_ID` is a declared FK to CUSTOMER — carve a non-matching fraction for the anti-join branch:

<!-- example:accept -->
```json
{ "anti_join_tables": [ { "table": "SALES.ORDERS", "fk_column": "CUST_ID", "anti_join_fraction": 0.2 } ] }
```

`SALES.SHIPMENT (ORDER_ID, LINE_NO)` references `SALES.ORDER_LINE` through a composite FK inferred from a join — name one member, and that fraction of shipments reference no order line:

<!-- example:accept -->
```json
{ "anti_join_tables": [ { "table": "SALES.SHIPMENT", "fk_column": "LINE_NO", "anti_join_fraction": 0.2 } ] }
```

`SALES.ORDERS.REP_ID` has no declared FK; without an inferred one in the same batch it cannot resolve:

<!-- example:reject TBD0014 -->
```json
{ "anti_join_tables": [ { "table": "SALES.ORDERS", "fk_column": "REP_ID", "anti_join_fraction": 0.1 } ] }
```
