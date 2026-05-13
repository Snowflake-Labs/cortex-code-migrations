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

Use `routing` from `migration_status()` tool output to follow ONE path:

---

### Path A: No Project Exists

**When:** `routing.project_exists` = false

**Step A.1: Configure project directory**

Use `directory_empty` from the `migration_status` response:

- If `directory_empty` is **false**, tell the user:
  > This directory isn't empty, so we can't initialize a project here. Would you like to create one in a new subdirectory?

  Suggest `<current_dir>/<database>-migration` or let the user pick. Once confirmed, call `configure(project_dir=<new_path>)`.

- If `directory_empty` is **true**, confirm with the user:
  > I'll use `<project_dir>` for the migration project. Can you confirm?

  If the user wants a different location, call `configure(project_dir=<new_path>)`. Otherwise, continue with the configured `<project_dir>`.

**Step A.2: Choose source dialect**

**Source dialect** — if `source_language` is not set yet, use `ask_user_question` (`multiSelect = false`):
   > "What source database system are you migrating from?"
   > 1. **SQL Server**
   > 2. **Redshift**
   > 3. **Teradata**
   > 4. **Oracle**

These are the 4 key workstreams, but the user might choose "Something else".

Match the response to this table:

| User choice | `source_language` |
|-------------|-------------------|
| SQL Server | `SqlServer` |
| Redshift | `Redshift` |
| Teradata | `Teradata` |
| Oracle | `Oracle` |
| Sybase IQ | `Sybase` |
| Azure Synapse | `synapse` |
| Spark SQL | `Spark` |
| Databricks SQL | `Databricks` |
| BigQuery | `BigQuery` |
| PostgreSQL | `Postgresql` |
| Greenplum | `Greenplum` |
| Netezza | `Netezza` |
| Vertica | `Vertica` |
| Hive | `Hive` |
| IBM DB2 | `Db2` |

Call `configure(source_language=<chosen dialect>)` to initialize the project and return routing metadata.

The `configure` response includes **user_overview** and `project_type` — YOU MUST present this ENTIRELY and EXACTLY to the user before moving on. DO NOT synthesize, just print it for the user.

If the latest `configure` response showed `project_type: code_conversion_only`, load `../code-conversion-only/SKILL.md`. **DO NOT GO TO ANY OTHER STEP**.

If the latest `configure` response showed `project_type: full_migration`, continue to Step A.3.

**Step A.3: Choose entry mode**

Ask the user:
> "Are you starting a new migration, or do you already have source SQL **and** pre-converted Snowflake SQL?"
> 1. **Starting fresh** — continue with the steps below
> 2. **Existing migration** — load `./midway-entry/SKILL.md` (SQL Server and Redshift only, Teradata and Oracle coming soon)

If the user picks **Existing migration**, load `./midway-entry/SKILL.md` and stop here. Otherwise continue.

**Step A.4: Configure Snowflake connection**

If `snowflake_connection` is not set, confirm with the user that the active SQL connection should be used for Snowflake queries. Once confirmed, call `configure(snowflake_connection=<name>)`.

**Step A.5: Set up source connection**

Ask the user:
> "Will you need to connect to your source system? Some common reasons are extracting code for conversion, migrating data, and testing functional equivalence."
> 1. **Yes** — set up a source connection
> 2. **No** — skip for now (you can set one up later)

If **No** → skip to Step A.6.

Call `configure(needs_source_connection=true)` to list existing source connections for the configured dialect.

If `existing_connections` listed connections, ask:
> "Would you like to:"
> 1. **Use an existing connection** — Select from the connections listed above
> 2. **Create a new connection** — Set up a new source database connection

If `existing_connections` was `none`, go directly to "Create new connection".

**Step A.5a: If "Use existing connection"**

Present the connections returned by `configure` and ask user to pick.

**Step A.5b: If "Create new connection"**

Load the connection sub-skill for `<SOURCE_DIALECT>`:
- `sqlserver` → `../connection/sql-server-connection/SKILL.md`
- `redshift` → `../connection/redshift-connection/SKILL.md`
- `oracle` → `../connection/oracle-connection/SKILL.md`
- `teradata` → `../connection/teradata-connection/SKILL.md`

**Step A.6: Ask about data migration and validation**

Ask the user:
> "Will you also need to migrate data from the source database into Snowflake?"
>
> 1. **Yes — configure shared data infrastructure now** — Read `./data-infrastructure/SKILL.md` and follow the instructions. Afterwards, continue to Step A.7.
> 2. **No** — Continue to Step A.7.

**Step A.7: Register source code**

Load `../register-code-units/SKILL.md`. When registration completes, return here and continue to Step A.8.

**Step A.8: Convert source code**

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
5. **Set up data migration and validation** → Load `./data-infrastructure/SKILL.md`

---

## Sub-Skills Reference

| Stage | Sub-skill | Location |
|-------|-----------|----------|
| 1 | sql-server-connection | `../connection/sql-server-connection/SKILL.md` |
| 1 | redshift-connection | `../connection/redshift-connection/SKILL.md` |
| 1 | oracle-connection | `../connection/oracle-connection/SKILL.md` |
| 1 | teradata-connection | `../connection/teradata-connection/SKILL.md` |
| — | midway-entry (existing project with pre-converted code; SQL Server/Redshift only) | `./midway-entry/SKILL.md` |
| 3 | register-code-units | `../register-code-units/SKILL.md` |
| 4 | convert | `../convert/SKILL.md` |
| 4 | code-conversion-only | `../code-conversion-only/SKILL.md` |
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
