# Enrichment prompt — null_fraction_override (value pass)

## Role
You override the fraction of NULLs generated for a column **when the workload needs a different fraction to exercise a branch**. Input: `list-unsolved` rows and the branch predicates that read the column. Emit into `column_enrichments[].null_fraction_override`.

This is a **coverage** control, not a fidelity one. Its job is to stop nulls from starving a predicate of rows — not to reproduce how often the column is null in the real source.

## Output schema (`column_enrichments[].null_fraction_override`)
```json
{ "column_enrichments": [ { "table": "<SCHEMA.TABLE>", "column": "<COL>", "null_fraction_override": 0.0, "source_evidence": "<...>" } ] }
```
`table` and `column` required; value in `[0,1]`. The column must exist and must be nullable (not a PK / NOT NULL).

## Negative constraint (the one rule)
**Every override needs a workload reason, named in `source_evidence` — the branch, predicate, or join that requires the column populated.** Do **not** infer a rate from the column's name: a name tells you what a column means, not how often it is null, and guessing one produces a number nothing can check. If no branch needs the fraction changed, omit the field; the generator's default stands.

**Never raise the null fraction on an FK-join column or a correlated-group column** — nulls there re-create the zero-row failure. A PK / NOT NULL column, or a fraction outside `[0,1]`, is rejected (`TBD0014`).

Note this rule is prose, not a gate: no deterministic check can tell a workload-grounded fraction from an invented one, so an override with no cited branch is left for the critic to reject.

## Work it out before you emit
Reason in prose first, then emit the fragment as your final output — deciding and formatting in the same
pass is where accuracy is lost. Per candidate, name the `list-unsolved` row that backs it and why it
holds, and say what you considered and dropped. Keep that reasoning out of the fragment: it carries only
the emitted type's own fields, and unknown fields are rejected.

## Examples
`process_order` filters `SALES.ORDERS.AMOUNT` with a `BETWEEN`, so a high null fraction leaves that branch with nothing to match. The override is grounded in the branch that needs the rows, and `source_evidence` names it:

<!-- example:accept -->
```json
{ "column_enrichments": [ { "table": "SALES.ORDERS", "column": "AMOUNT", "null_fraction_override": 0.05, "source_evidence": "PROC:process_order" } ] }
```

`SALES.CUSTOMER.CUST_ID` is a NOT NULL primary key — overriding its null fraction is rejected:

<!-- example:reject TBD0014 -->
```json
{ "column_enrichments": [ { "table": "SALES.CUSTOMER", "column": "CUST_ID", "null_fraction_override": 0.5 } ] }
```

A name-based rate is the shape to avoid: `DEATH_DATE` sounds mostly-null, but no branch asked for it and nothing in the workload says how often it is null — so there is no override to make, and emitting `0.95` would only bias the data on a guess. Omit the field.
