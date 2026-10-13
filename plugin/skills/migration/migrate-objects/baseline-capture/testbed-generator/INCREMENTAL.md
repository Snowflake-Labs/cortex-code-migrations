# Incremental table testbed

Generate this table's CSV. You have one `objectId`.

Never call `transition_status`, `setup_sandbox`, `deploy`, or a data tool.

## Paths

Let `<object-artifacts>` be this unit's exact `files.artifacts.path` from the
registry. These scoped files are the source of truth:

| Role | Path |
|---|---|
| Unsolved view | `<projectDir>/<object-artifacts>/testbed/unsolved-view.json` |
| Readiness view | `<projectDir>/<object-artifacts>/testbed/readiness-view.json` |
| Fragments | `<projectDir>/<object-artifacts>/testbed/fragments/<prompt_type>.json` |
| Critic request / verdict | `<projectDir>/<object-artifacts>/testbed/critic/critique-request.json`, `verdict.json` |
| Enrich report / view | `<projectDir>/<object-artifacts>/testbed/enrichment-report.json`, `enrichment-view.json` |

Never open `testbed/mine/unsolved-view.json`, `testbed/validate/readiness-view.json`,
`testbed/enrich/fragments/`, `testbed/enrich/critic/`, or glob/read raw
`artifacts/**/*.testbed.json`. Do not re-filter a scoped view: the CLI already
uses affected-table semantics and exact CodeUnitId matching.

Pass `objectId` only on every `testbed` call. Do not pass a name. The driver
turns that id into `--where "id = '<objectId>'"` for `init` and `generate`
(CUR filters). `list-unsolved` / `validate` / `propose-enrichments` still take
the object as a positional.

## Lease

Each mutating phase (`mine`, `enrich`, `compile`, `generate`) waits up to 30s for
a lock. If you get `table pipeline busy` after that wait, retry.

## Steps

1. Call `testbed(phase="mine", objectId=<id>)` to initialize
   the table and write a fresh `<object-artifacts>/testbed/unsolved-view.json`.
   If the message still says `table pipeline busy`, retry.
2. Read the fresh scoped unsolved view. Do not reopen a constraint that is not listed.
   Call `testbed(phase="validate", objectId=<id>)` and read
   `<object-artifacts>/testbed/readiness-view.json`. Skip enrich only when
   `total` is 0 and the readiness view is ready — then go to step 4. A ready
   view with a non-zero `total` still needs enrich.
3. Read [ENRICH.md](ENRICH.md) and finish **Write fragments** against this
   table's files (the Paths table above) before any `testbed(phase="enrich")`
   call. Do not call enrich, compile, or generate until those files are on disk
   **IMPORTANT**. Never edit a related routine or another table.

   Then follow ENRICH.md **Propose**: pass `objectId` on
   every enrich call so stale completion views cannot short-circuit this table.
   A blocker that needs a human or a code change is terminal: return `escalate`
   with concrete choices. Do not call `release`. `table pipeline busy` on
   enrich/compile/generate after the driver's wait is also `busy` — another
   walker held the lease for the full wait budget.
4. After enrich returns ready — or enrich was skipped in step 2 — call scoped
   validate once more and require `ready: true`. Then call scoped compile:

   ```
   testbed(phase="compile", objectId=<id>)
   ```

5. Generate only this table, without supplying a new seed:

   ```
   testbed(phase="generate", objectId=<id>)
   ```

   Never set `ignore_readiness`. The first table establishes the default seed;
   later tables inherit the manifest seed and treat earlier CSVs as immutable
   FK parents.
6. Read `testbed/generate/summary-view.json` and the manifest it names. Require
   this table to have a manifest CSV entry. A fresh run may write one CSV; a
   resumed run may write zero because the exact table CSV is already frozen.
   More than one newly written table is an ownership violation: escalate rather
   than loading another walker's data.

A child is not offered until every parent has a
loaded CSV. Independent roots may author fragments at the same time; they only
queue on the lease during mine/enrich/compile/generate.

## Files

- `.scai/testbed/state.bin` — opaque CLI state. Never read or edit it.
- `testbed/generate/summary-view.json` and the manifest it names — confirm
  **this** table's CSV entry only.
- `.scai/testbed/run.json` — derived progress ledger.
