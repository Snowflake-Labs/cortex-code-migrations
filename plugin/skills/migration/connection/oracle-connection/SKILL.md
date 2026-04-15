---
name: oracle-connection
description: Connect to a source Oracle database for migration to Snowflake using scai CLI. Requires a user-provided Oracle driver (NuGet package). Triggers: oracle, source connection, source database, connect to oracle, add oracle connection.
---

# Oracle Connection Skill

This skill guides you through connecting to a source Oracle database for migration to Snowflake using the `scai` CLI.

## Prerequisites

- Network access to the Oracle database instance
- Oracle credentials (username/password)
- The `scai` CLI installed and available
- The Oracle .NET driver NuGet package (`Oracle.ManagedDataAccess.Core.nupkg`) — **not** the JDBC driver — see Step 1

## Required Connection Details

| Parameter | Required | Description |
|-----------|----------|-------------|
| `-c, --connection` | Yes | Friendly name for this connection |
| `--auth` | Yes | Authentication method (`standard`) |
| `--host` | Yes | Oracle hostname or IP |
| `--port` | No | Port number (default: 1521) |
| `--service-name` | Yes | Oracle service name |
| `--user` | Yes | Oracle username |
| `--password` | Yes | Oracle password (prompted securely) |
| `--connection-timeout` | No | Connection timeout in seconds (default: 30) |

## Workflow

### Step 1: Provision the Oracle Driver

**CRITICAL: The required driver is the `Oracle.ManagedDataAccess.Core` NuGet package. Never refer to it as a JDBC driver — it is not. When communicating with the user, simply call it "the Oracle driver" or "the Oracle NuGet package".**

The user must download the NuGet package and provide its path once via `--driver-path`. SCAI caches the driver at `~/.snowflake/scai/drivers/oracle/` and reuses it machine-wide across all projects automatically.

**First, check if the driver is already cached (look for actual driver files, not just the directory):**

```bash
ls ~/.snowflake/scai/drivers/oracle/*.nupkg ~/.snowflake/scai/drivers/oracle/*.dll 2>/dev/null
```

If no `.nupkg` or `.dll` files are listed, the driver needs to be downloaded.

**Download and cache the driver — run these commands for the user:**

```bash
# macOS / Linux
curl -L -o Oracle.ManagedDataAccess.Core.nupkg \
  https://www.nuget.org/api/v2/package/Oracle.ManagedDataAccess.Core

# Windows PowerShell
curl.exe -L -o Oracle.ManagedDataAccess.Core.nupkg `
  https://www.nuget.org/api/v2/package/Oracle.ManagedDataAccess.Core
```

**IMPORTANT:** Always offer to run the `curl` command for the user. Do not just describe the download — execute it. After downloading, note the full path to the `.nupkg` file — it will be passed via `--driver-path` in Step 4.

### Step 2: Ask How to Provide Credentials

Ask the user:

> "I need the following to connect to Oracle:
> - **Host** (hostname or IP)
> - **Service name**
> - **Username** and **Password**
>
> How would you like to provide these?"

Options:
1. **Enter manually** - Provide values interactively

### Step 3: Add the Connection (Manual Entry)

**Interactive mode (recommended):**
```bash
scai connection add-oracle
```

**Inline mode:**
```bash
scai connection add-oracle \
  -c <CONNECTION_NAME> \
  --auth standard \
  --host <HOST> \
  --port 1521 \
  --service-name <SERVICE_NAME> \
  --user <USERNAME>
```
Password will be prompted securely.

### Step 4: Test the Connection

**Before testing, verify the driver is cached:**

```bash
ls ~/.snowflake/scai/drivers/oracle/*.nupkg ~/.snowflake/scai/drivers/oracle/*.dll 2>/dev/null
```

If **no driver files** are found, you must include `--driver-path` (using the file downloaded in Step 1):

```bash
scai connection test -l oracle -s <CONNECTION_NAME> --driver-path <PATH_TO_NUPKG>
```

If driver files **are** found in the cache, `--driver-path` is not needed:

```bash
scai connection test -l oracle -s <CONNECTION_NAME>
```

**Expected:** "Connection successful" with Oracle version and database details.

**If test fails:** See `./references/REFERENCE.md` for detailed troubleshooting.

**Common errors:**

| Error | Cause | Solution |
|-------|-------|----------|
| `ORA-12154: TNS:could not resolve the connect identifier` | Invalid host or service name | Verify host, port, and service name |
| `ORA-01017: invalid username/password` | Wrong credentials | Check username and password |
| `ORA-12541: TNS:no listener` | Listener not running or wrong port | Verify port number and that the listener is running |
| `Connection timed out` | Network/firewall issue | Check VPN, firewall rules, security groups |
| `Driver not found` | Missing or invalid `--driver-path` | Re-download the NuGet package and verify the file path |

### Step 5: Save Source Connection

After a successful connection test, save the connection name to the session config so other tools can use it:

Call the `configure` tool with `source_connection` set to the `<CONNECTION_NAME>` used above.

## CHECKPOINT

Confirm with user:
- [ ] Oracle driver downloaded and path provided (or already configured)
- [ ] Connection test passed
- [ ] Connection appears in `scai connection list -l oracle`
- [ ] Source connection saved to session config

## Limitations

- **Data migration is not supported for Oracle.** The `scai data migrate` command does not support Oracle as a source. Table data must be migrated through other means (e.g., external ETL tools, Oracle Data Pump, or manual export/import).
- **Data validation is not supported for Oracle.** The 2-sided testing framework (`scai test`) does not support Oracle as a source for baseline capture or result comparison.
- **Supported Oracle operations:** code extraction (`scai code extract`), code conversion (`scai code convert`), and deployment to Snowflake (`scai code deploy`).

## Next Steps

Go back to executing the migration skill.

## Security Rules

- **NEVER** log or display passwords in plain text
- **NEVER** include passwords in command-line arguments that might be logged
- Use interactive mode to avoid password exposure

## Quick Reference

| Action | Command |
|--------|---------|
| Download driver (macOS/Linux) | `curl -L -o Oracle.ManagedDataAccess.Core.nupkg https://www.nuget.org/api/v2/package/Oracle.ManagedDataAccess.Core` |
| Set driver globally | `scai project defaults set --driver-path <PATH_TO_NUPKG>` |
| Add connection (interactive) | `scai connection add-oracle` |
| Add connection (inline) | `scai connection add-oracle -c NAME --auth standard --host HOST --service-name SVC --user USER` |
| Test connection (first time) | `scai connection test -l oracle -s NAME --driver-path <PATH_TO_NUPKG>` |
| Test connection (driver saved) | `scai connection test -l oracle -s NAME` |
| List connections | `scai connection list -l oracle` |
| Set default | `scai connection set-default -l oracle -c NAME` |
| Extract code | `scai code extract -s NAME` |
