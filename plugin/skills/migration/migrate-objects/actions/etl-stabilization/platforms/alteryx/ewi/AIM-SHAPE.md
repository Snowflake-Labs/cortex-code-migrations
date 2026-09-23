# AIM-SHAPE — the element's column set or branching was not carried through

A `SHAPE` finding is about structure: which columns an element produces, or how many output branches
it has. The element's kind was recognised; its shape was not fully represented.

Full codes carry a per-instance digest (`AIM-SHAPE-1d790c23a72b`). This guide covers the family.

## The two constructs

### `element:column-set` — columns not declared by the document

The column list could not be derived. Downstream models then reference columns that the upstream
model does not select, which surfaces at execution as `No column X found`.

Read the element's configuration for the authority on its output columns:

- `AlteryxSelect` — `SelectField/@selected="False"` drops a field; `@rename` renames it. Check for a
  `*Unknown` entry before concluding a field was dropped.
- `Summarize` — output is **only** the group-by fields plus the aggregates.
- `Join` — output carries fields from both inputs.
- `DbFileInput` — the `Query` decides what enters the flow.

### `element:multi-output-branching` — branches collapsed

A tool with several outputs was represented as if it had one. This changes which rows flow
downstream, so it is a correctness problem rather than a cosmetic one.

- `Filter` has `True` and `False`. If both are wired, both branches must exist downstream.
- `Join` has `Join`, `Left`, and `Right` — matched, left-only, right-only.
- `Unique` has `Unique` and `Duplicate`.

Check `<Connections>` for which anchors are actually wired, and confirm each wired anchor has a
corresponding model with the right predicate or join type.

## Heterogeneous unions

The recurring case: a `Union` whose inbound branches carry different field sets. With `Mode=ByName`,
a field present in one branch and absent in the other must be null-filled for the branch that lacks
it. A model that selects the column from the branch without it fails at execution.

Decide from the source which is intended:

- the field is genuinely absent on that branch → select `NULL AS <field>` for it, typed to match
- the branch should supply it → the defect is upstream, in the branch, not in the union

Do not "fix" this by dropping the column from the union, which silently changes the output schema
every downstream model depends on.
