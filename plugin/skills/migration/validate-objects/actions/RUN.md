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

## Interactive (not a walker)

If the response has `status="started"` and a `monitor` block, you are on the
orchestrated path: infrastructure must already be up via `data_infrastructure(mode="up")`.
Arm the `monitor.watch_command` (or return `waiting` if you are a walker on a
sibling blocker). When its terminal event's `detail.completion` arrives, stamp the
outcome as in §2. Use `validate_data(mode="revalidate", workflow_name=<finished parent>)`
to retry only failed partitions of a finished orchestrated run.
