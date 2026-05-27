---
name: postgresql-connection
description: Connect to a source PostgreSQL database for migration to Snowflake using scai CLI. Triggers: postgresql, postgres, source connection, source database, connect to postgresql, add postgresql connection.
license: Proprietary. See License-Skills for complete terms
---

# PostgreSQL Connection Skill

## On Entry

Tell the user:
> **Setting up PostgreSQL connection** — I'll configure and test a connection to your source PostgreSQL database. I'll need a few connection details.

## Prerequisites

- Network access to the PostgreSQL host (managed: RDS / Cloud SQL / Azure / Supabase / Neon, or self-hosted)
- PostgreSQL username and password
- The `scai` CLI installed and available

## Required Connection Details

### Standard Auth (only auth method supported in MVP)

| Parameter | Required | Description |
|-----------|----------|-------------|
| `-c, --connection` | Yes | Friendly name for this connection |
| `--auth` | Yes | `standard` |
| `--host` | Yes | PostgreSQL host |
| `--port` | No | TCP port (default: `5432`) |
| `--database` | Yes | Database name |
| `--user` | Yes | PostgreSQL username |
| `--password` | Yes | PostgreSQL password |
| `--ssl-mode` | No | One of `Disable`, `Allow`, `Prefer`, `Require`, `VerifyCA`, `VerifyFull` (default: `Require`) |
| `--connection-timeout` | No | Connection timeout in seconds |

> SSL defaults to `Require` so managed PG (RDS, Cloud SQL, Azure, Supabase, Neon) works out of the box. For local Docker / dev, override with `--ssl-mode Disable` explicitly.

## Workflow

### Step 1: Ask How to Provide Credentials

Ask the user:
> "I need the following to connect to PostgreSQL:
> - **Host** and (optionally) **port**
> - **Database name**
> - **Username** and **password**
> - **SSL mode** (default `Require` is right for managed PG)
>
> How would you like to provide these?"

Options:
1. **1Password** — Credentials stored in 1Password vault
2. **Enter manually** — Provide values interactively

### Step 2: Route Based on Answer

| User says | Action |
|-----------|--------|
| "1Password" | Follow `../1PASSWORD.md` (PostgreSQL section, if present; otherwise treat as manual entry with secrets retrieved by the user) |
| "Enter manually" | Proceed to Step 3 |
| Other credential manager | Check if `../references/<NAME>.md` exists; if not, ask user to explain their setup |

### Step 3: Add the Connection (Manual Entry)

**Interactive mode (recommended):**

```bash
scai connection add-postgresql
```

**Standard auth (inline):**

```bash
scai connection add-postgresql \
  -c <CONNECTION_NAME> \
  --auth standard \
  --host <HOST> \
  --port 5432 \
  --database <DATABASE> \
  --user <USERNAME> \
  --password <PASSWORD> \
  --ssl-mode Require
```

For local Docker / unencrypted dev databases:

```bash
scai connection add-postgresql \
  -c <CONNECTION_NAME> \
  --auth standard \
  --host localhost \
  --port 5432 \
  --database <DATABASE> \
  --user <USERNAME> \
  --password <PASSWORD> \
  --ssl-mode Disable
```

### Step 4: Save and Test Source Connection

Call the `configure` tool with `source_connection` set to `<CONNECTION_NAME>`. The MCP server runs `scai connection test` internally and only persists the connection if the test passes.

- **On success:** the response includes `connection_test: ok`.
- **On failure:** the tool returns an error containing the scai message. Surface it to the user, help them fix the issue, then re-run `configure(source_connection=<CONNECTION_NAME>)`.

**Common errors:**

| Error | Cause | Solution |
|-------|-------|----------|
| `Operation timed out` | Network / firewall | Check VPN, security groups, firewall rules |
| `database "X" does not exist` | Wrong database name | Verify against the server (`\l` in `psql`) |
| `password authentication failed` | Bad credentials | Re-check username and password |
| `SSL connection required` | `ssl-mode` too permissive | Use `Require` for managed hosts |
| `SSL is not enabled on the server` | Server doesn't support SSL | Use `--ssl-mode Disable` for local dev only |

## CHECKPOINT

Confirm with user:
- [ ] `configure` returned `connection_test: ok`
- [ ] Connection appears in `scai connection list -l postgresql --json`
- [ ] Source connection saved to session config

## On Completion

After the CHECKPOINT passes, tell the user:
> **Connection configured** — Successfully connected to PostgreSQL using connection `<connection_name>`.

Then return to the calling skill.

## Security Rules

- **NEVER** log or display secrets (passwords) in plain text.
- **NEVER** include secrets in command-line arguments that might be logged. Prefer interactive mode or a credential manager.
- For managed PG, keep `--ssl-mode Require` (or stricter). Only relax for trusted local dev.

## Quick Reference

| Action | Command |
|--------|---------|
| Add connection (interactive) | `scai connection add-postgresql` |
| Add standard auth | `scai connection add-postgresql -c NAME --auth standard --host HOST --database DB --user USER --password PASS` |
| Test connection | `configure(source_connection=NAME)` (runs the test internally) |
| List connections | `scai connection list -l postgresql --json` |
| Set default | `scai connection set-default -l postgresql -c NAME` |
| Extract code | `scai code extract -s NAME --json` |
