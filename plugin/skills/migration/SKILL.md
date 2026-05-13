---
name: migration
description: End-to-end database migration to Snowflake. Orchestrates the full migration lifecycle from source connection through initial conversion. Triggers: migrate, migration, migrate to snowflake, end to end migration, e2e migration, full migration.
license: Proprietary. See License-Skills for complete terms
---

# Database Migration to Snowflake

Tell the user:
> **Welcome to the Snowflake Migrations plugin.** Let me get started by configuring your session.

## Step 0: Configure Session

Call `configure` with the current directory. If a saved config is found, the response shows all restored values — proceed to Step 1.

## Step 1: Detect Current State

Call the `migration_status` tool. It returns JSON with `project_exists`, `directory_empty`, `by_type`, `stage_totals`, `routing`, and `highest_stage_reached` fields.

### Step 1.A: If `project_exists` is false, this is a new project. Go to the setup skill ./setup/SKILL.md

### Step 1.B: If `project_exists` is true, construct a brief narrative summary for the user from the JSON before showing the checklist. Use the `routing` booleans and `by_type` counts to describe the current state in plain language. Examples of the tone and level of detail:

- **Early setup:** "Your project is initialized and connected to SQL Server. 147 objects are registered but haven't been converted yet. We're in the setup phase."
- **Mid-migration:** "Setup is complete — 147 objects registered and converted, assessment done. You're in the migration phase: 12 of 47 objects have been deployed so far (Wave 2). 8 tables deployed, 2 views deployed, 2 procedures passed testing."
- **Near completion:** "Almost there — 45 of 47 objects are deployed and tested. 2 procedures are still failing tests."

Also add the checklist based on the status JSON. Use `✅` (all done), `◐` (partial), `⬚` (not started):

```
<symbol> 1. Connect                  - Connected to <source>
<symbol> 2. Init                     - Project initialized
<symbol> 3. Register                 - <registered count> objects registered
<symbol> 4. Initial Conv             - <converted>/<total> converted
<symbol> 5. Assess                   - Assessment report generated / not run
<symbol> 6. Migrate Objects          - <table.deployed>/<table.total> tables, <view.deployed>/<view.total> views, <func+proc deployed>/<func+proc total> funcs/procs deployed; <table.data_migrated>/<table.total> data migrated; <table.validated>/<table.total> validated; <func+proc tested>/<func+proc total> tested
```

Follow the summary with the progress checklist (see below), then go to Step 2.

## Step 2: Ask the User

> "What would you like to do? You can:
> 1. **Continue with migration plan** — I'll start or pick up where we left off
> 2. **Something specific** — tell me what you need"

If the user picks **Continue** (or just says "continue", "next", etc.) → go to **Prescribed Path**.

If the user describes a **specific request** → go to **Skill Match**.

---

## Prescribed Path

Use `routing` from the status JSON to delegate to the next step:

| Condition | Sub-skill |
|-----------|-----------|
| `routing.project_exists` = false | Load `./setup/SKILL.md` |
| `routing.code_conversion_only` = true | Load `./code-conversion-only/SKILL.md` |
| `routing.assessed` = false | Load `./setup/SKILL.md` |
| `routing.assessed` = true | Load `./migrate-objects/SKILL.md` |

Each sub-skill handles its own internal routing based on the full `routing` object.

---

## State Queries

These answer common questions about project state without loading a sub-skill:

- **"What is the current state?"** — Call `migration_status`, construct the narrative summary (as in Step 1), and present the progress checklist.
- **"What should I work on next?"** — Call `next_object` to get the next dependency-ready object, or call `testing_progress` for a full summary.
- **"Show me objects that match rule X"** — Load `./migrate-objects/rule-engine/propagate/SKILL.md`.

---

## Skill Match

<skill-match>
Match the user's request to the most relevant skill and load it.

**Routing rules:**
- Prefer the **parent (router)** skill when the child is ambiguous — it will route.
- Indentation = parent/child. A child only applies when its parent's domain already fits.
- If the request is ambiguous between siblings, ask one clarifying question.
- If no skill matches, fall back to the section below.

### Setup & onboarding
- **setup** — full setup, steps 1–5: connect, init, register, convert, assess → `./setup/SKILL.md`
  - **midway-entry** — existing project with source + pre-converted Snowflake SQL (SQL Server / Redshift only) → `./setup/midway-entry/SKILL.md`
  - **data-migration-setup** — configure data migration: orchestrator, worker, workflow, Iceberg → `./setup/data-migration/SKILL.md`
  - **data-validation-setup** — configure cloud data validation: schema, metrics, row-level checks → `./setup/data-validation/SKILL.md`

### Source code: register & convert
- **register-code-units** — router for getting source code into the project → `./register-code-units/SKILL.md`
  - **extract-code-units** — extract DDL/code from a connected source database → `./register-code-units/extract-code-units/SKILL.md`
  - **add-code-units** — import local SQL files into the project → `./register-code-units/add-code-units/SKILL.md`
- **convert** — convert source → Snowflake SQL via SnowConvert (incl. optional Power BI `.pbit` repointing) → `./convert/SKILL.md`
  - **code-conversion-only** — convert local source files for code-conversion-only source systems (incl. optional Power BI `.pbit` repointing) → `./code-conversion-only/SKILL.md`
  - **powerbi-repointing** — collect `.pbit` folder path and `--powerbi-repointing` flag for Power BI repointing → `./powerbi-repointing/SKILL.md`
- **assessment** — analyze workloads: waves, object exclusion, dynamic SQL, ETL → `./assessment/SKILL.md`

### Migration & validation
- **migrate-objects** — deploy tables, views, functions, procedures wave-by-wave → `./migrate-objects/SKILL.md`
  - **baseline-capture** — capture source proc/function output as test baselines → `./migrate-objects/baseline-capture/SKILL.md`
  - **migrate-etl-package** — phase-based ETL package fixer (invoke by name only) → `./migrate-objects/actions/migrate-etl-package/SKILL.md`
- **validate-objects** — validate migrated data between source and Snowflake → `./validate-objects/SKILL.md`

### Rules
- **rule-engine** — search, apply, and manage migration rules → `./migrate-objects/rule-engine/SKILL.md`
  - **extract-rule** — extract a reusable rule from a code fix (interactive or git history) → `./migrate-objects/rule-engine/extract/SKILL.md`
  - **propagate-rule** — find all code units matching a rule for batch application → `./migrate-objects/rule-engine/propagate/SKILL.md`

## Fallback

If no skill matches, say so explicitly, then help with your own knowledge.
</skill-match>


## Rules

1. **Always detect first** — Call `migration_status` before routing
2. **Follow sub-skill instructions** — Complete each sub-skill fully before returning
3. **Confirm transitions** — Ask user before moving to next stage
