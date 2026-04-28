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

The required driver is the `Oracle.ManagedDataAccess.Core` NuGet package. Resolve it by following the canonical bootstrap flow:

> **Driver bootstrap:** see [`../references/driver-bootstrap.md`](../references/driver-bootstrap.md) with parameters
> `<dialect>=oracle`, `<package>=Oracle.ManagedDataAccess.Core`, `<driver_file>=Oracle.ManagedDataAccess.Core.nupkg`,
> `<cache_dir>=~/.snowflake/scai/drivers/oracle/`,
> `<nuget_url>=https://www.nuget.org/api/v2/package/Oracle.ManagedDataAccess.Core`.

That doc walks through cache check → ask-on-miss → user-provided path or download → first SCAI invocation with `--driver-path` if needed. Follow it silently — don't narrate "the bootstrap flow" or step labels to the user.

**Naming guard:** the driver is a `.NET` NuGet package, **not** a JDBC driver. Refer to it only as "the Oracle driver" or "the Oracle NuGet package" when talking to the user.

For this skill specifically, the first SCAI invocation called out by the bootstrap is the `connection test` command in **Step 4 below** — pass `--driver-path <PATH>` there if the driver wasn't already cached.

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

This is the "first SCAI invocation" called out as 1e in the bootstrap reference. Use the path resolved in Step 1:

```bash
# Branch A or B in Step 1 (driver not yet cached) — pass --driver-path once
scai connection test -l oracle -s <CONNECTION_NAME> --driver-path <PATH_TO_NUPKG>

# Step 1 hit the cache — --driver-path not needed
scai connection test -l oracle -s <CONNECTION_NAME>
```

The first call with `--driver-path` copies the driver into `~/.snowflake/scai/drivers/oracle/`, so every subsequent `scai` command (in this project or any other) can omit the flag.

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
- [ ] Oracle driver resolved via one of:
  - [ ] Already cached in `~/.snowflake/scai/drivers/oracle/` (Step 1a)
  - [ ] User-provided local path supplied via `--driver-path` (Step 1c)
  - [ ] Downloaded by the agent and supplied via `--driver-path` (Step 1d)
- [ ] Connection test passed
- [ ] Connection appears in `scai connection list -l oracle`
- [ ] Source connection saved to session config

## Limitations

- **Data migration is not supported for Oracle.** The `scai data migrate` command does not support Oracle as a source. Table data must be migrated through other means (e.g., external ETL tools, Oracle Data Pump, or manual export/import).
- **Data validation is not supported for Oracle.** The 2-sided testing framework (`scai test`) does not support Oracle as a source for baseline capture or result comparison.
- **Supported Oracle operations:** code extraction (`scai code extract`), code conversion (`scai code convert`), and deployment to Snowflake (`scai code deploy`).

## On Completion

After the CHECKPOINT passes, tell the user:
> **Connection configured** — Successfully connected to Oracle using connection `<connection_name>`.

Then return to the calling skill.

## Security Rules

- **NEVER** log or display passwords in plain text
- **NEVER** include passwords in command-line arguments that might be logged
- Use interactive mode to avoid password exposure

## Quick Reference

| Action | Command |
|--------|---------|
| Check driver cache | `ls ~/.snowflake/scai/drivers/oracle/*.nupkg ~/.snowflake/scai/drivers/oracle/*.dll 2>/dev/null` |
| Use existing local driver | `scai project defaults set -s <CONNECTION_NAME> --driver-path <PATH_TO_NUPKG>` |
| Download driver (macOS/Linux) | `curl -L -o Oracle.ManagedDataAccess.Core.nupkg https://www.nuget.org/api/v2/package/Oracle.ManagedDataAccess.Core` |
| Add connection (interactive) | `scai connection add-oracle` |
| Add connection (inline) | `scai connection add-oracle -c NAME --auth standard --host HOST --service-name SVC --user USER` |
| Test connection (first time) | `scai connection test -l oracle -s NAME --driver-path <PATH_TO_NUPKG>` |
| Test connection (driver cached) | `scai connection test -l oracle -s NAME` |
| List connections | `scai connection list -l oracle` |
| Set default | `scai connection set-default -l oracle -c NAME` |
| Extract code | `scai code extract -s NAME` |
