# Validation Pipeline (T1 compile → T2 unit test → T3 end-to-end, one repair loop)

## When to Load

Load after Step 6a (every `.sql` written and verified on disk). This is the only validation
orchestrator; the references it names hold method detail, not workflow.

Tools (stdlib Python, print only findings + one summary line — never `cat` their JSON):
`T=<skill>/tool`, `A=<sas>/assess-sas-migration/tool`.

| Tool | Use |
|---|---|
| `python3 $T/sql_check.py all --dir <out> --sas-dir <src> --tables <out>/tables.json` | static gate: comment desync, verified Snowflake constraints, cross-file names/arity/stubs, SAS-anchor fidelity |
| `python3 $A/tables.py summary|probe|ingest|import-ddl|get|gap|seed-targets|render-ddl` | the table registry: location, columns, where each came from |
| `python3 $T/sf_exec.py plan|next|record|reset|status|counts-sql|ingest-counts` | statement order, compile-vs-execute choice, first blocker per file, failure class, empty outputs |

---

## Step 1 inputs (asked once, with the other Step 1 questions — see SKILL.md)

| Question | Answer feeds |
|---|---|
| Validation depth: **T1** compile only (no credits) / **T2** + unit test on test data / **T3** + end-to-end on full data / none | which tiers run; no further consent prompts |
| Where do the source tables live in Snowflake? (schemas, or "not in Snowflake") | registry probe |
| DDL for inputs/outputs? (`.sql` CREATE TABLEs or `table,column,type` CSV) | `tables.py import-ddl` |
| Test data for T2? (tables, or CSV/parquet on a stage) — else synthetic | T2 seeding |
| SAS outputs to compare against? (tables/CSVs produced by SAS on the same inputs) — else LLM trace | T2/T3 baseline |
| T3 only: full-data location per input, and SAS full-run outputs if any | `tables.py update --full-data-fqn / --sas-output-fqn` |

Anything not supplied is inferred and **named as inferred in the report**. Credit-using tiers
(T2, T3) were approved by this answer; do not re-prompt per phase.

---

## Gate 0 — static check (always, zero credits)

```bash
python3 $T/sql_check.py all --dir <out> --sas-dir <src> --tables <out>/tables.json
```
- `malformed_statement` → `sql_check.py fix --dir <out>` (refuses if a real statement would be
  lost), then re-run.
- Every other `error` → fix the SQL (repair loop below, class `OWN_DEFECT`) and re-run until
  `errors=0`. Never suppress with `-- sql_check: allow <rule>` unless the finding is wrong for
  this code; say why in the same comment.
- `warn` lines are judgement calls: resolve or justify (`type_cast_without_reason` → add the
  `-- TYPE:` evidence or remove the cast; `no_sas_anchors` → add anchors).

Gate passes at `errors=0`. Record `gates.static_check`.

## Registry — know every table before touching data (zero credits except one metadata query)

1. Locations given → `tables.py probe tables.json --schemas DB.SCH[,…]` prints ONE query; run it,
   save its single JSON cell to `<out>/probe_result.json`, then `tables.py ingest tables.json
   probe_result.json --schemas …`. Inputs not found are marked `not_found`; bare names shared by
   two librefs are reported `ambiguous` — ask once, then `tables.py update … --fqn`.
2. DDL given → `tables.py import-ddl tables.json <file>`.
3. Remaining inputs with no columns → infer per `references/schema-inference.md`, recorded with
   `tables.py update --batch rows.jsonl --by convert` (one write). Add every WORK intermediate the
   SQL creates as `"role": "intermediate"`. Rows with `"macro_name": true` are name patterns
   (`LIB.T&SUFFIX`): bind the resolved name with `tables.py update … --fqn` before probing or seeding.
4. `tables.py render-ddl tables.json --roles input > <out>/source_table_ddl.sql` (never hand-edit).
5. `tables.py summary tables.json` → the counts go in the report (found / not_found / inferred).

---

## T1 — Compile (no warehouse credits)

```bash
python3 $T/sf_exec.py plan --dir <out> --tables <out>/tables.json --mode compile --stage @<validation_schema>.SAS_RUN/<run>
```
**Never re-type SQL that is on disk.** Create the stage once (`CREATE STAGE IF NOT EXISTS …`). With
`--stage`, `next` prints a `PUT` + `EXECUTE IMMEDIATE FROM` pair for the file's next run of executed
statements: send those two lines as one call and `record` the group's first id (an error's "on line N"
names the failing statement). Load `source_table_ddl.sql` and `synthetic_data.sql` the same way. Only
if `PUT` is rejected, re-plan without `--stage` and paste what `next` prints. Drop the stage at the end.
1. Create the source tables from `source_table_ddl.sql` in the validation schema (DDL only).
2. Loop: `sf_exec.py next --plan <out>/exec_plan_compile.json` prints one statement and
   `run_with=`; run it (`only_compile=true` when told) and record the outcome:
   `sf_exec.py record --plan … --id N --ok` or `--error "<first line of the error>"`.
   `record` prints the failure class. `DEFERRED` (needs an object an earlier statement creates)
   is not a failure — T2 checks it.
3. `sf_exec.py status` — exit 0 means every file compiled (deferred aside). Failures go to the
   repair loop; after a fix, `sf_exec.py reset --files <f>` and continue with `next`.

Run session-dependent statements (USE, SET, temp tables) one call at a time, never in parallel tool
calls: parallel calls can lose the session's schema. Harness CALLs use fully qualified names.
A recycled session ("session no longer exists", "no current database", a sudden privilege error — the
role may revert) loses USE/SET and temp tables: re-run `USE ROLE`/`USE SCHEMA`, `sf_exec reset` the
current file, and continue — never classify it as a conversion defect.

Write `compilation_results.json` (`total_files, passed, failed, deferred, failures[{file, line,
class, error}], fixes_applied[]`). A stored procedure that compiles has had its body parsed but
not resolved — names inside it are only proven in T2.

## T2 — Unit test on test data

**Data.** Seed only `tables.py seed-targets tables.json` (source leaves). User test data →
load/clone it into the validation schema at the names the code reads. Otherwise synthetic, per
`references/synthetic-data-rules.md` (5–8 rows per table; golden path through every join).

**Baseline (expected outputs).**
- SAS outputs supplied → they are the baseline (`--sas-output-fqn` or CSV under `tests/<file>/expected/`).
- Otherwise trace the SAS against the test data (`references/validation-execution.md`) for every
  file in scope; batch mode traces a **construct-covering** subset: at least one file for each
  construct the assessment found (MERGE, BY/FIRST./LAST., RETAIN/LAG, hash lookup, CALL EXECUTE,
  PROC SORT NODUPKEY, PROC SQL joins/aggregation, macro loops), largest files first.
- Trace every final output, and every intermediate that joins, filters, aggregates or carries
  RETAIN/BY state. A pass-through or rename-only intermediate gets row count + columns only.
- Tracing needs only the SAS, the registry, the seed and `run_assumptions.md`: data prep and tracers
  run as subagents while you convert, and tracers never see the converted SQL (`references/batch-mode.md`).
- Write the baseline **before** running the converted SQL, then stamp it:
  `tables.py stamp tables.json <csv> <tables it was traced against>`; `tables.py check-stale tables.json <out>/tests` after
  any registry change re-opens stale baselines.

**Run.** `sf_exec.py plan --mode run --stage …`, then the same `next`/`record` loop (all statements execute;
CALL each procedure the file defines if the file does not). T1 already created every routine; when T2 runs
in the same schema, for a file not edited since T1, record its `routine` steps `--ok` without re-sending
the body, and run only its CALLs and queries. If a program writes to one of its own inputs (PROC
APPEND, read-then-replace), re-run `synthetic_data.sql` before every T2/T3 re-run. Then:
```bash
python3 $T/sf_exec.py counts-sql --plan <out>/exec_plan_run.json   # run the one query it prints
python3 $T/sf_exec.py ingest-counts --plan … counts.json            # names EMPTY outputs
```
**Compare** each output with its baseline per `references/comparison-rules.md` — never hand-write the
compare SQL or read full results back. Baselines live at `tests/<file>/expected/expected_<TABLE>.csv`;
`sf_exec.py compare-sql --plan … --tests <out>/tests --schema <target>` writes one query (columns by
name, NULL = '', trailing blanks trimmed, dates by day, numbers rounded to `--digits` [6]; duplicates
counted) and prints how to run it. PASS = `MISSING = EXTRA = 0`; `DIFF_ROWS` shows up to 10. Write
`snowflake_execution_results.json` (`total_files, passed, failed, no_baseline, results[{file,
table, status: PASS|FAIL|NO_BASELINE|TRIVIAL_PASS|EMPTY_DEFECT|EMPTY_JUSTIFIED, mismatches,
class}]`).

## T3 — End-to-end on full data

1. Build the harness per `references/e2e-orchestration-test.md` (`orchestration/` DAG in
   `sf_exec` plan order — the harness and the scheduled DAG run the same order, the same files).
2. Point inputs at full data (`tables.json full_data_fqn`); read-only — never write to a source.
3. Run the plan (`--mode run`); every terminal output non-empty unless justified.
4. Compare with SAS full-run outputs when given, on a key-anchored sample (comparison-rules.md
   §Full-data sampling) plus whole-table row counts and column aggregates. Without SAS outputs,
   T3 proves only that the pipeline runs and fills its outputs — say so; never trace full data.
5. Write `e2e_test_results.json` (`steps_total, steps_passed, steps_failed, terminal_tables[{table,
   rows, status, baseline_match}], status`).

---

## Repair loop (every tier)

For each failure, in plan order (the first blocker of the earliest file first):

1. **Classify** — `sf_exec.py record` names the class for run errors; classify mismatches yourself:

| Class | Meaning | Action |
|---|---|---|
| `OWN_DEFECT` | the converted SQL is wrong | fix that file (smallest change; re-read the SAS lines in its `-- SAS:` anchor) |
| `UPSTREAM_CASCADE` | its input failed or was skipped | fix the upstream file; never patch the symptom here |
| `ORDER` | right SQL, wrong sequence | re-plan; never reorder statements by hand |
| `TEST_DATA_GAP` | test data/DDL lacks what the code needs (`tables.py gap` exit 3) | fix `tables.json` → `render-ddl` → reload; never change the SQL for it |
| `BASELINE_CORRECTED` | the trace was wrong, the SQL right | correct the expected CSV, re-stamp, record why |
| `SOURCE_DEFECT_PRESERVED` | SAS itself misbehaves and the SQL faithfully reproduces it | keep; report it to the user |
| `ENV` | permissions, warehouse, timeouts | stop and report; not a conversion result |
| `UNRESOLVED` | 3 attempts on this file and class failed | stop on this file, report the last error, continue with independent files |

2. **Fix**, re-run Gate 0 (`sql_check.py all`), then `sf_exec.py reset --files <f>` (resets its
   dependents too) and continue `next` from there. Only the changed file and its dependents re-run.
3. **Budget**: max 3 attempts per file per class; each attempt is recorded in
   `validation_results.json.repairs[{file, class, attempt, change, outcome}]`.

**False greens — never report these as passes:**
- an output with 0 rows while its inputs have rows (`EMPTY_DEFECT`);
- `expected = 0 AND actual = 0` (`TRIVIAL_PASS`, a warning);
- a file with statements still `pending`/`skipped` in `sf_exec.py status`;
- a value comparison on an output whose baseline is stale (`check-stale`);
- a fix that edited the baseline and the SQL in the same attempt.

---

## Results and state

`conversion_state.json` (fields read by Step 10 and on resume):
```json
{
  "validation_selections": {"depth": "T1|T2|T3|none", "test_data": "user|synthetic", "baseline": "sas_outputs|trace"},
  "gates": {"static_check": "PASSED|BLOCKED", "t1_compile": "PASSED|BLOCKED|SKIPPED",
            "t2_unit": "PASSED|BLOCKED|SKIPPED", "t3_e2e": "PASSED|BLOCKED|SKIPPED"},
  "trace_progress": {"files_traced": [], "files_remaining": []}
}
```
Artifacts: `sql_check.json`, `tables.json`, `source_table_ddl.sql`, `exec_plan_compile.json`,
`exec_plan_run.json`, `compilation_results.json`, `tests/<file>/expected/*.csv`,
`snowflake_execution_results.json`, `e2e_test_results.json`, `validation_results.json`
(`repairs[]`, unresolved items). Every file must exist — with a `status` of `SKIPPED` when the
tier did not run — because Step 10 reads them all.

**Batch checkpoints:** trace and execute in batches of 5 files. After each batch, update
`trace_progress`, save partial result files and `conversion_state.json`, and append a checkpoint
line (`references/checkpoint-logging.md`), then continue to the next batch. A compacted or new
session resumes from the saved state and execution plan. Large batches: hand one dependency
layer per subagent (`references/batch-mode.md`).

**Resume:** read `conversion_state.json`; re-run Gate 0; continue the earliest tier whose gate is
not `PASSED`/`SKIPPED` — `sf_exec.py status` shows where the plan stopped.

**Cleanup:** drop session temp tables, test stages and validation-only objects; keep deployed
procedures only if the user asked for deployment. Never drop or write anything outside the
validation and target schemas.

→ Step 10 (`workflows/step-10-report.md`).
