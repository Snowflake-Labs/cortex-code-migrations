---
name: configure-snowflake-target
description: Set the Snowflake target for object migration — connection name, and the database when convert wrote no bindings — then confirm the whole project configuration before the deploy loop starts. Persists via `configure(snowflake_connection=…)`, adding `snowflake_database=…` only when none is set yet or the user changes it.
license: Proprietary. See License-Skills for complete terms
---

# Configure Snowflake target

Invoked by the setup state machine once the user has opted into object
migration after the continue gate and `chooseRunMode`. Conversion and assessment
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

The converted objects deploy here. `snowflake_database` also names this
project's records in the metadata database (claims, task attempts, sandbox
events), so once the migration has started it must not change. Call
`configure()` and read `snowflake_targets:` (or `snowflake_database:`):

- **`snowflake_targets:` present** — convert wrote
  `.scai/bindings/database-bindings.yaml`; each `token → CATALOG` is where
  that catalog's objects deploy. Deploy, data migration and validation read
  this file, not `snowflake_database`. Confirm them in the recap; to
  retarget, edit that yaml. A target that is its own token (`hr → hr`)
  may be convert's placeholder: confirm that catalog exists, or ask below.
- **No `snowflake_targets:`** — ask `textInput` (no options). Prefill
  `defaultValue` from `configure()`'s source database (`source_database`,
  else the database on `source_connection`): uppercase, `-` and spaces to
  `_`, drop every other non-letter/digit/`_`. Omit `defaultValue` if unknown.
  > Which Snowflake database should I deploy into? Letters, digits, and
  > underscores only — `SALES-DB` must be double-quoted everywhere.

## Step 3: Confirm everything, then persist

Show one recap covering every value the migration phase depends on, pulled
from the `configure()` response:

> Before we start deploying, here's the setup:
> - **Snowflake connection:** `<snowflake_connection>`
> - **Target database:** `<snowflake_targets>` when the response has them,
>   otherwise `<snowflake_database>` or the name the user just gave
> - **Source connection:** `<source_connection>` — or "none (synthetic test
>   data only)" when unset
> - **Source dialect:** `<source_language>`
> - **Git branch:** `<git_main_branch>`
>
> Correct?

Ask via `ask_user_question` (`multiSelect = false`) with **Yes, continue**
and **Change something**. On "Change something", ask which value and loop
back to the relevant step. Only once the user confirms, persist in a
single call:

```
configure(snowflake_connection="<name>", snowflake_database="<db>")
```

Pass `snowflake_database` **only** when the response had none or the user
just changed it; otherwise leave it out. If the response says
`snowflake_database changed: OLD → NEW` and the user did not ask for that,
restore `OLD` right away as the note says, and tell the user.

`snowflake_database` is a setting, never a probe. Every re-check below is
`configure(ensure_metadata_schema=true)` with no other arguments.

## Step 4: Handle a missing or unreachable database

The `configure()` response now carries `schema_status_*` and
`prereq_status_*` lines. Only two matter here — the rest are checked by
`configure-testing.md`:

- `schema_status_metadata: error("…not visible…recreate_metadata_database=true")`
  → quote the message. Ask whether to restore/GRANT USAGE / repoint
  `metadata_database`, or start fresh. Only after they confirm starting
  fresh, call `configure(recreate_metadata_database=true)`. Do **not**
  treat this as a connection/PAT problem or a transient recheck.
- `schema_status_metadata: error("…cannot tell whether…already bootstrapped…")`
  → quote the message. If the user confirms the metadata database already
  exists, call `configure(ensure_metadata_schema=true)`. Only after they
  confirm starting **empty**, call `configure(recreate_metadata_database=true)`.
- `schema_status_metadata: error("…not reachable…")` → quote the message;
  rename the mixed-case database (same remedy as
  `database_name_unresolvable` below). Do **not** recreate.
- `schema_status_metadata: error("…could not verify…still exists…")` → quote
  the message; re-check once the session is healthy. Do **not** recreate.
- `schema_status_*: error("…")` (any other) → quote the error text to the
  user. Typical causes: PAT profile missing `token` / `token_file_path`, a
  connection name that is not in `~/.snowflake/connections.toml`, incomplete
  key-pair material, or a failed login. Do **not** guess a different
  authenticator or retry Entra SSO to "fix" a PAT error. Load
  `../connection/snowflake-connection/SKILL.md` when the user needs to
  edit the profile, then re-check after they save.
- `database_missing` in any `schema_status_*` → the configured database
  does not exist. **Ask before creating it** — the name may be a typo:
  > `<db>` doesn't exist yet. Create it, or did you mean a different name?

  On confirmation call `configure(ensure_target_database=true)`, then re-check.
- `schema_status_dmv: error("<msg>")` → `scai data migrate-schema` failed in
  the metadata database. Quote `<msg>`; re-check once the user fixes it.

- `schema_status_validation: database_name_unresolvable("<stored>")` → the
  database exists, but under a name that only a quoted reference reaches.
  Every later statement — here and in `scai` — names it unquoted, which
  Snowflake folds to upper case, so deploy would fail object by object with
  "does not exist". Don't work around it; the name has to change:
  > `<stored>` was created as a quoted, mixed-case name, so `USE DATABASE
  > <stored>` resolves to `<STORED>` and fails. Rename it to `<STORED>`, or
  > point me at a different database?

  On confirmation run `ALTER DATABASE "<stored>" RENAME TO <STORED>;` and
  re-persist the upper-case name, then re-check.
  Never create a target database with a quoted name.

## If the user won't name a database

Don't block and don't error. Conversion and assessment are already
complete and committed; the target can be named later. Tell the user the
deploy loop needs a current database and stop here:

> No problem — assessment is done and committed. I'll need a target
> database before deploying anything, so say the word when you've picked
> one.

## On completion

Return to the parent setup skill. The resolver will pick the next task.
