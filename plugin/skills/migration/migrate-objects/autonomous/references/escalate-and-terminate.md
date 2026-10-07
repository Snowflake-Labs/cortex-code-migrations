# Escalate, terminate, and report

## Escalate

Park first. Do not AskUserQuestion. The Escalations tab (and the inline Main
card) is the interrupt. An escalated object does not occupy a slot; keep
dispatching up to `N` live children while the user reads.

A child returning `stuck` is one source; the authoritative one is the queue, read
on every board read and not only when a child returns:

```
migration_status(mode="escalations")
```

It is project-wide, so it also surfaces escalations raised by another person's
agents and answers recorded in an earlier session — including one this session was
killed in the middle of. Do not open `notes` or `overrideAcceptedCases`. If the
object is not already parked, park it before reporting:

```
transition_status(status="escalate", task="<the task it keeps returning on>",
                  asks=["<choice>", "<choice>"],
                  cause="<sql|infra, from the agent's failed.error — omit it otherwise>",
                  reason="<what stopped you>", where="id = '<id>'")
```

`asks` is required. Report one concise line — for example
`dbo.AuditTrail: parked on migrateData — CLR is not enabled on the source` — and
return to the board and pool. Do not number the choices, call AskUserQuestion, or
wait for a chat answer. A parent that asks in chat instead of parking leaves
Escalations at 0/0 and the object Open.

If the user replies in this same parent Cortex conversation, re-read
`migration_status(mode="escalations")`, match the explicit reply to its open
row, and relay the user's words verbatim:

```
transition_status(status="answer", task="<parked task>",
                  resolution="<guidance|decompose|skip|needs_repair|mark_done>",
                  reason="<the user's words>", where="id = '<id>'")
```

Only the autonomous parent may make this call in `subagent_mode`; Cortex stamps
the current parent identity, so do not pass `agent_id`. Never call
`status="answer"` without an explicit user reply. Never infer a decision from
child output or your own diagnosis. Never use an answer to bypass a precondition.
Walkers cannot answer.

When `answered` shows a new human row, later-send with
`guidance: <their words>` for `guidance` or `decompose`.
`needs_repair` stays parked. `skip` takes the object out of scope. `mark_done`
stays parked until an interactive session performs the explicit finish; the
autonomous parent does not finish it.

Do not send an escalated object without an answer already on the row.
`error="human"` has no failure transition, so it remains parked until its stamp
is cleared.

A transient failure whose condition demonstrably cleared is not a decision.
Use a remediated reset to unpark it without recording a human choice.

A missing dependency (`reason: "missing"`) needs the register, stub, or
out-of-scope menu from [the interactive flow](../../SKILL.md). Register and stub
are dispatchable work. Keep scope and unmet-requirement choices parked.

Not every escalation is a failure. Missing source definitions, no Snowflake
equivalent, or two valid interpretations can arrive without `causeClass`.

If the user says to stop, let in-flight children land and then report.

## Termination

The loop ends only when all four conditions hold:

- `walkerRunning` is zero, no row is still unsettled at `flight=idle`, and no
  object is waiting on a relay job — that job is still the wave, even though it
  does not occupy a slot;
- the board has no ready objects;
- `next_objects` is empty;
- every remaining object is escalated, blocked, done, errored, or out of scope.

Escalated and blocked objects do not prevent termination; waiting forever for
them would hang on unanswered questions.

A leftover whose child is gone and whose object is not done is not terminal.
First-send a new child. Do not treat an empty `next_objects.objects` as an empty
wave while `leftover_claims` is non-empty or a retained conversation is still
waiting. Credential or OAuth expiry is not a human product decision; the run
cannot continue until the owner refreshes authentication.

A ready object with nothing in flight must be dispatched or parked. If an
object returns ready again with no completed tasks and no concrete remediation
or clearing evidence, park it:

```
transition_status(status="escalate", task="<the task it keeps returning on>",
                  asks=["<the choice you cannot make for the user>"],
                  cause="<sql|infra, from the agent's failed.error — omit otherwise>",
                  reason="<what the two dispatches tried>", where="id = '<id>'")
```

Then report. If escalated rows or an open escalation count remain, say that the
run finished but the wave did not.

## Where state lives

Keep no private ledger. Re-read authoritative state:

| Question | Source |
|---|---|
| Claimed ready work | `my_objects_board` with `bucket=ready` |
| Unclaimed work for a free slot | `next_objects` |
| Live versus yielded children | Board `flight`; `walkerRunning` is the slot count |
| Did a walker yield? | Its stop already settled it. `flight=none` with an `agentId` is a harvested waiter; without a walker the child is gone. Do not call `agent_output`. |
| Human queue and recorded answers | `escalations` |
| Claim holder | Board `agentId` — the live session while `flight` is `running` or `idle`, and a harvested waiter when `flight=none` still carries one |
| Relay recipient | UUID in the wake line; a wake naming the parent session means read the board and pool |
| Finished object | Board `bucket=done`, closed by the machine's verified terminal |
| Unreviewed judgments | `escalations.unreviewedCount` during the loop |

Do not call `next_task`, `my_objects_summary`, `my_objects_details`, or
`task_views` from the parent. Do not maintain a private live-child set: counting a
yielded child as live from memory parks the wave on sleeps while Monitor's wake is
already consumed. A leftover uses a first send when `leftover_claims` lists it; a
wake resumes the board `agentId` it names.

Escalations survive the session; read them instead of remembering them.

## Report

Call `migration_status()` and report as [the parent skill](../../SKILL.md) does,
plus autonomous outcomes: objects finished without intervention, open
escalations, and unreviewed notes as object plus task only. Do not pass
`details=true` or quote SQL and choice text. Batch
`transition_status(status="review", ...)`.

Also report children dispatched, remediated tasks reset, and outcomes stamped by
an agent because the machine could not observe them.

A stage count is not a done count. Use `objects_done` from `migration_status()`
for the active wave, and when the status payload carries a `wave`, name it along
with `in_scope_all_waves` (the all-waves scope denominator) to report wave progress
rather than presenting that wave's total as the migration's. Use board `doneCount`
for claimed objects only; do not sum `stage_totals`, because an object appears once
per cleared stage.

Build every confirmable line from the board. A child's `result` is a claim, not
a finding. Attribute anything the board cannot confirm to the child. Do not
turn a child's `completed` response into a completion report by itself.

Finally call `data_infrastructure(mode="down")`, or use
[the teardown skill](../../../data-infrastructure/teardown/SKILL.md) when the
project configured a `compute_pool` and data work ran.

## Resume after interruption

A killed session loses dispatch bookkeeping, not durable work. Claims,
registry stamps, git merges, escalations, and answers survive. Re-enter the
autonomous skill at preflight, then read the board and escalation queue. The
board shows dead-session claims as leftovers that a new first send can reclaim.

Read `migration_status(mode="escalations")` before dispatch. Questions remain
open and earlier answers still need to be delivered. Cortex `resume` ids died
with the session, so every reclaimed object uses a first send.
