# AIM-REF — a reference between generated units that does not resolve, or an edge the artifact does not carry

Shared across platforms. Full codes carry a per-instance digest (`AIM-REF-<digest>`); this
guide covers the family.

A `REF` finding is about wiring: a model reads an upstream element the generated project does not
provide (`reference:upstream-element`), or an edge in the document has no counterpart in the
generated graph.

## Fixing

1. Check the reference against the document's edges (the element's `source_fragment` and its
   neighbours) and against the project's models and `sources.yml`.
2. A `ref()` to a model that should exist is a conversion gap: tier 1/2 return to convert.
3. A `source()` to a table that is genuinely external is a declaration problem: add it to
   `sources.yml` only when the document states that table.
4. Never point a reference at a different model or table because it has the right columns.

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
