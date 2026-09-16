---
name: setup-sandbox
description: Populate the shared source catalog for one table, view, or function (`setupSandbox`). Deploys source DDL and, for a table, loads testbed rows. Triggers: setupSandbox, setup_sandbox, source catalog setup.
parent_skill: sandbox
license: Proprietary. See License-Skills for complete terms
---

# Set up source objects and data

Guide for the `setupSandbox` task. Tables, views, and functions only; the
machine invokes this after convert so a run from source code has something to
capture a baseline from or compare against.

## Call the tool

Call `setup_sandbox` with the `invocation` from `next_task` (already scoped to
this object's `where`). Reconstructing the call, pass `where` with object id.

This is **source-only**. It deploys the object's source DDL (`scai code deploy
-t source`) into the shared source catalog and, for a table, runs `scai
testbed load --source-only --where` so it has fixture rows. Snowflake is
untouched — that is the later `deploy` task. CREATE is skipped when the object
already exists.

Do **not** pass `--profile` or `--database-bindings` — the tool injects them.
Do **not** call `deploy`. Schema/ETL/BTEQ units and units with no source come
back as `skipped`, not failed.

## If the call fails

This is not yours to diagnose. Spawn **one** foreground
(`run_in_background=false`, `subagent_type="sandbox_specialist"`).
Do not call next_task first. Do not stamp `error=sql`. Do not DROP
shared WAVE_SRC. Do not write `source_ready` by hand.

Hand `objectId`, `projectDir`, and the tool JSON (`failure_class`,
`sample_rows`, `next_invocation`). Do not pass `agent_id`. Do not tell
it the verdict.

Wait. Then:

| Child `result` | Do |
|---|---|
| `done` | Continue the walk (`next_task`). |
| `escalate` | Park with that child's `asks`. |
| `needs_sql_fix` | Existing sqlFixLoop, then spawn the helper again for `load_only`. |

## After a successful call

Re-pull `migration_status(mode="next_task")` with this object's `object_id`.
Do **not** call `transition_status` for this task. Completion is
`ORCHESTRATION.SANDBOX_EVENTS`, not a registry stamp.
