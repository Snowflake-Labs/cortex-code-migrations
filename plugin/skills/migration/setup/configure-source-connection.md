---
name: configure-source-connection
description: Optionally set up a connection to the source database (extract DDL, migrate data, run baselines). Routes to per-dialect connection skills, defers the question for later, or marks the task excluded if the user opts out permanently.
license: Proprietary. See License-Skills for complete terms
---

# Configure source connection

Invoked by the setup state machine after the Snowflake connection is
set. Also re-invoked from `seedSourceDb` / `migrateData` when their
prereq isn't met.

## What to do

Ask the user:
> "Will you need to connect to your source system? Some common reasons
> are extracting code for conversion, migrating data, and testing
> functional equivalence."
> 1. **Yes** — set up a source connection now
> 2. **Skip for now** — keep the option open; I'll re-ask before tests-from-source or data migration
> 3. **Never** — won't need a source connection; use synthetic test data only

### If **Yes**

Call `configure(needs_source_connection=true)` to list existing
connections for the configured dialect.

- If `existing_connections` listed connections, ask the user to pick
  one.
- Otherwise, load the per-dialect connection sub-skill:
  - `sqlserver` → `../connection/sql-server-connection/SKILL.md`
  - `redshift` → `../connection/redshift-connection/SKILL.md`
  - `oracle` → `../connection/oracle-connection/SKILL.md`
  - `teradata` → `../connection/teradata-connection/SKILL.md`
  - `postgresql` → `../connection/postgresql-connection/SKILL.md`

### If **Skip for now**

Transient for this walk only:

```
progress_setup(mode="setup", skip="configureSourceConnection")
```

The next `progress_setup()` (or a later re-entry from `seedSourceDb` /
`migrateData`) may offer source-connection setup again.

### If **Never**

Permanent opt-out — persists to `.scai/config/plugin.yml`:

```
configure(tasks={"configureSourceConnection": {"enabled": false}})
```

## On completion

Return to the parent setup skill once the connection is set or the user
has chosen Skip / Never.
