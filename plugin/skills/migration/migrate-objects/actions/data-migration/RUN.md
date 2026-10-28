# Migrate data (per-object)

Guide for the `migrateData` task — migrate the tables the machine handed you (`where = id IN (...)`).

Under `subagent_mode` on SQL Server this is **synchronous** `scai data migrate start --direct`. No orchestrator, no worker, no Monitor, no waiting.

## 0. Record task start

```
transition_status(status="started", task="migrateData", where=<the batch's object filter>)
```

Do this once before `run`. Finish with `transition_status(status="advance", …)` once
the result is known (§2).

## 1. Run it

Call `migrate_data(mode="run", where=<the batch's object filter>)`. Setup is folded in: `run` generates the one-table workflow if needed, pins `extraction=regular` / `sync=full-replace` / `native`, and blocks until the load finishes. Pass `workflow_path` only to reuse an edited YAML.

`full-replace` deletes the rows already in the target before loading, so a re-run never duplicates them; it overrides a table-level strategy in an edited YAML too. An Iceberg target stays on `none`, which DMO requires, so a re-run appends: when one already holds rows and every one came from this project's earlier loads of it, whether complete or failed partway (so its count is at most the source count times those loads), `TRUNCATE TABLE <fqn>` before `run` and `note` it (`undo`: restore with Time Travel, `INSERT INTO <fqn> SELECT * FROM <fqn> BEFORE(STATEMENT => '<truncate query id>')`). A target holding rows anyone else loaded is an escalation.

Do not call `data_infrastructure`. Do not arm Monitor. Do not return `waiting`. The response `status` is the result (`completed` / `failed`).

## 2. Stamp the outcome

The machine reads live `DATA_MIGRATION.TABLE_PROGRESS` — there is no registry stamp.

- **Completed** → `transition_status(status="advance", task="migrateData", outcome="completed", where=<batch filter>)` so `TASK_EVENTS` get an `advanced` row — do not leave completion to `next_task` alone. The server refuses it unless the job oracle confirms.
- **Failed** → do not stamp (only a completed advance is oracle-confirmed for `migrateData`). Do not re-run the job and do not change Snowflake with `sql_execute`. A failed load is `error=sql` and the machine owns the next step.

Then `migration_status(mode="next_task", object_ids=["<id>"])`.

A judgment you made in the converted file (meanings vs compile) is a `note` after
the fix, not a live `ALTER` and not a re-dispatch of the same workflow.

## Interactive (not a walker)

When `.scai/config/plugin.yml` records `data_orchestrator_placement: direct`
(a small SQL Server source, chosen in data-infrastructure Step 0.a), the direct
path is the normal one: `migrate_data(mode="run", workflow_path=<path>)` runs
`--direct` synchronously with no `direct` argument and no infrastructure. Do not
call `data_infrastructure` and do not arm Monitor; the response `status` is the
result, stamped as in §2. Do not pass `direct=false`: it is refused, since no
orchestrator runs for this project.

If the response has `status="started"` and a `monitor` block, you are on the
orchestrated path: infrastructure must already be up via `data_infrastructure(mode="up")`.
Arm the `monitor.watch_command` (or return `waiting` if you are a walker on a
sibling blocker). Do not call `data_infrastructure` from this subagent. When its
terminal event's `detail.completion` arrives, stamp the outcome as in §2.

If the orchestrated run keeps failing on a SQL Server project, run the reviewed
workflow with `migrate_data(mode="run", workflow_path=<path>, direct=true)`: the
same synchronous `--direct` path, every table in the file, no infrastructure,
recorded as this task's attempt so §2's advance is confirmed. Never run
`scai data migrate start --direct` from a shell: that run is not recorded, and
the object stays on its last failed job. When the target tables already hold
rows (an earlier partial or unrecorded load), set the workflow's sync strategy to
`full-replace` (or `checksum`) first: `none` appends, so a reload duplicates them.

If a shell `--direct` run already loaded the tables, record it rather than
reloading: `migrate_data(mode="record", workflow_name=<its WORKFLOW.NAME>,
workflow_path=<the YAML it ran>)`. It works on every dialect and reruns nothing.
It records the run as each table's attempt only if the workflow finished, loaded
every table, and is newer than the table's last attempt. Then advance as in §2.
On `status="refused"`, its `message` says which table failed which check;
reload that table instead.
