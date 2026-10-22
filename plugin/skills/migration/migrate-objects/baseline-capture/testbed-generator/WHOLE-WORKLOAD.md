# Whole-workload testbed

Run mine → validate → enrich → compile → generate for the entire converted
workload.

The core phases are independent and resumable: **mine** (`init` → `list-unsolved`
→ whole-workload branch drill-down) inventories the constraint/branch coverage;
**validate** reads the mined state and reports readiness (fk gaps / type conflicts
/ unsatisfied constraints) — `ready: false` is a report, not a failure; **enrich**
is the reasoning + propose/validate loop that turns unsolved constraints into
enrichment JSON (see [ENRICH.md](ENRICH.md)); **compile** materializes the
data-coupling clusters + coordination spec that data generation consumes;
**generate** (readiness-gated) writes the CSV pool + manifest deliverable. Each
phase is deterministic — re-running it is safe and cheap.

## On Entry

Tell the user:

> "Running the testbed mine → validate → enrich → compile → generate phases: I'll inventory
> the branch/constraint coverage your converted workload needs and show the
> categorized unsolved-constraint view, report readiness (fk gaps / type conflicts /
> unsatisfied constraints), run the enrichment loop that turns the unsolved constraints
> into enrichment JSON (assemble → propose → validate, with a bounded retry/iterate budget),
> compile the data-coupling / coordination spec and show its cluster summary, then —
> readiness permitting — generate the CSV pool + manifest and show the row counts. This
> reads the conversion artifacts and the testbed state; the enrich phase mutates that state
> (through `propose-enrichments`) and only the generate phase writes data files."

## Scope

- In scope: `init` → `list-unsolved` (mine) → surface the categorized view; `validate` → surface the readiness view; `compile` → surface the cluster summary; the two-pass ENRICH reasoning in [ENRICH.md](ENRICH.md); `generate` (readiness-gated) → surface row counts + CSV/manifest deliverable; resume each phase; classify failures.
- In scope (orchestrate): assemble the per-type fragments into the 8-array envelope, drive `propose-enrichments`/`validate` with a bounded retry/iterate budget.
- Out of scope: `generate`'s CSV internals; the per-object test-YAML bridge; scoped per-table generation.
- Phase-scoped runs: each `testbed` phase (`mine`, `validate`, `enrich`, `compile`, `generate`) can be run and stopped independently — e.g. run `validate` to inspect readiness without generating data.

## Paths

Do not pass `objectId`. Project-level views are the source of
truth. Never open a table's `<object-artifacts>/testbed/` views.

| Role | Path |
|---|---|
| Unsolved view | `testbed/mine/unsolved-view.json` |
| Readiness view | `testbed/validate/readiness-view.json` |
| Fragments | `testbed/enrich/fragments/<prompt_type>.json` |
| Critic request / verdict | `testbed/enrich/critic/critique-request.json`, `verdict.json` |
| Enrich report / view | `testbed/enrich/enrichment-report.json`, `testbed/enrich/enrichment-view.json` |

## Steps

1. Ensure the MCP session is configured: if you were spawned as a sub-agent, call `configure(project_dir=<abs_path>)` first (you may be the first to touch the server, and there is no working-directory fallback).

   Every phase below is one call to the `testbed` MCP tool, which returns `{phase, rc, message}`: `rc: 0` means the phase completed and wrote its view, `rc: 1` means it stopped and `message` says why. The tool uses the configured project — no path is passed. "rc 0" / "rc 1" below refer to that field, and the `<station> failed [<code>] <message> (<class>)` / `generate blocked: …` text below is the returned `message`.
2. **Mine phase.** Call `testbed(phase="mine")`.
3. **On mine rc 0:** the tool wrote `testbed/mine/unsolved-view.json` and printed a one-line summary. Present the summary, then read `testbed/mine/unsolved-view.json` and show the per-`kind` counts (`fk`, `check`, `branch_predicate`, `join_edge`, `enum_domain`) and the `branches` drill-down (per object: `branch_count`, `unsolved_branches`). Do not paraphrase the counts — read them from the file. A table with `branch_count: 0` is normal — tables have no branches; do not report it as a gap.
4. **On mine rc 1:** the `message` is `"<station> failed [<code>] <message> (<class>)"`. Act on the class, then stop (do not proceed to compile):
   - `input_config` (e.g. `PRJ0003`, `TBD0007`): the project dir or artifacts path is wrong. Fix it and re-run step 2.
   - `data_isolable` / `data_quarantine`: the tool recorded the offending object as PENDING in `.scai/testbed/run.json` and continued where it could. Tell the user which objects are PENDING and why.
   - `escalate`: stop and surface the full error; do not retry.
5. **Validate phase (after mine rc 0).** Call `testbed(phase="validate")`.
6. **On validate rc 0:** the tool wrote `testbed/validate/readiness-view.json` and printed a one-line summary. Read the view and present `ready`, `counts` (`blocking`, `advisory`, `fk_gaps`, `type_conflicts`, `unsatisfied_constraints`, `overlaps`), and the `fk_gaps` / `type_conflicts` / `unsatisfied_constraints` / `overlaps` arrays. **`ready: false` is not an error** — it is a successful report of gaps carried in the view. If not ready, tell the user the blocking issues must be fixed (or explicitly overridden at generate) before data will generate. On a package-driven (SSIS) workload, FK-gap checking is suppressed and `overlaps` (Lookup / Merge-Join key domains that provably cannot match) is usually the only populated bucket — so it is the whole answer to "what is blocking this run", and each entry's `remediation.hint` is what the user must act on. Present every bucket the `counts` object reports; if a tally is non-zero and its array is empty, say so rather than reporting no issues.
7. **On validate rc 1:** act on the class (`input_config` `TBD0002`: state missing — re-run mine; `escalate` `TBD0003/4/5`: surface the CLI `suggestion` and stop).
8. **Enrich phase (after validate rc 0, before compile).** Follow [ENRICH.md](ENRICH.md). Finish **Write fragments** before any `testbed(phase="enrich")` call. That loop assembles the prompt fragments into one envelope, runs the deterministic critic station, proposes the envelope, and re-validates readiness (one bounded step of the retry/iterate loop).

   On **rc 0** the tool wrote `testbed/enrich/enrichment-view.json` and the workload is ready — proceed to compile. On **rc 1** read `testbed/enrich/enrichment-report.json` and act on its `stop_kind` (`reject` / `iterate` / `critique` / `documented-stop` / `budget-exhausted`); the full loop and each stop's remediation are in [ENRICH.md](ENRICH.md). **Enrich MUST precede compile** — it mutates the mined state that compile materializes into clusters, and its terminal `validate ready` is the readiness precondition the generate gate checks.
9. **Compile phase (only after enrich rc 0).** Call `testbed(phase="compile")`.
10. **On compile rc 0:** the tool wrote `testbed/compile/clusters-view.json` and printed a one-line summary. Present the summary, then read `testbed/compile/clusters-view.json` and show `clusters`, `coupled_objects`, `singleton_objects`, `largest_cluster`. Note for the user: per-cluster membership is not surfaced yet — that arrives with the (later) generate phase.
11. **On compile rc 1:** the `message` is `"compile failed [<code>] <message> (<class>)"`. Act on the class:
    - `input_config` (`TBD0002`): the testbed state (`.scai/testbed/state.bin`) is missing — the mine phase's `init` didn't run or was cleared. Re-run step 2, then step 9.
    - `escalate` (`TBD0003`/`TBD0004`/`TBD0005`): the state is unreadable, version-mismatched, or corrupt. Surface the CLI's `suggestion` verbatim (typically: re-run `init`, or remove a duplicate source object then re-mine). Do not retry blindly.
12. **Generate phase (after compile rc 0 and validate ready — or an explicit override).** Call `testbed(phase="generate")`.

    - If the workspace was **not ready** at validate, the tool blocks with `"generate blocked: N blocking issue(s); re-run with ignore_readiness=true to override"`. Only re-call with `testbed(phase="generate", ignore_readiness=true)` after telling the user which blocking issues will be bypassed.
    - If validate never ran, the tool blocks with `"generate blocked: run validate first"` — run Step 5 first.
13. **On generate rc 0:** the tool wrote `testbed/generate/summary-view.json` and printed a one-line summary. Read the view and present `tables`, `rows_written`, `csv_files`, `warnings`, and `readiness_overridden` — surface each warning (a non-fatal generation diagnostic, e.g. a declared width too narrow to hold `row_count` distinct key values). An empty workspace is a success with `csv_files: 0` and a `note` — surface the note. `out_path` is the **project root** the manifest's per-table `csv_path` entries are relative to (not a CSV directory), and `manifest_path` is the provenance `manifest.json` beside `state.bin`; to list the generated CSVs, read the `csv_path` entries from `manifest.json` at `manifest_path` — don't present `out_path` as the output directory.
14. **On generate rc 1:** act on the class (`input_config` `TBD0012`: state not compiled — run Step 9 first; `escalate`: surface the error and stop).
15. Do **not** call `transition_status`. `testbed/generate/summary-view.json` is the terminal deliverable.

## Files

- `.scai/testbed/state.bin` — opaque CLI state (mining spec + materialized clusters). Never read or edit it; treat it as a black box owned by `scai testbed`.
- `testbed/mine/unsolved-view.json` — the mine deliverable.
- `testbed/validate/readiness-view.json` — the validate deliverable. Scoped table validation never overwrites it.
- `testbed/enrich/fragments/`, `testbed/enrich/critic/`, `testbed/enrich/enrichment-report.json`, `testbed/enrich/enrichment-view.json`.
- `testbed/compile/clusters-view.json` — the compile deliverable.
- `testbed/generate/summary-view.json` — latest generate deliverable: row counts + CSV/manifest paths.
- Generated CSVs + provenance `manifest.json` — the `generate` deliverable. Each table's CSV lands under its own object's `<artifacts>/testbed/` folder; the `manifest.json` (beside `state.bin`, at the view's `manifest_path`) lists them as project-root-relative `csv_path` entries. The view's `out_path` is that project root — not a CSV directory. No output dir is passed to `scai testbed generate`.
- `.scai/testbed/run.json` — derived progress ledger (mine/validate/compile/generate status, PENDING records).
