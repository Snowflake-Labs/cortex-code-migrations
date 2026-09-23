---
name: deploy-sandbox
description: Create the private AIMSBX catalog pair for one object (`deploySandbox`) and deploy the closure there so capture and tests do not mutate shared rows.
parent_skill: sandbox
license: Proprietary. See License-Skills for complete terms
---

# Set up the procedure sandbox

Guide for the `deploySandbox` task. Your object mutates data, so you
get a private binding rather than sharing the catalog and conflicting
with other walkers' work.

## Call the tool

Call `deploy` with the `invocation` from `next_task` — it already has
`sandbox=true` and a scoped `where`. Reconstructing the call:

| Need | Call |
|---|---|
| Transitive closure into the sandbox | `sandbox=true`, omit `mode` (same as `mode=setup`) |
| This object only into a live pair | `sandbox=true`, `mode=redeploy_object` |
| This object only onto the common catalogs | omit `sandbox` — that is the later `deploy` task, not this one |

Omit `mode` creates empty `AIMSBX_*` catalogs unless a live leftover yaml
already names the pair — then it does not DROP or CLONE, but it still
deploys tables (CSV reload), functions, views, **and this object** from
current converted SQL into that pair. That is how a helper fix reaches the
sandbox: call this again with no `mode` after the helper walker finished
(see `RUN_TESTS.md`). `mode=redeploy_object` skips tables / functions /
views — use it after a SQL fix of **your assigned** object. `mode=reload_tables`
reloads closure table CSVs into that pair on both sides (wipes AIMSBX DML).

Converted-only procedures (no `source`) get a Snowflake-only catalog: skip
`-t source`. Otherwise first setup clones the closure's tables from the
common catalogs in `.scai/bindings/database-bindings.yaml`, rebuilds them
on the source from captured DDL plus testbed CSVs, then deploys the
closure's functions and views and the procedure itself there. Closure
units with no source (SnowConvert helpers) are deployed to Snowflake only.
It writes that object's leftover yaml
(`.scai/bindings/sandbox/{hash}.yaml`) so `captureBaseline` and `runTests`
walk those catalogs even after MCP restart or a new walker.
Two procedure walkers must not capture against the shared catalog at the
same time.

Do **not** pass `--profile` or `--database-bindings` — the tool injects them.
Do **not** `configure(snowflake_database=…)` onto a sandbox catalog. Do **not**
execute the CREATE PROCEDURE SQL yourself.

The JSON includes a `sandbox` object (`snowflake` / `source` token → catalog
maps, `bindingsPath`). Use those catalogs for tests, `sql_execute`, and
`query_source`.

## Pre-deploy file checks

Converted files may contain issues that need a bounded edit **before** this
call:

1. Leave a leading `USE DATABASE` in the file. The tool comments it out after
   substituting bindings.
2. Keep the converted qualifier (`<%token%>.dbo.X`, `TaskTracker.dbo.X`, or
   `schema.X`). Do **not** write the another database name into the
   file.
3. **Variable binding in LANGUAGE SQL procedures:** Parameters and variables
   inside SQL statements must use `:param_name` syntax. SnowConvert often
   omits the colon prefix — always verify.
4. **Preserve original comments** when editing converted SQL.

If you edit, change the SQL file in `snowflake/` first, then call the tool.
A Snowflake-only deploy is overwritten on the next run from disk.

## If the call fails

This is not yours to diagnose. Spawn **one** foreground
(`run_in_background=false`, `subagent_type="sandbox_specialist"`).
Do not call next_task first. Do not stamp `error=sql`. Do not DROP
shared WAVE_SRC.

Hand `objectId`, `projectDir`, the tool JSON (`failure_class`,
`sample_rows`, `next_invocation`), and the leftover yaml path.
Do not pass `agent_id`. Do not tell it the verdict.

Wait. Then:

| Child `result` | Do |
|---|---|
| `done` | Continue the walk (`next_task`). If still `deploySandbox`, retry `deploy(sandbox=true)` once. |
| `escalate` | Park with that child's `asks`. |
| `needs_sql_fix` | Existing sqlFixLoop (`error=sql`), then spawn the helper again for `mode=redeploy_object`. |

## After a successful call

Re-pull `migration_status(mode="next_task")` with this object's `object_id`.
Completion is `ORCHESTRATION.SANDBOX_EVENTS` (`live_bindings`), not
INFORMATION_SCHEMA on the common catalogs and not `cloudStatus.deployment`.
