# Deploy to the shared source catalog

Deploy an object + data to the common bindings that are shared
by all agents.

## Record task start

```
transition_status(status="started", task="deployCommonSandbox", where="id = '<object_id>'")
```

Do this once at entry, before the table-only data generation. Finish with
`transition_status` after the tool succeeds (§After a successful call).

## Table-only data generation

For a **table**, generate its CSV before calling `setup_sandbox`. Spawn one
foreground `testbed_generator` subagent
(`run_in_background=false`, `subagent_type="testbed_generator"`). You remain
the claim holder; the helper only writes this table's CSV.

```
Generate this table's testbed CSV, following your agent definition.

objectId:  <objectId>
projectDir: <projectDir>
pluginDir: <pluginDir>
```

| Helper `result` | Do |
|---|---|
| `done` | Continue with `setup_sandbox`; it loads that generated CSV. |
| `busy` | Return `partial`. The helper already waited for the pipeline lease. Do not generate the table yourself. |
| `escalate` | Park `deployCommonSandbox` with the helper's `reason` and `asks`, then return `stuck`. |

## All objects deployment

Call `setup_sandbox` with the `invocation` from `next_task` (already scoped to
this object's `where`). Reconstructing the call, pass `where` with object id.

This is **source-only**. It deploys the object's source DDL (`scai code deploy
-t source`) into the shared source catalog and, for a table, runs `scai
testbed load --source-only --where`. The loader expands `--where` along
declared FKs with constraints on. The table and its FK descendants are
cleared (children first) and reloaded (parents first), so a delete never
runs while a child in that set still references it. The parents those
tables reference are loaded only when empty and never cleared, because
tables outside the set may still reference their rows. A sibling fact that
only shares a parent stays out. For an extracted project where any `source:`
binding still maps a catalog to itself (convert's default), or a selected
object's catalog has none, the connected catalog is the customer's live source:
the tool skips DDL and fixture loading, records the object ready, and preserves
its rows; `mode=load_only` is refused there. A SQL Server testbed project gets an
empty `AIMSBX_TB_*` source catalog per self-mapped entry at configure, so it loads
there once every entry is rebound; elsewhere, or if a create failed, it stays
preserved. The loader also refuses, before any
delete, a table that holds rows testbed did not write: surface that refusal
verbatim and stop, never retry with `--allow-existing-data`. Snowflake is
untouched — that is the later `deploy` task. CREATE is skipped when the object
already exists.

Do **not** pass `--profile` or `--database-bindings` — the tool injects them.
Do **not** call `deploy`. Schema/ETL/BTEQ units and units with no source come
back as `skipped`, not failed.

## If the call fails

Read `failure_class` and `missing_objects` from the JSON. Do not diagnose
past that table. Do not stamp `error=sql`. Do not DROP shared databases.
Do not write `source_ready` by hand. Do not
`update_registry(patch=...)` or `update_registry(unit=...)`.

| What the JSON says | Do |
|---|---|
| `failure_class=testbed_not_generated` (the table's CSV is not in the manifest yet; nothing ran) | Not a failure: do not park, do not spawn `sandbox_specialist`. Run §Table-only data generation for this table, then retry `setup_sandbox` once. |
| Converted compile (`failure_class=sql`, no `missing_objects`) that is not an unknown function / tokenless catalog | sqlFixLoop (`error=sql`). Do not spawn. |
| `failure_class=missing_object` (or 42S02 / unknown function), a named id has `onDependsOn` false, `id` is null, **or** that object's SQL/CUR has no bindable catalog (`PUBLIC.X`, tokenless CREATE, empty `target.database`) | Spawn **one** foreground `cur_reconciler` (`run_in_background=false`, `subagent_type="cur_reconciler"`). Then `next_task`. Do not retry from `next_invocation`. Do not sqlFixLoop. |
| `failure_class=missing_object`, every named id has `onDependsOn` true **and** that SQL/CUR is already bindable | The edge exists. `next_task`. `blockedOn` → `partial`. Do not spawn. Do not stamp. |
| `failure_class=cannot_open_database` (SQL Server 4060) | The source catalog is missing, the login cannot access it, or it is unavailable; 4060 alone does not say which. Do not spawn. Testbed project: `configure` once (it binds unedited `source:` entries to empty `AIMSBX_TB_*` catalogs), then retry this call once. Still failing → park with one ask naming `cannot_open_database` and the tool's `hint`: check it exists and is online, and that the login can open it; create it, grant access, or rebind `source:`. Do not call it a bad password. |
| Any other `failure_class` | Spawn **one** foreground `sandbox_specialist` (`run_in_background=false`, `subagent_type="sandbox_specialist"`). Do not call `next_task` first. |

Hand the child's listed fields. `cur_reconciler`: `objectIds` (this object
plus `missing_objects[].id` when set), `reason`, evidence, `missingName`,
`projectDir`. `sandbox_specialist`: `objectId`, `projectDir`, `pluginDir`,
`task=deployCommonSandbox`, and the tool JSON. Do not pass `agent_id`.
Do not tell it the verdict.

Wait. Then:

| Child `result` | Do |
|---|---|
| `repaired` / `clean` | `next_task`. `blockedOn` / `wait` → `partial` / `waiting`. Retry `setup_sandbox` once when the task is still this one and not `blocked`. |
| `done` | `note` the child's `notes` when present (bindable pin inverse: next convert overwrites). Retry `next_invocation` once, then `next_task`. `blockedOn` → `partial`. Do not ask `next_task` first — the leftover `source_failed` watermark still reads `errored` until that retry writes `source_ready`. |
| `escalate` / `deferred` | Park with that child's `asks`. |
| `scope_exceeded` | Park with the remaining ids. |
| `needs_sql_fix` | `note` the child's `notes` when present. Existing sqlFixLoop, then spawn the helper again for `load_only`. |
| `needs_cur` | Spawn `cur_reconciler` as in the missing-dependency row. |

## After a successful call

Completion is read from `ORCHESTRATION.SANDBOX_EVENTS` (source ready); there
is no registry stamp. Still advance, so `TASK_EVENTS` get an `advanced` row —
`next_task` alone writes none:

```
transition_status(status="advance", task="deployCommonSandbox", outcome="completed", where="id = '<object_id>'")
```

The server checks the sandbox oracle. If advance refuses (`does not confirm
completion`), wait for the oracle and retry. Then keep going with `next_task`.
