# Batch Mode (10+ Files)

Batch mode turns on when the input is a directory or list of 10+ `.sas` files, or the user says
"convert all" / "batch convert". It changes only how often the skill stops and how work is split
across context windows -- never the conversion or validation rules.

## Stopping points

| Step | Interactive | Batch |
|---|---|---|
| Step 1: inputs (incl. validation depth and data questions) | ask | ask ONCE for the whole set |
| Step 4: block analysis | stop for review | log per file; one aggregate summary at the end |
| Validation (`workflows/validation-pipeline.md`) | runs to the approved depth | same -- no per-phase or per-file prompts |
| Step 10: report | present | one consolidated report |

## Conversion method (mandatory)

Each SAS file is read and converted by the LLM writing the `.sql` directly -- never a script or
regex converter. Convert 10-20 files per context window, writing each `.sql` to disk and
updating `conversion_state.json` before moving on.

## Splitting work across windows and subagents

| Unit | Batch | State | Resume |
|---|---|---|---|
| Conversion | 10-20 files | `conversion_state.json` per-file status | convert files without a `.sql` |
| Trace (T2 baselines) | 5 files | `trace_progress.files_remaining` | continue the list |
| Compile / run | the plan | `exec_plan_<mode>.json` step status | `sf_exec.py next` continues where it stopped |

## Parallel subagents (any input size)

Spawn a subagent for a unit only when it is **independent** (needs no unfinished work — check
`cross_file_graph` / plan `deps`) and **big enough** to repay ~20 s plus re-reading its references
(rough guide: outputs whose trace takes more than a few row steps).
Small units stay inline. Dispatch with `run_in_background: true`, collect with `agent_output`; each
writes files and state to disk and returns a ≤20-line summary — never file contents.

| Unit | Starts when | Reads | Writes |
|---|---|---|---|
| Data prep (validation in scope) | Step 4 done and any `tables.py probe` run — then you convert | SAS, `tables.json`, `run_assumptions.md`, validation-pipeline §Registry, `schema-inference.md`, `synthetic-data-rules.md` | inputs' registry rows, `source_table_ddl.sql`, `synthetic_data.sql` — files only, no SQL |
| Trace one file's outputs | data prep returned | SAS, `tables.json`, seed, `run_assumptions.md`, `synthetic-data-rules.md`, `comparison-rules.md`, `validation-execution.md`; **never the converted SQL** | one `tests/<file>/expected/expected_<TABLE>.csv` per table **you list in its prompt**: the T2 set — final outputs and intermediates that join, filter, aggregate or carry RETAIN/BY/LAG state (WORK ones by bare SAS name; skip tables the program deletes); then `tables.py stamp` |

Before dispatching, write `<out>/run_assumptions.md` (≤15 lines): run date and every macro variable's
value, YEARCUTOFF, what each external macro / missing format is assumed to do. Converter, data prep and
tracers all follow it, so a baseline can only disagree with the SQL on logic. Conversion stays with the
agent that did Steps 1-4 (a fresh converter loses that analysis: measured more runtime and fidelity
defects); only 10+ file batches split conversion, for context, as below. Add your WORK intermediates
to `tables.json` after data prep returns (one writer at a time). Never in a subagent: SQL against the
validation session (temp tables and session variables live there) — you load the DDL and seed.

**Batch subagents.** Hand each subagent ONE dependency layer (from `exec_plan_run.json` `order`/`deps`)
or ≤10 files to convert, with the output dir, the registry path and the exact steps it must
finish. Independent layers/files may be dispatched together with `run_in_background: true` and
collected with `agent_output`; a layer starts only after the layers it depends on finished.
Subagents write files and state to disk and return a ≤20-line summary -- never file contents.
Validation of one plan stays in one session (temp tables and session variables live there).

**Batch checkpoints.** Work through the batch continuously. After each file and at each batch
boundary, write `conversion_state.json` and any output CSVs, then continue to the next file.
Finish each file before checkpointing because a partial trace is invalid; a compacted or new
session resumes from the saved state.

## Recovery in a new window

1. List `<out>/*.sql`; read `conversion_state.json` and `gates`.
2. Re-run Gate 0 (`sql_check.py all`); continue the earliest gate that is not `PASSED`/`SKIPPED`.
3. If re-running a conversion into a new output dir, the new output must have ≥ the file count of
   the previous one.

## Batch report

Aggregate counts per tier and gate, the top failure classes (`sf_exec.py status`, `sql_check`
rule counts), one cross-file DAG and one orchestration recommendation -- not per-file sections.
