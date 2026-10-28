# Database Migration to Snowflake

## Working with the MCP state machine

The built-in MCP server runs a state machine that guides you through user flows and will ask you to "tell the user x" or "ask the user y". This is expected — follow its lead. It is the official MCP server of Snowflake migrations.

## Install check

Before the first tool call of this flow, run `scai doctor`. Exit 0: continue. Any other exit: stop, show the output, and do not call `configure`, `progress_setup`, or `migration_status`. If the `doctor` command is missing, this scai predates the check — continue; SessionStart already gated the install.

## Step 1: Detect current state

Call `migration_status`. It returns JSON with `project_exists`, `directory_empty`, `by_type`, `stage_totals`, `routing`, and `highest_stage_reached`.

**If `project_exists` is false**, this is a new project — go to the setup skill `setup/SKILL.md` (read it under the skills root given in `<migration-skills>`).

**If `project_exists` is true**, give the user a brief prose summary of where the migration stands, built from the `routing` booleans and `by_type` counts. The UI panel already shows the stage-by-stage numbers, so your job is the sentence the panel cannot write: what phase this project is in and what stands out. Aim for this level of detail:

- **Early setup:** "Your project is initialized and connected to SQL Server. 147 objects are registered but haven't been converted yet — we're still in the setup phase."
- **Mid-migration:** "Setup is complete and assessment is done. You're in the migration phase: of the 47 objects in Wave 2, 12 are deployed so far."
- **Near completion:** "Almost there — 45 of 47 objects are deployed and tested. 2 procedures are still failing tests."

Then go to Step 2.

Reading `by_type` correctly matters:

- **Type absent** (`total` absent or 0): don't mention it. A project with no functions has no function story.
- **Type present but not in the current wave** (`total` > 0, wave-scoped counts absent or 0): acknowledge it anyway — e.g. "you also have 1 Informatica ETL workflow staged for a later wave." Don't let the current wave hide work that exists elsewhere in the project.
- **A wave is active** (`wave` present): `in_scope`, `objects_done` and every `stage_totals` count are that wave only; `total_objects` and `by_type.<type>.total` are project-wide. Name the wave and `in_scope_all_waves` whenever you quote them — "69 objects in wave 1, of 1,110 in scope across all waves" — never report a wave's count as the project's.
- Never describe a project as "<type>-only" (e.g. "table-only") when `by_type` lists any other type with `total` > 0.
- Counts that never incremented are absent from the JSON — treat them as 0.
- **BTEQ scripts have no deploy step.** They run their converted SQL inside the test itself, so report them only by `tested`, never "deployed"; `by_type.bteq` carries no `deployed` count.

## Step 2: Ask the user

> "What would you like to do? You can:
> 1. **Continue with migration plan** — I'll start or pick up where we left off
> 2. **Something specific** — tell me what you need"

If the user picks **Continue** (or says "continue", "next", etc.) → **Prescribed Path**.
If the user describes a **specific request** → **Skill Match**.

---

## Prescribed Path

<prescribed-path>
**Missing Snowflake connection:** when the status JSON has `snowflake_connection_missing`, the project's Snowflake connection (`name`) is not defined on this machine, so nothing that touches Snowflake can run. Do not route on. Ask the user which of `available` to use instead, or whether to create a new one (load `./connection/snowflake-connection/SKILL.md`), then call `configure(snowflake_connection=<their choice>)` and run `migration_status` again.

Use `routing` from the status JSON to delegate to the next step:

| Condition | Sub-skill |
|-----------|-----------|
| `routing.project_exists` = false | Load `./setup/SKILL.md` |
| `routing.data_validation_only` = true | Load `./validate-objects/SKILL.md` |
| `routing.code_conversion_only` = true | Load `./code-conversion-only/SKILL.md` |
| `routing.assessed` = false | Load `./setup/SKILL.md` |
| `routing.assessed` = true | Load `./migrate-objects/SKILL.md` |

Each sub-skill handles its own internal routing based on the full `routing` object.
</prescribed-path>

---

## State Queries

These answer common questions about project state without loading a sub-skill:

- **"What is the current state?"** — Call `migration_status(mode="summary")` and give the prose summary described in Step 1.
- **"What should I work on next?"** — Call `migration_status(mode="my_objects_summary")` to get per-`(task, object_type)` counts plus `errored_count` and `done_count`. Present the list and **ask the user what they want to work on — do not pick for them**. When the user picks a group, drill down with `migration_status(mode="my_objects_details", group=<id>)`.
- **"Show me objects that match rule X"** — Load `migrate-objects/rule-engine/propagate/SKILL.md`.
- **"Can I change conversion settings?"** / **"I picked defaults but need a conversion flag"** — Load `convert/SKILL.md` → "Changing Conversion Settings Later". The same project keeps working: no new project or re-import.
- **"How do I extend / customize the migration plugin?"** / **"How do I override task X?"** — Load `extensibility/TASKS.md` for the full reference: overridable task ids, per-task contracts, and the project-local + `$AIM_SKILL_EXT_DIR` paths. Optionally call `migration_status(mode='extensions')` to show which overrides are active.

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
  - **midway-entry** — existing project with source + pre-converted Snowflake SQL (SQL Server / Redshift only) → `./setup/midway-entry.md`
  - **configure-snowflake-target** — set or change the Snowflake connection and target database for object migration. Triggers: "change the target database", "deploy to a different database", "switch Snowflake connection" → `./setup/configure-snowflake-target.md`
  - **snowflake-connection** — create or repair a Snowflake target authenticator. Use for Microsoft Entra ID / Azure AD / OIDC (`oauth_authorization_code`); do not use `externalbrowser` for Entra → `./connection/snowflake-connection/SKILL.md`
  - **configure-testing** — pick or change the testing path (source-data vs synthetic) for procedure/function equivalence tests. Triggers: "change testing path", "switch to synthetic tests", "use query logs" → `./setup/configure-testing.md`
  - **data-validation-setup** — configure cloud data validation: schema, metrics, row-level checks → `./setup/data-validation/SKILL.md`
    - **l3-pushdown-setup** — L3 signature extract via object storage (faster) + Snowflake external stage; wait if they still need a bucket. Triggers: "L3 pushdown", "UNLOAD for validation", "external stage for DV", "S3/GCS bucket for row validation" → `./setup/data-validation/l3-pushdown/SKILL.md`
  - **data-infrastructure-teardown** — suspend SPCS service + compute pool, stop local worker (cost-saving) → `./data-infrastructure/teardown/SKILL.md`

### Data infrastructure (reusable actions)
- **data-infrastructure** — shared infrastructure for data migration and validation: compute pools, workers, network access → `./data-infrastructure/SKILL.md`
  - **worker-local-setup** — install and start the worker on a user-managed machine (laptop, VM, or on-prem) → `./data-infrastructure/worker-local-setup/SKILL.md`
  - **budget-guardrail** — cap SPCS / hybrid spend: one Snowflake Budget over the warehouse and compute pool that suspends both at a threshold; runs before the first `up` on SPCS. Triggers: "cap spend", "budget", "stop overspending" → `./data-infrastructure/budget-guardrail/SKILL.md`

### Source code: register & convert
- **register-code-units** — router for getting source code into the project → `./register-code-units/SKILL.md`
  - **extract-code-units** — extract DDL/code from a connected source database → `./register-code-units/extract-code-units/SKILL.md`
  - **add-code-units** — import local SQL files into the project → `./register-code-units/add-code-units/SKILL.md`
- **convert** — convert source → Snowflake SQL (incl. optional Power BI `.pbit` and Tableau `.twb`/`.tds` repointing) → `./convert/SKILL.md`
  - **code-conversion-only** — convert local source files for code-conversion-only source systems (incl. optional Power BI `.pbit` repointing) → `./code-conversion-only/SKILL.md`
  - **powerbi-repointing** — collect `.pbit` folder path and `--powerbi-repointing` flag for Power BI repointing → `./powerbi-repointing/SKILL.md`
  - **tableau-repointing** — collect `.twb`/`.tds` folder path and `--tableauRepointing` flag for Tableau repointing. Triggers: tableau, tableau migration, tableau repointing, migrate tableau, repoint tableau → `./tableau-repointing/SKILL.md`
  - **dbt-consolidation** — before SSIS or Informatica dbt conversion, ask one question about consolidating projects and models by package/folder, consolidating SSIS into one dbt project, or retaining the per-Data-Flow/per-mapping layout; use `--consolidate-dbt-projects`, or `--consolidate-as-single-dbt-project` for the SSIS-only single-project choice → `./dbt-consolidation/SKILL.md`
- **assessment** — analyze workloads: waves, object exclusion, dynamic SQL, ETL → `./assessment/SKILL.md`

### Migration & validation
- **migrate-objects** — deploy tables, views, functions, procedures wave-by-wave → `./migrate-objects/SKILL.md`
  - **migrate-etl** — claim an ETL code unit, then stabilize it. Entry point for "fix ETL package", "fix SSIS/Informatica conversion", "proceed with stabilization", "resume ETL fixing" — it claims the unit (so it appears in `my_objects_summary` with the current user as owner) before delegating to the phase-based etl-stabilization engine. → `./migrate-objects/migrate-etl/SKILL.md`
  - **data-migration-setup** — choose approach, generate workflow YAML, create target database for `migrate_data` → `./migrate-objects/actions/data-migration/SKILL.md`
  - **testbed-generator** — bootstrap coupling state (`generateTestbed`); generate one table's CSV (`INCREMENTAL.md`); or mine/validate/enrich/compile/generate the whole workload (`WHOLE-WORKLOAD.md`). Triggers: generate testbed, mine testbed, validate testbed, compile testbed, enrich testbed, testbed data source → `./migrate-objects/baseline-capture/testbed-generator/SKILL.md`
- **validate-objects** — validate data between a source and Snowflake, including project-based Snowflake-to-Snowflake validation. Triggers: "validate Snowflake to Snowflake", "compare Snowflake tables/databases", "run SF-to-SF DV" → `./validate-objects/SKILL.md`
  - **l3-pushdown-setup** — configure L3 extract transport (object storage vs through the worker) before row validation runs → `./setup/data-validation/l3-pushdown/SKILL.md`

### Object metadata
- **tag-objects** — tag or untag code units with the user's own labels (`extensions.tags`), and find objects by tag. Tags render as chips on the object rows in the Objects panel. Triggers: "tag this table", "label these objects", "untag", "which objects are tagged" → `./tag-objects/SKILL.md`

### Rules
- **rule-engine** — search, apply, and manage migration rules → `./migrate-objects/rule-engine/SKILL.md`
  - **extract-rule** — extract a reusable rule from a code fix (interactive or git history) → `./migrate-objects/rule-engine/extract/SKILL.md`
  - **propagate-rule** — find all code units matching a rule for batch application → `./migrate-objects/rule-engine/propagate/SKILL.md`

### Customization
- **task-overrides** — replace the skill that runs for any built-in task with the user's own `SKILL.md`, scoped to the project or to a global directory via `$AIM_SKILL_EXT_DIR`. Triggers: "extend the plugin", "customize task X", "swap out the skill for Y", "override registerCode/convertCode/deploy/...". Reference: `./extensibility/TASKS.md`

## Fallback

If no skill matches, say so explicitly, then help with your own knowledge.
</skill-match>

## Rules

1. **Detect migration state first** — call `migration_status` before routing. Snowflake-to-Snowflake validation uses a Snowflake-source project and follows the same project state flow.
2. **Follow sub-skill instructions** — complete each sub-skill fully before returning.
3. **Confirm transitions through the machine** — stage gates arrive as MCP prompts (`continueToMigration`, `chooseRunMode`); ask those when they come rather than adding a confirmation turn between sub-skills, and ask before loading migrate-objects after setup completes.
4. **Diagnose against the source before retrying or touching shared infrastructure** — when a step fails, reproduce it first: run the failing statement (from the error, or the task's `statement` in the worker's `data_exchange_agent.log` under scai's `logs/data/`) with `query_source`, and check any theory (a version mismatch, a missing file) against what the tools report before acting on it. Never re-dispatch an unchanged workflow to see whether it fails again, and never update, recreate or restart the orchestrator, worker or compute pool to test a guess: they are shared by every project on the account. Change them only with evidence that they are the cause, after the user agrees with who else it affects named. Until the cause is found, say what you checked and that you don't know yet; never "not your setup" when the setup is what you haven't ruled out.
5. **Say what the product can't do** — when no supported setting does what the user asked, say so plainly before acting and offer what is possible. Never build the nearest thing and report the request as done.
6. **Switch to manual only when the user asks** — when the user asks to go manual, work interactively or stop running autonomously, confirm with them, then call `configure(subagent_mode=false)` from this session (never from a subagent). Between waves it switches the project back to manual for this and every later session. While walkers are running or objects are still claimed it is refused, naming them: tell the user, and offer to let the wave finish first. Never change the mode on your own initiative.
