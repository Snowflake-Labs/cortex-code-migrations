# AIM-REPR — the intermediate representation has no member for the construct

Shared across platforms. Full codes carry a per-instance digest (`AIM-REPR-<digest>`); this
guide covers the family.

A `REPR` finding means the migrator could not place the element in its vocabulary: either no
member describes it (`no-vocabulary-member`) or it was carried as a catch-all class that drops its
specifics (`degraded-to-catch-all-class`).

## Fixing

1. Identify what the element is from `source_fragment` (its kind and configuration).
2. If it has a straightforward set-based equivalent (aggregate, deduplicate, lookup, generate a
   fixed row set), a tier-3 model may implement it from the configuration.
3. If it has none (file and network operations, messaging, row-by-row scripts with side
   effects), the finding is correct and residual: record the gap and the remediation target.
4. A REPR finding on a containment element (a pipeline or job that holds others) is about
   structure, not a model; there is nothing to edit in a model for it.

## Do not

Replace a degraded element with a plausible passthrough. The finding is the only signal that the
meaning is missing; clearing it leaves the data wrong.

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
