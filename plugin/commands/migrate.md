---
description: SnowConvert migrations helper
allowed-tools: Bash(open:*)
---

Help me using the reference skills below.

$ARGUMENTS

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
  - **data-validation-setup** — configure cloud data validation: schema, metrics, row-level checks → `./setup/data-validation/SKILL.md`
  - **data-infrastructure-teardown** — suspend SPCS service + compute pool, stop local worker (cost-saving) → `./data-infrastructure/teardown/SKILL.md`

### Data infrastructure (reusable actions)
- **data-infrastructure** — shared infrastructure for data migration and validation: compute pools, workers, network access → `./data-infrastructure/SKILL.md`
  - **worker-local-setup** — install and start the worker on a user-managed machine (laptop, VM, or on-prem) → `./data-infrastructure/worker-local-setup/SKILL.md`

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
  - **etl-stabilization** — phase-based ETL package fixer (invoke by name only) → `./migrate-objects/actions/etl-stabilization/SKILL.md`
  - **data-migration-setup** — choose approach, generate workflow YAML, create target database for `migrate_data` → `./migrate-objects/actions/data-migration/SKILL.md`
- **validate-objects** — validate migrated data between source and Snowflake → `./validate-objects/SKILL.md`

### Rules
- **rule-engine** — search, apply, and manage migration rules → `./migrate-objects/rule-engine/SKILL.md`
  - **extract-rule** — extract a reusable rule from a code fix (interactive or git history) → `./migrate-objects/rule-engine/extract/SKILL.md`
  - **propagate-rule** — find all code units matching a rule for batch application → `./migrate-objects/rule-engine/propagate/SKILL.md`

### Customization
- **task-overrides** — replace the skill that runs for any built-in task with the user's own `SKILL.md`, scoped to the project or to a global directory via `$AIM_SKILL_EXT_DIR`. Triggers: "extend the plugin", "customize task X", "swap out the skill for Y", "override registerCode/convertCode/deploy/...". Reference: `./extensibility/TASKS.md`

## Fallback

If no skill matches, say so explicitly, then help with your own knowledge.
</skill-match>
