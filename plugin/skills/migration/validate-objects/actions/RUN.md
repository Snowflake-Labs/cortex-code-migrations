# Validate data (per-object)

Guide for the `validateData` task — validate the tables the machine handed you (`where = id IN (...)`).

Under `subagent_mode` on SQL Server this is **synchronous** `scai data validate start --direct`. No orchestrator, no worker, no Monitor, no waiting.

## 0. Record task start

```
transition_status(status="started", task="validateData", where=<the batch's object filter>)
```

Do this once before `run`. Finish with `transition_status(status="advance", …)` once
the result is known (§2).

## 1. Run it

Call `validate_data(mode="run", where=<the batch's object filter>)`. Setup is folded in: `run` generates the one-table workflow if needed (matching keys, `sync=none`) and blocks until validation finishes. Pass `workflow_path` only to reuse an edited YAML.

Do not call `data_infrastructure`. Do not arm Monitor. Do not return `waiting`. The response `status` is the result (`completed` / `failed`).

## 2. Stamp the outcome

The machine reads live `DATA_VALIDATION.TABLE_PROGRESS_DETAIL` — there is no registry stamp.

- **Completed** → `transition_status(status="advance", task="validateData", outcome="completed", where=<batch filter>)` so `TASK_EVENTS` get an `advanced` row — do not leave completion to `next_task` alone. The server refuses it unless the job oracle confirms.
- **Failed** → do not stamp (only a completed advance is oracle-confirmed for `validateData`).

Then `migration_status(mode="next_task")`.

Offer re-validation only after the report identifies a changed input or a transient
condition that has cleared. A repeatable source/target row mismatch, schema drift,
or invalid identifier / compilation error in generated validation SQL is
deterministic: park it with the exact evidence and required repair instead of
dispatching the same workflow again.

Under `subagent_mode`, a row-count mismatch that is a bad load of a table this
project loaded itself ([data-migration](../../migrate-objects/actions/data-migration/SKILL.md),
*Clearing a bad load*) is no park: spawn one foreground `task_invalidator` with this
table's id as `codeUnitIds` and `waiterId`, resume task `migrateData`, and the source
and target counts as `reason`. Then `migration_status(mode="next_task")` and run
`migrateData` again; its reload replaces the rows. Any other mismatch parks as above.

## Interactive (not a walker)

When `.scai/config/plugin.yml` records `data_orchestrator_placement: direct`
(a small SQL Server source, chosen in data-infrastructure Step 0.a), the direct
path is the normal one: `validate_data(mode="run", workflow_path=<path>)` runs
`--direct` synchronously with no `direct` argument and no infrastructure. Do not
call `data_infrastructure` and do not arm Monitor; the response `status` is the
result, stamped as in §2. Do not pass `direct=false`: it is refused, since no
orchestrator runs for this project. Re-validation needs an orchestrator too: on `direct`,
re-run `validate_data(mode="run")` on the failed tables instead of `revalidate`.

If the response has `status="started"` and a `monitor` block, you are on the
orchestrated path: infrastructure must already be up via `data_infrastructure(mode="up")`.
Arm the `monitor.watch_command` (or return `waiting` if you are a walker on a
sibling blocker). When its terminal event's `detail.completion` arrives, stamp the
outcome as in §2. Use `validate_data(mode="revalidate", workflow_name=<finished parent>)`
to retry only failed partitions of a finished orchestrated run.

If the orchestrated run keeps failing on a SQL Server project, run the reviewed
workflow with `validate_data(mode="run", workflow_path=<path>, direct=true)`
(synchronous `--direct`, metrics validation off, recorded as this task's
attempt). Never run `scai data validate start --direct` from a shell: that run
is not recorded.

If a shell `--direct` run already validated the tables, record it with
`validate_data(mode="record", workflow_name=<its WORKFLOW.NAME>,
workflow_path=<the YAML it ran>)` instead of running it again. It works on every
dialect, and records the run only if the workflow finished, passed every table,
and is newer than the table's last attempt. A `status="refused"` names the table
and the check it failed.
