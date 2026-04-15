---
name: setup
description: Set up a migration project — connect to source, initialize, extract objects, convert, and assess. Covers steps 1-5 of the migration lifecycle.
license: Proprietary. See License-Skills for complete terms
---

# Migration Setup

```
⬚ 1. Connect                  - Connect to a source system
⬚ 2. Init                     - Initialize scai project
⬚ 3. Register                 - Register objects for conversion
⬚ 4. Initial Conv             - Convert objects to assess errors
⬚ 5. Assess                   - Run assessments to plan the migration
```

This skill handles the setup phase of a migration. It is invoked by the parent `SKILL.md` router after detecting the project state via `migration_status`.

## Routing

The parent passes the project state. Use `routing` from the status JSON to follow ONE path:

---

### Path A: No Project Exists

**When:** `routing.project_exists` = false

**Step A.1: Ask connection preference**

Ask the user:
> "No migration project found. Would you like to:"
> 1. **Use an existing connection** - Select from configured connections
> 2. **Create a new connection** - Set up a new source database connection

**Step A.2a: If "Use existing connection"**

```bash
scai connection list -l sqlserver 2>/dev/null
scai connection list -l redshift 2>/dev/null
scai connection list -l oracle 2>/dev/null
scai connection list -l teradata 2>/dev/null
```

Present results and ask user to pick. If no connections exist, redirect to "Create new connection".

**Step A.2b: If "Create new connection"**

Ask which source dialect, then load:
- **SQL Server** → `../connection/sql-server-connection/SKILL.md`
- **Redshift** → `../connection/redshift-connection/SKILL.md`
- **Oracle** → `../connection/oracle-connection/SKILL.md`
- **Teradata** → `../connection/teradata-connection/SKILL.md`

**Step A.3: Initialize project**

**IMPORTANT:** `scai init` requires an empty directory.

Ask: "Where would you like to create the migration project?"
- Suggest: `<database>-migration`

```bash
mkdir -p <PROJECT_PATH>
cd <PROJECT_PATH>
scai init -n <PROJECT_NAME> -l <sqlserver|redshift|oracle|teradata>
```

**Flag reference for `scai init`:**
- `-n` — project name (defaults to folder name if omitted)
- `-l` — **source language** (the database you are migrating **from**: `sqlserver`, `redshift`, `oracle`, or `teradata`)
- `-c` — **Snowflake connection** name (the migration **target**, not the source). This is the TOML profile from `~/.snowflake/connections.toml`. Optional — can be set later via `scai project defaults set -c <NAME>`.

**Do NOT pass the source connection name to `-c`.** The source connection is configured separately via `scai project defaults set -s <SOURCE_CONNECTION>` or through the `configure` MCP tool.

**Stay in the project directory** for all subsequent commands.

**Step A.4: Configure project defaults (shared vs local)**

Load `./configure-defaults/SKILL.md`

This prompt must happen after project creation and connection registration so the user can choose:

1. **Shared defaults** in `.scai/config/project.yml` (team/project settings, intended to be committed)
2. **Local defaults** in `.scai/config/project.local.yml` (`--local`, workspace-specific, typically gitignored)
3. **Skip for now**

**Step A.5: Ask about data migration**

**Skip this step for Oracle and Teradata** — data migration is not supported for these sources. Go directly to Step A.6.

For SQL Server and Redshift, ask the user:
> "Will you also need to migrate data from the source database into Snowflake?"
>
> 1. **Yes** — Load `./data-migration/SKILL.md` to configure data migration (orchestrator, worker, workflow). After setup completes, return here and continue to Step A.6.
> 2. **Not now / No** — Continue to Step A.6.

**Step A.6: Register source code**

Load `../register-code-units/SKILL.md`

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
4. **Skip to code conversion** → Load `../migrate-objects/SKILL.md`
5. **Set up data migration** (SQL Server and Redshift only) → Load `./data-migration/SKILL.md`

---

## Sub-Skills Reference

| Stage | Sub-skill | Location |
|-------|-----------|----------|
| 1 | sql-server-connection | `../connection/sql-server-connection/SKILL.md` |
| 1 | redshift-connection | `../connection/redshift-connection/SKILL.md` |
| 1 | oracle-connection | `../connection/oracle-connection/SKILL.md` |
| 1 | teradata-connection | `../connection/teradata-connection/SKILL.md` |
| 2 | configure-defaults | `./configure-defaults/SKILL.md` |
| 3 | register-code-units | `../register-code-units/SKILL.md` |
| 4 | convert | `../convert/SKILL.md` |
| 5 | snowconvert-assessment | `../assessment/SKILL.md` |
| — | data-migration-setup | `./data-migration/SKILL.md` |

## Rules

1. **Follow sub-skill instructions** — Complete each sub-skill fully before returning
2. **Confirm transitions** — Ask user before moving to next stage
