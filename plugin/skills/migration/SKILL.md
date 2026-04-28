---
name: migration
description: End-to-end database migration to Snowflake. Orchestrates the full migration lifecycle from source connection through initial conversion. Triggers: migrate, migration, migrate to snowflake, end to end migration, e2e migration, full migration.
license: Proprietary. See License-Skills for complete terms
---

# Database Migration to Snowflake

Tell the user:
> **Welcome to the Snowflake Migrations plugin.** Let me get started by configuring your session.

## Step 0: Configure Session

Call `configure` with `project_dir` (use the current directory, or ask the user). If a saved config is found, the response shows all restored values — proceed to Step 1.

## Step 1: Detect Current State

Call the `migration_status` tool. It returns JSON with `project_exists`, `directory_empty`, `by_type`, `stage_totals`, `routing`, and `highest_stage_reached` fields.

If `project_exists` is false, this is a new project. Handle the following in order:

1. **Directory check** — use `directory_empty` from the response:
   - If `directory_empty` is **false** — tell the user:
     > This directory isn't empty, so we can't initialize a project here. Would you like to create one in a new subdirectory?

     Suggest `<current_dir>/<database>-migration` or let the user pick. Once confirmed, call `configure(project_dir=<new_path>)`.

   - If `directory_empty` is **true** — confirm with the user:
     > I'll initialize the migration project in `<project_dir>`. Can you confirm?

     If the user wants a different location, call `configure(project_dir=<new_path>)`.

2. **Source dialect** — if `source_language` is not set in the Step 0 configure response, ask:
   > "What source database system are you migrating from?"
   > 1. **SQL Server**
   > 2. **Redshift**
   > 3. **Teradata**
   > 4. **Oracle**
   > 5. **Something else**

   Call `configure(source_language=<chosen dialect>)`. The response includes **user_overview** — YOU MUST present this ENTIRELY and EXACTLY to the user before moving on. DO NOT synthesize, just print it for the user.

3. Ask the user:
   > "Are you starting a new migration, or do you already have source SQL **and** pre-converted Snowflake SQL?"
   > 1. **Starting fresh** — continue with the steps below
   > 2. **Existing migration** — load `./setup/midway-entry/SKILL.md` (SQL Server and Redshift only, Tedata and Oracle coming soon)

   If the user picks **midway entry**, load `./setup/midway-entry/SKILL.md` and stop here. Otherwise continue.

4. **Snowflake connection** — if `snowflake_connection` is not set, confirm with the user that the active SQL connection should be used for Snowflake queries. Once confirmed, call `configure(snowflake_connection=<name>)`.

Then go directly to `./setup/SKILL.md`. DO NOT go to Step 2.

If `project_exists` is true, construct a brief narrative summary for the user from the JSON before showing the checklist. Use the `routing` booleans and `by_type` counts to describe the current state in plain language. Examples of the tone and level of detail:

- **Early setup:** "Your project is initialized and connected to SQL Server. 147 objects are registered but haven't been converted yet. We're in the setup phase."
- **Mid-migration:** "Setup is complete — 147 objects registered and converted, assessment done. You're in the migration phase: 12 of 47 objects have been deployed so far (Wave 2). 8 tables deployed, 2 views deployed, 2 procedures passed testing."
- **Near completion:** "Almost there — 45 of 47 objects are deployed and tested. 2 procedures are still failing tests."

Follow the summary with the progress checklist (see below), then go to Step 2.

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
<symbol> 6. Migrate Objects          - <table.deployed>/<table.total> tables, <view.deployed>/<view.total> views, <func+proc deployed>/<func+proc total> funcs/procs deployed; <table.data_migrated>/<table.total> data migrated; <table.validated>/<table.total> validated; <func+proc tested>/<func+proc total> tested
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

- **"What is the current state?"** — Call `migration_status`, construct the narrative summary (as in Step 1), and present the progress checklist.
- **"What should I work on next?"** — Call `next_object` to get the next dependency-ready object, or call `testing_progress` for a full summary.
- **"Show me objects that match rule X"** — Load `./migrate-objects/rule-engine/propagate/SKILL.md`.

---

## Skill Match

Match the user's request to the most relevant skill below and load it. If the request is ambiguous, ask a clarifying question. If no skill matches, say so and offer the prescribed path instead.

| Skill | Description | Location |
|-------|-------------|----------|
| setup | Connect, init project, register, convert, assess (steps 1-5) | `./setup/SKILL.md` |
| midway-entry | Bring an existing project (source + pre-converted Snowflake SQL) into scai. SQL Server / Redshift only | `./setup/midway-entry/SKILL.md` |
| register-code-units | Register source code (extract from DB or add local files) | `./register-code-units/SKILL.md` |
| extract-code-units | Extract DDL/code from a connected source database | `./register-code-units/extract-code-units/SKILL.md` |
| add-code-units | Import local SQL files into the project | `./register-code-units/add-code-units/SKILL.md` |
| convert | Convert source code to Snowflake SQL via SnowConvert | `./convert/SKILL.md` |
| assessment | Analyze workloads — waves, object exclusion, dynamic SQL, ETL | `./assessment/SKILL.md` |
| data-migration-setup | Configure data migration — orchestrator, worker, workflow, Iceberg | `./setup/data-migration/SKILL.md` |
| data-validation-setup | Configure cloud data validation — schema, metrics, row-level checks | `./setup/data-validation/SKILL.md` |
| migrate-objects | Deploy all object types wave-by-wave (tables, views, functions, procedures) | `./migrate-objects/SKILL.md` |
| validate-objects | Validate migrated data between source and Snowflake | `./validate-objects/SKILL.md` |
| baseline-capture | Capture source proc/function output as test baselines | `./migrate-objects/baseline-capture/SKILL.md` |
| rule-engine | Search, apply, extract, propagate, and manage migration rules | `./migrate-objects/rule-engine/SKILL.md` |
| extract-rule | Extract a reusable rule from a code fix (interactive or git history) | `./migrate-objects/rule-engine/extract/SKILL.md` |
| propagate-rule | Find all code units matching a rule for batch application | `./migrate-objects/rule-engine/propagate/SKILL.md` |
| migrate-etl-package | Phase-based ETL package fixer — invoke by name only | `./migrate-objects/actions/migrate-etl-package/SKILL.md` |


## Rules

1. **Always detect first** — Call `migration_status` before routing
2. **Follow sub-skill instructions** — Complete each sub-skill fully before returning
3. **Confirm transitions** — Ask user before moving to next stage
