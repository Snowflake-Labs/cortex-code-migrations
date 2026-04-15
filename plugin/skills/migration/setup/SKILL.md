---
name: setup
description: Set up a migration project — connect to source, initialize, extract objects, convert, and assess. Covers steps 1-5 of the migration lifecycle.
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
```

Present results and ask user to pick. If no connections exist, redirect to "Create new connection".

**Step A.2b: If "Create new connection"**

Ask which source dialect, then load:
- **SQL Server** → `../connection/sql-server-connection/SKILL.md`
- **Redshift** → `../connection/redshift-connection/SKILL.md`

**Step A.3: Initialize project**

**IMPORTANT:** `scai init` requires an empty directory.

Ask: "Where would you like to create the migration project?"
- Suggest: `<database>-migration`

```bash
mkdir -p <PROJECT_PATH>
cd <PROJECT_PATH>
scai init -n <PROJECT_NAME> -l <sqlserver|redshift>
```

**Stay in the project directory** for all subsequent commands.

**Step A.4: Register source code**

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
1. **Run assessment** → Load `../snowconvert-assessment/SKILL.md`
2. **Re-convert** → Load `../convert/SKILL.md`
3. **Review converted** → Show contents of `snowflake/` and `artifacts/`
4. **Skip to code conversion** → Load `../migrate-objects/SKILL.md`

---

## Sub-Skills Reference

| Stage | Sub-skill | Location |
|-------|-----------|----------|
| 1 | sql-server-connection | `../connection/sql-server-connection/SKILL.md` |
| 1 | redshift-connection | `../connection/redshift-connection/SKILL.md` |
| 3 | register-code-units | `../register-code-units/SKILL.md` |
| 4 | convert | `../convert/SKILL.md` |
| 5 | snowconvert-assessment | `../snowconvert-assessment/SKILL.md` |

## Rules

1. **Follow sub-skill instructions** — Complete each sub-skill fully before returning
2. **Confirm transitions** — Ask user before moving to next stage
