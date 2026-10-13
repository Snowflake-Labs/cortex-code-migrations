---
name: configure-sandbox-profile
description: Configure the authoritative sandbox profile and database bindings for migration execution.
license: Proprietary. See License-Skills for complete terms
---

# Configure sandbox profile

For non-Snowflake sources, this step defines the execution identity for
deploy/migrate/validate: a sandbox profile (`--profile`) plus canonical
database bindings (`.scai/bindings/database-bindings.yaml`).

`configureExtractionSource` may already have set a source connection for
extraction, and `configure()` may already report a Snowflake connection. This
step is authoritative for the sandbox: it pre-fills those values and the user
confirms them once, in the Step 6 recap, instead of answering them again one by
one.

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

## Step 2: Choose the sandbox profile name

Pick a profile name (default `sandbox`). Ask via `ask_user_question`
(`multiSelect = false`) whether to use that name or type another. Read
`configure()` first: when Step 3 has a connection to ask, ask it in this same
card.

If `.scai/config/profiles.local.yaml` already has this name, say so and ask
whether to refresh it later in this flow (replace) or pick a different name.
Do **not** write the profile yet — connections and bindings come first; Step 6
persists.

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
(`multiSelect = false`), in the Step 2 name card:

1. **Source connection** — existing source connections for this dialect.
   Always include **Create a new connection** last.
2. **Target Snowflake connection** — existing Snowflake connections. Always
   include **Create a new connection** last.

If they pick **Create a new connection**, load the matching skill, then return
and re-ask that question so the answer is final:

- **Source** — route by dialect (same map as `configure-source-connection.md`):
  `sqlserver` → `../connection/sql-server-connection/SKILL.md`;
  `redshift` → `../connection/redshift-connection/SKILL.md`;
  `oracle` → `../connection/oracle-connection/SKILL.md`;
  `teradata` → `../connection/teradata-connection/SKILL.md`;
  `postgresql` → `../connection/postgresql-connection/SKILL.md`;
  `db2` → `../connection/db2-connection/SKILL.md`;
  `bigquery` → `../connection/bigquery-connection/SKILL.md`;
  `synapse` / `azuresynapse` → `../connection/azure-synapse-connection/SKILL.md`
- **Snowflake target** — `../connection/snowflake-connection/SKILL.md`

Re-read `configure()` after any create. Carry the final pair to Step 6.

## Step 4: Select database scope and bindings

Discover every database on the chosen source connection (dialect catalog query
via `query_source`, or distinct source DBs from registered code units). Suggest
a Snowflake target per source DB (same name, or reuse
`.scai/bindings/database-bindings.yaml` on rerun).

AskUserQuestion has checkboxes/radios and freeform text — collect scope and
mappings in **two** cards:

### 4a. Which source databases are in scope?

`ask_user_question` (`multiSelect = true`): one checkbox per source DB; label
`<SOURCE_DB>`; description `Suggested Snowflake database: <SUGGESTED_TARGET>`.
Require at least one.

### 4b. Confirm or edit each target mapping

One `ask_user_question` with one question per selected source DB
(`multiSelect = false`): suggested target labelled **(recommended)**; freeform
override allowed. Reject duplicate targets; re-ask on conflict.

Profile `database_bindings` must point at
`.scai/bindings/database-bindings.yaml`. On rerun: keep unchanged, replace
changed, remove deselected.

## Step 5: Validate target DB existence and create missing DBs

For each mapping target: verify on the Snowflake connection; create if missing
(idempotent). On failure, stop with remediation.

## Step 6: Confirm, persist, and complete

Show a recap (name, description, source connection, Snowflake connection,
bindings file, mappings) and ask **Yes, save profile** / **Change something**.
This recap is where the user confirms connections Step 3 pre-filled. On
**Change something**, ask what to change; for a connection, ask the Step 3
question for that connection (the current one first, labelled **current**,
**Create a new connection** last), then show the recap again. Only after Yes:

1. Write `.scai/bindings/database-bindings.yaml`. Convert already generates this
   with fixed schema:

   ```yaml
   source:
     SOURCE_DB: "${token}"
   snow:
     TARGET_DB: "<%token%>"
   ```

   Read the existing file when present. Keep both `source:` and `snow:` maps;
   update `snow:` for selected mappings; drop deselected. Never replace with a
   source→target-only scratch list.

2. Create the profile:

```bash
scai profile create <name> \
  --source-connection <source> \
  --snowflake-connection <snowflake> \
  --database-bindings .scai/bindings/database-bindings.yaml \
  --sandbox \
  --description "Sandbox profile for migrating <project-name> — source and Snowflake connections used by AIM for deploy, migrate, validate, and test."
```

On confirmed refresh of an existing name: `scai profile remove <name>` then
create again.

3. `scai profile set-default <name>`

4. Persist profile **and** connections — the machine completes only when all
   three are set. Use the first confirmed target as `snowflake_database`:

```
configure(
  sandbox_profile="<name>",
  source_connection="<source>",
  snowflake_connection="<snowflake>",
  snowflake_database="<first_target_db>",
  ensure_target_database=true
)
```

Return to the parent setup skill. The resolver advances to `chooseTestingPath`.

## Skip this run only

```bash
progress_setup(mode="setup", skip="configureSandboxProfile")
```

This task is locked — there is no permanent opt-out via `configure(tasks=…)`.
