---
name: migration
description: End-to-end database migration to Snowflake. Orchestrates the full migration lifecycle from source connection through initial conversion. Triggers: migrate, migration, migrate to snowflake, end to end migration, e2e migration, full migration.
license: Proprietary. See License-Skills for complete terms
---

# Database Migration to Snowflake

## Step 0: Configure Session

Configure the MCP server with `project_dir` and `snowflake_connection`. Other settings (source connection, database) are set later by sub-skills as the workflow progresses.

1. Call `configure` with `project_dir` (use the current directory, or ask the user). If a saved config is found, the response shows all restored values — skip to Step 1.
2. If `snowflake_connection` is not set, ask the user which Snowflake connection to use and call `configure` again with it.

**IMPORTANT** Only SQL Server, Redshift, Oracle, and Teradata projects are currently supported.

## Step 1: Detect Current State

Call the `migration_status` tool. It returns JSON with `project_exists`, `by_type`, `stage_totals`, and `routing` fields.

If `project_exists` is false, no scai project was found — go directly to `./setup/SKILL.md`. DO NOT go to step 2.

## Step 2: Ask the User

Show the progress checklist (see below), then ask:

> "What would you like to do? You can:
> 1. **Continue with migration plan** — I'll start or pick up where we left off
> 2. **Something specific** — tell me what you need"

If the user picks **Continue** (or just says "continue", "next", etc.) → go to **Prescribed Path**.

If the user describes a **specific request** → go to **Skill Match**.

### Progress Checklist

Render from `by_type` in the status JSON. Use `✅` (all done), `◐` (partial), `⬚` (not started):

```
<symbol> 1. Connect                  - Connected to <source>
<symbol> 2. Init                     - Project initialized
<symbol> 3. Register                 - <registered count> objects registered
<symbol> 4. Initial Conv             - <converted>/<total> converted
<symbol> 5. Assess                   - Assessment report generated / not run
<symbol> 6. Migrate Objects          - <table.deployed>/<table.total> tables, <view.deployed>/<view.total> views, <func+proc deployed>/<func+proc total> funcs/procs deployed; <table.data_migrated>/<table.total> data migrated; <func+proc tested>/<func+proc total> tested
```

---

## Prescribed Path

Use `routing` from the status JSON to delegate to the next step:

| Condition | Sub-skill |
|-----------|-----------|
| `routing.project_exists` = false | Load `./setup/SKILL.md` |
| `routing.assessed` = false | Load `./setup/SKILL.md` |
| `routing.assessed` = true | Load `./migrate-objects/SKILL.md` |

Each sub-skill handles its own internal routing based on the full `routing` object.

---

## State Queries

These answer common questions about project state without loading a sub-skill:

- **"What is the current state?"** — Call `migration_status`, present the progress checklist above.
- **"What should I work on next?"** — Call `next_object` to get the next dependency-ready object, or call `testing_progress` for a full summary.
- **"Show me objects that match rule X"** — Load `./migrate-objects/rule-engine/propagate/SKILL.md`.

---

## Skill Match

Match the user's request to the most relevant skill below and load it. If the request is ambiguous, ask a clarifying question. If no skill matches, say so and offer the prescribed path instead.

| Skill | Description | Location |
|-------|-------------|----------|
| setup | Connect, init project, register, convert, assess (steps 1-5) | `./setup/SKILL.md` |
| register-code-units | Register source code (extract from DB or add local files) | `./register-code-units/SKILL.md` |
| extract-code-units | Extract DDL/code from a connected source database | `./register-code-units/extract-code-units/SKILL.md` |
| add-code-units | Import local SQL files into the project | `./register-code-units/add-code-units/SKILL.md` |
| convert | Convert source code to Snowflake SQL via SnowConvert | `./convert/SKILL.md` |
| assessment | Analyze workloads — waves, object exclusion, dynamic SQL, ETL | `./assessment/SKILL.md` |
| data-migration-setup | Configure data migration — orchestrator, worker, workflow, Iceberg | `./setup/data-migration/SKILL.md` |
| migrate-objects | Deploy all object types wave-by-wave (tables, views, functions, procedures) | `./migrate-objects/SKILL.md` |
| baseline-capture | Capture source proc/function output as test baselines | `./migrate-objects/baseline-capture/SKILL.md` |
| rule-engine | Search, apply, extract, propagate, and manage migration rules | `./migrate-objects/rule-engine/SKILL.md` |
| extract-rule | Extract a reusable rule from a code fix (interactive or git history) | `./migrate-objects/rule-engine/extract/SKILL.md` |
| propagate-rule | Find all code units matching a rule for batch application | `./migrate-objects/rule-engine/propagate/SKILL.md` |
| migrate-etl-package | Phase-based ETL package fixer — invoke by name only | `./migrate-objects/actions/migrate-etl-package/SKILL.md` |


## Rules

1. **Always detect first** — Call `migration_status` before routing
2. **Follow sub-skill instructions** — Complete each sub-skill fully before returning
3. **Confirm transitions** — Ask user before moving to next stage
