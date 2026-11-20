# AIM-EMIT — the construct was represented and the renderer produced no usable output

Shared across platforms. Full codes carry a per-instance digest (`AIM-EMIT-<digest>`); this
guide covers the family.

An `EMIT` finding is about a **generated file**: the element was understood, and what came out is
not working SQL. The brief names the file in `models` and the element in `element_ids`.

## What to check

| Marker in the model | Meaning |
|---|---|
| `!!!RESOLVE EWI!!!` | a blocking placeholder: the file does not parse |
| `__PRODUCER_EXPRESSION_NOT_CONVERTED__` | a producer sentinel: it parses, and computes nothing for that expression |

The second is the dangerous one. "It compiles" is not evidence that an EMIT finding is resolved.

## Fixing

1. Read the element's configuration in `source_fragment`, not the surrounding generated SQL (that
   is what failed).
2. Tier 1 or 2: the next convert regenerates this file. A fix belongs in conversion
   (`return-to-convert` with the element id); a hand edit is allowed only as a logged engine
   defect.
3. Tier 3: write the SQL the configuration states, keep the model's `ref()` wiring (it came from
   the document's edges, not from the body that failed), keep the header and add a `Repaired:`
   line.
4. Re-run. A model that still carries either marker is not fixed.

## Do not

Clear the marker with a constant, `NULL`, or a passthrough of the upstream columns.

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
