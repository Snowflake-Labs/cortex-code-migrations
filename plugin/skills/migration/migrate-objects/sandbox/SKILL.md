---
name: sandbox
description: Private AIMSBX catalogs for procedure tests (`createIsolatedSandbox`), on-demand private catalogs when a view/function needs fixture data reshaped, and shared source-catalog deploy for tables, views, functions, and (after tests) procedures (`deployCommonSandbox`). Triggers: createIsolatedSandbox, deployCommonSandbox, setup_sandbox, procedure sandbox, AIMSBX, make_testable.
parent_skill: migrate-objects
license: Proprietary. See License-Skills for complete terms
---

# Sandbox

The state machine routes here under `configure(subagent_mode=true)`. Load the
child that matches `next_task`.

| `next_task` | Guide |
|-------------|-------|
| `deployCommonSandbox` | [DEPLOY_COMMON.md](DEPLOY_COMMON.md) |
| `createIsolatedSandbox` | [CREATE_ISOLATED.md](CREATE_ISOLATED.md) |

`deploy` (Snowflake common catalogs) is a later task. Procedures reach
`deployCommonSandbox` after tests, then `deploy`. `finish` drops the
`AIMSBX_*` catalogs. Do not `configure(snowflake_database=…)` onto a sandbox
name — the session is shared across walkers.

Views and functions stay on the shared catalogs unless fixture data blocks
tests. Then sandbox_specialist calls `deploy(sandbox=true)` for **that**
object only. The machine does not add `createIsolatedSandbox` to their walk.
