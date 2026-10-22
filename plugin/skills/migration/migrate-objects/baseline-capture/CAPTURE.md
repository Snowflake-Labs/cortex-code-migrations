# Capture and Upload Baselines

After creating the test YAML files, capture baselines from the source database and upload to Snowflake.

> **⚠️ SCOPE: Capture baselines for ONE object at a time.**

## Record task start

```
transition_status(status="started", task="captureBaseline", where="id = '<object_id>'")
```

Do this once at entry. Finish with `transition_status` when capture is confirmed.

## Capture Baselines from Source Database

Call `run_tests(mode=capture, where='id = xyz')`. Do **not** pass
`--profile`, `--database-bindings`, `--isolation-strategy`, or
`--restore-from-bindings` — the tool injects leftover sandbox yaml when
present, else the project common yaml. Call `run_tests`, not a raw
`scai test capture` shell.

Both connections come from `configure` for this project — read them back from
`migration_status` rather than from anything in your own environment. In particular the
connection your `sql_execute` tool uses is **not** one of them: it is a read-only reader
scoped to its own databases, and passing it here fails with `CNX0021` /
`390201 The requested database does not exist or not authorized`, which reads as the project
being misconfigured rather than as the wrong connection having been named.

The compact JSON is the verdict (`passed` / `failed` / `failing`;
`captured_rows` on capture). `success: false` with `passed > 0` or
`captured_rows > 0` is mixed — succeeded cases uploaded. Read `failing`
for the rest. Not a CLI error.

You must edit the test YAML to fix `failing` cases without dropping test
coverage. Do not omit the row, and do not `ALTER` the source. Leave only
after `failing` is empty.

## Verify

List the stage, filtering server-side to just this object's baselines:

```bash
snow stage list-files @<TESTING_RESULTS_DATABASE>.VALIDATION.BASELINES \
  --pattern ".*<schema>_<object_name>/.*" \
  -c <SNOWFLAKE_CONNECTION_NAME>
```

`sql_execute` is equally acceptable — it is the same server-side filter:

```sql
LIST @<TESTING_RESULTS_DATABASE>.VALIDATION.BASELINES
  PATTERN = '.*<schema>_<object_name>/.*';
```

Either channel satisfies this step. `PATTERN = '.*'` does not: it lists the whole stage, so it
cannot show that *this* object's baselines landed.

Each object's files sit in a folder named `<schema>_<object_name>` (a BTEQ script's is its name or file stem), with
`.`, spaces, `/\<>:"|?*` turned into `_` (`baselines/<YYYYMMDD>/dbo_GetTaskAge/...`), so `<schema>\.<object_name>`
matches nothing. `run_tests` prints these listings, filled in for each object, after a capture succeeds.

## Mark capture complete

Confirm the oracle, then advance so `TASK_EVENTS` get an `advanced` row:

- **Procedures/functions** — `VALIDATION.BASELINE_METADATA` has a successful row for the object (`SUCCESS` true, even when `ROW_COUNTS` is empty or all zeros), or one whose `ROW_COUNTS` sum to more than zero. A failed capture with an empty count stays pending. Do not wait on `source_ready`: procedures do not write that table-only watermark. Then:
  `transition_status(status="advance", task="captureBaseline", outcome="completed", where="id = '<unit_id>'")`
- **BTEQ scripts** — baseline is on the stage and `VALIDATION.BASELINE_METADATA` is not written, so stamp explicitly the same way:
  `transition_status(status="advance", task="captureBaseline", outcome="completed", where="id = '<unit_id>'")`

Do not leave completion to `next_task` alone. If advance refuses, finish capture and retry.

## If capture fails

Do not stamp `error=sql` or `infra`. Do not edit WAVE_SRC or a table
unit's shared CSV. Leftover sandbox yaml is the binding; `run_tests`
injects it.

Would the object succeed on a **different legal dataset** that still fits
the table DDL? Then this is the specialist. If it fails on every legal
dataset, that is a source defect — escalate, do not spawn.

| Evidence | Do |
|---|---|
| `failure_class=missing_object` / 42S02 / unknown function and a named id is not on `dependsOn`, `id` is null, **or** that object's SQL/CUR is not bindable | Spawn **one** foreground `cur_reconciler` (`run_in_background=false`, `subagent_type="cur_reconciler"`), then `next_task`. Do not retry from `next_invocation`. |
| `failure_class=missing_object` and every named id is already on `dependsOn` **and** SQL/CUR is bindable | `next_task` (`blockedOn` → `partial`) **or** one foreground `sandbox_specialist` to remint the pair |
| empty join, a concat of legal `VARCHAR(n)` values that overflows a temp table, a filter the fixture never produced, or nothing captured (`passed` 0 and no `captured_rows`) | Spawn **one** foreground `sandbox_specialist` (`run_in_background=false`, `subagent_type="sandbox_specialist"`) with `task=captureBaseline` and the tool JSON or evidence |

**Interactive session, fixture rows:** tell the user the fixture cannot
exercise the object, and wait. Do not spawn `sandbox_specialist`.

Hand `objectId`, `projectDir`, `pluginDir`, `task=captureBaseline`, and
the evidence. `cur_reconciler`: `objectIds` (this object plus
`missing_objects[].id` when set), `reason`, evidence, `missingName`. Do
not pass `agent_id`. Do not tell it the verdict.

Wait. Then:

| Child `result` | Do |
|---|---|
| `done` / `repaired` / `clean` | `note` the reshape (inverse = drop this AIMSBX pair / reload generated CSVs). After `cur_reconciler` `repaired` / `clean`, `deploy(sandbox=true)` omit `mode`. Then retry capture when the task is still this one and not `blocked`. `blockedOn` / `wait` → `partial` / `waiting`. |
| `escalate` / `deferred` | Park with that child's `asks`. |
| `needs_cur` | Spawn `cur_reconciler` as in the missing-dependency row. |

## CHECKPOINT

Confirm:
- [ ] Baselines captured for `<object_name>` from source database
- [ ] Baselines visible on Snowflake stage `@<TESTING_RESULTS_DATABASE>.VALIDATION.BASELINES`
- [ ] At least 15-25 test cases for this object
