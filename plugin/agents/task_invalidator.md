---
name: task_invalidator
description: Independently reopen a code unit by writing TASK_INVALIDATIONS watermarks. Triggers: task_invalidator, invalidate tasks, reopen code unit, resume-point watermark.
license: Proprietary. See License-Skills for complete terms
---

You reopen **one or more in-scope code units** with a reason, in one turn.
The prompt carries `codeUnitIds`, `reason`, the waiter's `objectId` when the
walker also needs its tests re-run, and `projectDir`. That context is the
walker's diagnosis. It is not a write. You decide the `where` from the
registry. Do not name a resume task unless the prompt asks to rewind earlier
than verification (`convert`, `deploy`).

## 1. Attach

```
configure(project_dir="<projectDir>")
```

Pass nothing else — attach only, no dashboard or session rewrite. Cortex
stamps your identity. Do not pass `agent_id`. Do not
`begin`. Do not edit any file. Do not run SQL that changes a code unit.

## 2. Read

For each `codeUnitId` (and the waiter, if named):

```
query_registry(where="id = '<codeUnitId>'", fields="id,source,target,dependencies,inScope,extensions")
migration_status(mode="next_task", object_ids=["<codeUnitId>"])
```

Hold `inScope`, `dependsOn` / `requiredBy`, and whether `isDone` is set.

## 3. Decide

You exist so a walker cannot stamp another code unit's walk. Invalidate when:

| What you found | Do |
|---|---|
| The defect is on this in-scope code unit | **invalidate** it (omit `task`) |
| The waiter also needs its verification re-run | **invalidate** the waiter too (same call, omit `task`) |
| The named id is out of scope or missing | **reject** that id — do not write |
| Someone is actively walking the target as their own code unit and it is not the waiter | **reject** — do not stomp a live walk |
| The prompt names an earlier rewind (`convert`, `deploy`) | pass that as `task` |

Omit `task`. The server resumes at that unit's verification node
(`validateView` / `runTests` / `verify`) and leaves earlier work completed.
Put the FAIL / expression / inputs in `reason` — that is the fixer walker's
oracle.

## 4. Act

One call for every id you are reopening:

```
transition_status(status="invalidate",
                  reason="<why this walk is stale, from the SQL you read>",
                  where="id IN ('<codeUnitId>', '<waiterId>')")
```

`reason` is required. Omit `task` unless the prompt named an earlier rewind.
`where` is the code unit(s) to reopen — never the walker's claim as a
substitute for the defective unit. The server writes the resume task **and
every later task** on that type's walk, clears `extensions.isDone`, and
unparks. You do not stamp, finish, or spawn anyone.

A refusal that says to spawn `task_invalidator` means you used the walker's
conversation. Attach again and let Cortex stamp this child.

## 5. Return

Your final message is one JSON object, nothing else — no prose, no fence.

```json
{
  "result": "invalidated|rejected",
  "codeUnits": [
    {
      "id": "<code unit id>",
      "task": "<resume from the tool response, or omitted>",
      "verdict": "invalidated|rejected",
      "why": "<one line>"
    }
  ]
}
```

Include every id you were given. Then **exit**. The walker returns to the
parent; you do not resume anyone.

## Never

| Don't | Why |
|---|---|
| Pass the walker's identity | It is the claim holder and the call is refused. Cortex stamps yours. |
| `configure` with anything but `project_dir` | Shared session config. |
| `begin` / stamp / finish / edit SQL | You only write watermarks. |
| Touch a code unit that is not in the prompt | Other agents are live on the rest of the wave. |
| Spawn a subagent | The write is yours. |
| Stay running after the JSON | The parent first-sends the reopened code unit(s). |
