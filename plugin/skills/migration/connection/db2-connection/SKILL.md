---
name: db2-connection
description: Connect to a source IBM DB2 (LUW) database for migration to Snowflake using scai CLI. Triggers: db2, ibm db2, source connection, source database, connect to db2, add db2 connection.
license: Proprietary. See License-Skills for complete terms
---

# DB2 Connection Skill

## On Entry

Tell the user:
> **Setting up DB2 connection** — I'll configure and test a connection to your source IBM DB2 (LUW) database. I'll need a few connection details.

## Prerequisites

- Network access to the DB2 host (self-hosted LUW or cloud-hosted)
- DB2 username and password with read access to the system catalog (`SYSCAT`)
- The `scai` CLI installed and available

## Required Connection Details

### Standard Auth (only auth method supported in MVP)

Values the connection needs (how they are collected depends on the form in Step 3):

| Parameter | Interactive (omit `--auth`) | Inline (no tty) | Description |
|-----------|----------------------------|-----------------|-------------|
| `-s, --source-connection` | Optional (prompted if omitted) | Required | Friendly name for this source connection |
| `--auth` | Omit — that selects the prompts | Required (`standard`) | Auth method |
| `--host` | Prompted | Required | DB2 host |
| `--port` | Prompted (default `50000`) | Optional (default `50000`) | TCP port |
| `--database` | Prompted | Required | Database name |
| `--user` | Prompted | Required | DB2 username |
| `--password` | Hidden prompt | Required | DB2 password |
| `--connection-timeout` | Prompted | Optional | Connection timeout in seconds |

> DB2 is read through the `ibm_db` DB-API driver, which stages Parquet — there is no ODBC install required on the worker host.

## Workflow

### Step 1: Ask How to Provide Credentials

Ask the user for the **non-secret** fields (host, port, database, username) and how they want to supply the password:

> "I need the following to connect to DB2:
> - **Host**
> - **Port** (default `50000`)
> - **Database name**
> - **Username**
>
> How would you like to provide the password?"

Gate the password options on whether **your** `bash` is a real tty — the same rule Step 3 uses. Do not offer a dead option through `ask_user_question`.

**When your bash is a tty** (Cortex CLI in a terminal):
1. **1Password** — Credentials stored in a 1Password vault (`op run` in the same command)
2. **Type it at the prompt** — interactive form in Step 3; do **not** send the password to the agent
3. **Pass it once inline** — only if they insist; agent asks once and passes `--password` (never echoed back)

**When bash has no tty** (desktop app, CI) — omit "Type it at the prompt":
1. **1Password** — Credentials stored in a 1Password vault (`op run` in the same command)
2. **Pass it once for a no-tty caller** — the agent asks once and passes `--password` (never echoed back)

### Step 2: Route Based on Answer

| User says | Action |
|-----------|--------|
| "1Password" | Follow `../1PASSWORD.md` (DB2 section) |
| "Type it at the prompt" | Proceed to Step 3 interactive form (**tty only** — never offer this when bash has no tty) |
| "Pass it once…" / no tty | Proceed to Step 3 inline form |
| Other credential manager | Check if `../references/<NAME>.md` exists; if not, ask user to explain their setup. Prefer managers that resolve the value inside the same command (`op run`); a store `scai` cannot read is not a path. |

### Step 3: Add the Connection

Pick the form by whether **your** `bash` can prompt — not by whether the user's machine has a terminal elsewhere.

**Interactive form — prefer this when your bash is a real tty** (Cortex CLI in a terminal). Omitting `--auth` selects the prompts; the password prompt is hidden, so the secret never reaches an argv, shell history or this conversation.

```bash
scai connection add-db2 -s <CONNECTION_NAME>
```

`-s` supplies the connection name only; omit it as well and the command asks for that too. Tell the user to have the values from Step 1 ready to type at the prompts, and **not** to send the password to you.

**Inline form — required when bash has no tty** (desktop app, CI). `--password` is required and there is no prompt fallback, so the secret does land on the command line once. Ask for it in the conversation only if you must, pass it straight into the flags below, and **never echo or restate it**. Prefer `op run` (or equivalent) so the value resolves inside the same command when a credential manager is available.

```bash
scai connection add-db2 \
  -s <CONNECTION_NAME> \
  --auth standard \
  --host <HOST> \
  --port <PORT> \
  --database <DATABASE> \
  --user <USERNAME> \
  --password <PASSWORD>
```

- Omit `--port` if the server uses the default (`50000`).

### Step 4: Save and Test Source Connection

Call the `configure` tool with `source_connection` set to `<CONNECTION_NAME>`. The MCP server runs `scai connection test` internally and only persists the connection if the test passes.

- **On success:** the response includes `connection_test: ok`.
- **On failure:** the tool returns an error containing the scai message. Surface it to the user, help them fix the issue, then re-run `configure(source_connection=<CONNECTION_NAME>)`.

**Common errors:**

| Error | Cause | Solution |
|-------|-------|----------|
| `Operation timed out` | Network / firewall | Check VPN, security groups, firewall rules |
| `SQL30081N` (communication error) | Wrong host/port or server down | Verify host, port (default `50000`), and that DB2 is listening |
| `SQL1013N` (database not found) | Wrong database name | Verify the database alias / name on the server |
| `SQL30082N` (auth failed) | Bad credentials | Re-check username and password |

## CHECKPOINT

Confirm with user:
- [ ] `configure` returned `connection_test: ok`
- [ ] Connection appears in `scai connection list -l db2 --json`
- [ ] Source connection saved to session config

## On Completion

After the CHECKPOINT passes, tell the user:
> **Connection configured** — Successfully connected to DB2 using connection `<connection_name>`.

Then return to the calling skill.

## Security Rules

- **NEVER** log or display secrets (passwords) in plain text, and never echo a password the user gave you.
- **Prefer the interactive form in Step 3 when your bash is a tty** — its prompt is hidden. **When bash has no tty** (desktop app, CI), use the inline form once; do not run a prompting command that will fail after approval.
- A credential manager helps only when it resolves the value inside the same command (1Password `op run`). Storing the password elsewhere first does not, because `scai` reads credentials only from its own files under `~/.snowflake/scai/connections/`.

## Quick Reference

| Action | Command |
|--------|---------|
| Add connection (interactive, hidden password prompt) | `scai connection add-db2 -s NAME` |
| Add connection (inline, for a caller with no tty) | `scai connection add-db2 -s NAME --auth standard --host HOST --port 50000 --database DB --user USER --password PASS` |
| Test connection | `configure(source_connection=NAME)` (runs the test internally) |
| List connections | `scai connection list -l db2 --json` |
| Set default | `scai connection set-default -l db2 -s NAME` |
| Extract code | `scai code extract -s NAME --json` |
