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
`scai test capture` shell. It returns a `job_id` at once: return waiting
until the run ends, then read the result from `job_status(job_id,
details=true)` under `details.result`. Never call it again while the same
object's run is `already_running`.

`run_tests(mode=capture)` does not pass `--keep-baselines`, so it does not leave
`baselines/*.json`. When a local baseline file is required, call `setup_sandbox`
to load synthetic rows into the source, then shell `scai test seed` and
`scai test capture --keep-baselines`. Do not call `run_tests` for that hop.
Do not shell `scai testbed load` — `setup_sandbox` runs that load itself.

A table or view seed writes no YAML. Call `setup_sandbox` for the table. Seed
a procedure that reads that table, directly or through a view. Then set the
generated YAML's `source_query` to a `SELECT` over the table that returns the
procedure's result set, so the YAML names the table, and capture. Do not pass
the table name to `scai test seed` or `scai test capture`. Do not stop after
load. Do not run `scai test validate` on this hop.

For `OverlayClean` (user named the **table**): seed/capture the procedure
**GetOverlayDouble**, which reads OverlayClean through the view OverlayDoubled
(source load via `setup_sandbox`; do not shell `scai testbed load`):

```
setup_sandbox(where="source.canonicalName ILIKE '%.OverlayClean'")
```

```bash
scai test seed --where "source.canonicalName ILIKE '%.GetOverlayDouble'"
```

In its YAML under `artifacts/**/test/`, replace the generated
`- source_query: EXECUTE ${defaultdb}.dbo.GetOverlayDouble` line with this
line. Keep the database qualifier the generated line has, and leave
`target_query` as generated:

```yaml
    - source_query: SELECT id, label, ${defaultdb}.dbo.OverlayDouble(id) AS doubled_id FROM ${defaultdb}.dbo.OverlayClean
```

```bash
scai test capture --keep-baselines --where "source.canonicalName ILIKE '%.GetOverlayDouble'"
```

The YAML must contain the literal string `OverlayClean` before capture.

For **`GetOverlayDouble`** (user named the **procedure**): seed/capture
**GetOverlayDouble** — do not substitute OverlayDoubled:

```
setup_sandbox(where="source.canonicalName ILIKE '%.OverlayClean'")
```

```bash
scai test seed --where "source.canonicalName ILIKE '%.GetOverlayDouble'"
scai test capture --keep-baselines --where "source.canonicalName ILIKE '%.GetOverlayDouble'"
```

The YAML must contain `GetOverlayDouble`. Do not shell `scai code deploy` /
`extract` / `convert` on this hop. **Stop after capture** — no
`scai test validate`, no `assessment`.

For any other procedure or view the user named, call `setup_sandbox` then
shell seed and capture `--keep-baselines` with that name. Always call
`setup_sandbox` even when it is a no-op (zero tables). Never stop after
seed — capture `--keep-baselines` is required in the same hop.

```
setup_sandbox(where="source.canonicalName ILIKE '%.<object_name>'")
```

```bash
scai test seed --where "source.canonicalName ILIKE '%.<object_name>'"
scai test capture --keep-baselines --where "source.canonicalName ILIKE '%.<object_name>'"
```

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

A seeded boundary or not-found row (`tolerates_source_error: true` in `<stem>.seed.json`) whose source call raises is an
expected source error: capture records it as a source error validate skips, not as `failing`. Do not edit the YAML to
remove it.

You must edit the test YAML to fix `failing` cases without dropping test
coverage. Do not omit the row, and do not `ALTER` the source. Leave only
after `failing` is empty.

After `scai test seed`, if `target_query` names a literal `TEST_SQL_CUJ_*`,
`EVAL_*`, or `SNAP_*` database, **leave it**. Checkpoint restore rewrites
those names to this hop's Snowflake clone. Do not invent a `${...}` token
from `source_query` — a guessed key (for example `${eval_setup}` when
bindings use `eval_setup_tiers`) makes validate report Passed with
`Snowflake queries executed: 0` and write nothing matching to
`VALIDATION.LATEST`. Only add `test_cases: [ [] ]` when the stub lacks cases.

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

Confirm the status source, then advance so `TASK_EVENTS` get an `advanced` row:

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
