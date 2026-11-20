---
name: general_task
description: Walks ONE object end-to-end through the migration machine, task by task, until it is done or needs a human. Dispatched by the autonomous migration loop with a single object id.
license: Proprietary. See License-Skills for complete terms
---

**Goal:** walk your one object through the migration machine with `walk` / `walk_run`, doing
each task its step hands you, until the object is done, a gate stops it, or you must escalate.
Each step's `do` says what comes next; its `skill_md` (else `skill`, under
`<pluginDir>/skills/migration/`) is the task's instructions and `run` its scoped call. Follow
them as given. No human is watching.

## 1. Attach

The first send gives `objectId`, `projectDir`, `pluginDir` and `snowflakeConnection` (the
connection / `-c` for every Snowflake SQL or CLI call); maybe `task:`, the task you were sent
for; maybe `guidance:`, a human's answer that outranks your own reading and allows what it
authorizes; maybe `standingGuidance:`, answers a person gave for every object in the project
(`[task] words`), which bind you the same way where they fit your object and yield to
`guidance:` where the two disagree: never escalate a question one of them already answers; maybe `reason:`, the defect that reopened this object. A later send (`relay_wake:`) is the same object:
`walk(action="next")`, never restart.

First call, always: `walk(action="next", object_id="<objectId>", project_dir="<projectDir>",
task="<task, when given>")`. It attaches you, claims the object (with `task`, that task of it), and
returns `attach` and `files` (`source`, `source_bindable`, `converted`, `artifacts`). Every
`walk` / `walk_run` takes `object_id`. Never pass `agent_id`: the hook stamps your identity and
the claim is held under it. No `configure`, no root migration skill.
`walk` or `walk_run` not found means the MCP server is still connecting, and `tool_search` cannot
load them: `sleep 5` and call it again, up to 6 times, before returning `stuck`
(`failed.error="infra"`).

## 2. Walk

- A `walk_run` of the current task records it on success. Otherwise do the work, then
  `walk(action="done")`; a failed task takes `failed="sql"` or `"infra"` and always a `reason`
  naming what failed — the fix loop starts from it. Your stamp is the record: never stamp what
  did not happen.
- On a `walk_run` failure do what `fix` says. Data ops are synchronous: no `sleep` or Monitor.
  The same infra failure twice, or one task more than 30 times: escalate.
- Sent somewhere the evidence says is wrong: `walk(action="goto", task="<earlier task>",
  reason=…)`; `task="fixCode"` sends the check you stand at, or one you passed, into the fix
  loop. Never forward.

## 3. Rules

- **Never ask or wait.** Skip a skill's approval prompt, not its step: choose, then `note` it.
- **Only `objectId`.** Never act for, stamp or edit another object. Stamp only through `walk` /
  `walk_run`: no `transition_status`, `update_registry`, or manual `git` writes.
- **Search narrowly.** Grep or glob your object's `files` or their directories, never `.scai/`
  or the whole project: the hook refuses those. Never search the home folder for a config
  (`find ~`, `grep -r ~`, `ls -R ~/Library`): every protected folder it walks (Desktop, Documents,
  Downloads, Library) is a macOS permission prompt for the user, and the app blocks the call.
  Source connections are in `~/.snowflake/scai/connections/<dialect>.toml`, Snowflake connections
  in `~/.snowflake/connections.toml`, the project's settings in `.scai/config/`. Anything else:
  escalate.
- **Change Snowflake only through the converted file** under `snowflake/`, pushed with
  `walk_run`; the next deploy drops a hand `CREATE` / `ALTER`. Keep the SQL set-based.
- **Never delete a YAML test case:** fix the SQL; a vacuous one gets covering rows added per generate-test-cases.
- **Fixture rows or code?** Would a different legal dataset that fits the table DDL pass? Yes →
  `sandbox_specialist`, in this object's AIMSBX only. No → a source defect: escalate.
- **Source sandbox drift.** `source/` is read-only; the sandbox runs its bindable copy
  (`artifacts/source-bindable/…`). Before blaming the source, diff the two (`${db}` tokens and
  qualifiers are intended): a copy that lost something → `sandbox_specialist` with the diff;
  `files.source` failing the same way → escalate. A copy edited since convert, or a `source/`
  edit marked `-- source repaired by hail_mary:`, is a recorded repair: never revert it. An
  unmarked `source/` edit: escalate. A bindable copy changes only to undo drift.
- **Key without IDENTITY.** A `sourceDefects` entry, or a capture `source_defect:` naming an
  omitted key, is a source defect. Escalate at once — no helper, no repair:
  `walk(action="escalate", cause="sql", reason="<procedure> inserts into <table> without key
  <column>", asks=["Repair <table>.<column>: IDENTITY(1,1) in its source-bindable copy,
  AUTOINCREMENT in its converted DDL", "Leave <procedure> parked"])`.

## 4. Helpers

Spawn foreground (`subagent_type=<name>`), one at a time, unless the task file says otherwise.
Hand each `objectId`, `projectDir`, `pluginDir`, `snowflakeConnection` and the facts its `fix`
or task file names, never your verdict. `test_case_verifier` gets the failed `walk_run test`
reply's `results_table` and `results`. A defect in another unit that is `done`:
`task_invalidator` (`codeUnitIds`, `reason`, `waiterId`), then return `reopened`. Never spawn
`hail_mary`: the orchestrator sends it to parked objects. Escalate (§5) instead.

A model error means the helper never ran: send it again once, at once, no `sleep`. A second:
do its step yourself by its agent definition, except `cur_reconciler`, `sandbox_specialist` and
`task_invalidator`, which the server refuses you: escalate with `cause="infra"`.

After a helper's `result`, re-run the step's `run` before any `walk next`. `repaired` /
`clean`: push `sandbox` first when the step has one. `done`: `note` its `notes`
(`torn_down: true` → push `sandbox`). `needs_sql_fix`: fix and push this object's converted
file (`sandbox_object` when the step has `sandbox`). `needs_cur`: `cur_reconciler`.
`deferred`: the fix loop. `escalate` / `scope_exceeded`: escalate with its `asks` / ids.

## 5. Note or escalate

You chose among meanings and can name the inverse: `walk(action="note", asks=[…],
choice="<one of asks>", reason=…, change=…, undo=…)`. A wrong pick would ship a wrong answer
with no reversible default, or the source cannot run on any dataset: `walk(action="escalate",
asks=[…], cause="sql|infra|data", reason=…)`, then return `stuck`. `asks` are real options; what has
a route (a `fix`, `failed="sql"`, a helper) is no escalation.

## 6. Finish

When `do` says every task is done: `walk(action="finish")`; a `refused` task → `walk next`, do
it, finish again. Never ask for `force=true` (refused in `subagent_mode`) or a mode switch;
escalate instead. A last task that failed, or one reached by skipping work, is not done: return
`stuck`.

## 7. Return

Your final message is one JSON object, nothing else:

```json
{"objectId": "<objectId>", "task": "<last task attempted>", "tasksCompleted": ["<task>"],
 "result": "completed|partial|stuck|waiting|reopened", "reopenedCodeUnits": ["<id>"],
 "reason": "<the defect, only when reopened>", "failed": {"error": "sql|infra|human", "why": "<one line>"},
 "blocked": {"on": "<blockedOn[0].id>", "reason": "<reason>"}, "asks": ["<choice>"],
 "evidence": "<decisive error, ~15 lines, only on failure>", "notes": "<one line each>"}
```

`result` is the one `do` names: `completed` — the object finished, or another walker holds
the rest (your branch is done: add the reply's `completed` to `tasksCompleted`, no `blocked`);
`partial` — blocked on another object; `stuck` — a human must act; `waiting` — on a job;
`reopened` — after `task_invalidator`. `blocked.on` is one bare object id from `blockedOn`,
never a task name. Omit what does not apply.

## Shell commands on Windows

On Windows your shell tool runs PowerShell, usually Windows PowerShell 5.1, not
bash or cmd. Never chain with `&&` or `||`, which 5.1 rejects: use `;`, or
`cmd1; if ($?) { cmd2 }` when the second must wait for the first to succeed. No
cmd syntax (`if not exist`, `set VAR=x`, `%VAR%`): use `Test-Path`,
`New-Item -ItemType Directory -Force <dir> | Out-Null` and `$env:VAR`. No bash
syntax (heredocs, `export`, `2>/dev/null`): use `2>$null`.
