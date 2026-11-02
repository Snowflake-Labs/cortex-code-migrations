---
name: oracle-connection
description: Connect to a source Oracle database for migration to Snowflake using scai CLI. Requires a user-provided Oracle driver (NuGet package). Triggers: oracle, source connection, source database, connect to oracle, add oracle connection.
---

# Oracle Connection Skill

## On Entry

Tell the user:
> **Setting up Oracle connection** — I'll configure and test a connection to your source Oracle database. This requires a driver download on first use.

## Prerequisites

- Network access to the Oracle database instance
- Oracle credentials (username/password)
- The `scai` CLI installed and available
- The Oracle .NET driver NuGet package (`Oracle.ManagedDataAccess.Core.nupkg`) — **not** the JDBC driver — see Step 1

## Required Connection Details

| Parameter | Required | Description |
|-----------|----------|-------------|
| `-s, --source-connection` | Yes | Friendly name for this connection |
| `--auth` | Yes | Authentication method (`standard`) |
| `--host` | Yes | Oracle hostname or IP |
| `--port` | No | Port number (default: 1521) |
| `--service-name` | Yes | Oracle service name |
| `--user` | Yes | Oracle username |
| `--password` | Yes | Oracle password (prompted securely) |
| `--connection-timeout` | No | Connection timeout in seconds (default: 30) |

## Workflow

### Step 1: Provision the Oracle Driver

The required driver is the `Oracle.ManagedDataAccess.Core` NuGet package. Resolve it by following the canonical bootstrap flow:

> **Driver bootstrap:** see [`../references/driver-bootstrap.md`](../references/driver-bootstrap.md) with parameters
> `<dialect>=oracle`, `<package>=Oracle.ManagedDataAccess.Core`, `<driver_file>=Oracle.ManagedDataAccess.Core.nupkg`,
> `<cache_dir>=~/.snowflake/scai/drivers/oracle/`,
> `<nuget_url>=https://www.nuget.org/api/v2/package/Oracle.ManagedDataAccess.Core`.

That doc walks through cache check → ask-on-miss → user-provided path or download → first SCAI invocation with `--driver-path` if needed. Follow it silently — don't narrate "the bootstrap flow" or step labels to the user.

**Naming guard:** the driver is a `.NET` NuGet package, **not** a JDBC driver. Refer to it only as "the Oracle driver" or "the Oracle NuGet package" when talking to the user.

For this skill specifically, the first SCAI invocation called out by the bootstrap is the `configure` tool call in **Step 4 below** — pass `driver_path=<PATH>` there if the driver wasn't already cached. The MCP server invokes `scai connection test --driver-path <PATH>` internally, which seeds the driver cache.

### Step 2: Ask How to Provide Credentials

Ask the user:

> "I need the following to connect to Oracle:
> - **Host** (hostname or IP)
> - **Service name**
> - **Username**
>
> How would you like to provide these? For security, enter the password only in the masked terminal prompt; do not send it in chat."

Options:
1. **1Password** - Credentials stored in 1Password vault
2. **Enter manually** - Provide values directly

Route on the answer:

| User says | Action |
|-----------|--------|
| "1Password" | Follow `../1PASSWORD.md` (Oracle section) |
| "Enter manually" | Proceed to Step 3 |
| Other credential manager | Check if `../references/<NAME>.md` exists; if not, ask user to explain their setup. Prefer managers that resolve the value inside the same command (`op run`); a store `scai` cannot read is not a path. |

### Step 3: Add the Connection (Manual Entry)

```bash
scai connection add-oracle \
  -s <CONNECTION_NAME> \
  --auth standard \
  --host <HOST> \
  --port 1521 \
  --service-name <SERVICE_NAME> \
  --user <USERNAME>
```

- Omit `--port` if the listener uses the default (`1521`).
- The CLI prompts for the password securely. Never include it in the command line.
- When your `bash` has no terminal (the desktop app), that prompt cannot be answered. Get the password with the app's `request_secret` tool and follow the app's rule for filling it into the command; never ask for it in chat.

### Step 4: Save and Test Source Connection

This is the "first SCAI invocation" called out as 1e in the bootstrap reference. Use the path resolved in Step 1.

Call the `configure` tool with `source_connection` set to `<CONNECTION_NAME>`. The MCP server runs `scai connection test` internally and only persists the connection if the test passes.

- **First use (driver not yet cached):** also pass `driver_path=<PATH_TO_NUPKG>`. The first call copies the driver into `~/.snowflake/scai/drivers/oracle/`, so every subsequent `configure` call (in this project or any other) can omit `driver_path`.

  ```
  configure(source_connection=<CONNECTION_NAME>, driver_path=<PATH_TO_NUPKG>)
  ```

- **Driver already cached:** omit `driver_path`.

  ```
  configure(source_connection=<CONNECTION_NAME>)
  ```

- **On success:** the response includes `connection_test: ok`.
- **On failure:** the tool returns an error containing the scai message. Surface it to the user, help them fix the issue, then re-run `configure(...)`. See `./references/REFERENCE.md` for detailed troubleshooting.

**Common errors:**

| Error | Cause | Solution |
|-------|-------|----------|
| `ORA-12154: TNS:could not resolve the connect identifier` | Invalid host or service name | Verify host, port, and service name |
| `ORA-01017: invalid username/password` | Wrong credentials | Check username and password |
| `ORA-12541: TNS:no listener` | Listener not running or wrong port | Verify port number and that the listener is running |
| `Connection timed out` | Network/firewall issue | Check VPN, firewall rules, security groups |
| `Driver not found` | Missing or invalid `driver_path` | Re-download the NuGet package and verify the file path |

## CHECKPOINT

Confirm with user:
- [ ] Oracle driver resolved via one of:
  - [ ] Already cached in `~/.snowflake/scai/drivers/oracle/` (Step 1a)
  - [ ] User-provided local path supplied via `driver_path` (Step 1c)
  - [ ] Downloaded by the agent and supplied via `driver_path` (Step 1d)
- [ ] `configure` returned `connection_test: ok`
- [ ] Connection appears in `scai connection list -l oracle --json`
- [ ] Source connection saved to session config

## On Completion

After the CHECKPOINT passes, tell the user:
> **Connection configured** — Successfully connected to Oracle using connection `<connection_name>`.

Then return to the calling skill.

## Security Rules

- **NEVER** log or display secrets (passwords) in plain text.
- **NEVER** include secrets in command-line arguments that might be logged. Omit `--password`; the CLI prompts for it securely in an interactive terminal.
- A credential manager helps only when it resolves the value inside the same command (1Password `op run`). Storing the password elsewhere first does not, because `scai` reads credentials only from its own files under `~/.snowflake/scai/connections/`.

## Quick Reference

| Action | Command |
|--------|---------|
| Check driver cache | List `.nupkg`/`.dll` files in `~/.snowflake/scai/drivers/oracle/` (POSIX) or `%USERPROFILE%\.snowflake\scai\drivers\oracle\` (Windows) |
| Use existing local driver | `scai project defaults set -s <CONNECTION_NAME> --driver-path <PATH_TO_NUPKG>` |
| Download driver (macOS/Linux) | `curl -L -o Oracle.ManagedDataAccess.Core.nupkg https://www.nuget.org/api/v2/package/Oracle.ManagedDataAccess.Core` |
| Download driver (Windows PowerShell) | `curl.exe -L -o Oracle.ManagedDataAccess.Core.nupkg https://www.nuget.org/api/v2/package/Oracle.ManagedDataAccess.Core` |
| Add connection (inline) | `scai connection add-oracle -s NAME --auth standard --host HOST --service-name SVC --user USER` |
| Test connection (first time) | `configure(source_connection=NAME, driver_path=<PATH_TO_NUPKG>)` |
| Test connection (driver cached) | `configure(source_connection=NAME)` |
| List connections | `scai connection list -l oracle --json` |
| Set default | `scai connection set-default -l oracle -s NAME` |
| Extract code | `scai code extract -s NAME --json` |
