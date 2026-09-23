---
name: informatica-pmcmd-connection
description: "Register Informatica PowerCenter pmcmd credentials as a scai connection so scai test etl-validate can launch workflows without re-exporting environment variables. Triggers: informatica, pmcmd, powercenter, etl connection, pmcmd credentials, add informatica connection."
license: Proprietary. See License-Skills for complete terms
---

# Informatica PowerCenter (`pmcmd`) Connection Skill

## On Entry

Tell the user:
> **Setting up the Informatica `pmcmd` connection** — I'll register the PowerCenter credentials `scai` needs to launch workflows, then verify them against the live Integration Service.

## Prerequisites

- The `scai` CLI installed and available
- Network access from this machine to the Informatica domain / Integration Service
- A PowerCenter repository user with permission to start workflows
- The seven values listed in Step 2 **to hand**, password included: the user types every one of
  them at the CLI's own prompts, never into this conversation (see Security Rules)

## Required Connection Details

Every one of these is prompted for interactively, so nothing here has to be assembled into a
command line. The flag names matter only for the inline form (CI):

| Parameter | Required | Description |
|-----------|----------|-------------|
| `-s, --source-connection` | Yes | Friendly name for this connection |
| `--auth` | Inline only | Authentication method — always `pmcmd` (see the note below) |
| `--pmcmd-path` | Yes | Absolute path to the `pmcmd` executable on this machine |
| `--user` | Yes | PowerCenter repository user |
| `--password` | Yes | Repository password (prompted securely) |
| `--service` | Yes | Integration Service name (`pmcmd -sv`) |
| `--domain` | Yes | Informatica domain the service belongs to (`pmcmd -d`) |
| `--infa-domains-file` | No | Path to `domains.infa`; leave blank unless the domain needs it |

Two things to know about this table before you use it:

- **`--auth pmcmd` is only meaningful for the inline (non-interactive) form.** Omitting `--auth` is
  exactly what selects the interactive prompts, which is the form this skill uses.
- **`--service` and `--domain` are required here but optional in the runner.** `pmcmd` itself
  accepts an omitted domain and falls back to its own defaults; the connection requires both so
  that `scai connection test` has something deterministic to probe. A project that genuinely
  relies on `pmcmd`'s defaults cannot register a connection at all, and should fill the
  `informatica:` section of `.scai/settings/test_config.yaml` instead.

## Workflow

### Step 1: Check Whether a Connection Already Exists

```bash
scai connection list -l informatica --json
```

If a connection is listed, note its name and skip to Step 3 — re-registering an existing
connection only risks overwriting working credentials. This probe is read-only and safe to repeat.

It is also the set of names already taken — registering onto an existing name fails with
`ConnectionAlreadyExists` — so read the names back to the user before they choose one.

### Step 2: Register the Connection Interactively

Run the add command with **no options at all** and let the user answer each prompt:

```bash
scai connection add-informatica-pmcmd
```

**STOPPING POINT** — the command is what collects the values, in this order:

| # | Prompt | Notes |
|---|--------|-------|
| 1 | Select authentication method | one choice, `pmcmd (repository credentials)` |
| 2 | Path to the pmcmd executable | absolute path |
| 3 | Informatica repository user | |
| 4 | Password | **hidden** — the characters are not echoed |
| 5 | Integration Service name | `pmcmd -sv` |
| 6 | Informatica domain | `pmcmd -d` |
| 7 | Path to `domains.infa` (optional) | Enter on its own leaves it unset |
| 8 | `Connection name:` | how every later command refers to it |

Tell the user to have those seven values ready to **type at the prompts**, and not to send any of
them to you — least of all the password. Nothing here needs to pass through the conversation: the
prompts talk to the user directly, and the hidden one keeps the secret out of an argv, out of shell
history, and out of this transcript.

On success the command prints `Connection '<name>' added successfully` and the path it wrote. Read
the name off that line — it is what Step 3 needs.

Pass `-s <CONNECTION_NAME>` only when the name is already decided elsewhere: if
`.scai/config/project.yml` (or `project.local.yml`) sets `informatica_connection`, register under
that exact name so what gets stored is what the run will select. It supplies prompt 8 from the
command line and nothing else — interactive mode is selected purely by **omitting `--auth`**, so
every credential field is still prompted.

There is an inline form, and it is the reason this skill does not use one. Omitting the secret does
not make it usable — `--password` is required, so this variant is **rejected**:

```bash
scai connection add-informatica-pmcmd -s <CONNECTION_NAME> --auth pmcmd --pmcmd-path <PMCMD_PATH> --user <USER> --service <SERVICE> --domain <DOMAIN>   # rejected: MissingRequiredParameters
```

Supplying the secret is what makes it work, and that is exactly what puts it on the command line.
Use inline mode only in CI, where the value comes from a secret store and the transcript is not a
human's terminal.

### Step 3: Select It and Verify

```bash
scai connection set-default -l informatica -s <CONNECTION_NAME>
scai connection test -l informatica -s <CONNECTION_NAME>
```

`set-default` is what makes the run actually use it; registering alone does not. (A project that
selects its connection through `informatica_connection` in `.scai/config/project.yml` is already
pointed at this name and needs no default — see Step 0c of the `etl-validate` skill.)

`connection test` runs `pmcmd pingservice` and then `pmcmd getservicedetails`: the first proves the
Integration Service is reachable, the second proves the user and password are actually accepted —
`pingservice` alone takes no credentials and would report success against a wrong password. A
failure names `pmcmd`, the step that failed and the Integration Service — plus the user when it was
the credential step — never a database driver. The domain appears only where pmcmd echoes it in its
own output, and a `pmcmd` that could not be launched at all names neither service nor domain.

## CHECKPOINT

Confirm with the user:
- [ ] The connection appears in `scai connection list -l informatica --json`
- [ ] It is the default for `informatica`, or its name was recorded for later steps
- [ ] `scai connection test` reported success against the live Integration Service

## Supported Operations

Informatica is an **ETL-only** source: it is a tool endpoint, not a queryable database. This connection is consumed by the ETL testing path only:

- **ETL testing:** `scai test seed`, `scai test etl-validate` (workflow launch + result comparison)

It is deliberately **not** a `scai query` / `scai code extract` source — those commands reject `-l informatica`, and the connection carries no SQL driver or connection string.

## On Completion

After the CHECKPOINT passes, tell the user:
> **Connection configured** — Informatica `pmcmd` credentials are registered as connection `<connection_name>`.

Then return to the calling skill.

## Security Rules

- **NEVER** log or display the repository password in plain text
- **NEVER** pass the password with `--password` outside CI — a command line is recorded in shell
  history, in process listings, and in this transcript
- **NEVER** ask the user to type the password into the chat, and never accept it if offered — it
  belongs only in the hidden interactive prompt
- **NEVER** echo the value back to the user for confirmation, and never repeat it in a summary
- Use interactive mode so the prompt hides the secret as it is typed
- `scai connection list` and `scai connection test` output **is** safe to show: stored passwords
  are masked there, so paste them freely when reporting what happened
- **`informatica.toml` stores the password in cleartext**, exactly as every other `scai` connection
  file does. Masking applies to command output, not to the file. So if the user asks where the
  secret ends up, tell them it is a plain file under `~/.snowflake/snowct/` protected by nothing but
  filesystem permissions — what registering buys is that the secret lives in one machine-level file
  instead of in a committed project file and in every shell's environment, not that it is encrypted.
  Suggest they restrict it to their own account (`chmod 600 ~/.snowflake/snowct/informatica.toml`):
  the shared TOML writer creates the file with the process umask, so it is not owner-only by default

## Quick Reference

| Action | Command |
|--------|---------|
| List connections | `scai connection list -l informatica --json` |
| Add connection (interactive, prompts for everything) | `scai connection add-informatica-pmcmd` |
| Add under a name already chosen | `scai connection add-informatica-pmcmd -s <CONNECTION_NAME>` |
| Set default | `scai connection set-default -l informatica -s <CONNECTION_NAME>` |
| Test connection | `scai connection test -l informatica -s <CONNECTION_NAME>` |
