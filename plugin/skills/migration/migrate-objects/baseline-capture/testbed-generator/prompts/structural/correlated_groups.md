# Enrichment prompt — correlated_groups (structural pass)

## Role
You emit **multi-table value tuples** that must co-occur so a compound cross-table filter returns rows. Input: `list-unsolved` compound `branch_predicate` rows and their `join_edge` context. Never raw SQL.

## Output schema (`correlated_groups[]`)
```json
{ "correlated_groups": [ { "group_id": "<id>", "tables": [ { "table": "<SCHEMA.TABLE>", "columns": ["<COL>"] } ], "tuple_columns": ["<SCHEMA.TABLE.COL>"], "sample_tuples": [ ["<v>"] ], "repeat": 5 } ] }
```
All fields required. A group must span **>= 2 tables**, carry **>= 1 `tuple_columns`**, supply **>= 3 `sample_tuples`** (each of the same arity as `tuple_columns`), and `repeat >= 1`. Every `tuple_columns` entry must be covered by a `tables[].columns` entry.

## Negative constraint (the one rule)
Emit **multi-table FK-keyed tuples**, never single-table per-table entries. A single-table group cannot fix the empty intersection that a compound cross-table predicate produces — it is rejected (`TBD0014`, "must span at least 2 tables").

## Examples
`CLASSIFY_ORDER` filters `c.STATUS='A' AND r.REGION_CODE = c.REGION_CODE` across CUSTOMER and SALES_REP — the region codes must agree:

<!-- example:accept -->
```json
{ "correlated_groups": [ { "group_id": "g_classify_region", "tables": [ { "table": "SALES.CUSTOMER", "columns": ["STATUS", "REGION_CODE"] }, { "table": "SALES.SALES_REP", "columns": ["REGION_CODE"] } ], "tuple_columns": ["SALES.CUSTOMER.STATUS", "SALES.CUSTOMER.REGION_CODE", "SALES.SALES_REP.REGION_CODE"], "sample_tuples": [ ["A", "NW", "NW"], ["A", "SE", "SE"], ["I", "EA", "EA"] ], "repeat": 5 } ] }
```

A single-table group reproduces the empty intersection and is rejected:

<!-- example:reject TBD0014 -->
```json
{ "correlated_groups": [ { "group_id": "g_bad", "tables": [ { "table": "SALES.CUSTOMER", "columns": ["STATUS"] } ], "tuple_columns": ["SALES.CUSTOMER.STATUS"], "sample_tuples": [ ["A"], ["I"], ["P"] ], "repeat": 2 } ] }
```
