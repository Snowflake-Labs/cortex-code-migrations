---
name: configure-snowflake-connection
description: Confirm or set the Snowflake connection name and target database for the migration. Persists via `configure(snowflake_connection=…, snowflake_database=…)`.
license: Proprietary. See License-Skills for complete terms
---

# Configure Snowflake connection

Invoked by the setup state machine after the source dialect is chosen
and `config.snowflakeConnection` is not yet set. Corresponds to
"Step A.4" of the legacy `setup/SKILL.md`.

## What to do

If a `snowflake_connection` is already attached to the active SQL
session, confirm it with the user:

> The active Snowflake connection is `<name>`. Use it for this
> migration?

Otherwise ask the user to provide a connection name that resolves
through `cortex connections list`. Once confirmed, call
`configure(snowflake_connection=<name>)`.

## Set the target database

Ask the user which database to deploy migrated objects to, then verify
it exists:

```sql
SHOW DATABASES LIKE '<db>';
```

If empty, ask before creating:

> Database `<db>` does not exist. Create it?

On confirmation, run `CREATE DATABASE IF NOT EXISTS <db>`. If declined,
ask for a different name and re-check.

Once the database exists, call `configure(snowflake_database=<db>)`.

## On completion

Return to the parent setup skill. The resolver will pick the next task.
