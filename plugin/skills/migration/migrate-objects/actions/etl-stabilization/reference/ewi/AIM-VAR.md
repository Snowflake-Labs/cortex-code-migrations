# AIM-VAR — a run-time variable or parameter whose value the generated project does not carry

Shared across platforms. Full codes carry a per-instance digest (`AIM-VAR-<digest>`); this
guide covers the family.

A `VAR` finding is about run-time values: a built-in run-time name (`reference:built-in-variable`),
a reference to a name with no value (`reference:unset-variable`), or per-run override files
(`config:parameter-file`).

## Fixing

1. The value the source run used is a fact about that run (its parameters file, its environment),
   not about the model. Read the launcher's `params.json` and the project's variable configuration.
2. If the converted model reads the variable through `var()`, the fix is the value supplied to the
   run, not the model body.
3. A built-in run-time name (run date, file name, host) has no fixed value: treat a column derived
   from it like a clock column.

## Do not

Inline the value one run used into the model as a literal.

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
