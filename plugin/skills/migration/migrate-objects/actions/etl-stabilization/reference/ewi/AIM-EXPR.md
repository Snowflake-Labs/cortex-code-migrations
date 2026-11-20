# AIM-EXPR — text in a language this pipeline does not lower to the target dialect

Shared across platforms. Full codes carry a per-instance digest (`AIM-EXPR-<digest>`); this
guide covers the family.

An `EXPR` finding is narrow: the element and its columns are fine, but how a column's value is
computed (a formula, a calculator operation, a scripted expression) was not lowered to SQL, or was
lowered from a language the converter does not translate.

## Fixing

1. Find the expression in `source_fragment` (the element's own configuration) and the output
   column it feeds.
2. Translate its semantics, not its spelling: integer versus decimal division, null propagation
   (`NULL + 1`), string concatenation with null, date arithmetic units, and the source runtime's
   time zone (see the platform table's `runtime.time_zone`) are where a faithful-looking
   translation computes a different value.
3. Tier 3 models are edited in place. Tier 1/2: return to convert, or correct the model-supplied
   payload (tier 2) rather than the generated SQL.

## Do not

Drop the column, replace it with a constant, or exclude it from comparison to make a
difference disappear.

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
