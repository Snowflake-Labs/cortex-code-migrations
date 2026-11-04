# AIM-SEM — a write or processing semantic the set-based target applies differently

Shared across platforms. Full codes carry a per-instance digest (`AIM-SEM-<digest>`); this
guide covers the family.

A `SEM` finding states that the converted model reproduces the element's effect under an
assumption: for a keyed write (`write:keyed-table`, reason `one-input-row-per-key`) that each key
arrives once; for a stateful write (`write:stateful-table`, reason
`input-rows-applied-in-a-fixed-order`) that applying the rows in a fixed order equals the
source's row-at-a-time processing.

## In a repair

1. A comparison difference on such a sink is first a question about the input: duplicate keys, or
   an order the source did not have. Check the input rows before touching the model.
2. Stateful sinks (the platform table's `runtime.stateful_transforms`, `sink_writes.json` mode)
   keep state across runs. A difference that only appears on a second run is the runtime's, not
   the model's (see the repair skill's classification).
3. If the input breaks the stated assumption, the finding is the explanation: report it with the
   rows; do not rewrite the merge or SCD macro to match one run.

## Do not

Weaken the merge key, drop the version or date columns from the comparison, or switch an
incremental sink to a full refresh to make the counts agree.

## Read first

- The brief item for this finding (`reports/AiFirstRemediation/<unit>/remediation-brief.json`):
  `source_fragment` and `source_lines` are the element's own lines in the source document;
  `intent_excerpt` is what the gates said the source and the SQL do.
- The model's tier in the unit's `extensions.aiFirst.models` (or
  `reports/AiFirstElementMap/<unit>/element_map.json`): 1 engine, 2 `SSC-AI-ASSISTED`,
  3 `SSC-AI-AUTHORED`. Tier decides where a fix belongs; see the tier policy in the
  skill that sent you here.
- Platform-specific detail, when the platform has a pack, in `platforms/<platform>/ewi/` (checked
  first by `stabilization_tools.py ewi-guide-resolve`).
