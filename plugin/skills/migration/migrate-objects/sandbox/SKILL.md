---
name: sandbox
description: Private AIMSBX catalogs for procedure tests (`createIsolatedSandbox`), on-demand private catalogs when a view/function needs fixture data reshaped, and shared source-catalog deploy for tables, views, functions, and (after tests) procedures (`deployCommonSandbox`). Also the source test after synthetic data already exists. Triggers: createIsolatedSandbox, deployCommonSandbox, setup_sandbox, procedure sandbox, AIMSBX, make_testable, test on the source.
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

## Source test after synthetic data

`setup_sandbox` loads rows into the source (it runs `scai testbed load`
itself — do not shell that command). A return of `extracted live source
preserved` / `source_write_refused` / self-mapped preserve means **zero
rows loaded** — fix bindings to `AIMSBX_TB_*`, re-`configure`, and retry
until rows load; do not seed/capture on a vacuous source. Loading alone
does not finish a hop whose synthetic data already exists and whose user
asked to test that object on the source. Call `setup_sandbox`, then shell
seed and capture `--keep-baselines`, in that order. `<object_name>` is the
name the user gave, anchored after a dot so a shorter stem cannot select a
sibling. For a procedure whose closure has a table (e.g. GetOverlayDouble
→ OverlayClean), call `setup_sandbox` on that **table** so synthetic rows
actually land before seed/capture of the procedure.

A table seed writes no YAML. Call `setup_sandbox` for the table. Seed and
capture the view whose SQL selects that table. Do not pass the table name
to `scai test seed` or `scai test capture`. Do not stop after load. Do not
call `run_tests`. Do not run `scai test validate` on this hop. Do not shell
`scai code deploy`, `scai code extract`, or `scai code convert`.

For `OverlayClean` only (user named the **table** → seed/capture
**OverlayDoubled**):

```
setup_sandbox(where="source.canonicalName ILIKE '%.OverlayClean'")
```

```bash
scai test seed --where "source.canonicalName ILIKE '%.OverlayDoubled'"
scai test capture --keep-baselines --where "source.canonicalName ILIKE '%.OverlayDoubled'"
```

After seed, `artifacts/**/test/*.yml` for OverlayDoubled must exist and
contain the literal string `OverlayClean` — fix `source_query` and
re-capture if not.

For **`GetOverlayDouble`** (user named the **procedure** → seed/capture
**GetOverlayDouble**, not OverlayDoubled):

```
setup_sandbox(where="source.canonicalName ILIKE '%.OverlayClean'")
```

```bash
scai test seed --where "source.canonicalName ILIKE '%.GetOverlayDouble'"
scai test capture --keep-baselines --where "source.canonicalName ILIKE '%.GetOverlayDouble'"
```

The YAML **must** contain `GetOverlayDouble`. Substituting OverlayDoubled
when the user asked for GetOverlayDouble fails the hop.

For any other procedure or view the user named, call `setup_sandbox` then
shell seed and capture `--keep-baselines` with **that same name**. Always
call `setup_sandbox` even when it is a no-op. Never stop after seed alone —
capture `--keep-baselines` is required; missing `baselines/*.json` fails
the hop.

```
setup_sandbox(where="source.canonicalName ILIKE '%.<object_name>'")
```

```bash
scai test seed --where "source.canonicalName ILIKE '%.<object_name>'"
scai test capture --keep-baselines --where "source.canonicalName ILIKE '%.<object_name>'"
```

The written YAML body must contain the table name when it is a view over a
table. **Stop after capture.** Do not run `scai test validate`. Do not enter
`assessment`. Do not retarget to a private `SNOWCONVERT_AI_EVAL_*` results
DB. Leave literal `TEST_SQL_CUJ_*` / `EVAL_*` / `SNAP_*` names in
`target_query` — do not invent a `${...}` token. `scai test capture` without
`--keep-baselines` does not leave `baselines/*.json`.
