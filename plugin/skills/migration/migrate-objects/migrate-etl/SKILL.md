---
name: migrate-etl
description: Stabilize an ETL code unit (SSIS, Informatica, or other platforms) by handing the converted artifacts off to migrate-etl-package and recording the result on the registry entry.
parent_skill: migrate-objects
license: Proprietary. See License-Skills for complete terms
---

# Migrate ETL

Wraps [actions/migrate-etl-package/SKILL.md](../actions/migrate-etl-package/SKILL.md) so it runs as a state-machine task on a single ETL code unit.

The platform of an ETL code unit is recorded on its registry entry as `source.platform` (`ssis`, `informatica`, …). `migrate-etl-package` already covers every supported platform via per-platform profiles in `actions/migrate-etl-package/platforms/`. This skill does not replicate that work — it only:

1. Resolves the converted-artifacts folder and source-definition paths from the registry entry.
2. Invokes `migrate-etl-package` against them.
3. Updates `codeStatus.stabilization` on the registry entry when stabilization finishes (or the unit is excluded).

## Step 0: Scope

**Stabilization** for this version means: run `migrate-etl-package` until its Final Validation phase reports clean. That covers everything `migrate-etl-package` does — scan, ROADMAP, phased TDD across orchestration elements and dbt sub-projects, EWI fixes, etc.

**Out of scope here:** ETL deployment to Snowflake is currently not supported by scai or the migration skill yet.

## Step 1: Resolve Inputs From the Registry

Read the unit (the executor passes `object_id`, or call `migration_status(mode="my_objects_details", group=<id>)`):

| Field | Used as |
|---|---|
| `files.source.path` | source definition file (e.g. `.dtsx` for SSIS, `.xml` for Informatica) — `{SOURCE_FILE_PATH}` for `migrate-etl-package` |
| `source.platform` | `{PLATFORM_ID}` for `migrate-etl-package` (skip its Step 1b auto-detect prompt) |
| `parts[]` → derived converted folder | `{PACKAGE_FOLDER}` for `migrate-etl-package` |

**Deriving the converted folder.** Converted output is recorded per part in `parts[].target`:

- Data-flow parts (e.g. `partType: "Microsoft.Pipeline"` for SSIS) → `target.format: "dbt"`, `target.path` points to a **dbt project folder** (one per data flow).
- Other part types (e.g. `Microsoft.ExecuteSQLTask` for SSIS) → `target.format: "snowflakeSQL"`, `target.path` points to a single **orchestration `.sql` file** shared by every non-dbt part of this code unit.

Resolve `{PACKAGE_FOLDER}` as the parent directory of any part whose `target.format == "snowflakeSQL"`. The dbt sub-project folders should sit alongside that orchestration file under the same parent — verify before handing off.

If `parts[]` is empty or no part has a `target` yet, the converted output has not been produced — the `convert` task should have run first. Surface that to the user and stop; do not try to stabilize an unconverted ETL unit.

## Step 2: Hand Off to `migrate-etl-package`

Load [../actions/migrate-etl-package/SKILL.md](../actions/migrate-etl-package/SKILL.md) and run its workflow with the inputs from Step 1. You are skipping its Step 1 (Gather Inputs) prompt because the registry already provides every value it would have asked for.

Follow `migrate-etl-package` end-to-end:
- no `STATE.md` yet → its Planning Workflow (scan → context-mapping → ROADMAP → user approval at Step 9) → Execution Workflow.
- existing `STATE.md` → straight into Execution Workflow at the next pending phase.

Stay there through Final Validation. **Do not exit back to this skill phase-by-phase** — `migrate-etl-package` is autonomous between its declared stopping points.

## Step 3: Mark Completion

When `migrate-etl-package` finishes its Final Validation cleanly, advance the state machine:

```
transition_status(status="advance", task="stabilization", outcome="completed", where="id = '<etl_id>'")
```

Stabilization is **terminal** for ETL in the current state machine — there is no `extractRules` step after it, and deploy is out of scope.

## Step 4: Failures

If `migrate-etl-package` halts because of an issue it cannot resolve on its own, mark the task as failed:

```
transition_status(status="advance", task="stabilization", outcome="failed", error="<short summary>", where="id = '<etl_id>'")
```

Then surface the issue to the user for resolution. When resolved, retry from Step 2 — `migrate-etl-package` will resume from `STATE.md`.

Anything that is **not** resolvable within `migrate-etl-package` (corrupt converted output, missing source file, Snowflake-side infrastructure problem) should be handled as an Error Recovery case within that skill before retrying.

## Step 5: Exclusion

If the user decides this ETL unit is out of scope (deprecated, replaced, manual migration), mark it out of scope:

```
update_registry(field="inScope", status="false", objects="<etl_id>")
```

Out-of-scope units stop appearing in `next_objects` and stop counting toward migration totals.
