# Incremental table testbed

Make this one table's enrichment ready; the walker's `walk_run(op="source")` compiles and
generates its CSV. Never edit a related routine or another table.

## Paths

`<obj>` = the directory of `files.unsolved_view` in `mine`'s reply. The scoped files behind
the inline payload:

| Role | Path |
|---|---|
| Unsolved view (when `mine` says `truncated`) | `<obj>/unsolved-view.json` |
| Fragments | `<obj>/fragments/<prompt_type>.json` |
| Critic request / verdict | `<obj>/critic/critique-request.json`, `verdict.json` |
| Enrich report | `<obj>/enrichment-report.json` |

Never open the whole-workload `testbed/` views, `.scai/testbed/`, or raw
`artifacts/**/*.testbed.json`. Do not re-filter a scoped view: the CLI already applies
affected-table semantics. Pass `objectId` (never a name) on every `testbed` call.

## Steps

1. `testbed(phase="mine", objectId=<id>)`. The reply carries `unsolved` (rows by kind),
   `readiness`, `prompts` (the text of each prompt type those rows need) and `next`.
2. `next: "compile"` → return `done`; the server compiles and generates.
3. Otherwise follow [enrich.md](enrich.md). rc 0 → return `done`. A blocker that needs a
   human or a code change is terminal: return `escalate` with concrete choices.
