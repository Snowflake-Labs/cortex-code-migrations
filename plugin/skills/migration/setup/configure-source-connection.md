---
name: configure-source-connection
description: Set up a connection to the source database (extract DDL, migrate data, run baselines). Routes to per-dialect connection skills; offers deferral or a permanent opt-out only if the user pushes back.
license: Proprietary. See License-Skills for complete terms
---

# Configure source connection

Two ways in, and they differ in whether a connection has already been agreed to:

- **From setup**, because the user chose **Extract from database** at
  `chooseCodeSource`. That answer already *is* "yes, I need a source
  connection" — don't ask again, go straight to **Set up the connection**.
- **From `generateTestCases` / `migrateData`**, whose prereq isn't met. Here the user
  has no connection and may never have wanted one, so name the capability that
  needs it and ask before setting one up.

A user importing local SQL files never reaches this skill from setup.

## Before connecting — tell the user

Before proceeding to connection setup, show this **verbatim** on every entry path.

> **What this connection is used for:** This source connection will be used
> throughout the migration lifecycle for metadata extraction, DDL/code
> extraction, schema introspection, data migration reads, and validation
> queries.

**Never** show the non-production / heavy-read warning on
`configureExtractionSource` — extraction reads metadata and DDL only. That
warning belongs on `configureSandboxProfile` (see
`configure-sandbox-profile.md`), which is the step that establishes the
connections used for data migration and validation.

## Set up the connection

If `progress_setup` already returned a connection picker as `next_prompt`
(`write_to` is `source_connection`), ask that prompt as given — it already
says we will extract all objects from the picked connection's database.
Submit the chosen name with `progress_setup(answers={"source_connection": "<name>"})`.
If they pick **Create a new connection**, do not write `source_connection`;
create a connection with the per-dialect sub-skill below, then call
`configure(source_connection=<name>)` with the new name.

Otherwise, call `configure(needs_source_connection=true)` to list existing
connections for the configured dialect. Safe to repeat — it only reads.

- If `existing_connections` is non-empty, ask the user to pick one. Then call
  `configure(source_connection=<name>)` with a name from that list. If they type
  something that isn't a listed name, such as "show me the details" or "which
  one is prod?", it's a request, not a connection. Run
  `scai connection list -l <dialect>`, show what they asked for, and ask again.
  If they want a new connection, load the per-dialect sub-skill below.
- Otherwise, load the per-dialect connection sub-skill:
  - `sqlserver` → `../connection/sql-server-connection/SKILL.md`
  - `redshift` → `../connection/redshift-connection/SKILL.md`
  - `oracle` → `../connection/oracle-connection/SKILL.md`
  - `teradata` → `../connection/teradata-connection/SKILL.md`
  - `postgresql` → `../connection/postgresql-connection/SKILL.md`
  - `db2` → `../connection/db2-connection/SKILL.md`
  - `bigquery` → `../connection/bigquery-connection/SKILL.md`
  - `synapse` / `azuresynapse` → `../connection/azure-synapse-connection/SKILL.md`

## If the user pushes back

Don't offer these up front on the setup path — only once the user says they
don't want to connect now, or the re-entry question above gets a "no".

**Defer for this run:**

```
progress_setup(mode="setup", skip="configureExtractionSource")
```

Nothing is persisted, so a later `progress_setup()` — or a re-entry from
`generateTestCases` / `migrateData` — can offer it again.

**Permanent opt-out:**

```
configure(tasks={"configureExtractionSource": {"enabled": false}})
```

Say what it costs first: code already in the project still converts and
deploys; extracting code from the source, tests-from-source and data migration
stay unavailable until they reconsider.

## On completion

Return to the parent setup skill once the connection is set, or the user has
deferred or opted out.
