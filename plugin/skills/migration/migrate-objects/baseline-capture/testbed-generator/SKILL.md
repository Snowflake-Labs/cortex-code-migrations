---
name: testbed-generator
description: >
  Synthetic Testbed Generator. Setup `generateTestbed` bootstraps non-table
  coupling state. A `testbed_generator` helper generates one table via
  INCREMENTAL.md. An explicit whole-workload run uses WHOLE-WORKLOAD.md.
  Triggers: generate testbed, mine testbed, validate testbed, compile testbed,
  enrich testbed, run testbed phases, resume testbed, inspect unsolved
  constraints, testbed data source.
parent_skill: baseline-capture
license: Proprietary. See License-Skills for complete terms
---

# Testbed generator

Sequences `scai testbed` phases. The data lives in the CLI's opaque state. It
replaces production *data*, not source *access* — a source connection is still
required downstream to capture the baseline.

If you are generating one table's CSV for a single `objectId`, follow
[INCREMENTAL.md](INCREMENTAL.md).

If the user asked to mine, validate, enrich, compile, or generate the whole
workload, follow [WHOLE-WORKLOAD.md](WHOLE-WORKLOAD.md).

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
