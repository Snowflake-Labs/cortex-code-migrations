# State-machine tools: `transition_status` and `migration_status`

The tool descriptions are one line per status or mode and point here. The skill
or agent that makes a call restates what it needs; this file is the full list.

## `transition_status`

Every status except `skip` takes `where`, a registry filter:
`"id = '<id>'"`, `"id IN ('<id1>', '<id2>')"`, `"source.schema = 'sales'"`.

Under `configure(subagent_mode=true)` Cortex stamps `agent_id`; never pass it.
`begin` records it on the claim, and every later write for that object must come
from the same agent. A write aimed at an object another agent holds is refused,
naming both agents.

| Status | What it does | Requires |
|---|---|---|
| `begin` | Claim every matched object for this session. Returns `{status, action, actual_size}` plus `reclaimed_from_other_sessions`; read claims with `migration_status(mode="my_objects_summary")`. | `where` |
| `started` | Spool a `started` TASK_EVENT for an agent-skill or mcpTool task. Call once at skill entry. Stamps nothing and does not advance; finish with `advance`. Refused for shell tasks. | `task` |
| `advance` | Stamp `task` with `outcome` for every matched object; returns per-object `{advanced, blocked}`. | `task`, `outcome` |
| `escalate` | Park for a human decision. | `task`, `asks` |
| `answer` | Record a person's decision on objects parked at `task` and un-park what it implies. | `task`, `resolution` |
| `note` | Record a judgment call and keep going. Does not park. | `task`, `asks`, `choice`, `reason`, `change`, `undo` |
| `review` | A person has looked at the notes at `task`. | `task` |
| `override_accept_case` | Overlay-accept one failing test case. | `task="runTests"`, `params_hash`, `asks`, `choice`, `reason` |
| `invalidate` | Reopen a code unit whose walk is stale. | `reason` |
| `bypass` | Override a task's unmet preconditions. | `task`, `reason` |
| `reset` | Clear what holds `task` back so the next walk re-emits it. | `task` |
| `finish` | Mark objects done, land their files, release the claims. | `where` |
| `hail_mary_step` | Narrative row for a hail_mary child. | `where`, `reason` |
| `skip` | Deprecated: use `progress_setup(skip="<task>")`. One-time skip of a setup step; persists nothing. | `task` |

### `advance`

- `outcome` is `completed` or `failed`. On `failed`, `error` is the class:
  `sql` routes into the fix loop; `infra` is a transient environment failure,
  retried with `reset`. The vocabulary is in
  [../../extensibility/TASKS.md](../../extensibility/TASKS.md#outcome-vocabulary).
- A `completed` advance is refused when the task's status source disagrees.
- Do not stamp a dependency wait: the walk derives `blocked` / `blockedOn` from
  the dependency's live status, and `error='dependency'` is refused.
- An advanced entry with `nextTaskBlocked: true` names in `nextTaskBlockedOn` the
  dependencies its `nextTask` waits on. The object stopped there; it is not work
  to dispatch.

### `escalate`

- Prefer it to `advance` with `error='human'`: leaving out the error class there
  makes the escalation a routing failure and sends the object into the fix loop,
  where no code change resolves it.
- `outcome` and `error` are implied and refused. Optional `cause` (`sql` |
  `infra`) is the failure that led here; `human` is refused as circular. Optional
  `reason` is what actually stopped you.
- Escalated objects surface as `needsHuman` groups with `escalatedCount` in
  `my_objects_summary`, never as fix candidates.

### `answer`

The authoritative contract is the `answerWith` field of
`migration_status(mode="escalations")`.

| `resolution` | Effect |
|---|---|
| `guidance` | Clears the task stamp so a re-dispatch proceeds. `reason` (the person's words) is required: a re-dispatch without it repeats the failure. |
| `decompose` | Clears the task stamp, as `guidance` does. |
| `skip` | A person's only, with `reason`: retires the object as skipped (`inScope=false` plus `extensions.skipped` = who, why, when, task), supersedes its claim and never marks it done. A live walker's object needs `reclaim=true`. `finish` reports it `skipped` and refuses `force`; counts report it as `objects_skipped`. Its dependents stay blocked. |
| `skip_data` | Answers only a `migrateData` escalation. The table stays in scope with its structure deployed but no rows copied: `extensions.taskExclusions` excludes its `migrateData` and `validateData`, the walk continues, and each dependent gate follows its declared `onDependencyExcluded`. |
| `needs_repair` | Leaves the object parked. It drops out of the open queue but still reads `needsHuman`, so it is never re-offered as work. |
| `mark_done` | Records the decision only. Finishing is a separate, explicit `finish` call. |
| `unvalidated` | At `captureBaseline`/`runTests` only, with `reason`, and never from a hail_mary: nothing about the object can be tested. Both read passed over, so `finish` needs no force; it counts as `unvalidated`, never tested. |

Who may answer: an interactive session directly. Under `subagent_mode`, the
autonomous parent may relay an explicit user reply from its own conversation,
and a privileged hail_mary child (`AIM_HAIL_MARY=on|full`) may answer. Ordinary
walkers are refused so their writes cannot look like a person's. A person's
answer leaves `ANSWERED_BY_AGENT` empty (`human: true`); a parent relay or
hail_mary answer stamps its id (`human: false`). A `test_case_verifier` honors
override-accept only from a `human: true` row.

`scope`: `object` (the default) answers the matched objects alone. `scope="project"`,
with `resolution="guidance"` only, also hands the person's words to every other
object: `next_objects` writes them into each walker's first send as
`standingGuidance:`, newest first, below that object's own `guidance:`, which wins
where they disagree. It is the person's choice, never an inference: pass it only when
the user says the answer applies to every object. It is refused from the autonomous
parent and from hail_mary, so under `subagent_mode` it comes only from the app's
"Apply this answer to every object in this project" box.

### `note` and `review`

A note surfaces as an unreviewed note on `mode="escalations"`, not as a
`needsHuman` group. `choice` must be one of `asks`. When there is no nameable
`undo`, the call should have been `escalate`.

`review` acknowledges a person has read the notes; it does not undo them, and
disagreement is new work. Optional `escalation_id` limits it to one note. It is a
person's call only: refused for every agent under `subagent_mode`.

### `override_accept_case`

- Overlay only: RESULTS still holds the FAIL, and the next `scai test validate`
  cannot erase it. Does not park and does not stamp `runTests`.
- The `runTests` status source joins `(code_unit_id, params_hash, target)`. `test_name` is display
  only and defaults to `source.name`.
- With `require_independent_override_accept` in `plugin.yml` (on by default), it
  is refused for the `runTests` walker that holds the claim, and refused without
  an `agent_id` once `subagent_mode` is on. After the fix loop, spawn one
  `test_case_verifier` with fresh context for the object's remaining failing
  cases. Do not call `configure(subagent_mode=true)` for that: the latch is the
  autonomous orchestrator's, set before it dispatches walkers. `false` turns the
  requirement off. The parent is always refused.

### `invalidate`

- Omitting `task` resumes at the unit's verification node (`validateView`,
  `runTests`, or `verify` for source-less helpers). Passing `task` rewinds from
  that node instead (e.g. `convert`).
- Writes `ORCHESTRATION.TASK_INVALIDATIONS` for the resume task and every later
  task on the unit's walk, clears `extensions.isDone`, and unparks. Stale
  readings count as Pending until `updated_at > INVALIDATED_AT`.
- `where` names the code unit(s) to reopen, not the waiter as a substitute.
- Refused for the claim holder and for the parent: spawn a `task_invalidator`
  (it shares the attached server). The target must be in scope and in the
  transitive `dependsOn` closure of a code unit claimed live in this session.

### `bypass`

Last resort. Stamps `extensions.preconditionBypass.<task> = true`. Only for tasks
that declare preconditions; bypassing any other task is refused. A bypassed task
is surfaced distinctly, never as satisfied. Prefer resolving the blocker, and use
it only when the user explicitly insists.

### `reset`

Clears the registry stamp behind the task's status source, the escalation park,
or both. Use it to retry a transient failure of a long-running task
(`migrateData`, `validateData`, `runTests`) after fixing the cause, and to retry
an object parked by an `infra` escalation; the response reports what it
`unparked`. It does not answer the escalation: the queue row stays open, because
retrying the work is not a decision.

### `finish`

Stamps `extensions.isDone`, lands the objects' files on `origin/main`, rebases
the branch, and closes the claims; see
[../actions/finish_objects.md](../actions/finish_objects.md). Objects whose walk
has not reached done are refused, and nothing is marked or committed, unless
`force=true` from an interactive human session or a privileged hail_mary child.
An ordinary `force=true` is refused under `subagent_mode`. Neither `begin` nor
`finish` returns claim status.

### `hail_mary_step`

Writes a TASK_EVENTS row with `event='hail_mary'`; optional `task` and `change`.
Does not move the machine. Needs `AIM_HAIL_MARY=on|full`.

### The autonomous parent

Under `subagent_mode` the parent session may call only `reset`, `escalate`, and
`answer` to relay an explicit user reply. It cannot `begin`, `finish`, `advance`,
`started`, `bypass`, `note`, `review`, `override_accept_case`, `invalidate`, or
`skip`, and it never finishes a `mark_done`.

## `migration_status`

| Mode | Returns |
|---|---|
| `summary` (default) | Project status counts and routing flags. `objects_done` counts finished objects in the active wave; when the payload carries a `wave`, report it with `in_scope_all_waves`. `stage_totals` counts objects per stage cleared, so summing it overstates completion. |
| `my_objects_summary` | Interactive loop: claimed objects grouped by `(task, object_type)` with stable group `id`s (e.g. `task:table:deploy`), plus errored and done counts. The autonomous parent uses `my_objects_board` instead, because this mode names the current task. |
| `my_objects_details` | One group. `group` is a task group id (`task:<object_type>:<task>`, or `task:<object_type>:<task>:<skill-file>` for a forked skill), `errored`, or `done`. A group carries the same `executor.skill` / `skillPath` pair as `next_task`. |
| `my_objects_board` | The autonomous parent's board: one row per object (`objectId`, `displayName`, `type`, `agentId`, `bucket`, `flight`) with no task, reason, or asks. Field meanings are in [../autonomous/SKILL.md](../autonomous/SKILL.md) Step 2a. |
| `next_objects` | Objects ready to claim. `limit` defaults to 5; `total_available` is the whole ready pool. Under `subagent_mode` open claims are hidden, and those with no walker whose walk can start come back as `leftover_claims`. |
| `next_task` | The next task and its executor for each of `object_ids`, as a `{ objectId: entry }` map. |
| `escalations` | Every object parked on a human decision, project-wide and across sessions, oldest first, with `asks`, `causeClass`, `answered` rows, unreviewed `notes`, and `allNotes`. `details=true` restores decision and review fields; the autonomous parent never passes it. |
| `task_views` | Debug: the resolver's per-task snapshot for `object_ids` ("why did it pick X?"). |
| `health_check` | One-call triage: project initialized, machines loaded, registry present, errored count. |
| `extensions` | Overridable tasks and any active override. |
| `object_timelines` | Per-object phase segments from TASK_EVENTS. |
| `object_claim_lineage` | Claim history (`agentIds`) per object. |
| `ready_tasks` | Under task claims: tasks that may run now and are not held by a live walker, plus the open task claims. |

`summary` and `next_objects` first fetch and rebase the current branch onto
`origin/main`, so they reflect collaborators' work
([collaboration-model.md](collaboration-model.md)). `local: true` skips that.

### `next_task` entries

- Each entry carries `do`: follow it rather than re-deriving the branch from
  flags. When `result` is set, it is the walker's stop JSON `result`.
- `executor.skill` is relative to the plugin's `skills/` directory, not the
  project. When an entry carries `skillPath`, that is the same file as an
  absolute path: prefer it, and expect it to be absent.
- A walker's stamped `agent_id` registers a wait when `blockedOn` is another
  object's `migrateData` / `validateData`: the entry carries `wait` (`subscribed`
  or `pending`) and `do` / `result` say waiting. Dependents do not call
  `job_status(wake=true)`.
- `task` walks from that task instead of the machine's start, for a walker that
  holds one task's claim.
