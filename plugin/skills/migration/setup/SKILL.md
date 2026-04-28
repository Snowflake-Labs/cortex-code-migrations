---
name: setup
description: Set up a migration project — connect to source, initialize, extract objects, convert, and assess. Covers steps 1-5 of the migration lifecycle.
license: Proprietary. See License-Skills for complete terms
---

# Migration Setup

## On Entry

Tell the user:
> **Phase 1: Setup** — I'll walk you through connecting to your source database, initializing the project, registering your objects, converting them to Snowflake SQL, and generating an assessment report.

## Routing

Use `routing` from the migration_status tool output to follow ONE path:

---

### Path A: No Project Exists

**When:** `routing.project_exists` = false

**Step A.1: Ask about source connection**

Ask the user:
> "Will you need to connect to your source system? Some common reasons are extracting code for conversion, migrating data, and testing functional equivalence."
> 1. **Yes** — set up a source connection
> 2. **No** — skip for now (you can set one up later)

If **No** → skip to Step A.3.

**Step A.2: Set up source connection**

Call `configure(needs_source_connection=true)` to list existing source connections for the configured dialect.

If `existing_connections` listed connections, ask:
> "Would you like to:"
> 1. **Use an existing connection** — Select from the connections listed above
> 2. **Create a new connection** — Set up a new source database connection

If `existing_connections` was `none`, go directly to "Create new connection".

**Step A.2a: If "Use existing connection"**

Present the connections returned by `configure` and ask user to pick.

**Step A.2b: If "Create new connection"**

Load the connection sub-skill for `<SOURCE_DIALECT>`:
- `sqlserver` → `../connection/sql-server-connection/SKILL.md`
- `redshift` → `../connection/redshift-connection/SKILL.md`
- `oracle` → `../connection/oracle-connection/SKILL.md`
- `teradata` → `../connection/teradata-connection/SKILL.md`

**Step A.3: Configure project defaults (shared vs local)**

Load `./configure-defaults/SKILL.md`

This prompt must happen after project creation and connection registration so the user can choose:

1. **Shared defaults** in `.scai/config/project.yml` (team/project settings, intended to be committed)
2. **Local defaults** in `.scai/config/project.local.yml` (`--local`, workspace-specific, typically gitignored)
3. **Skip for now**

**Step A.4: Ask about data migration and validation**

**Skip this step if `<SOURCE_DIALECT>` is `oracle` or `teradata`** — data migration is not supported for these sources. Go directly to Step A.5.

For `sqlserver` and `redshift`, ask the user:
> "Will you also need to migrate data from the source database into Snowflake?"
>
> 1. **Yes — set up data migration and data validation** — First load `./data-infrastructure/SKILL.md` to configure shared infrastructure (compute pool, worker config, source database/schema). Then load `./data-migration/SKILL.md` for migration-specific setup (approach, workflow config, target database). Then load `./data-validation/SKILL.md` for validation-specific setup (scope, validation config, service verification). After all three complete, return here and continue to Step A.5.
> 2. **Yes — set up data migration only** — First load `./data-infrastructure/SKILL.md` to configure shared infrastructure. Then load `./data-migration/SKILL.md` for migration-specific setup. After setup completes, return here and continue to Step A.5.
> 3. **No** — Continue to Step A.5.

**Step A.5: Register source code**

Go to Path B: Project Exists, No Source Code

**Step A.6: Convert source code**

Load `../convert/SKILL.md`

---

### Path B: Project Exists, No Source Code

**When:** `routing.registered` = false

Load `../register-code-units/SKILL.md`

---

### Path C: Source Code Exists, Not Converted

**When:** `routing.registered` = true AND `routing.converted` = false

Offer options:
1. **Register more** → Load `../register-code-units/SKILL.md`
2. **Convert** → Load `../convert/SKILL.md`
3. **Review source** → Show contents of `source/`

---

### Path D: Converted Code Exists, No Assessment

**When:** `routing.converted` = true AND `routing.assessed` = false

Offer options:
1. **Run assessment** → Load `../assessment/SKILL.md`
2. **Re-convert** → Load `../convert/SKILL.md`
3. **Review converted** → Show contents of `snowflake/` and `artifacts/`
4. **Skip to migrate objects** → Load `../migrate-objects/SKILL.md`
5. **Set up data migration** → Load `./data-infrastructure/SKILL.md` first, then `./data-migration/SKILL.md`
6. **Set up data validation** → Load `./data-infrastructure/SKILL.md` first (no-op if already configured), then `./data-validation/SKILL.md`

---

## Sub-Skills Reference

| Stage | Sub-skill | Location |
|-------|-----------|----------|
| 1 | sql-server-connection | `../connection/sql-server-connection/SKILL.md` |
| 1 | redshift-connection | `../connection/redshift-connection/SKILL.md` |
| 1 | oracle-connection | `../connection/oracle-connection/SKILL.md` |
| 1 | teradata-connection | `../connection/teradata-connection/SKILL.md` |
| 2 | configure-defaults | `./configure-defaults/SKILL.md` |
| — | midway-entry (existing project with pre-converted code; SQL Server/Redshift only) | `./midway-entry/SKILL.md` |
| 3 | register-code-units | `../register-code-units/SKILL.md` |
| 4 | convert | `../convert/SKILL.md` |
| 5 | snowconvert-assessment | `../assessment/SKILL.md` |
| — | data-infrastructure-setup | `./data-infrastructure/SKILL.md` |
| — | data-migration-setup | `./data-migration/SKILL.md` |
| — | data-validation-setup | `./data-validation/SKILL.md` |

## Rules

1. **Follow sub-skill instructions** — Complete each sub-skill fully before returning
2. **Confirm transitions** — Ask user before moving to next stage

## On Completion

When all setup paths have been exhausted (the user has reached `routing.assessed = true` or chosen to skip to migrate-objects), tell the user:
> **Setup complete** — Your migration project is configured: connected to <source_type>, <N> objects registered, code converted, and assessment generated. Ready to start migrating objects to Snowflake.

Then return to the parent migration skill.
