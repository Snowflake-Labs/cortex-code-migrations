---
name: testbed-generator
description: >
  Synthetic Testbed Generator. Setup `generateTestbed` bootstraps non-table
  coupling state. A `testbed_generator` helper generates one table via
  INCREMENTAL.md. An explicit whole-workload run uses WHOLE-WORKLOAD.md.
  Triggers: generate synthetic data, generate testbed, mine testbed, validate
  testbed, compile testbed, enrich testbed, run testbed phases, resume
  testbed, inspect unsolved constraints, testbed data source.
parent_skill: baseline-capture
license: Proprietary. See License-Skills for complete terms
---

# Testbed generator

Sequences `scai testbed` phases. The data lives in the CLI's opaque state. It
replaces production *data*, not source *access* — a source connection is still
required downstream to capture the baseline.

On SQL Server, `configure` creates an empty `AIMSBX_TB_*` source catalog and
binds it in `.scai/bindings/database-bindings.yaml` in place of each self-mapped
`source:` entry, and the generated rows load there. Other dialects, and a catalog
`configure` could not create, keep the self-mapped entry: an extracted project
then preserves its live source and loads nothing. `scai testbed load` itself refuses,
before any delete, a source table holding rows testbed did not write (it records
the tables it loaded under `.scai/testbed/loaded_tables.json`). Surface that refusal
to the user; do not rerun with `--allow-existing-data`, which is only for a
database the user confirms is a disposable copy.

If you are generating one table's CSV for a single `objectId`, follow
[INCREMENTAL.md](INCREMENTAL.md).

If the user asked to mine, validate, enrich, compile, or generate the whole
workload, follow [WHOLE-WORKLOAD.md](WHOLE-WORKLOAD.md). Naming one object is
not a whole-workload request.

## Named object with no table

Enter this skill for "generate synthetic data" for one named object.

If that object is not a table, read its dependency closure. When the closure
has no table, the procedure reads no tables — still run the testbed phases.
An empty closure is **not** permission to skip the tool when the user asked
to generate synthetic data for that object:

1. Follow [INCREMENTAL.md](INCREMENTAL.md) with that object's `objectId`
   (`mine` → `validate` → `compile` → `generate`). Skip `enrich` only when
   the readiness view is ready with nothing to enrich.
2. When a phase on that object fails (`mine` rc 1, "did not write a readable view")
   or generate leaves **0 CSVs** / `TBD0017` / "not a table", do not stop or ask:
   the hop still needs project testbed deliverables. Query the registry for a real
   **table** (prefer `OverlayClean` when present) and run
   [INCREMENTAL.md](INCREMENTAL.md) for **that table's** `objectId` until
   `.scai/testbed/manifest.json` and `testbed/generate/generate-summary.json`
   exist. That is producing the project CSV pool, not inventing a fake table
   name for the procedure.
3. Do not enter `synthetic-seeder`.
4. Do not shell `scai test`, `scai test seed`, `scai test capture`, or
   `scai testbed load`.
5. Leave the converted SQL unchanged.
6. Stop only when those two deliverable paths exist (or the table generate
   failed with a tool error you surface). Refusing the phases fails the hop.

## Setup bootstrap

When the setup machine enters this skill as `generateTestbed`, initialize only
the workload-level coupling objects:

```
testbed(phase="bootstrap")
```

Read `testbed/bootstrap/summary-view.json`, report its persisted-object counts
and diagnostics, then return to the setup parent. Do **not** mine, enrich,
compile, or generate any table here. The setup completion predicate is the
bootstrap view; table CSV ownership begins later in each table's
`deployCommonSandbox` walker. Do **not** call `transition_status` for
`generateTestbed` — it is a setup-machine task (a `filesystemProxy` status
source) and the resolver detects the view.
