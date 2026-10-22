---
name: configure-sandbox-profile
description: Configure the authoritative sandbox profile and database bindings for migration execution.
license: Proprietary. See License-Skills for complete terms
---

# Configure sandbox profile

For non-Snowflake sources, this step defines the execution identity for
deploy/migrate/validate: a sandbox profile (`--profile`) plus canonical
database bindings (`.scai/bindings/database-bindings.yaml`).

Connections `configure()` already reports are pre-filled; the user confirms
them in the Step 6 recap.

## Step 1: Explain what this step configures

Tell the user:

> **Sandbox profile** — a named, project-local bundle that tells AIM which
> connections and databases to use for migration work.
>
> **What it's for:** Every deploy / migrate / validate / test run uses this
> profile so those steps always hit a safe sandbox — not production. AIM only
> allows migration execution against a sandbox profile.
>
> **What it includes:**
> - A **source connection** (where objects and data come from)
> - A **Snowflake target connection** (where we deploy and run tests)
> - **Database bindings** — which source databases map to which Snowflake
>   databases
>
> Next we'll pick a profile name and database bindings, then confirm the
> connections with the rest of the profile and save it. You can change them
> later from Settings.

A source connection is **required**, even when the user only wants synthetic
test data: deploy, migrate and validate read from it, and the profile can't be
saved without one. Say so if the user asks to go on without a source.

## Step 2: Choose the sandbox profile name

Ask via `ask_user_question` (`multiSelect = false`) to use `sandbox` or type
another name. Read `configure()` first: ask any Step 3 connection question in
this same card.

If `.scai/config/profiles.local.yaml` has this name, ask whether to replace
it (in Step 6) or pick another. Don't write the profile yet.

## Step 3: Resolve source and target connections

Call `configure()` and read `source_connection` and `snowflake_connection`.

Show this **verbatim** first, whether or not anything is asked below:

> **Use a non-production instance.** Connect to a dev, test, or sandbox
> database — not production. Migration operations can introduce significant
> query load, long-running reads, and potential locking on the source database
> during data migration and validation phases.

**Both already set:** do **not** ask about either connection here. Tell the
user which ones the sandbox will use, then go on to Step 4:

> For the sandbox I'll use:
> - **Source:** `<source_connection>`
> - **Snowflake:** `<snowflake_connection>`
>
> These are for iterative deploy/migrate/test cycles — not production. You'll
> confirm them with the rest of the profile before it's saved.

**One or both missing:** ask only for the missing ones, one question each
(`multiSelect = false`), in the Step 2 card:

1. **Source connection** — existing source connections for this dialect.
   Always include **Create a new connection** last. **Never** offer "no
   source connection", "synthetic only", or "skip".
2. **Target Snowflake connection** — existing Snowflake connections, a
   `last_used_snowflake_connection:` first as `<name> (recommended)`,
   description "Last used": only a recommendation, so save nothing until
   the user picks. Always include **Create a new connection** last.

On **Create a new connection**, load its skill, then re-ask:

- **Source** — `../connection/<dialect>-connection/SKILL.md` (same map as
  `configure-source-connection.md`) for `redshift`, `oracle`, `teradata`,
  `postgresql`, `db2` and `bigquery`; `sql-server-connection` for
  `sqlserver`; `azure-synapse-connection` for `synapse` / `azuresynapse`
- **Snowflake target** — `../connection/snowflake-connection/SKILL.md`

Re-read `configure()` after any create. Carry the final pair to Step 6.

No source connection available now: stop, setup resumes once there is one.

## Step 4: Bind each source database the code covers

Bind exactly the source databases the registered code lives in. Never list
the connection's databases, run a catalog query, or ask which are in scope: a
database with no registered code is never offered and never bound.

1. `query_registry` silently stops at `limit` (100 by default), so collect
   every unit's source database in rounds: `query_registry(fields="source")`,
   then
   `query_registry(where="source.database NOT IN (<seen>)", fields="source")`
   (values seen so far, quoted as returned: `'${token}'`, `''`) until it
   returns `[]`. `NOT IN` skips a missing database, so also run
   `query_registry(where="source.database IS NULL", fields="id", limit=1)`.
   Use no `limit` or a positive one, never `limit=0`. If a call fails, stop.
   Resolve each `${token}` via the bindings file's `source:` map.
2. Code with no database part (an added `schema.name` file) sits under a
   placeholder (`defaultdb`, `database_unspecified`, or none). It belongs to
   the source connection's own database (`scai connection list -l <dialect>
   --json`): bind it there and show it in the Step 6 recap.
3. Nothing registered: stop. Tell the user to add or extract code first.

Suggest a target per database: its `configure()` `snowflake_targets:` entry,
else `snowflake_database:` for the first, else the source database's name.

### Confirm each target

One `ask_user_question` with one question per database with code
(`multiSelect = false`), headed by the source database: suggested target
labelled **(recommended)**; freeform override allowed. Reject duplicate
targets; re-ask on conflict.

## Step 5: Check which target DBs exist

For each target, run `SHOW DATABASES LIKE '<TARGET>'`. It exists only if a
returned `name` equals it exactly (upper-cased if unquoted): `LIKE` ignores
case and `_` is a wildcard. Create nothing yet; carry the missing ones to the
Step 6 recap. If the check fails, stop with remediation.

## Step 6: Confirm, persist, and complete

Show a recap (name, description, source connection, Snowflake connection,
bindings file, each source database and its target, targets to create) and
ask **Yes, save profile** / **Change something**. On
**Change something**, ask what to change; for a connection, ask the Step 3
question for that connection (the current one first, labelled **current**,
**Create a new connection** last), then show the recap again. Re-run Step 5
after changing the Snowflake connection or a mapping. Only after Yes:

1. `CREATE DATABASE IF NOT EXISTS <TARGET>` for each Step 5 missing target.
   On failure, stop with remediation.

2. Write `.scai/bindings/database-bindings.yaml`. Convert already generates
   it; both maps key on convert's token name:

   ```yaml
   source:
     <token>: <SOURCE_DB>   # source database
   snow:
     <token>: <TARGET_DB>   # confirmed target
   ```

   Edit the existing file. Per database with code keep its `source:` entry
   (a placeholder's points at the connection's database) and set `snow:` to
   the confirmed target. Drop `source:` and `snow:` entries for databases with
   no registered code only after the Step 4 inventory is complete; else keep
   them all. Never replace the file with a source→target-only list.

3. Create the profile:

```bash
scai profile create <name> \
  --source-connection <source> \
  --snowflake-connection <snowflake> \
  --database-bindings .scai/bindings/database-bindings.yaml \
  --sandbox \
  --description "Sandbox profile for migrating <project-name> — source and Snowflake connections used by AIM for deploy, migrate, validate, and test."
```

To replace an existing name: `scai profile remove <name>`, then create.

4. `scai profile set-default <name>`

5. Persist profile **and** connections (the task completes only when all
   three are set), with the first target as `snowflake_database`:

```
configure(
  sandbox_profile="<name>",
  source_connection="<source>",
  snowflake_connection="<snowflake>",
  snowflake_database="<first_target_db>",
  ensure_target_database=true
)
```

Return to the parent setup skill.

This task is locked: no skipping, no `configure(tasks=…)` opt-out.
