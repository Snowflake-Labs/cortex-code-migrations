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
  - Else `deploy(sandbox=true, where="id = '<objectId>'")` — omit `mode`.
    Closure (tables from CSVs, functions, views, peer procedures) on both
    sides, and this object on source. Then
    `deploy(sandbox=true, mode=redeploy_object, where="id = '<objectId>'")`.
- **Else:** `deploy(sandbox=true, mode=redeploy_object, where="id = '<objectId>'")`.

`mode=redeploy_object` `failure_class=sql` is this object's converted body.
sqlFixLoop (`error=sql`), then `mode=redeploy_object` again. The pair is
still `ready`. Do not spawn `sandbox_specialist`. Do not retry setup.
Omit-`mode` `sql` is a peer — "../sandbox/CREATE_ISOLATED.md".

## Run validation

Call `run_tests` with `object_name` or `where` (`mode` defaults to `validate`).

- Do **not** pass `--profile`, `--database-bindings`, `--isolation-strategy`,
  or `--restore-from-bindings`. The tool injects `--database-bindings` from
  leftover sandbox yaml, else `.scai/bindings/database-bindings.yaml`.
- Isolation `bound` + `--restore-from-bindings` only for a procedure sandbox:
  cases run in `AIMSBX_*`; mutated tables restore from the common catalogs
  before the next case.
- After AIMSBX DML the tools did not see (`sql_execute`),
  `run_tests(restore_from="sandbox")` so restore uses a clone of that
  pair instead. `reload_tables` and mutating `query_source` into AIMSBX
  latch this automatically.
- Capture: same tool, `mode=capture` (no restore).

JSON: `success`, `exit`, `total`, `passed`, `failed`, `errors`,
`no_baseline`, optional capped `failing` (`name`, `status`, `error_message`),
short `warnings`. Capture also returns `captured_rows`. Use those counts.
No result grids, empty baseline/actual tables, diffs, or coverage report.

- `success: false` with `passed > 0` is mixed — read `failing`. Do not treat
  it as empty.
- `params_hash` / `differences` are not in that summary. Cases land in
  `<metadata_database>.VALIDATION.RESULTS`. Query `VALIDATION.LATEST`
  (`.scai/config/plugin.yml` `metadata_database` — `SNOWCONVERT_AI` unless
  overridden; same catalog as ORCHESTRATION, not the migration target) only
  in the fix loop / verifier. No `<project_dir>/test-results/results.json`.
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
  The server checks it against the `testValidationResults` oracle
  (`VALIDATION.RESULTS`) and refuses it when they disagree. Do not write
  `codeStatus.testing`. Return.
- **Any fail (not dependency):** do not stamp — only a completed advance is
  oracle-confirmed here; `codeStatus.testing` is read-only. The oracle already
  reads failed (`error='sql'`) and the walk routes to rule application.
  `next_task.reason` names the latest-run breakdown (`N passed, M failed
  and override-accepted, K failed hash … with no overlay`). Use those
  unresolved hashes — including leftover RESULTS hashes no longer in the
  YAML. Continue into the fix loop. Do not spawn a verifier on the first
  numeric FAIL. Transient infrastructure (timeouts, connection drops) →
  escalate, not the SQL fix loop.
- **Still failing after the fix loop**, and either a Snowflake-SQL or YAML
  change would be illogical (source wall-clock expression; source-side
  non-determinism such as `TOP` ties with no unique `ORDER BY`; do not
  edit source to make a case pass) **or** the remaining hashes are leftover
  RESULTS identities after you replaced illogical YAML inputs with a
  still-covering row: spawn **one** foreground `test_case_verifier`
  (`run_in_background=false`, `subagent_type="test_case_verifier"`) with
  fresh context for **all** remaining hashes on this object.
  - Hand `objectId`, `projectDir`, `pluginDir`, the `params_hash` list,
    and the RESULTS diffs — not a verdict, not a ready-made call. Do not
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
    `reason` are required. The oracle joins
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
  - `scai test validate` only runs rows still in the file; the oracle
    scores every `params_hash` it has ever seen in `VALIDATION.RESULTS`.
    Dropping a failing row prints 20/20 while `runTests` stays failed.
  - Replacing illogical inputs (harness-rounded MONEY past the type limit)
    with a still-covering row is not a delete — the old hash stays FAIL
    in RESULTS and is `override_accept_case` once coverage has not dropped.
  - A case that should not count is `override_accept_case`, not a YAML omit.
