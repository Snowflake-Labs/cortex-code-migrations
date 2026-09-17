---
name: azure-synapse-connection
description: Connect to a source Azure Synapse database for full migration to Snowflake using scai CLI (code extract, scai test, cloud table data migration/validation). Triggers: azure synapse, synapse, source connection, connect to synapse, add synapse connection.
license: Proprietary. See License-Skills for complete terms
---

# Azure Synapse Connection Skill

## On Entry

Tell the user:
> **Setting up Azure Synapse connection** — I'll configure and test a connection to your source Azure Synapse SQL pool. I'll need server URL, database, pool type, and credentials shortly.

## Prerequisites

- Network access to the Azure Synapse workspace SQL endpoint
- Credentials for **standard** (SQL auth), **service-principal** (Azure AD app), or **interactive** (Azure AD browser) authentication
- The `scai` CLI installed and available
- Whether the target is a **dedicated** SQL pool or **serverless** SQL pool

## Required Connection Details

| Parameter | Required | Description |
|-----------|----------|-------------|
| `-s, --source-connection` | Yes | Friendly name for this connection |
| `--auth` | Yes | `standard`, `service-principal`, or `interactive` |
| `--server-url` | Yes | Synapse workspace SQL endpoint (e.g. `myworkspace.sql.azuresynapse.net`) |
| `--database` | Yes | Database name |
| `--pool-type` | Yes | `dedicated` or `serverless` |
| `--user` | For standard / service-principal | SQL username or Azure AD client ID |
| `--password` | For standard / service-principal | SQL password or client secret (prompted securely) |
| `--port` | No | Port number (default: 1433) |
| `--trust-server-certificate` | No | Trust server certificate |
| `--encrypt` | No | Encrypt connection (default: true) |

## Workflow

### Step 1: Ask How to Provide Credentials

Ask the user:

> "I need the following to connect to Azure Synapse:
> - **Server URL** (workspace SQL endpoint)
> - **Database name**
> - **Pool type** — dedicated SQL pool or serverless SQL pool
> - **Authentication** — standard SQL login, service principal, or interactive Azure AD
>
> How would you like to provide these?"

Options:
1. **1Password** — credentials stored in 1Password vault
2. **Enter manually** — provide values interactively

### Step 2: Route Based on Answer

| User says | Action |
|-----------|--------|
| "1Password" | Follow `../1PASSWORD.md` |
| "Enter manually" | Proceed to Step 3 (manual entry) |
| Other credential manager | Check if `../references/<NAME>.md` exists; if not, ask user to explain their setup |

### Step 3: Add the Connection (Manual Entry)

**Interactive mode (recommended):**
```bash
scai connection add-synapse
```

**Inline mode (standard auth, dedicated pool):**
```bash
scai connection add-synapse \
  -s <SOURCE_CONNECTION_NAME> \
  --auth standard \
  --server-url <SERVER_URL> \
  --database <DATABASE> \
  --pool-type dedicated \
  --user <USERNAME>
```

**Inline mode (service principal, serverless pool):**
```bash
scai connection add-synapse \
  -s <SOURCE_CONNECTION_NAME> \
  --auth service-principal \
  --server-url <SERVER_URL> \
  --database <DATABASE> \
  --pool-type serverless \
  --user <CLIENT_ID>
```

Password or client secret will be prompted securely.

### Step 4: Save and Test Source Connection

Call the `configure` tool with `source_connection` set to `<SOURCE_CONNECTION_NAME>`. The MCP server runs `scai connection test` internally and only persists the connection if the test passes.

- **On success:** the response includes `connection_test: ok`.
- **On failure:** the tool returns an error containing the scai message. Surface it to the user, help them fix the issue, then re-run `configure(source_connection=<SOURCE_CONNECTION_NAME>)`.

## CHECKPOINT

Confirm with user:
- [ ] `configure` returned `connection_test: ok`
- [ ] Connection appears in `scai connection list -l AzureSynapse --json`
- [ ] Source connection saved to session config
- [ ] Pool type (`dedicated` vs `serverless`) matches the user's Synapse deployment

## On Completion

After the CHECKPOINT passes, tell the user:
> **Connection configured** — Successfully connected to Azure Synapse using connection `<connection_name>`.

Then return to the calling skill.

## Supported Operations

With a configured Azure Synapse source connection, the project supports:

- `scai code extract` — pull DDL and code from the source database
- `scai code convert` / deploy / `scai test` — full migration object workflow
- `migrate_data` / `validate_data` — cloud table data migration and validation (ODBC `regular` or `cet_as` extraction)

## Legacy Projects

> **Legacy projects:** If an older project has `project_type: code_conversion_only` in `project.yml`, the CLI honors that setting and routes through the code-conversion-only flow. New Azure Synapse projects default to `full_migration`.

## Security Rules

- **NEVER** log or display passwords or client secrets in plain text
- **NEVER** include secrets in command-line arguments that might be logged
- Use interactive mode or credential managers to avoid secret exposure

## Quick Reference

| Action | Command |
|--------|---------|
| Add connection (interactive) | `scai connection add-synapse` |
| Add connection (inline) | `scai connection add-synapse -s NAME --auth standard --server-url HOST --database DB --pool-type dedicated --user USER` |
| Test connection | `configure(source_connection=NAME)` (runs the test internally) |
| List connections | `scai connection list -l AzureSynapse --json` |
