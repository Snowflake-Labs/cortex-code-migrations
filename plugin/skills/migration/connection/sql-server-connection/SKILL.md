---
name: sql-server-connection
description: Connect to a source SQL Server database for migration to Snowflake using scai CLI. Triggers: sql server, sqlserver, source connection, source database, connect to sql server, add sql server connection, windows authentication, integrated security, kerberos.
license: Proprietary. See License-Skills for complete terms
---

# SQL Server Connection Skill

## On Entry

Tell the user:
> **Setting up SQL Server connection** — I'll configure and test a connection to your source SQL Server database. I'll need some connection details from you shortly.

## Prerequisites

- Network access to the SQL Server instance
- SQL Server credentials (username/password for Standard auth, or domain credentials for Windows auth)
- The `scai` CLI installed and available

## Required Connection Details

| Parameter | Required | Description |
|-----------|----------|-------------|
| `-s, --source-connection` | Yes | Friendly name for this connection |
| `--auth` | Yes | Authentication method: `standard` or `windows` |
| `--server-url` | Yes | SQL Server hostname or IP |
| `--database` | Yes | Default database; the connection still reaches every database on the server |
| `--user` | For standard auth | SQL Server username |
| `--password` | For standard auth | SQL Server password (prompted securely) |
| `--port` | No | Port number (default: 1433) |
| `--trust-server-certificate` | No | Trust server certificate |
| `--encrypt` | No | Encrypt connection |
| `kerberos_principal` | SPCS Windows auth | Client principal (`client@REALM`) written on the profile after `add-sql-server`. Not a SQL username. |

### One connection covers every database on the server

`--database` is only the connection's default. Extraction reaches the server's other databases with `-d` (`scai code extract -s <NAME> -d A,B`, see `../../register-code-units/extract-code-units/SKILL.md`), and deploy, migrate and validate find each object's database through the project's database bindings.

- **Never** create one connection per database: a project spanning several databases on one server uses one connection.
- **Never** point the connection at `master` or another system database to "cover" several; pick a user database the project migrates.
- "A connection with both databases" (or several) means one connection whose default is one of them, then extracting with `-d A,B`. Tell the user so.

## Workflow

### Step 1: Ask which authentication the server accepts

Skip this question when the user already said Windows authentication is required; go to Step 1b. Skip it when they already said SQL authentication; go to Step 1c.

Ask the user:

> How should I sign in to this SQL Server?
> 1. SQL authentication — username and password
> 2. Windows authentication — a domain account, no SQL login

**Wait for the user's response — do not proceed until they choose.**

| Answer | Action |
|--------|--------|
| SQL authentication | Step 1c, then Step 2 |
| Windows authentication | Step 1b |

### Step 1b: Where the worker runs

Ask the user:

> Windows authentication uses the account that is already signed in when the worker runs on a domain-joined Windows machine. On Snowpark Container Services the worker is Linux, so it needs a Kerberos keytab. Where will the Data Exchange Worker run?
> 1. On a domain-joined Windows machine
> 2. On Snowpark Container Services

**Wait for the user's response — do not proceed until they choose.**

| Answer | Action |
|--------|--------|
| Domain-joined Windows machine | Step 3 (Windows on this host), then Step 4. When this session is WSL or Linux, follow `./references/wsl-windows-auth.md` before Step 4. |
| Snowpark Container Services | Read [`../../data-infrastructure/references/sqlserver-spcs-windows-auth.md`](../../data-infrastructure/references/sqlserver-spcs-windows-auth.md) and complete only **Save the source connection**. Then Step 4. |

### Step 1c: Ask how to provide SQL credentials

Ask the user:

> I need the following to connect to SQL Server:
> - **Server URL** (hostname or IP)
> - **Default database** (a user database, not `master`; the connection still reaches the server's other databases)
> - **Username** and **Password**
>
> How would you like to provide these?

Options:
1. **1Password** - Credentials stored in 1Password vault
2. **Enter manually** - Provide values interactively

### Step 2: Route Based on Answer

| User says | Action |
|-----------|--------|
| "1Password" | Follow `../1PASSWORD.md` |
| "Enter manually" | Proceed to Step 3 (manual entry) |
| Other credential manager | Check if `../references/<NAME>.md` exists; if not, ask user to explain their setup |

### Step 3: Add the Connection

**SQL authentication, interactive:**
```bash
scai connection add-sql-server
```

Enter the password only at the CLI's hidden prompt. If a CI runner already
injects it through a named environment variable, keep the command text opaque:
reference the variable (for example, `--password "$PASSWORD_ENV_VAR"`), never
copy its value into the command. Inspect variable names only; never print the
environment or the variable's value.

**SQL authentication, inline.** Password is prompted securely. Use the port
the user supplied (`--port`); do not assume 1433 when they named a different
one.
```bash
scai connection add-sql-server \
  -s <SOURCE_CONNECTION_NAME> \
  --auth standard \
  --server-url <SERVER_URL> \
  --port <PORT> \
  --database <DATABASE> \
  --user <USERNAME> \
  --trust-server-certificate
```

**Windows authentication on this host.** No username and no password:
```bash
scai connection add-sql-server \
  -s <SOURCE_CONNECTION_NAME> \
  --auth windows \
  --server-url <SERVER_URL> \
  --port 1433 \
  --database <DATABASE>
```

Snowpark Container Services Windows authentication is added from the reference in Step 1b. Do not add it again here.

**Correcting a saved profile** (a wrong database, host, port, user or password):
re-run the same `add-sql-server` command under the same `-s` name with every
field, the corrected one included, plus `--replace` and `--json`. That updates
the profile in place, so the project's `source_connection` still names it. Do
not remove and re-add it. Without `--replace` the CLI refuses the name with
`CNX0002` and keeps the old profile. Never pipe `add-sql-server` through `tail`
or `head`. Read its JSON: unless it says `"success":true`, the correction was
not saved, so surface the error instead of re-testing.

Do not use `docker exec`, `sqlcmd -P`, `echo`, or `printf` with a password to
diagnose this connection. Use `scai connection test` through `configure` below.
When the user already supplied a database, do not enumerate databases first.

### Step 4: Save and Test Source Connection

When Step 1b already followed the SPCS Windows authentication reference, that file already called `configure`. Use its result for the checkpoint below. Do not call `configure` again on this visit.

Otherwise call the `configure` tool with `source_connection` set to `<SOURCE_CONNECTION_NAME>`. The MCP server runs `scai connection test` internally and only persists the connection if the test passes.

- **On success:** the response includes `connection_test: ok`.
- **On failure:** the tool returns an error containing the scai message. Surface it to the user, help them fix the issue, then re-run `configure(source_connection=<SOURCE_CONNECTION_NAME>)`. See `./references/REFERENCE.md` for troubleshooting.
- **SPCS Windows authentication, and this machine cannot sign in:** apply **When the local test cannot pass** in [`../../data-infrastructure/references/sqlserver-spcs-windows-auth.md`](../../data-infrastructure/references/sqlserver-spcs-windows-auth.md). When they choose "only the SPCS worker", the profile stays saved and this checkpoint does not require `connection_test: ok`.
- **`OpenSSL library could not be loaded` on macOS** (ODBC Driver 17 or 18): follow "macOS: the ODBC driver can't load OpenSSL" in `./references/REFERENCE.md`: check where Homebrew's `openssl` alias points, lead with the tested no-`sudo` `DYLD_LIBRARY_PATH` step, label the alias repoint "likely, unverified", and never offer links into `/usr/local/lib`; then re-test. Do not upgrade `msodbcsql18`. Switching to Direct does not avoid it: `--direct` reads the source with the same mssql-python driver as the worker, and a working `query_source` (.NET SqlClient) proves nothing about that driver.
- **`Cannot open database "<name>" requested by the login`** (SQL Server 4060, even when it ends "Login failed for user"): the sign-in was accepted; that database is missing or the login isn't mapped to it. Say exactly that. Do not ask for the password again, do not re-run `configure`, and do not create probe profiles on other databases. Follow "Cannot open database (4060)" in `./references/REFERENCE.md`: ask via `ask_user_question` *"May I list the databases `<USERNAME>` can open on this server?"* (**List them** / **I'll type the name**); on yes, run its one read-only `scai query ... --database master`, show the list and ask which to use, even when only one is listed. **Wait for the user's response — do not proceed until they choose.** Never change a connection's database without the user's confirmation: everything extracted without `-d` comes from that database. Then correct the profile with `--replace --json` and re-run `configure` once.

## CHECKPOINT

Confirm with user:
- [ ] `configure` returned `connection_test: ok`, or the SPCS Windows path left the profile saved because this machine cannot sign in
- [ ] Connection appears in `scai connection list -l sqlserver --json`
- [ ] SPCS Windows path: `credentialsMaskedJson` includes `kerberos_principal`
- [ ] Source connection saved to session config when the test passed

## On Completion

After the CHECKPOINT passes with `connection_test: ok`, tell the user:
> **Connection configured** — Successfully connected to SQL Server using connection `<connection_name>`.

When the SPCS Windows path saved the profile and this machine could not sign in, tell the user:
> **Connection profile saved** — `<connection_name>` is ready for the Snowpark Container Services worker. This machine is not the session source until a sign-in from here succeeds.

Then return to the calling skill.

## Security Rules

- **NEVER** log or display passwords in plain text
- **NEVER** include passwords in command-line arguments that might be logged
- **NEVER** repeat a user-supplied password in a Bash tool call, including
  `--password`, `sqlcmd -P`, `docker exec`, `echo`, or `printf`
- **NEVER** write the password characters in an assistant message. Saying you
  will not inline it is still a repeat when the value appears. Say "the supplied
  password"
- In CI, reference an existing secret environment variable by name; never
  interpolate its value into agent-authored command text
- Use interactive mode or credential managers to avoid password exposure

## Quick Reference

| Action | Command |
|--------|---------|
| Add connection (interactive) | `scai connection add-sql-server` |
| Add connection (inline, SQL auth) | `scai connection add-sql-server -s NAME --auth standard --server-url HOST --database DB --user USER` |
| Add connection (Windows auth) | `scai connection add-sql-server -s NAME --auth windows --server-url HOST --database DB` |
| Correct a saved connection | the same `add-sql-server` command with every field, plus `--replace --json` |
| Test connection | `configure(source_connection=NAME)` (runs the test internally) |
| List databases the login can open (after asking) | `scai query -s NAME --database master -q "SELECT name FROM sys.databases WHERE database_id > 4 AND HAS_DBACCESS(name) = 1 ORDER BY name" --json` |
| Set default | `scai connection set-default -l sqlserver -s NAME` |
