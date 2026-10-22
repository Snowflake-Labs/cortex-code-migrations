# AIM-SHAPE — the element's column set or branching was not carried through

A `SHAPE` finding is about structure: which columns an element produces, or how many output
branches it has. The element's kind was recognised; its shape was not fully represented.

Full codes carry a per-instance digest (`AIM-SHAPE-1d790c23a72b`). This guide covers the family.

## The two constructs

### `element:column-set` — columns not declared by the document

The column list could not be derived. Downstream models then reference columns that the upstream
model does not select, which surfaces at execution as `No column X found`.

Read the element's configuration for the authority on its output columns:

- `tMap` — `nodeData/outputTables/mapperTableEntries` is the output column list; the `reject`
  output (`outputTables[@reject="true"]`) is a separate column set entirely.
- `tAggregateRow` — output is **only** the group-by fields plus the aggregates.
- `t*Input`/`t*Output` — `metadata/column` states the exact column set; the `QUERY`
  `elementParameter` decides which of the source table's columns actually enter the flow.

### `element:multi-output-branching` — branches collapsed

A component with several outputs was represented as if it had one. This changes which rows flow
downstream, so it is a correctness problem rather than a cosmetic one.

- `tMap` can have several `outputTables`, plus one or more `reject` outputs. Each is a distinct
  `FLOW` connection; only the wired ones exist downstream.
- `tParallelize` fans out to every `PARALLELIZE`-connected target concurrently — collapsing it to
  a single successor loses the fan-out.
- `tRunJob` chains sequenced by `SUBJOB_OK` are execution-order branches, not data branches;
  conflating them with a `FLOW` graph mis-states dependency order (see `workflow-guide.md`).

Check the `connection` elements for which anchors (`@source`/`@target` pairs, keyed by `@connectorName`)
are actually wired, and confirm each wired anchor has a corresponding model with the right logic.

## Reject flows are a real branch

The recurring case for Talend: a `tMap`'s `reject` output (`outputTables[@reject="true"]`) is a
genuine second branch, not dead configuration. If it is wired downstream (a `FLOW` connection off
the reject anchor), the rejected rows have their own consumer and need their own model
(`<model>__rejected.sql`) with the reject reason carried through. If nothing is wired to it, the
reject output can be dropped without loss — but that has to be verified from the connection graph,
not assumed.

Do not "fix" a missing reject model by merging its rows back into the main output, which silently
changes which rows the main model's row count represents.
