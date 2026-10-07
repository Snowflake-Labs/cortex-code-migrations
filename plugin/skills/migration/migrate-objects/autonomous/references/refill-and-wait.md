# Refill and wait

This session is headless: ending the turn exits the process and kills every
child. Keep it alive with one wait per turn, only after filling every free slot.

## Top off, then wait

Re-read the board and pull `next_objects` before every wait: after a child
returns, after a wake, and after an empty hub wake. First-send every
`leftover_claims` entry as a new child with no `resume` — skipping any harvested
waiter (`flight=none` that still carries an `agentId`) — then issue every other
first send and pending wake for the turn. Do not wait while leftovers or free
slots remain. A live child on one object does not block filling other slots.
Neither does a waiting object or escalation.

A child's stop settles its own turn, so there is nothing to collect: never call
`agent_output`. `flight=idle` means the stop is not folded into the board yet —
re-read the board instead of reaching for the transcript. A harvested waiter
(`flight=none` with an `agentId`) keeps its `resume` id until a wake, or until
the walk is terminal and `leftover_claims` offers the object again.

`Background agent finished`, a Monitor wake naming the parent session id, and
`bash sleep` all mean the same thing: re-read the board and top off again.
Helpers (`cur_reconciler`, `test_case_verifier`, `task_invalidator`,
`sandbox_specialist`, `edge_cases`, `business_logic`, `data_driven`) do not stamp
`flight` and do not occupy slots; do not poll them.

## The single wait

Wait once after every send for this turn:

- If `walkerRunning > 0`, run `bash sleep 30`, then re-read the board and top off
  again. Sleep only paces the next board read. **Never sleep more than 30
  seconds** — a longer sleep stalls the wave while Monitor's wake is already
  consumed.
- If `walkerRunning` is zero and `next_objects` returned nothing, call
  `hub(mode="wait", confirm=true, cursor=<last>)` instead of ending the turn.
  `job_status(wait=true)` is the same gate. Without `confirm=true`, the hub
  returns a reminder and does not block. Empty `wakes` means read the board and
  pool again, not wait again with idle slots.

Never call `hub(mode="wait")` while `next_objects` can still return objects.

Arm one Monitor for the wave from `orchestrator_watch.watch_command` returned
by `configure`, `hub(mode="status")`, or `job_status(monitor=true)`, with
`persistent: true`. Each line is an instruction. Do not open the job, call
`job_status` on it, or read the relay log.

A wake line naming a UUID is a later send:

```
wake up 550e8400-e29b-41d4-a716-446655440000 and ask it to check new event from relay. ...
```

Call `task(resume=<that UUID>)` with only the `relay_wake:` line. Do not spawn a
new `general_task`. The later send occupies a slot only while the board lists
it as running.

A wake naming the parent session id means read the board and pool again. Do not
inspect the event.

## Process child returns

Read only `objectId`, `tasksCompleted`, `result`, and `reopenedCodeUnits` from
the child's result JSON. Ignore `Recent Output`, `task`, `failed`, `blocked`,
`evidence`, `asks`, and `notes` — the board, not a child's JSON, is what the
report is built from. Then read the board and pool before sending a wake or
waiting again. Report one line per return and maintain the tally.

| `result` | Action |
|---|---|
| `completed` | Re-read the board. If the object is `done`, drop its `resume` id. Otherwise the child died holding the claim; first-send a new child with no `resume`. |
| `partial` | Re-read the board. Leave `blocked` alone; later-send `ready`; handle `escalated` through the escalation procedure. |
| `stuck` | Use the escalation procedure. Do not send again until a person answers. |
| `waiting` | Keep the `resume` id and free the slot. Later-send only when a wake names that id. |
| `reopened` | Keep the waiter's `resume` id and free the slot. First-send each `reopenedCodeUnits` id that is not already running. Do not later-send the waiter until those walks finish. |

Do not send again for a `partial` result whose board bucket is still blocked.

## Reset only after remediation

Reset only from evidence already available: infrastructure now reports ready
or a shared job reached terminal. Never infer remediation from the child's
`failed` payload.

```
transition_status(status="reset", task="<task>", where="id = '<id>'")
```

Then later-send the same object once. **That is the whole recovery sequence.** Do
not follow `reset` with `status="answer"`, and do not manufacture
`resolution="guidance"` from your own diagnosis or repair notes: `answer` records
a human decision, so a verified remediation belongs in the later-send prompt and
the wave report, never in a row attributed to the user.

If a child parked the object before a foreground recovery helper returned `done`,
that successful repair is clearing evidence: `reset`, then later-send the same
walker with the repair fact. Do not leave a mechanically repaired object parked,
and do not answer its historical row.

Record the remediation or clearing evidence. If nothing changed, leave an
existing escalation open, or park the object with the exact failure and repair
needed before a rerun if it is not parked yet.

Deterministic row mismatches, schema drift, invalid identifiers, generated SQL
compilation errors, and tool calls that fail identically on repeat are not
transient infrastructure failures. Park them instead of resetting or repeating
unchanged work. `reset` clears the task stamp and the Snowflake park (`PARKED`);
using it before remediation erases the durable record of a failure the next run
will reproduce.
