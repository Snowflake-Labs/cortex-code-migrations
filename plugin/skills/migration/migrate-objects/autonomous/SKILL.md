---
name: migrate-objects-auto
description: Autonomous version of migrate-objects — dispatches one subagent per ready task group, refills as they finish, and parks stuck work as an escalation instead of asking in chat. Triggers: autonomous migration, run unattended, migrate objects automatically, auto-pilot the wave, migrate everything in parallel, swarm the objects.
parent_skill: migrate-objects
license: Proprietary. See License-Skills for complete terms
---

# Migrate Objects — Autonomous

## On Entry

Tell the user:

> **Autonomous mode.** I'll work the wave by giving each object its own subagent,
> which walks it the whole way — convert, deploy, tests, fixes — and I'll refill as
> they finish. Stuck work and human decisions land on Escalations — I won't ask in
> chat. Data migration runs without asking. Say "stop" at any point and I'll let
> in-flight work land.

## Step 0: Preflight

1. `configure(project_dir=<project dir>, subagent_mode=true, snowflake_connection=<the user's target connection — the one they named for deployment, NOT the system-reminder "active SQL connection" which is the agent's inference account>)`. Read the appended migration-status block. Always migrate data — do not ask, and do not skip.

   On SQL Server, skip `data_infrastructure(mode="up")`: walkers run `migrate_data` / `validate_data` synchronously via `scai --direct`. For any other dialect, call `data_infrastructure(mode="up")` until it reports `ready` (follow `remediation` on `status="not_ready"`; a first local bring-up can take more than one call). `status="failed"` (a process exited at start), `"degraded"` (`skip_doctor` overrode doctor checks) or `"error"` (`doctor_failures`) never clears with another `up`: stop and escalate with the named checks. Relay `cost_reminder`.

2. If `configure()` reports setup is not finished, read [../../setup/SKILL.md](../../setup/SKILL.md) then come back here.

3. Quote any `schema_status_*: error(...)` from `configure()` to the user and in the final report. For `DMG0011` report the message's cause; suggest upgrading the orchestrator or re-enabling auto-update only if it says `migrate-schema` is unsupported.

- If `configure` or `migration_status` is deferred, use the host's tool discovery to load both tools, then call `configure`.
- A **Connected** label in the MCP manager is not readiness evidence; a successful tool call is.
- If either tool is absent or reports a disconnected MCP, wait 15 seconds (`Bash` `sleep 15` only), refresh tool discovery, and retry `configure`. Repeat until both tools are callable or 3 minutes have elapsed. Do not stop after one retry.
- If both tools are still unavailable after 3 minutes, stop and ask the user to reconnect or restart the plugin. In an unattended session, report the unavailable tool names and end the run immediately. The final response is the report; do not run commands or inspect files to record the blocker elsewhere. Do not inspect the plugin directory, project directory, `.scai`, or the MCP implementation; do not try `fdbt`, `scai`, or any shell except `sleep N`. Do not read `registry/`, infer `next_objects`, or hand-pick object ids. Do not dispatch a probe child.

`subagent_mode` stays on, in plugin.yml too, until the user asks to go manual: then, between waves only, call `configure(subagent_mode=false)` (refused while walkers run or claims are open). Never on your own initiative. Cortex stamps identity — do not pass `agent_id`. Object-level writes (`begin`, `deploy`, `migrate_data`, `validate_data`) are the walker's; the parent is refused. Of `transition_status` the parent may call only `reset`, `escalate`, and `answer` (relaying an explicit user reply); every other status is refused. Never review a note.

## Step 1: Load `N`

Read `autonomous_max_subagents` from `configure`'s reply (its `Configured` block, or `Attached.` on a re-attach). That is `N`. If absent, `N = 4`. Do not ask, and never exceed `N`.

## Step 1b: Speculative fixes

`speculative_sandbox(mode="list")`. Before the first walker, first-send one
[`speculative_fixer`](../../../../agents/speculative_fixer.md) per object it returns, in one
background batch (`run_in_background=true`, `subagent_type="speculative_fixer"`):

```
Speculatively fix this object, following your agent definition.

objectId:            <object_id>
projectDir:          <project dir>
snowflakeConnection: <the connection you passed to configure>
```

They take no slot and write only `speculative.sql`. Never wait for, poll, resume or act on them.

## Step 1c: Early table enrichment

Before the first walker, call `testbed(phase="prepare")` and send each `helper_prompts` entry verbatim as a background [`testbed_generator`](../../../../agents/testbed_generator.md) (`run_in_background=true`, `subagent_type="testbed_generator"`). No slot; never wait for, poll or resume them. `prepare` hands out 8 at a time: when a helper finishes with `remaining` above 0, call it again and send them.

## Step 2: The loop

One object, one [`general_task`](../../../../agents/general_task.md) walker, whole pipeline. You keep no ledger — re-read the board. Track the Cortex conversation UUID only to resume; liveness is `my_objects_board`.

Each turn: **read → fill every free slot → wait once → repeat.**

### 2a. Read

```
migration_status(mode="my_objects_board")
migration_status(mode="escalations")
```

Re-read both whenever a child returns; no `details=true`. Do not read `notes[].asks`, `choice` or `overrideAcceptedCases`. `unreviewedCount` is for Step 3.

Do not call `my_objects_summary`, `my_objects_details`, `next_task`, `task_views`, or `hub(mode="status")` for dispatch.

If Cortex explicitly reports a walker cancelled, killed, failed, or completed while the board still shows it `running`, call `agent_output(agent_id=<its stored resume id>, wait=false)` once. That is terminal-status reconciliation, not polling: its PostToolUse hook drops the dead ledger row and mirrored claim, so the open claim reappears in `next_objects` `leftover_claims`. Never call `agent_output` otherwise.

| Field | Use |
|---|---|
| `bucket` | `ready` / `blocked` / `done` / `escalated` / `errored` |
| `flight` | `running` or `idle` → that object already has a live child; do not first-send. `idle` is unsettled — re-read. `none` with `agentId` is a harvested waiter — do not first-send; later-send only on a wake or a 2c continue. |
| `agentId` | Conversation UUID when `flight` is `running`/`idle`, or when a harvested waiter still carries one |
| `walkerRunning` | Live-child slot count. `free_slots` = `N` − this |
| `hailMaryMode` | Absent = off. `on` = last-ditch after ordinary paths. `full` = any escalation |

### 2b. Fill slots

The board lists claimed objects only. Pull unclaimed work every turn, even while siblings are in flight:

```
migration_status(mode="next_objects", limit=<free_slots>)
```

If it has `testbed_helpers`, send them first (Step 1c).

`leftover_claims` is `{object_id, display_name}` — open claims with **no walker**. Waiters, live children and parked/blocked walks are omitted. **Before waiting, first-send leftovers** (new child, no `resume`), at most `free_slots`; spawn from `objects` for any slots left.

Hand each `object_id` to its child — **the child claims**. Never call `transition_status(status="begin")` yourself: the agent that does the work owns the claim. A spawn that dies before `begin` returns on the next `next_objects` pull; a child that dies after `begin` returns via `leftover_claims`.

Keep (object id, conversation UUID) only to match a wake to `task(resume=…)`; prefer the board `agentId`.

Claim only this turn's `next_objects` ids, only `free_slots` of them, never a category `where` — a claim hides the object from every teammate's picker, and `N` is the authorized batch, not the wave.

### 2c. Dispatch

Always `general_task`. **One live child per object** — two conversations race on the same files and registry. Check `answered` before every send: an answered row is already un-parked, so it looks like ordinary work. If the object is there, the next prompt includes `guidance:` (later send when you have the UUID, first send when you don't) — dropping it sends a walker to re-decide something a person already decided.

Never pass `fork_conversation_history`. Do not send again for a board `blocked` row.

**First send** — no conversation UUID. One `task` call per object, `description` set, no `resume`. **Pass the entry's `walker_prompt` from `next_objects` verbatim as the prompt** (`objects` and `leftover_claims` both carry it); append only a `reason:` line from a `reopened` return. It already holds `guidance:` from `answered`. The task hook denies any other first send, so do not write or extend the prompt yourself. On `walker_prompt_warning`, append `guidance:` yourself for any object listed under `answered`.

`task` returns `agentId` (UUID). Store it as this object's conversation id. A later `task(resume=…)` returns a **different** UUID (wait handle for that send) — do not overwrite the stored conversation id with it.

Do not tell the child to load `snowflake-migration:migration`, or add retry limits, return schemas, or "don't escalate" — the agent definition is the contract.

**Later send** — you have the conversation UUID. Prompt is **only the new line**; the hook denies anything else. Do not repeat `objectId` / `projectDir` / `pluginDir` / `snowflakeConnection` / the migrate line.

```
relay_wake: <the wake line, verbatim>
```

or, after a person answered:

```
guidance: <verbatim from `answered`>
```

or, when the board says `ready` after a `partial` / remediated `reset`:

```
Continue this object from the machine's next task.
```

Finish every first send and wake for this turn, then wait once in 2d.

If `task(resume=<conversation UUID>)` fails or the conversation is gone: first-send a new child (full prompt, no `resume`). Do not retry `resume`. Do not first-send while `flight` is `running` or `idle`.

A child returning `refused to reclaim … live Cortex walker` met the object's own walker: never park it or send hail_mary for it. `flight` `running`/`idle` → leave it; `none` → `task(resume=<board agentId>)`; a failed resume drops it to `leftover_claims`.

### 2d. Wait

Headless: ending the turn kills every child. **Top off, then wait.** Do not start a wait while leftovers or free slots remain. Helpers (`cur_reconciler`, `test_case_verifier`, `task_invalidator`, `sandbox_specialist`, `edge_cases`, `business_logic`, `data_driven`, `speculative_fixer`) do not occupy slots — do not poll them. `hail_mary` is a walker: it occupies a slot and stamps `flight`.

A `Background agent finished` line, a Monitor `wake up <parent session id>`, and a `hub(mode="wait")` return mean re-read 2a/2b.

Wait once after every free slot is filled: `hub(mode="wait", confirm=true, cursor=<last>, timeout_secs=60)`, then 2a/2b. It returns once a walker finishes or completes a task another object waits on; keep its `cursor` for the next wait. Without `confirm=true` it does not block. Never `bash sleep`. Do not wait while 2b would return objects.

Arm **one** Monitor for the wave: `orchestrator_watch.watch_command` from `configure`, `hub(mode="status")`, or `job_status(monitor=true)`, `persistent: true`. Each line is an instruction.

A wake `wake up <UUID> and ask it to check new event from relay. …` is a later send: `task(resume=<that UUID>)` with the `relay_wake:` line. That UUID is the child's `agentId`. A wake naming the parent session id means 2a/2b. After `task_invalidator` reopens defective units, 2b first-sends them; the waiter that parked stays harvested until those walks finish.

Report from the board, not from a child's final JSON.

**Reset** only from evidence you already have (infrastructure now ready, or a shared job reached terminal) — never from the child's `failed` payload:

```
transition_status(status="reset", task="<task>", where="id = '<id>'")
```

Then later-send that object once; never follow `reset` with `status="answer"`. Record the remediation in the wave report. If a child parked before a helper returned `done`, `reset` then later-send with the repair fact — do not answer the historical row.

Row mismatches, schema drift, invalid identifiers, compile errors and repeat tool failures are not transient. Park them. `reset` before remediation erases the durable record of a failure the next run will reproduce.

### 2e. Escalate

Park first. Do not AskUserQuestion. An escalated object does not occupy a slot — keep dispatching.

A walker that returns `stuck` may already have escalated, so check `migration_status(mode="escalations")` for an open row on that object first. If the object is not already parked:

```
transition_status(status="escalate", task="<the task it keeps returning on>",
                  asks=["<choice>", "<choice>"],
                  cause="<sql|infra|data, from the agent's failed.error — omit it otherwise>",
                  reason="<what stopped you>", where="id = '<id>'")
```

`asks` is required. `alreadyEscalated` means the open row for that object and task was reused with this call's reason and asks: still one question for the user. Then one transcript line and back to 2a/2b. Do not number the choices or wait for a chat answer.

Never settle an open row from a child's output or your own diagnosis. The autonomous parent may relay an explicit user reply from this Cortex conversation with `status='answer'`; walkers cannot answer. Relay the user's words verbatim, matched to the open row they answer, as [Escalate and terminate](references/escalate-and-terminate.md) shows. When `answered` shows a new row — a person's, or a reply you relayed — later-send with `guidance:` if the resolution was `guidance` or `decompose`. `needs_repair` stays parked. `skip` / object-level outcomes stay parked for the interactive session. `skip_data`: re-read. Do not send again without an answer already on the row.

A transient failure whose condition has cleared is a 2d `reset`, not an answer.

A bad load (target rows duplicated or short against the source) in a table this project loaded is no question for the user: `reset` the task it is parked at (`migrateData` or `validateData`) and later-send its walker, whose reload replaces the rows ([data-migration](../actions/data-migration/SKILL.md), *Clearing a bad load*). An unparked walker reopens `migrateData` itself. Never hand the user a truncate or a reload.

A missing or non-bindable dependency (`reason: "missing"`, tokenless
`PUBLIC.X` / empty `target.database`, unknown UDF for a project object) is
[`cur_reconciler`](../../../../agents/cur_reconciler.md) — it scans `source/`
and source-bindable, mints a CUR entry when the file is there, wires
`dependsOn`, and qualifies converted / source-bindable SQL plus CUR identity
so bindings substitute. Any object kind. Register / stub / out-of-scope stay
parked only when that child returns `escalate`. Design decisions (no Snowflake
equivalent, two readings that differ) arrive with no `causeClass` — park them;
they are not failures. SQL CLR is a rewrite: park only what
[TS0143](../rule-engine/resolving-ewis/reference/SSC-EWI-TS0143.md) parks.

`hailMaryMode` on the board (or configure's policy line) picks the rule for sending [`hail_mary`](../../../../agents/hail_mary.md):

- `on` — last-ditch after ordinary paths are exhausted (leftover first-send, later-send, helper, invalidation, register/stub, reset). Not because the row is `escalated`. Parked is still the wait: a person, a harvested waiter on a relay job, or a `task_invalidator` reopening a defective unit. Leave those.
- `full` — any `escalated` object that is waiting for a human. After you park in this section, send. Already-parked rows on each 2a/2b pass are still work. Send is mandatory: do not skip it because you judge hail_mary cannot help. hail_mary decides that and returns `needs_repair` / `refused`; only then does the row stay with the person.

Never while `flight` is `running`/`idle`, the object is `waiting`, a helper for it (or a unit it is blocked on) is in flight, `hailMaryAgentId` is set, or `answered` already has a human row. One live hail_mary per object. One send per parked row — after `needs_repair` / `refused`, leave parked. Its first-send prompt and what to do with its return are in [hail_mary](references/hail-mary.md); read it before the first send.

### 2f. Stop

The loop ends when all four hold:

- nothing in flight (`walkerRunning` is 0, `hailMaryRunning` is 0, no `flight=idle`, and no object `waiting` on a relay job),
- the board has no `ready` objects (`escalated` / `blocked` do not block termination),
- `next_objects` is empty and `leftover_claims` is empty,
- every remaining object is `escalated`, `blocked`, `done`, `errored`, or out of scope.

Do not send hail_mary to satisfy 2f when `hailMaryMode` is `on`. When `full`, remaining `escalated` rows that have not had a hail_mary send (and are not in the never-while list) are still work — dispatch them before stop. After hail_mary `needs_repair` / `refused`, that object may stay escalated.

Credential / OAuth expiry is not a human question — the run cannot continue until the owner refreshes auth.

A `ready` object with nothing in flight: dispatch it or park it, never report around it. An object that returns `ready` again with empty `tasksCompleted` must not be dispatched again until the board changes; if there is no remediation, park it (2e).

A refused `finish` parks the object like any other (2e); it never stops the wave. Never ask the user to switch to interactive mode to close it, and once they say to keep going, do not ask again.

Then Step 3. If `escalated` rows remain or `openCount` is non-zero, say so — the run finished, the wave did not.

## Step 3: Report

Call `migration_status()` and report as [../SKILL.md](../SKILL.md) Step 3 does, plus: objects finished without intervention, objects escalated (open asks), unreviewed notes as **object + task** only (do not pass `details=true`; do not quote SQL or choice text), left for the person to review — never call `transition_status(status="review")`. Also: subagents dispatched, remediated tasks reset, and outcomes stamped by an agent because the machine could not observe them.

A stage count is not a done count. Take the finished number from the
`migration_status()` you already called — `objects_done` — and leave `stage_totals`
out of it: an object can be deployed, data-migrated, and still not finished, so
adding stage counts together counts one object several times. `objects_done` covers
the active wave, so when the status payload carries a `wave`, name it and
`in_scope_all_waves` rather than presenting that wave's total as the migration's;
`doneCount` on `my_objects_board` counts only what you hold a claim on.

Build every line the board can confirm from the board. If you cannot tell how many resets there were, say what you saw instead of a number.

Then `speculative_sandbox(mode="sweep")`, check its preview, and call it again with its `confirm`.

After the wave, call `migration_status(mode="next_objects")` (the summary lacks the wave hint). On a `next_pending_wave`, call bare `configure()` to move there (`Wave <N> is finished; moved to wave <M>.`) and continue from Step 1; `configure(wave=<M>)` picks another wave.

With no wave pending, call `data_infrastructure(mode="down")`, or [../../data-infrastructure/teardown/SKILL.md](../../data-infrastructure/teardown/SKILL.md) when the project configured a `compute_pool` and data work ran.

## Interrupted run

Laptop-kill, MCP death, and flock drop are not child death — Cortex children outlive the MCP process. Re-enter this skill: Step 0, then 2a; dispatch each row as 2c says. Read `escalations` before dispatching: a question from before the session died is still open, and an answer the user gave is still waiting to be acted on.
