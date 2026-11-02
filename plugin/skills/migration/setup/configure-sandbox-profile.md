---
name: configure-sandbox-profile
description: Configure the authoritative sandbox profile and database bindings for migration execution.
license: Proprietary. See License-Skills for complete terms
---

# Configure sandbox profile

For non-Snowflake sources: the sandbox profile (`--profile`) and database
bindings deploy/migrate/validate run on.

## Step 1: Explain what this step configures

Tell the user:

> **Sandbox profile** — the connections and databases every deploy /
> migrate / validate / test run uses, so they hit a sandbox, not production:
> a **source connection**, a **Snowflake target connection** and **database
> bindings** (source → Snowflake databases). You'll confirm it before it's
> saved; change it later in Settings.

A source connection is **required**, even when the user only wants synthetic
test data: deploy, migrate and validate read from it. Say so if asked to go
on without one.

A profile names its bindings file (`--database-bindings`); editing one
changes every profile using it. A profile for some databases binds a copy
keeping their code's tokens. A run's scope isn't a profile's.

## Step 2: Choose the sandbox profile name

Ask via `ask_user_question` (`multiSelect = false`) to use `sandbox` or type
another name. Read `configure()` first: ask any Step 3 connection question in
this same card.

If `.scai/config/profiles.local.yaml` has this name, ask whether to replace
it (in Step 6) or pick another.

## Step 3: Resolve source and target connections

Call `configure()` and read `source_connection` and `snowflake_connection`.

Show this **verbatim** first, asked anything or not:

> **Use a non-production instance.** Connect to a dev, test, or sandbox
> database — not production. Migration operations can introduce significant
> query load, long-running reads, and potential locking on the source database
> during data migration and validation phases.

**Both already set:** do **not** ask about either connection here. Say the
sandbox will use **Source:** `<source_connection>` and **Snowflake:**
`<snowflake_connection>`, confirmed before saving, then go on to Step 4.

**One or both missing:** ask only for the missing ones, one question each
(`multiSelect = false`), in the Step 2 card:

1. **Source connection** — existing source connections for this dialect.
   Always include **Create a new connection** last. **Never** offer "no
   source connection", "synthetic only", or "skip".
2. **Target Snowflake connection** — existing Snowflake connections, a
   `last_used_snowflake_connection:` first as `<name> (recommended)`,
   description "Last used": only a recommendation, so save nothing until
   the user picks. Always include **Create a new connection** last.

On **Create a new connection**, load its skill (source: the dialect's, as
mapped in `configure-source-connection.md`; Snowflake:
`../connection/snowflake-connection/SKILL.md`), then re-read `configure()`
and re-ask.

No source connection yet: stop; setup resumes once there is one.

## Step 4: Bind each source database the code covers

Bind exactly the source databases the registered code lives in. Never list
the connection's databases, run a catalog query, or ask which are in scope: a
database with no registered code is never offered and never bound.

One source connection covers every database here: never ask for, or create,
a connection or profile per database.

Call `list_source_databases()`; if it fails, stop. Nothing registered: stop.
Tell the user to add or extract code first. Each entry's `token` keys the
bindings file. A `placeholder` entry (`defaultdb`, `database_unspecified`)
or `unitsWithoutDatabase` is code with no database part: bind it to the
source connection's default database (`scai connection list -l <dialect>
--json`) and show it in the Step 6 recap.

Suggest a target per database: its `configure()` `snowflake_targets:` entry,
else `snowflake_database:` for the first, else the entry's `suggestedTarget`
(an unbound placeholder has none: the default database's name).
When the result has `databasePrefix`, the Snowflake account is shared: every
target, suggested or typed, must start with it, so prepend it to any that
doesn't.
Then one `ask_user_question` with one question per database with code
(`multiSelect = false`), headed by the source database: suggested target
labelled **(recommended)**; freeform override allowed. Reject duplicate
targets; re-ask on conflict.

## Step 5: Check the target DBs

For each target, run `SHOW DATABASES LIKE '<TARGET>'`. It exists only if a
returned `name` equals it exactly (upper-cased if unquoted): `LIKE` ignores
case and `_` is a wildcard. Create nothing yet; carry missing ones to the
recap. If the check fails, stop with remediation.

For existing targets, call
`configure(check_target_tables="<token>=<TARGET>,…", check_target_connection="<snowflake>")`
and carry each `target_tables_with_rows:` line to the recap; on
`unavailable: …`, say the check couldn't run.

## Step 6: Confirm, persist, and complete

Show a recap (name, description, source connection, Snowflake connection,
bindings file, each source database and its target, targets to create). Per
`target_tables_with_rows` line add "_<DB> has N tables deploy will
replace (e.g. DBO.ORDERS, 1,204 rows). Their current rows will be lost._"
Then ask **Yes, save profile** / **Change something**. On
**Change something**, ask what to change; for a connection, ask the Step 3
question for that connection (the current one first, labelled **current**,
**Create a new connection** last), then show the recap again. Re-run Step 5
after changing the Snowflake connection or a mapping. Only after Yes:

1. Create no database: item 5 creates each missing target from its
   converted DDL, collation included. On a
   `target_database_status_<db>: error`, stop with its remediation.

2. Write `.scai/bindings/database-bindings.yaml` (convert generates it);
   both maps key on convert's token:

   ```yaml
   source:
     <token>: <SOURCE_DB>
   snow:
     <token>: <TARGET_DB>
   ```

   AIM reads only this file for now, so every profile points at it: edit it
   in place. Per database with code keep its `source:` entry (a
   placeholder's is the connection's default) and set `snow:` to the
   confirmed target. Drop `source:` and `snow:` entries for databases with
   no registered code only after the Step 4 inventory is complete; else keep
   them all. Never replace the file with a source→target-only list, or
   drop a database with code to fit one profile.

3. Create the profile:

```bash
scai profile create <name> \
  --source-connection <source> \
  --snowflake-connection <snowflake> \
  --database-bindings .scai/bindings/database-bindings.yaml \
  --sandbox \
  --description "Sandbox profile for <project-name>: AIM's deploy, migrate, validate and test connections."
```

To replace a name, `scai profile remove <name>` first.

4. `scai profile set-default <name>`

5. Persist profile **and** connections, the first target as
   `snowflake_database`:

```
configure(sandbox_profile="<name>", source_connection="<source>",
  snowflake_connection="<snowflake>", snowflake_database="<first_target_db>",
  ensure_target_database=true)
```

Return to the parent setup skill.

This task is locked: no skipping, no `configure(tasks=…)` opt-out.
