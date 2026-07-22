# Enrichment prompt — must_include (value pass)

## Role
You declare a **floor** of values that must appear in a column (e.g. lookup values a `check` or a downstream join depends on). Input: `list-unsolved` `check` rows and lookup columns. Emit into `column_enrichments[].must_include`.

## Output schema (`column_enrichments[].must_include`)
```json
{ "column_enrichments": [ { "table": "<SCHEMA.TABLE>", "column": "<COL>", "must_include": ["<v>"], "source_evidence": "<...>" } ] }
```
`table` and `column` required; the column must exist.

## Negative constraint (the one rule)
A **floor** (at least these values exist), not a full-domain model. The values must satisfy any `check` on the column — but note the `check` contradiction is **not** caught by `propose-enrichments`; it surfaces later at `validate` (the readiness gate), which fails the whole state. So a `must_include` that violates a `check` is accepted here yet blocks `validate` — get it right at authoring time.

## Examples
`SALES.ORDER_LINE.SKU` is a `VARCHAR(40)` lookup column — force the SKUs a branch depends on to exist:

<!-- example:accept -->
```json
{ "column_enrichments": [ { "table": "SALES.ORDER_LINE", "column": "SKU", "must_include": ["ABC-1", "XYZ-9"], "source_evidence": "PROC:process_order predicates[4]" } ] }
```

A non-existent column is rejected:

<!-- example:reject TBD0014 -->
```json
{ "column_enrichments": [ { "table": "SALES.ORDER_LINE", "column": "NOPE", "must_include": ["ABC-1"] } ] }
```
