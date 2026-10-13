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

Call `migrate_data(mode="run", where=<the batch's object filter>)`. Setup is folded in: `run` generates the one-table workflow if needed, pins `extraction=regular` / `sync=none` / `native`, and blocks until the load finishes. Pass `workflow_path` only to reuse an edited YAML.

Do not call `data_infrastructure`. Do not arm Monitor. Do not return `waiting`. The response `status` is the result (`completed` / `failed`).

## 2. Stamp the outcome

The machine reads live `DATA_MIGRATION.TABLE_PROGRESS` — there is no registry stamp.

- **Completed** → `transition_status(status="advance", task="migrateData", outcome="completed", where=<batch filter>)` so `TASK_EVENTS` get an `advanced` row — do not leave completion to `next_task` alone. The server refuses it unless the job oracle confirms.
- **Failed** → do not stamp (only a completed advance is oracle-confirmed for `migrateData`). Do not re-run the job and do not change Snowflake with `sql_execute`. A failed load is `error=sql` and the machine owns the next step.

Then `migration_status(mode="next_task", object_ids=["<id>"])`.

A judgment you made in the converted file (meanings vs compile) is a `note` after
the fix, not a live `ALTER` and not a re-dispatch of the same workflow.

## Interactive (not a walker)

If the response has `status="started"` and a `monitor` block, you are on the
orchestrated path: infrastructure must already be up via `data_infrastructure(mode="up")`.
Arm the `monitor.watch_command` (or return `waiting` if you are a walker on a
sibling blocker). Do not call `data_infrastructure` from this subagent. When its
terminal event's `detail.completion` arrives, stamp the outcome as in §2.
