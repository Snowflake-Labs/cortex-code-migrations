# Element Type Reference — Unsupported (agnostic fallback)

Named platforms (`ssis/element-types.md`, `informatica/element-types.md`) document a fixed
vocabulary of source element types (tasks, transforms, containers) because they know the source
platform. This profile does not — that is the entire point of the fallback. There is
intentionally **no per-tool element vocabulary here**, and none should be added to prove out one
platform (`findings/61` SS13.1: Alteryx is a proving corpus, not this pack's identity).

## What identifies an element here

Instead of a source element type, this profile identifies affected elements the way the
remediation brief already does:

- `element_ids` — node identifiers from AI-First's IR/emitter (not source-platform task names)
- `models` — dbt model names, when the unit is dbt-flavored

Both come straight from the brief's `items[]` (see `brief-guide.md`) — never re-derive an
element identity from the SQL text when the brief already names it.

## Generic dbt/SQL element categories (not a source taxonomy)

These describe what is already on disk in the *emitted* tree, not a source concept:

| category | what it is | where it shows up |
|---|---|---|
| model | a `.sql` file under `models/` (staging/intermediate/mart) | `models[]` in the brief, `element_ids` |
| source | a `sources.yml` entry / raw-loaded table | Gate B `pointers` around source loci |
| seed | a static CSV-backed table | rarely brief-relevant unless flagged `residual` |
| snapshot | a dbt snapshot model | same handling as `model` |
| macro | shared dbt macro | only relevant if a brief item's `element_ids` names one |
| orchestration task | a `CREATE TASK` / procedure body outside dbt (scripting flavor) | `statements[]` in `scan.json`, not the brief |

## Growing this file

Per `findings/61` SS13.4 P2, agnostic element-classification procedures get added here **only
after they are validated against evidence from the proving corpus and written without bias
toward that corpus's vocabulary** (e.g. do not add an "Alteryx Filter tool" entry — add "row
filtering emitted as a `WHERE` clause with a missing predicate" if that pattern generalizes).
Until P2 lands, this file stays intentionally thin.
