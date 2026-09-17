---
name: configure-sandbox-profile
description: Create a sandbox scai profile binding the Snowflake target and source connections for iterative workload conversion. Persists via `configure(sandbox_profile=…)`.
license: Proprietary. See License-Skills for complete terms
---

# Configure sandbox profile

AIM currently pre-sets `sandbox_profile=sandbox` in `bootConfigureParams`,
so this step is not asked. Do not load this skill until that default is
removed.

Runs after `configureSnowflakeTarget`. Both the Snowflake connection +
database and a source connection must be confirmed before creating a
**sandbox** profile that downstream migration commands resolve through
`--profile`.

## Step 1: Read current connections

Call `configure()` and read:

- `snowflake_connection` — required (set by `configureSnowflakeTarget`)
- `source_connection` — may already be set from `configureSourceConnectionExtract`
  or an earlier source-connection step

If `source_connection` is empty, load `configure-source-connection.md` first
and return here once it is set.

## Step 2: Confirm sandbox connections

Even when `source_connection` was configured for extraction, confirm the user
wants **the same** source for sandbox workload conversion:

> For sandbox workload conversion I'll use:
> - **Snowflake:** `<snowflake_connection>` → database `<snowflake_database>`
> - **Source:** `<source_connection>`
>
> These connections are for iterative deploy/migrate/test cycles — not production.
> Use these for sandbox?

Ask via `ask_user_question` with **Yes, use these** and **Use different
connections**. On "different", loop through connection setup for whichever
side they want to change, then re-read `configure()`.

## Step 3: Create the sandbox profile

Pick a profile name (default **`sandbox`** unless the user prefers another).
Create it with the CLI:

```bash
scai profile create <name> \
  --snowflake-connection <snowflake_connection> \
  --source-connection <source_connection> \
  --sandbox \
  --description "Sandbox profile for iterative workload conversion"
```

If a profile with that name already exists, run `scai profile show <name>` and
confirm it has `sandbox: true` and the expected connections. Update via remove +
recreate only when the user asks.

Optionally set it as default:

```bash
scai profile set-default <name>
```

## Step 4: Persist and complete

```
configure(sandbox_profile="<name>")
```

Return to the parent setup skill. The resolver advances to `chooseTestingPath`.

## Skip this run only

```
progress_setup(mode="setup", skip="configureSandboxProfile")
```

Permanent opt-out:

```
configure(tasks={"configureSandboxProfile": {"enabled": false}})
```
