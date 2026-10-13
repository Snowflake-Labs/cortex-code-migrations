# Set up the procedure sandbox

## Record task start

```
transition_status(status="started", task="createIsolatedSandbox", where="id = '<object_id>'")
```

Do this once at entry. Finish with `transition_status` after the tool succeeds.

## Call the tool

Call `deploy` with the `invocation` from `next_task` — it already has
`sandbox=true` and a scoped `where`. Reconstructing the call:

| Need | Call |
|---|---|
| Transitive closure into the sandbox | `sandbox=true`, omit `mode` (same as `mode=setup`) |
| This object only into a live pair | `sandbox=true`, `mode=redeploy_object` |
| Reload closure table CSVs (wipes AIMSBX DML; latches restore-from-sandbox) | `sandbox=true`, `mode=reload_tables` |
| This object only onto the common catalogs | omit `sandbox` — that is the later `deploy` task, not this one |

After AIMSBX DML the tools did not see (`sql_execute`), pass `restore_from="sandbox"` on `deploy` or `run_tests`.

Omit `mode` on a live `ready` leftover pair still deploys tables (CSV
reload), peer functions/views/procs, and this object on source — no DROP
or CLONE. Snowflake CREATE of this id is `mode=redeploy_object` (after a
SQL fix of **your assigned** object, and before `runTests`). Unready
leftover yaml is DROPped at setup start so the retry remints. The same
call fills tables missed on first setup (dynamic SQL names `dependsOn`
omitted / 42S02). Converted-only procedures (no `source`) are
Snowflake-only.

Do **not** pass `--profile`, `--database-bindings`, `--isolation-strategy`,
or `--restore-from-bindings` — the tool injects them. Do **not**
`configure(snowflake_database=…)` onto a sandbox catalog. Do **not**
execute the CREATE PROCEDURE SQL yourself.

Use the JSON `sandbox` maps (`snowflake` / `source`, `bindingsPath`) for
tests, `sql_execute`, and `query_source`. Those `AIMSBX_*` catalogs, not
the common `snow:` values. Pass `sql_execute` `connection` (`-c`) as attach
/ first-prompt `snowflakeConnection` on every call — Cortex does not inherit
`configure`. Fully qualify; never substitute `source.database`, a
`SNAP_USE_*` clone, or `SNOWCONVERT_AI*`. Never `SHOW DATABASES`,
`SHOW … IN ACCOUNT`, or `CREATE SCHEMA` through `sql_execute`. If the tool
is unavailable, denied, times out, or the catalog is missing, park; do not
roam other databases. Mutating `query_source` SQL that names a common
catalog while a sandbox is live is refused — qualify the `AIMSBX_*` name
from the maps.

A `redeploy_object` response reports only deployments that mutated an
object during that call.

## Pre-deploy file checks

Setup does not Snowflake-CREATE this id. Do not enter sqlFixLoop to
unblock this call. The checks below apply when you `redeploy_object`
(`runTests` / after sqlFixLoop), not to make setup `ready`.

Bounded edits **before** `redeploy_object`:

1. Leave a leading `USE DATABASE` in the file. The tool comments it out
   after substituting bindings.
2. Keep the converted qualifier (`<%token%>.dbo.X`, `TaskTracker.dbo.X`,
   or `schema.X`). Do **not** write the SNAP / configure database name
   into the file.
3. LANGUAGE SQL procedures: parameters and variables in SQL statements
   need `:param_name`. SnowConvert often omits the colon.
4. Preserve original comments when editing converted SQL.

If you edit, change the SQL file in `snowflake/` first, then call
`redeploy_object`. A Snowflake-only deploy is overwritten on the next
run from disk.

## If the call fails

Read `failure_class` and `missing_objects` from the JSON. Do not diagnose
past that table. Do not stamp `error=sql`. Do not DROP shared WAVE_SRC.
Do not write `ready` by hand. Do not
`update_registry(patch=...)` or `update_registry(unit=...)`.

| What the JSON says | Do |
|---|---|
| Converted compile (`failure_class=sql`, no `missing_objects`) that is not an unknown function / tokenless catalog | Setup did not CREATE this id — that error is a **peer** Snowflake body. Do not sqlFixLoop this object. Do not spawn `sandbox_specialist`. Named peer on `dependsOn` and bindable → `next_task` (`blockedOn` → `partial`). Named peer not on `dependsOn`, `id` null, or SQL/CUR not bindable → `cur_reconciler` as in the missing-object row. Cannot name a registry id from the error → park with the compile text. |
| `failure_class=missing_object` (or 42S02 / unknown function), a named id has `onDependsOn` false, `id` is null, **or** that object's SQL/CUR has no bindable catalog (`PUBLIC.X`, tokenless CREATE, empty `target.database`) | Spawn **one** foreground `cur_reconciler` (`run_in_background=false`, `subagent_type="cur_reconciler"`). Then `next_task`. Do not retry from `next_invocation`. Do not sqlFixLoop. |
| `failure_class=missing_object`, every named id has `onDependsOn` true **and** that SQL/CUR is already bindable | The edge exists. `next_task`. `blockedOn` → `partial`. Do not spawn. Do not stamp. |
| Any other `failure_class` | Spawn **one** foreground `sandbox_specialist` (`run_in_background=false`, `subagent_type="sandbox_specialist"`). Do not call `next_task` first. |

Hand the child's listed fields. `cur_reconciler`: `objectIds` (this object
plus `missing_objects[].id` when set), `reason`, evidence, `missingName`,
`projectDir`. `sandbox_specialist`: `objectId`, `projectDir`, `pluginDir`,
`task=createIsolatedSandbox`, and the tool JSON. Do not pass `agent_id`.
Do not tell it the verdict.

Wait. Then:

| Child `result` | Do |
|---|---|
| `repaired` / `clean` | `deploy(sandbox=true)` omit `mode` (callee SQL and call sites changed), then `next_task`. `blockedOn` / `wait` → `partial` / `waiting`. Retry the sandbox tool once when the task is still this one and not `blocked`. |
| `done` | `note` the child's `notes` when present (bindable pin inverse: next convert overwrites). Retry `next_invocation` / `deploy(sandbox=true)` once, then `next_task`. `torn_down: true` is `mode=setup` (the pair is gone) — do not `redeploy_object`. `blockedOn` / `wait` → `partial` / `waiting`. Do not ask `next_task` first — the leftover `failed` watermark still reads `errored` until that retry writes `ready`. |
| `escalate` / `deferred` | Park with that child's `asks`. |
| `scope_exceeded` | Park with the remaining ids. |
| `needs_sql_fix` | `note` the child's `notes` when present. Existing sqlFixLoop (`error=sql`). Then you push: leftover yaml still names a live pair → `mode=redeploy_object`; `torn_down: true` or no pair → `mode=setup`. Do not spawn the helper for that push. |
| `needs_cur` | Spawn `cur_reconciler` as in the missing-dependency row. |

## After a successful call

Completion is `ORCHESTRATION.SANDBOX_EVENTS` (`live_bindings`), not
INFORMATION_SCHEMA on the common catalogs and not `cloudStatus.deployment`.
`ready` is source closure + this object + data, and Snowflake closure
only — not this object's converted body. Still advance, so `TASK_EVENTS` get
an `advanced` row — `next_task` alone writes none:

```
transition_status(status="advance", task="createIsolatedSandbox", outcome="completed", where="id = '<object_id>'")
```

The server checks the sandbox oracle. If advance refuses, wait for the oracle
and retry.
