# AIM-SHAPE — a structural property (columns, branches, ports) the representation does not carry

Shared across platforms. Full codes carry a per-instance digest (`AIM-SHAPE-<digest>`); this
guide covers the family.

A `SHAPE` finding is about structure: which columns an element produces (`element:column-set`) or
how many output branches it has (`element:multi-output-branching`).

## Fixing

1. The element's own configuration in `source_fragment` is the authority on its output columns
   and branches.
2. A collapsed branch changes which rows flow downstream; check the document's edges for which
   outputs are wired, and that each wired output has a model with the right rows.
3. An error or reject output is a real branch when something consumes it. When nothing does, it
   can be dropped, but verify that from the edges, never assume it.
4. Tier 3 models are edited in place; tier 1/2 return to convert.

## Do not

Merge a missing branch's rows into the main output: that silently changes what the main model's
row count means.

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
