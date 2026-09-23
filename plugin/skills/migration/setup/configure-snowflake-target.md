---
name: configure-snowflake-target
description: Set the Snowflake target for object migration — connection name and database — then confirm the whole project configuration before the deploy loop starts. Persists via `configure(snowflake_connection=…, snowflake_database=…)`.
license: Proprietary. See License-Skills for complete terms
---

# Configure Snowflake target

Invoked by the setup state machine once the user has opted into object
migration at the `chooseRunMode` step. Conversion and assessment
have already run — they don't need a Snowflake target, which is why this
question waits until now.

## Step 1: Snowflake connection

Call `configure(needs_snowflake_connections=true)` and read both
`snowflake_connection` (the one already resolved, from `project.local.yml`
or `$SNOWFLAKE_CONNECTION`) and `existing_snowflake_connections:` (every
connection in the user's TOML). Safe to repeat — it only reads.

Ask via `ask_user_question` (`multiSelect = false`), never by asking the
user to type a name:

- Options are the names from `existing_snowflake_connections:`, the
  resolved or active one first and labelled **currently selected**.
- Leave the `(default)` suffix on whichever name carries it: that marks the
  TOML default, which may be a different connection. Two names may end up
  labelled, one per meaning.
- Add **Create a new connection** as the last option — always, even when
  the list is long.

`existing_snowflake_connections: none` means there is nothing to offer:
say so and go straight to creating one — including when
`snowflake_connection` already resolves, because a name that is in no TOML
names nothing scai can connect with. `(unavailable: …)` is the opposite
case: scai did not answer, so propose the resolved or active connection by
name and let the user correct it; do not tell them they have no
connections.

On **Create a new connection**, or when the current one fails SSO against
Microsoft Entra ID / Azure AD / OIDC, load
`../connection/snowflake-connection/SKILL.md` before persisting a name.
Use `oauth_authorization_code` for Entra OIDC — never `externalbrowser`.

## Step 2: Target database

This is where the migration tracking database and the converted objects
will live. Call `configure()` and look for `active_bindings:`:

- **Present** — Read that YAML. `snow:` values are the Snowflake catalogs
  convert already bound. Confirm them in the recap; don't re-ask unless
  the user wants a different database.
- **Absent** — convert did not write bindings. Ask, with the naming rule in
  the question so it is read before a name is typed:
  > Which Snowflake database should I deploy into? Use letters, digits and
  > underscores — a hyphen isn't a Snowflake identifier character, so
  > `SALES-DB` has to be double-quoted and case-sensitive everywhere it is
  > referenced.

## Step 3: Confirm everything, then persist

Show one recap covering every value the migration phase depends on, pulled
from the `configure()` response:

> Before we start deploying, here's the setup:
> - **Snowflake connection:** `<snowflake_connection>`
> - **Target database:** `<snowflake_database>` — from `active_bindings`
>   `snow:` when that yaml exists, otherwise the name the user just gave
> - **Source connection:** `<source_connection>` — or "none (synthetic test
>   data only)" when unset
> - **Source dialect:** `<source_language>`
> - **Git branch:** `<git_main_branch>`
>
> Correct?

Ask via `ask_user_question` (`multiSelect = false`) with **Yes, continue**
and **Change something**. On "Change something", ask which value and loop
back to the relevant step. Only once the user confirms, persist both
values in a single call:

```
configure(snowflake_connection="<name>", snowflake_database="<db>")
```

## Step 4: Handle a missing database

The `configure()` response now carries `schema_status_*` and
`prereq_status_*` lines. Only one matters here — the rest are checked by
`configure-testing.md`:

- `schema_status_validation: database_missing` → the configured database
  does not exist. **Ask before creating it** — the name may be a typo:
  > `<db>` doesn't exist yet. Create it, or did you mean a different name?

  On confirmation run `CREATE DATABASE <snowflake_database>;`, then
  `configure(ensure_metadata_schema=true)` to refresh.

## If the user won't name a database

Don't block and don't error. Conversion and assessment are already
complete and committed; the target can be named later. Tell the user the
deploy loop needs a current database and stop here:

> No problem — assessment is done and committed. I'll need a target
> database before deploying anything, so say the word when you've picked
> one.

## On completion

Return to the parent setup skill. The resolver will pick the next task.
