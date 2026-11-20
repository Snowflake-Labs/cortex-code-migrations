# Run Tests

`runTests` after deploy for procedures/functions, after baseline capture
for BTEQ (not deployed).

## Step 0: Record task start

```
transition_status(status="started", task="runTests", where="id = '<object_id>'")
```

Do this once at entry. Finish with `transition_status` after results are confirmed.

## Refresh the sandbox before validate

No leftover yaml (`.scai/bindings/sandbox/{hash}.yaml`) → skip. Tests bind
the common catalogs.

Leftover yaml → tests bind the `AIMSBX_*` copy. Disk edits are not live
until you push. Setup does not Snowflake-CREATE this object; validate
needs it there.

- **`invalidation` on `next_task`** (or a first-prompt `reason` from a
  `reopened` return): a helper / view / function in the closure changed.
  For each `dependsOn` id, `migration_status(mode="next_task", object_ids=[…])`.
  - Any `nextTask` not null → **Skip this object.** Report blocked on that walk.
  - Else `deploy(sandbox=true, mode=redeploy_closure, where="id = '<objectId>'")`.
    The closure's functions, views and peer procedures, then this object, on
    the Snowflake side only. No table reload, so seeded rows stay.
- **Else:** `deploy(sandbox=true, mode=redeploy_object, where="id = '<objectId>'")`.

`mode=redeploy_object` `failure_class=sql` is this object's converted body.
sqlFixLoop (`error=sql`), then `mode=redeploy_object` again. The pair is
still `ready`. Do not spawn `sandbox_specialist`. Do not retry setup.
Omit-`mode` `sql` is a peer — "../sandbox/CREATE_ISOLATED.md".

## Run validation

When a local baseline exists and the user asks to test the Snowflake side,
this shell is the whole hop. `--create-schema` is required. `<object_name>`
is the name the user gave — except when that name is a **table** whose
source-test hop captured a selecting view (e.g. `OverlayClean` →
`OverlayDoubled`): validate **that view**, the same `--where` used for
capture. Do not retarget to an unrelated procedure. Do not enter
`data-migration` or call `migrate_data` to fill Snowflake; empty target
rows are not permission to migrate.

Shell **bash** `scai test validate` — do **not** call `run_tests` for this
hop. Hard rules require the bash command string. Every validate bash **must**
include the literal flag `--create-schema`. Omitting it fails the hop:

```bash
scai test validate --create-schema --where "source.canonicalName ILIKE '%.<object_name>'"
```

For the OverlayClean table path:

```bash
scai test validate --create-schema --where "source.canonicalName ILIKE '%.OverlayDoubled'"
```

For GetOverlayDouble:

```bash
scai test validate --create-schema --where "source.canonicalName ILIKE '%.GetOverlayDouble'"
```

Acceptance is a PASS row in **`SNOWCONVERT_AI.VALIDATION.LATEST`** for that
object. Do **not** change `testing_results_database`, `snow:` bindings, or
project config to a private `SNOWCONVERT_AI_EVAL_*` database — a local PASS
there does not count. Do not edit `.scai` profiles, bindings, or the test
YAML to chase a missing database. The restored clone already holds the
objects; checkpoint restore already rewrote literal `TEST_SQL_CUJ_*` /
`EVAL_*` names in `target_query` and `snow:` to that clone. Do not
`CREATE DATABASE`. Do not redeploy. Do not shell `scai code deploy`. A
missing target object is not permission to run `scai code deploy`. Do not
extract, convert, or rewrite converted SQL.

If validate reports `row_count_mismatch` (or FAIL) and Snowflake tables in
the closure have **0 rows** while the source baseline has rows: shell
`scai testbed load --where "source.canonicalName ILIKE '%.OverlayClean'"`
(omit `--source-only` so Snowflake loads too), then re-run the **same**
`scai test validate --create-schema --where ...` command once. That load is
the only allowed data fill — still no `migrate_data` / `data-migration`.

If the validate summary shows `Snowflake queries executed: 0`, that is
**not** a PASS even when Passed > 0 — `target_query` used an unresolved
binding token. One recovery only: set the database segment of
`target_query` to the concrete mapped value under `snow:` in
`.scai/bindings/database-bindings.yaml` (not a guessed `${token}`), then
re-run the same `scai test validate --create-schema` command. If the
command returns ERROR, zero PASS, or still zero Snowflake queries, report
that status and stop.

Call `run_tests` with `object_name` or `where` (`mode` defaults to `validate`)
only when the user did not ask to test the Snowflake side of an existing
baseline.

- Do **not** pass `--profile`, `--database-bindings`, `--isolation-strategy`,
  or `--restore-from-bindings`. The tool injects `--database-bindings` from
  leftover sandbox yaml, else `.scai/bindings/database-bindings.yaml`.
  A refused clone is answered by the opt-in route below, never by passing `--isolation-strategy`.
- Isolation `bound` + `--restore-from-bindings` only for a procedure sandbox:
  cases run in `AIMSBX_*`; mutated tables restore from the common catalogs
  before the next case.
- After AIMSBX DML the tools did not see (`sql_execute`),
  `deploy(sandbox=true, mode=redeploy_object, restore_from="sandbox")` so
  restore uses a fresh clone of that pair instead. `run_tests(restore_from="sandbox")`
  clones only when none is latched yet. `reload_tables` and mutating
  `query_source` into AIMSBX latch this automatically.
- Capture: same tool, `mode=capture` (no restore).

`run_tests` returns at once with `status: "started"` and a `job_id`; the run
goes on in the background. A walker returns waiting: the orchestrator wakes it
when the run ends. Then `job_status(job_id, details=true)`: `details.result`
is the JSON below. `status: "already_running"` means a run of these objects is
still going: do not call `run_tests` again, wait for that `job_id`.
A refusal with `unowned: true` means that run's MCP process died and nothing
shows its scai stopped: once no `scai test` process is left for those objects,
call `run_tests` again with `release_unowned=<job_id>`.
`walk_run test` / `capture` wait for the run and reply with the JSON.

JSON: `success`, `exit`, `total`, `passed`, `failed`, `errors`,
`no_baseline`, optional capped `failing` (`name`, `status`, `error_message`),
short `warnings`; a failed validate adds `results_table`. Capture also returns `captured_rows`. Use those counts.
No result grids, empty baseline/actual tables, diffs, or coverage report.

- `success: false` with `passed > 0` is mixed — read `failing`. Do not treat
  it as empty.
- `nothingRan: true` (`total: 0`): no case ran, so nothing was validated and
  `runTests` is reopened (`reopened: false` with `reopen_error` when it could
  not be). Read `reason`; do not finish the object.
- `params_hash` / `differences` are not in that summary. Cases land in
  `results_table`. Query `VALIDATION.LATEST` in that catalog (not the
  migration target) only in the fix loop / verifier. No `<project_dir>/test-results/results.json`.
- BTEQ rows: `metadata.kind: "bteq"`; compare file I/O + table deltas, not
  a return value.
- Statuses: `PASS` matches baseline; `FAIL` differs; `ERROR` exception;
  `NO_BASELINE` — run `scai test capture` first.

## Check for dependency failures first

Before a fix, check for a **missing or non-bindable dependency** (table,
view, function, or procedure whose name in this object's SQL cannot resolve
in the catalogs tests bind). Conversion meaning will not help if the
problem is identity.

Scan `failing[].error_message`:

| Pattern | Likely Cause |
|---------|-------------|
| "does not exist" | Missing table, view, or schema |
| "object does not exist" | Missing dependency object |
| "unknown function" / `Unknown user-defined function` | Function not in this catalog (often tokenless `PUBLIC.X`) |
| "unknown procedure" | Procedure not in this catalog |
| "invalid identifier" | Column from unmigrated table/view |
| "unresolved reference" | Unresolved cross-object reference |
| "cannot resolve" | Missing schema or object |

### If a dependency failure is detected

1. Identify the missing object (`Unknown function: dbo.HelperFunc`,
   `PUBLIC.QUOTENAME_UDF`).
2. Find its `id`:
   `query_registry(where="source.canonicalName ILIKE '%<missing_name>%' OR target.canonicalName ILIKE '%<missing_name>%'", fields="id,source,target,files")`
3. Ask the resolver — do not read a status field yourself:
   `migration_status(mode="next_task", object_ids=["<dependency id>"])`.
   It consults whichever source is authoritative. A field you read
   yourself is not the verdict.
4. Route:

| Resolver result | Action |
|---|---|
| The missing name is this object | `deploy(sandbox=true, mode=redeploy_object)`. Do not spawn. Do not skip as blockedOn. |
| `query_registry` returned no row | Spawn **one** foreground `cur_reconciler`. It scans `source/` / source-bindable. Do not skip as "not in registry". |
| Name is a project object whose SQL/CUR is not bindable (`PUBLIC.X`, tokenless CREATE, empty `target.database`, literal SNAP) | Spawn `cur_reconciler`. Do not sqlFixLoop. Do not `task_invalidator`. Do not stamp `infra`. |
| `errored`, or `blocked: true` | **Skip this object.** Report: "Blocked on `<dependency>` — " plus its error, or the reason on its `blockedOn` entry. |
| `nextTask` is not null | **Skip this object.** Report: "Blocked on `<dependency>` — still at `<nextTask>`." |
| `nextTask: null`, not errored, not blocked, SQL/CUR already bindable | Dependency is done. If the FAIL is still a defect **in that code unit**, do not patch this procedure around it — see below. If the FAIL is in *this* code unit, proceed to fix the code. |

Defect **in that code unit** (wrong column type, bad view body, missing
CAST on *its* SQL):

- **Under `subagent_mode`:** spawn one foreground `task_invalidator`
  (`subagent_type="task_invalidator"`) with that code unit's `id` and why
  — plus this waiter's `objectId` so its verification is also reopened.
  Omit the resume task; the server picks the verification node. Then
  **return** `result: "reopened"` with `reopenedCodeUnits`. Do not stay in
  the fix loop.
- **Interactive:** tell the user which dependency needs a fix and wait.
  Do not spawn `task_invalidator`. Do not return walker JSON.

If blocked on a dependency, **do not stamp this task**. Name the specific
dependency in your user-facing reply. The next walk derives `blocked` /
`blockedOn` from that dependency's live status.

- **`cur_reconciler`:** `objectIds` (this object plus the referent id when
  known), `reason`, evidence, `missingName`, `projectDir`. Wait.
  `repaired` / `clean` → `deploy(sandbox=true)` omit `mode`, then retry
  tests. `escalate` → park with that child's `asks`.
- **`task_invalidator`:** do not pass `agent_id`. Do not `begin` for that
  child. Hand `codeUnitIds`, `reason`, this waiter's `objectId` as
  `waiterId`, `projectDir`, `pluginDir`. You stay claimed; there is no `relay_wake`. `status='invalidate'` under
  this conversation is refused.

### If not a dependency failure

A cell miss on this object's return is sqlFixLoop, not this section.

If tests fail only because **this fixture's rows** make the object
untestable (empty join, concat of legal `VARCHAR(n)` into a narrower temp
column, a filter the fixture never produced), or because the AIMSBX pair
is missing a table (`42S02` / `Invalid object name` /
`failure_class: missing_object`):

Do not stamp `error=sql` or `infra`. Do not edit WAVE_SRC or a table
unit's shared CSV. Succeed on a different legal dataset that still fits
the table DDL → specialist. Fail on every legal dataset → source defect:
escalate, do not spawn.

| Evidence | Do |
|---|---|
| Named id not on `dependsOn`, `missing_objects[].id` null, **or** SQL/CUR of the named object is not bindable | Spawn **one** foreground `cur_reconciler`, then `next_task`. |
| Every named id already on `dependsOn`, SQL/CUR bindable, or fixture-row shape | **Under `subagent_mode`:** spawn **one** foreground `sandbox_specialist` (`subagent_type="sandbox_specialist"`) with `task=runTests` and the tool JSON or evidence. **Interactive:** tell the user and wait. Do not spawn `sandbox_specialist`. |

Hand `objectId`, `projectDir`, `pluginDir`, `task=runTests`, and the
evidence. Do not pass `agent_id`. Do not tell it the verdict. Wait. Then:

| Child `result` | Do |
|---|---|
| `done` | `note` the reshape (inverse = drop this AIMSBX pair / reload generated CSVs), then retry. Leftover sandbox yaml is the binding; `run_tests` injects it. |
| `repaired` / `clean` | `deploy(sandbox=true)` omit `mode`, then retry tests. |
| `escalate` | Park with that child's `asks`. |
| `needs_cur` | Spawn `cur_reconciler` as in the missing-dependency row. |

Otherwise proceed — the machine routes to the fix loop.

## After tests complete

- **All pass:** stamp so `TASK_EVENTS` get an `advanced` row — do not leave
  completion to `next_task` alone:
  `transition_status(status="advance", task="runTests", outcome="completed", where="id = '<object_id>'")`.
  The server checks it against the `testValidationResults` status source
  (`VALIDATION.RESULTS`) and refuses it when they disagree. Do not write
  `codeStatus.testing`. Return.
- **Not run because of isolation:** when the walk reads `runTests` `failed` with `error='infra'`, the object's failing cases have no verdict (not run, or, for recovery required, run but their changes could not be confirmed restored); nothing in the SQL caused them, so do not edit SQL and do not enter the fix loop. Tell the cases apart by each case whose `status` is `"error"`: a row with `infra_reason` is routed by that value, whatever its `error_message` says (only the opening of the error, cut at 200 characters):
  - `needs_cloning`: tell the user what unlocks it (the message says);
  - `isolation_setup_failed` whose `error_message` contains "Insufficient privileges to operate on account": a refused clone (next bullet);
  - `recovery_required`, or any other `isolation_setup_failed`: surface it and stop on this object.
  - no case of this object ran, and `run_tests` returned an `error` starting "Validation recovery/cleanup failed: Recovery required at run start": surface that error and stop on this object.

  A row without `infra_reason` (an older scai) is told apart by its `error_message`: containing `Not run: needs cloning` is `needs_cloning`; containing "Insufficient privileges to operate on account" is a refused clone; anything else is surfaced and stops this object. The run-start stop has no row, so it keeps its message route.

  Under `subagent_mode`, park it. `reason` is the opening of `error_message`, cut at 200 characters; do not pass the rest of the message. The refused-clone case follows the next bullet.
  - `needs_cloning` (or, without `infra_reason`, an `error_message` containing `Not run: needs cloning`): `transition_status(status="escalate", task="runTests", cause="infra", asks=[{"value": "clone", "label": "Switch this project to clone (needs CREATE DATABASE)"}, {"value": "skip", "label": "Leave this procedure not run"}], reason="<that opening>", where="id = '<id>'")`.
  - `recovery_required`, or any other `isolation_setup_failed` (or, without `infra_reason`, anything else): the same call with `asks=[{"value": "retry", "label": "Run the tests again"}]` and `reason="Recovery required: <that opening>"`.
  - **No case ran for this object** (`failing` lists none of its cases, and `run_tests` returned an `error` starting "Validation recovery/cleanup failed: Recovery required at run start"): the run stopped before any case. Park with the same call and `reason="Recovery required: the run stopped before any case ran"` (that error names config files, so it is not passed on). When the error says the recovery table "can't be created or read", or that the metadata database "is the target", use `asks=[{"value": "clone", "label": "Switch this project to clone (needs CREATE DATABASE)"}]`; otherwise use the retry ask. Grants and a different metadata database are an admin's; do not name a config file.

  When other cases fail too, the walk reads `error='sql'`: fix those; the not-run cases stay as described here.
- **A refused clone** (the walk reads `error='infra'` and a case whose `status` is `"error"` has an `error_message` containing "Insufficient privileges to operate on account"): offer the opt-in, at most once per conversation per project, and not if the user already answered it in this conversation.
  - Interactive: ask with `ask_user_question` (question as in isolation-opt-in.md; options "Yes, test on the live target" / "No, keep clone"). Yes → `configure(isolation_strategy="auto")`; run `run_tests` again for these objects only after a `Set isolation_strategy:` reply. A reply that `test_config.yaml` "can't be edited in place" gets the rewrite question in isolation-opt-in.md first; any other `Warning:` reply: surface it and report which procedures were not run. No → keep clone and report which procedures were not run.
  - Under `subagent_mode`: never `ask_user_question` and never answer. First read `migration_status(mode="escalations")`. Then park the object with `transition_status(status="escalate", task="runTests", cause="infra", asks=[{"value": "auto", "label": "Yes, test on the live target", "description": "Each case's changes are restored right after it"}, {"value": "clone", "label": "No, keep clone"}], reason="Isolation opt-in for this project: <the question>", where="id = '<id>'")`. Use the same reason and asks as an open isolation opt-in row if one exists, so the parent answers them together. Two walkers that park at the same moment can still open two rows; that is benign, because the parent answers every open row whose reason starts "Isolation opt-in for this project:" with the one reply. Then return.
- **Any fail (not dependency):** do not stamp — only a completed advance is
  confirmed by the status source here; `codeStatus.testing` is read-only. The
  status source already
  reads failed (`error='sql'`) and the walk routes to rule application;
  not-run cases read `error='infra'` and stay out of the fix loop (above).
  `next_task.reason` names the latest-run breakdown (`N passed, M failed
  and override-accepted, K failed hash … with no overlay`). Use those
  unresolved hashes — including leftover RESULTS hashes no longer in the
  YAML. Continue into the fix loop. Do not spawn a verifier on the first
  numeric FAIL. Transient infrastructure (timeouts, connection drops) →
  escalate, not the SQL fix loop.
- **Still failing after the fix loop**, and either a Snowflake-SQL or YAML
  change would be illogical (source wall-clock expression; source-side
  non-determinism such as `TOP` ties with no unique `ORDER BY`; identity /
  sequence / UUID values each side generates, and their copies in
  referencing columns; do not
  edit source to make a case pass) **or** the remaining hashes are illogical
  YAML rows you added a covering row for, or leftover RESULTS
  identities: spawn **one** foreground `test_case_verifier`
  (`run_in_background=false`, `subagent_type="test_case_verifier"`) with
  fresh context for **all** remaining hashes on this object.
  - Hand `objectId`, `projectDir`, `pluginDir`, the `params_hash` list,
    `results_table` from the failed reply, and the RESULTS diffs — not a
    verdict, not a ready-made call. Do not
    pass `fork_conversation_history` or `agent_id`.
  - That child reads each case and the human `answered` row (`human: true`
    is binding override-accept). Do **not** call
    `configure(subagent_mode=true)` for this.
  - Call `override_accept_case` yourself only if the project set
    `require_independent_override_accept: false`:

```
transition_status(status="override_accept_case", task="runTests",
                  params_hash="<RESULTS params_hash>",
                  asks=["override-accept the named case", "<the other reading>"],
                  choice="override-accept the named case",
                  reason="<the known limitation, named>",
                  where="id = '<objectId>'")
```

  - `task` must be `runTests`. `params_hash`, `asks`, `choice`, and
    `reason` are required. The status source joins
    `(code_unit_id, params_hash, target)`.
  - Wait. For each `cases[]` row: `accepted` — keep going; `rejected` —
    stamp `error="sql"` and fix (a Snowflake-SQL or YAML edit exists; a
    table CSV is not that edit). Do not escalate "shared CSV is
    theoretically editable." After that fix, if the same hash still
    FAILs, spawn a **new** verifier — the first child judged the pre-fix
    SQL. A second override-accept is allowed.
  - Do not stamp `runTests` completed. Do not delete the YAML case.
    RESULTS still shows FAIL. Do not escalate leftover hashes as "purge
    RESULTS" when the YAML still covers the path.
- Do not edit the YAML to remove a test case (delete, comment out, or omit
  on regenerate — overflow, short-input, leftover RESULTS FAIL).
  - `scai test validate` only runs rows still in the file; the status source
    scores every `params_hash` it has ever seen in `VALIDATION.RESULTS`.
    Dropping a failing row prints 20/20 while `runTests` stays failed.
  - For illogical inputs (harness-rounded MONEY past the type limit), add
    a row that covers the same path and keep the illogical one; if it
    fails, its hash is `override_accept_case`.
  - A case that should not count is `override_accept_case`, not a YAML omit.
