---
name: configure-source-connection
description: Optionally set up a connection to the source database (extract DDL, migrate data, run baselines). Routes to per-dialect connection skills or marks the task excluded if the user opts out.
license: Proprietary. See License-Skills for complete terms
---

# Configure source connection

Invoked by the setup state machine after the Snowflake connection is
set. Corresponds to "Step A.5" of the legacy `setup/SKILL.md`.

## What to do

Ask the user:
> "Will you need to connect to your source system? Some common reasons
> are extracting code for conversion, migrating data, and testing
> functional equivalence."
> 1. **Yes** — set up a source connection
> 2. **No** — skip for now (you can set one up later)

If **No**, mark the task excluded by calling:

```
transition_status(machine="setup", task="configureSourceConnection", outcome="excluded")
```

The resolver will then pick `registerCode` as the next task.

If **Yes**, call `configure(needs_source_connection=true)` to list
existing connections for the configured dialect.

- If `existing_connections` listed connections, ask the user to pick
  one.
- Otherwise, load the per-dialect connection sub-skill:
  - `sqlserver` → `../connection/sql-server-connection/SKILL.md`
  - `redshift` → `../connection/redshift-connection/SKILL.md`
  - `oracle` → `../connection/oracle-connection/SKILL.md`
  - `teradata` → `../connection/teradata-connection/SKILL.md`
  - `postgresql` → `../connection/postgresql-connection/SKILL.md`

## On completion

Return to the parent setup skill once the connection is set or the user
has chosen to skip.
