---
name: validate-etl-resolve-scripts
description: Resolves the SSC-EWI-SSIS0004 blocks SnowConvert left in a validate-flow SSIS unit before deploy, converting variable-only Script Tasks to Snowflake Scripting and failing the rest by name instead of leaving silent no-ops. Use when the validateEtlResolveScripts task is dispatched for a unit whose parts carry SSC-EWI-SSIS0004.
parent_skill: migrate-objects
license: Proprietary. See License-Skills for complete terms
---

# Validate-flow ETL: Resolve Script Tasks

SnowConvert cannot translate an SSIS Script Task (C# or VB.NET), or a few other control-flow elements. For each one it writes an `SSC-EWI-SSIS0004` marker, the original DTSX as comments, and a `NULL;` that does nothing. The marker breaks deploy. Turning it into a comment would let the package run on as if the script had succeeded.

This skill replaces every such block in one ETL unit, then hands the unit to `deploy`. It belongs only to the `validateEtlResolveScripts` task. Do not load stabilization skills, `scan_unit.py`, or anything under `<UNIT>/stabilization/`.

```
SCRIPT = uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/script_tasks.py
```

## Step 0: Resolve the unit and record start

Read the registry entry for the dispatched `object_id`: `{ETL_ID}`, `parts[]`, `files`.

```
transition_status(status="started", task="validateEtlResolveScripts", where="id = '{ETL_ID}'")
```

## Step 1: Inventory

```bash
$SCRIPT inventory --project-dir {PROJECT_DIR} --unit-id {ETL_ID}
```

The output lists every open block, with:
- its task path, element type and language;
- whether it is disabled, and the variables it reads or writes;
- the `Main()` body, the API signals found in it, and a `classification`.

`inactive_parts` are inside a container SnowConvert already commented out and never run, so leave them alone. A non-empty `unlocated_parts` means the registry names a block the file does not contain. That is a **STOPPING POINT**: report it and do not edit.

Show the user one row per block: task path, type, class and signals.

## Step 2: Decide each block

The class fixes which actions are allowed. `apply` refuses anything else.

| Class | Meaning | Action |
|---|---|---|
| `disabled` | `Disabled="True"` in SSIS, never runs | `remove` |
| `notification` | Only sends mail or writes a log, typically an OnError handler | `eliminate`: a comment pointing at `SYSTEM$SEND_EMAIL` or Alerts, no raise |
| `external` | Calls HTTP/REST, file shares, a database connection, Excel or a process, or is not a Script Task at all | `raise`: a named error that fails the task, with `Main()` kept as a comment |
| `variables_only` | Reads and writes SSIS variables, nothing else | `replace` with Snowflake Scripting you write (below), or `raise` |

You may only move a block to a stricter action, never to a looser one. Example: you may `raise` a `variables_only` block whose logic you cannot reproduce faithfully. Never guess source semantics. When unsure, `raise`.

### Writing a `replace`

Translate `Main()` into Snowflake Scripting statements that run in place of the block, inside the task body:

- **Variable writes.** `Dts.Variables["User::X"].Value = expr;` becomes `CALL public.UpdateControlVariable('User_X', '<scope>', TO_VARIANT(<expr>));`.
  - `::` becomes `_` in the variable name.
  - `<scope>` is the block's `scope` from the inventory.
- **Variable reads.** Use the variable already declared in the task body (`:User_X`, `:System_StartTime`), or `public.GetControlVariableUDF('User_X', '<scope>')`.
- **Expressions.** C# string, date and math map to SQL: `DateTime.Now` → `CURRENT_TIMESTAMP()`, `+` on strings → `||`, a ternary → `IFF` or `CASE`, `if` → `IF … END IF;`.
- **`Dts.TaskResult = (int)ScriptResults.Failure`** on a path becomes a `RAISE` on that path. `Success` needs no statement.

Give each `replace` a one-line `summary` of what the script did.

## Step 3: Apply and check

Write the plan to `{PROJECT_DIR}/<files.artifacts.path>/script-tasks/plan.json`. It needs one decision per block id from Step 1:

```json
{
  "decisions": [
    { "block": "Package\\Set Status", "action": "replace",
      "summary": "sets User::ScriptStatus to OK",
      "sql": "CALL public.UpdateControlVariable('User_ScriptStatus', 'Package', TO_VARIANT('OK'));" },
    { "block": "Package.EventHandlers[OnError]\\Send Email", "action": "eliminate" },
    { "block": "Package\\Call API", "action": "raise" }
  ]
}
```

```bash
$SCRIPT apply --project-dir {PROJECT_DIR} --unit-id {ETL_ID} --plan <plan.json>
$SCRIPT check --project-dir {PROJECT_DIR} --unit-id {ETL_ID}
```

`apply` writes either everything or nothing. It refuses (exit 4) when a block has no decision, an action is not allowed for its class, a `replace` would drop a variable write, or the edit would change a task tag or `CREATE` statement. Fix the plan and run it again. Never edit the orchestration SQL by hand.

On success it writes `script-tasks/resolution.json` beside the plan.

`check` must exit 0: no open `SSC-EWI-SSIS0004` marker, and every registry part carrying the code is resolved.

## Step 4: Advance

```
transition_status(status="advance", task="validateEtlResolveScripts", outcome="completed", where="id = '{ETL_ID}'")
```

The machine then routes the unit to `deploy`. Tell the user:
- how many blocks were converted, eliminated, removed and raised;
- the task path of every `raise`. Those tasks need manual migration, and each fails by name when the Snowflake task graph runs, so validation reports them instead of passing over them.

If `check` still fails and you cannot fix the plan, advance with `outcome="failed"` and `error="sql"`, and surface the `check` output.

## Constraints

- Edit only files named by `parts[].target.path`, and only through `apply`.
- The source `.dtsx` is read-only.
- Never deploy, run tasks, or create helper objects here. `deploy` is the next task.
