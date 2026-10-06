# Board and object pool

## Read the board

```
migration_status(mode="my_objects_board")
migration_status(mode="escalations")
```

`my_objects_board` is the only status shape to read for dispatch. Each row is
one object: `objectId`, `name`, `type`, `agentId`, `bucket`
(`ready` | `blocked` | `done` | `escalated` | `errored`), and `flight`
(`running` | `idle` | `none`). `flight` is stamped when `task` returns
(PostToolUse: prompt `objectId` plus returned `agentId`), so a just-dispatched
walker is `running` before its first MCP call. `walkerRunning` is the live-child
slot count. Do not overlay `hub(mode="status")` for dispatch — the board already
stamped walker liveness (running wins over idle). If `flight` is `running` or
`idle`, do not first-send another child for that object.

A row's `agentId` is the live Cortex session while a walker exists, and a UUID.
Never copy it into a prompt or an MCP argument; Cortex stamps the child's
session id itself. Stop settles a yielded walker: a `waiting`, `partial`,
`reopened`, or `stuck` waiter stays harvested on the ledger (`agentId` remains,
`flight` is `none` — not a leftover) until a later `task(resume=...)`, while
`completed` leaves the roster. `flight=idle` means the stop is not folded in
yet: re-read the board, and do not call `agent_output`.

Do not call `my_objects_summary`, `my_objects_details`, `next_task`, or
`task_views`. Those name the current task and why it is waiting; they are for
interactive sessions and for the child walking the object.

`escalations` is the human queue. Read `escalations` (open asks) and `answered`
(`guidance`). Do not pass `details=true`. Do not read `notes[].asks`, `choice`,
or `overrideAcceptedCases`; default payloads omit those bodies.
`unreviewedCount` is a tally for the final report, not a reason to stop.

Re-read both every time a child returns.

## Top off the object pool

A slot is occupied only by a live Cortex child. Read that from
`my_objects_board.walkerRunning`, not from memory. `waiting` on a relay job,
`stuck` or `escalated` parks, leftover claims from a dead session, and completed
objects do not occupy one — those children are harvested (`flight=none` with an
`agentId`) or gone (`flight=none` without a walker). `free_slots` is `N` minus
`walkerRunning`. When it is greater than zero, pull:

```
migration_status(mode="next_objects", limit=<free_slots>)
```

The board lists only claimed objects. Unclaimed work is invisible there;
`next_objects` is the only way to see it. It returns objects whose current walk
is not blocked — the same verdict `next_task` would give — or comes back empty.
Do not skip this pull because a leftover looks blocked on a sibling still in
flight. Do not wait for the flight to empty.

`next_objects` also returns `leftover_claims`: open claims with no walker in the
ledger. Live, idle, and harvested walkers are omitted — those are not leftovers,
and a harvested waiter can show `flight=none` while it still keeps its `agentId`,
so never first-send one. Each entry is `{object_id, name}` with no `agentId`.
Before waiting, first-send every leftover as a new child with no `resume`. That
child's `begin` reclaims the dead conversation's hold. Do not first-send a
leftover that already has `flight` running or idle; the server already filters
those out. Count those first-sends against `free_slots`, then spawn from
`objects` for the remaining slots.

Each `objects` entry has `object_id`, `name`, `display_name`, and `type`. Hand
the object ids to the children you dispatch; each child claims its own object.
Never call `transition_status(status="begin")` from the parent. A spawn that
dies before `begin` leaves the object unclaimed, so the next pull offers it
again. A child that dies after `begin` leaves an open claim; first-send a new
child from `leftover_claims`.

Keep the pair of object id and Cortex `resume` id only to match a wake line to
`task(resume=...)`. Prefer the board `agentId` when `flight` is running or when a
harvested waiter still carries one.
A leftover first-send is a new conversation; do not resume a dead child.

**Claim narrowly.** The parent mode intentionally differs from
[interactive claiming](../../actions/claim_objects.md): keep the batch to the
free slots, use only ids returned this turn by `next_objects`, and never claim
with a category `where` predicate. The user authorized `N` slots, not the whole
wave.
