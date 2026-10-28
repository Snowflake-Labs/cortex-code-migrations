---
name: hail_mary
description: Unstick a parked object with full authority — answer the escalation, edit source and target, register missing units, override a disagreeing oracle, bypass a step, force-finish, or migrate/verify out of band. Triggers: hail_mary, unstick parked object, hail mary, force finish, override oracle, repair source defect.
license: Proprietary. See License-Skills for complete terms
---

The parent sent you on **one parked object**. Do not share learnings
with siblings as they do not have your powers. You must trace all your
steps as outlined below. Hard stops:

- Do not interfere with another object's live walker.
- Never write the app's metadata (`ORCHESTRATION`, `DATA_MIGRATION`,
  `DATA_VALIDATION`, `RULE_ENGINE`, `COMMON`, `TEMP` in the metadata
  database) with SQL or a script. Those rows change only through the MCP
  tools.
- A privileged call refused means return `refused`, not a workaround.

If this object is waiting for some other work and will be unstuck eventually
without your help, e.g. it still has `flight=running`/`idle`, is `waiting` on a
relay job, or a `task_invalidator` (or other helper) is in flight for it
or a unit it is blocked on, return `refused`. Do not `begin`.

## 1. Attach

```
configure(project_dir="<projectDir>")
```

Pass nothing else, your powers will be granted automatically.

## 2. Trace

Before every mutating MCP call, record why:

```
transition_status(status="hail_mary_step", where="id = '<objectId>'",
                  task="<task you are on>",
                  reason="<one line: what you are about to do and why>",
                  change="<optional: file, SQL, script path>")
```

The server also shadows every other `transition_status` / registry write
as `event='hail_mary'` in TASK_EVENTS. The step row is the narrative.

## 3. Read

```
migration_status(mode="escalations", details=true)
query_registry(where="id = '<objectId>'",
               fields="id,source,target,files,dependencies,inScope,extensions")
migration_status(mode="next_task", object_ids=["<objectId>"])
```

Hold the parked `asks` / `cause` / `reason`, `files.source.path`,
`files.converted.path`, `dependsOn`, and `nextTask`. Read the SQL and
the oracle (`VALIDATION.LATEST`, INFORMATION_SCHEMA, job_status) yourself.
The walker prompt is a lead, not evidence.

`begin` this `objectId` so you reclaim a dead walker's hold. Do **not**
`begin` any other id.

## 4. Isolation

Before you write a **different** code unit (dependency, stub, CUR patch):

- Live walker (`flight=running`/`idle` on the board / hub) → **do
  not** edit its files, deploy it, stamp it, patch its CUR, or invalidate
  it. Bypass *this* object's precondition, stub in *this* object's
  sandbox, or `answer(needs_repair)` naming the live walker.
- Unclaimed / parked / done / harvested → you may edit, register, deploy,
  and patch CUR. Still do not `begin` that id — leave it for the
  dispatcher unless you just created it as a stub this object needs.

## 5. Act — get it unstuck

Prefer returning the object to the machine. Force only when the machine
cannot observe the work.

| Situation | Do |
|---|---|
| Conversion / Snowflake SQL bug | Edit `files.converted`, deploy, retry the task |
| Source is wrong on every legal dataset | Edit `files.source`, recapture / redeploy the twin, `note` or `answer(guidance)` |
| Capture / EXEC fails on *this fixture's* shape | Fix AIMSBX data or spawn nothing — reshape here |
| Missing dependency, not being walked | `update_registry(unit=…)` if absent from CUR (scan `source/` / source-bindable), `update_registry(patch=…)` for `dependsOn`, qualify converted / source-bindable SQL with `<%token%>` / `${token}` so bindings substitute (any object kind), deploy. Then retry this object |
| Missing dependency with a live walker | Bypass this object's unmet precondition or park `needs_repair` |
| `runTests` cannot run but the object is faithful | `override_accept_case` for named hashes, or `bypass` / `advance(completed)` the task with `reason` |
| Oracle / DMV does not confirm done after you verified | `advance(outcome="completed")` — your type is allowed to override a disagreeing source. `reason` on the hail_mary_step |
| `migrateData` / `validateData` failed and scai cannot finish it | Write a Python/SQL script under `<files.artifacts.path>/hail_mary/` that moves data only, run it, verify, then override-advance or `bypass` that task |
| Tests / a step are permanently inapplicable | `bypass` (preconditions) or `answer(skip)` (out of scope) or `answer(mark_done)` + `finish(force=true)` |
| Design fork in `asks` | Pick, edit, `answer(resolution="guidance", reason="<the pick>")` so a new walker continues |
| You still must not choose | `answer(resolution="needs_repair", reason="…")` — stays parked |

`finish(force=true)` is allowed. Use it when the remaining tasks are
ceremonial and you have evidence the object belongs on the clone. It also
closes any escalation still open on the object as `mark_done` under your id
(`escalations_closed` on the response), so the user is not left a stale card.

Do not `status='answer'` as a person — your `ANSWERED_BY_AGENT` must
stay set. Do not wait for chat.

## 6. Return

One JSON object, nothing else:

```json
{
  "objectId": "<objectId>",
  "result": "unstuck|forced|skipped|needs_repair|refused",
  "task": "<task you were on>",
  "actions": ["<hail_mary_step reasons, in order>"],
  "touchedIds": ["<this object and any unclaimed deps you wrote>"],
  "reason": "<one line>"
}
```

`unstuck` — machine can continue (guidance / decompose / reset / a
real completed stamp). `forced` — `force=true` or an oracle override.
`skipped` — out of scope. `needs_repair` — still parked. `refused` —
env off, wrong type, a privileged call refused, or a live walker
blocked the only fix.

## Shell commands on Windows

On Windows your shell tool runs PowerShell, usually Windows PowerShell 5.1, not
bash or cmd. Never chain with `&&` or `||`, which 5.1 rejects: use `;`, or
`cmd1; if ($?) { cmd2 }` when the second must wait for the first to succeed. No
cmd syntax (`if not exist`, `set VAR=x`, `%VAR%`): use `Test-Path`,
`New-Item -ItemType Directory -Force <dir> | Out-Null` and `$env:VAR`. No bash
syntax (heredocs, `export`, `2>/dev/null`): use `2>$null`.
