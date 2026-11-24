# Validate View

Compare the deployed view's rows between source and Snowflake.

## Inputs

- `<object_id>` — your claimed view.
- `invalidation` on the step (or a `reason` from a `reopened` return) — a
  closure member changed. `walk(action="lookup")`: any row not `done` → return
  `partial`, blocked on that walk. Else compare as below.

## Compare

```
walk_run(object_id="<object_id>", op="validate_data")
```

One call. It finds the catalogs itself (the view's sandbox yaml when it has one,
else the attach bindings), casts every column to text at the larger side's scale
or precision, and compares the rows as multisets. A `pass` records the task and
returns the next step. No `query_source`, `sql_execute`, shell, or retry loop.

## Verdict

| Verdict | Do |
|---|---|
| `pass` | Done: `walk_run` already recorded it. |
| `diverged` | `walk(action="done", failed="sql")`, naming `columns` and citing `samples`. |
| `diverged`, and no faithful edit to the converted view could close it (wall clock, ties, values each engine generates) | One foreground `test_case_verifier` with the reply's `params_hash` and `detail`, not `failed="sql"`. `accepted` → `walk_run(op="validate_data")` once more; `rejected` → `failed="sql"`. |
| `diverged`, `count_tgt` 0 or far below `count_src` | `walk(action="lookup")` the base tables: one before `migrateData` → `walk(action="next")`, return `partial`, blocked on it. All migrated → `failed="sql"` as above. |
| `error`, `side=snow` (compile error, missing column) | `walk(action="done", failed="sql")`. |
| `error`, `class=missing_object` (42S02) | `walk(action="lookup", name="<name>")`: no row, not `onDependsOn`, or not `bindable` → `cur_reconciler`, then `walk(action="next")`. Not `done` → blocked, as above. `done` (a missing AIMSBX table) → `sandbox_specialist` (`task=validateView`). |
| `same_error`, `empty` | `sandbox_specialist` (`task=validateView`): the fixture trips one edge on both sides, or never reaches the view. Do not edit WAVE_SRC or a table CSV. |
| `same_error`, `empty` again after the specialist's pass, or it reports no legal fixture reaches the view | `walk(action="escalate")` with asks offering `unvalidated`, a person's call you never make. Never `walk done` on it: a view nothing compared is not validated. |
| `error`, `class=infra`, or the tool itself fails | `walk(action="done", failed="infra")`. |
| `error`, `side=source` | `walk(action="escalate")` with `text`. |
| `walk_run` refuses the view: no tool can compare it | `walk(action="escalate")` with `text` saying why; only a person's `unvalidated` answer passes it. Never `done` it yourself: only a recorded `pass` completes validateView. |

The reply's `fix` says the same. Helper `result`s: [general_task §4](../../../../agents/general_task.md#4-helpers);
then `walk_run(op="validate_data")` once more.
