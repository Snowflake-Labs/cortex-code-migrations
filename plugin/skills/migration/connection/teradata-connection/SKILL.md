---
name: teradata-connection
description: Connect to a source Teradata database for migration to Snowflake using scai CLI. Requires a user-provided Teradata driver (NuGet package). Triggers: teradata, source connection, source database, connect to teradata, add teradata connection.
---

# Teradata Connection Skill

This skill guides you through connecting to a source Teradata database for migration to Snowflake using the `scai` CLI.

## Prerequisites

- Network access to the Teradata database instance
- Teradata credentials (username/password) — standard or LDAP-backed
- The `scai` CLI installed and available
- The Teradata .NET driver NuGet package (`Teradata.Client.Provider.nupkg`) — see Step 1

## Required Connection Details

| Parameter | Required | Description |
|-----------|----------|-------------|
| `-s, --source-connection` | Yes | Friendly name for this connection |
| `--auth` | Yes | Authentication method (`standard` or `ldap`) |
| `--host` | Yes | Teradata hostname or IP |
| `--database` | Yes | Teradata database name |
| `--port` | No | Port number (default: 1025) |
| `--user` | Yes | Teradata username |
| `--password` | Yes | Teradata password (prompted securely) |
| `--connection-timeout` | No | Connection timeout in seconds (default: 30) |

## Workflow

### Step 1: Provision the Teradata Driver

**CRITICAL: The required driver is the `Teradata.Client.Provider` NuGet package. Never refer to it as a JDBC driver — it is not. When communicating with the user, simply call it "the Teradata driver" or "the Teradata NuGet package".**

The user must download the NuGet package and provide its path once via `--driver-path`. SCAI caches the driver at `~/.snowflake/scai/drivers/teradata/` and reuses it machine-wide across all projects automatically.

**First, check if the driver is already cached (look for actual driver files, not just the directory):**

```bash
ls ~/.snowflake/scai/drivers/teradata/*.nupkg ~/.snowflake/scai/drivers/teradata/*.dll 2>/dev/null
```

If no `.nupkg` or `.dll` files are listed, the driver needs to be downloaded.

**Download and cache the driver — run these commands for the user:**

```bash
# macOS / Linux
curl -L -o Teradata.Client.Provider.nupkg \
  https://www.nuget.org/api/v2/package/Teradata.Client.Provider

# Windows PowerShell
curl.exe -L -o Teradata.Client.Provider.nupkg `
  https://www.nuget.org/api/v2/package/Teradata.Client.Provider
```

**IMPORTANT:** Always offer to run the `curl` command for the user. Do not just describe the download — execute it. After downloading, note the full path to the `.nupkg` file — it will be passed via `--driver-path` in Step 4.

### Step 2: Ask How to Provide Credentials

Ask the user:

> "I need the following to connect to Teradata:
> - **Host** (hostname or IP)
> - **Database** name
> - **Username** and **Password**
> - **Authentication method** — `standard` (username/password) or `ldap` (LDAP-backed credentials)
>
> How would you like to provide these?"

Options:
1. **Enter manually** - Provide values interactively

### Step 3: Add the Connection (Manual Entry)

**Interactive mode (recommended):**
```bash
scai connection add-teradata
```

**Inline mode (standard auth):**
```bash
scai connection add-teradata \
  -s <CONNECTION_NAME> \
  --auth standard \
  --host <HOST> \
  --database <DATABASE> \
  --port 1025 \
  --user <USERNAME>
```

**Inline mode (LDAP auth):**
```bash
scai connection add-teradata \
  -s <CONNECTION_NAME> \
  --auth ldap \
  --host <HOST> \
  --database <DATABASE> \
  --user <USERNAME>
```

Password will be prompted securely.

### Step 4: Test the Connection

**Before testing, verify the driver is cached:**

```bash
ls ~/.snowflake/scai/drivers/teradata/*.nupkg ~/.snowflake/scai/drivers/teradata/*.dll 2>/dev/null
```

If **no driver files** are found, you must include `--driver-path` (using the file downloaded in Step 1):

```bash
scai connection test -l teradata -s <CONNECTION_NAME> --driver-path <PATH_TO_NUPKG>
```

If driver files **are** found in the cache, `--driver-path` is not needed:

```bash
scai connection test -l teradata -s <CONNECTION_NAME>
```

**Expected:** "Connection successful" with Teradata version and database details.

**If test fails:** See `./references/REFERENCE.md` for detailed troubleshooting.

**Common errors:**

| Error | Cause | Solution |
|-------|-------|----------|
| `Socket closed` | Invalid host or port | Verify host and port (default 1025) |
| `Logon failed` | Wrong credentials | Check username and password |
| `Database does not exist` | Invalid database name | Verify the database name |
| `Connection timed out` | Network/firewall issue | Check VPN, firewall rules, security groups |
| `Driver not found` | Missing or invalid `--driver-path` | Re-download the NuGet package and verify the file path |
| `LDAP authentication failed` | Invalid LDAP credentials | Verify LDAP username and password with your admin |

### Step 5: Save Source Connection

After a successful connection test, save the connection name to the session config so other tools can use it:

Call the `configure` tool with `source_connection` set to the `<CONNECTION_NAME>` used above.

## CHECKPOINT

Confirm with user:
- [ ] Teradata driver downloaded and path provided (or already cached)
- [ ] Connection test passed
- [ ] Connection appears in `scai connection list -l teradata`
- [ ] Source connection saved to session config

## Limitations

- **Data migration is not supported for Teradata.** The `scai data migrate` command does not support Teradata as a source. Table data must be migrated through other means (e.g., Teradata Parallel Transporter, external ETL tools, or manual export/import).
- **Data validation is not supported for Teradata.** The 2-sided testing framework (`scai test`) does not support Teradata as a source for baseline capture or result comparison.
- **Supported Teradata operations:** code extraction (`scai code extract`), code conversion (`scai code convert`), and deployment to Snowflake (`scai code deploy`).

## Next Steps

Go back to executing the migration skill.

## Security Rules

- **NEVER** log or display passwords in plain text
- **NEVER** include passwords in command-line arguments that might be logged
- Use interactive mode to avoid password exposure

## Quick Reference

| Action | Command |
|--------|---------|
| Download driver (macOS/Linux) | `curl -L -o Teradata.Client.Provider.nupkg https://www.nuget.org/api/v2/package/Teradata.Client.Provider` |
| Set driver globally | `scai project defaults set --driver-path <PATH_TO_NUPKG>` |
| Add connection (interactive) | `scai connection add-teradata` |
| Add connection (standard) | `scai connection add-teradata -s NAME --auth standard --host HOST --database DB --user USER` |
| Add connection (LDAP) | `scai connection add-teradata -s NAME --auth ldap --host HOST --database DB --user USER` |
| Test connection (first time) | `scai connection test -l teradata -s NAME --driver-path <PATH_TO_NUPKG>` |
| Test connection (driver saved) | `scai connection test -l teradata -s NAME` |
| List connections | `scai connection list -l teradata` |
| Set default | `scai connection set-default -l teradata -s NAME` |
| Extract code | `scai code extract -s NAME` |
