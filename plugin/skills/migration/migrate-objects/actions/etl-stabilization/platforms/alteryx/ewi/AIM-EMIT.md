# AIM-EMIT — the generated model is not usable as emitted

An `AIM-EMIT` finding is about a **generated file**, not about a source element's meaning. The
element was understood; what came out could not be rendered as working SQL. The brief states the
file in `models` and the element it belongs to in `element_ids`.

Full codes carry a per-instance digest (`AIM-EMIT-c585d372314d`), so two findings of the same kind
never share a code. This guide covers the family.

## What to check first

Read the emitted model and look for one of two markers:

| Marker | Meaning |
|--------|---------|
| `!!!RESOLVE EWI!!!` | a blocking placeholder — the file will not parse |
| `__PRODUCER_EXPRESSION_NOT_CONVERTED__` | a producer sentinel — parses, but the expression is absent |

The second is the dangerous one: the model is syntactically valid and will pass a parse check while
computing nothing. Do not treat "it compiles" as evidence that an EMIT finding is resolved.

## Fixing

1. Find the element in the `.yxmd` by its `ToolID` and read its configuration (see `tool-guide.md`).
2. Write the SQL the tool's configuration actually specifies. Derive it from the source
   configuration, never from the surrounding generated SQL — that is what failed.
3. Keep the model's existing `ref()` wiring. The graph was derived from `<Connections>` and is
   independent of the body that failed to render.
4. Re-run the model. A model that still carries either marker is not fixed.

## When the tool has no SQL equivalent

`RunCommand`, `Email`, and the R/Python tools have no warehouse equivalent. These are correctly
reported and belong in the residual lane — do not invent SQL to clear the finding. Record the
external dependency instead.
