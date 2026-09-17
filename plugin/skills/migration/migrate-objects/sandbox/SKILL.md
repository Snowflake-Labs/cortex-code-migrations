---
name: sandbox
description: Private AIMSBX catalogs for procedure tests (`deploySandbox`), on-demand private catalogs when a view/function needs fixture data reshaped, and shared source-catalog setup for tables, views, and functions (`setupSandbox`). Triggers: deploySandbox, setupSandbox, setup_sandbox, procedure sandbox, AIMSBX, make_testable.
parent_skill: migrate-objects
license: Proprietary. See License-Skills for complete terms
---

# Sandbox

The state machine routes here under `configure(subagent_mode=true)`. Load the
child that matches `next_task`.

| `next_task` | Guide |
|-------------|-------|
| `setupSandbox` | [setup/SKILL.md](setup/SKILL.md) |
| `deploySandbox` | [deploy/SKILL.md](deploy/SKILL.md) |

`deploy` (common catalogs) is a later task, after tests. `finish` drops the
`AIMSBX_*` catalogs. Do not `configure(snowflake_database=…)` onto a sandbox
name — the session is shared across walkers.

Views and functions stay on the shared catalogs unless fixture data blocks
tests. Then sandbox_specialist calls `deploy(sandbox=true)` for **that**
object only. The machine does not add `deploySandbox` to their walk.
