---
name: redshift-connection
description: Connect to a source Redshift database for migration to Snowflake using scai CLI. Triggers: redshift, source connection, source database, connect to redshift, add redshift connection.
license: Proprietary. See License-Skills for complete terms
---

# Redshift Connection Skill

## On Entry

Tell the user:
> **Setting up Redshift connection** — I'll configure and test a connection to your source Redshift cluster. I'll need some connection details from you shortly.

## Prerequisites

- Network access to the Redshift cluster or serverless endpoint
- For IAM auth: AWS credentials (access key ID + secret access key)
- For standard auth: Redshift username and password
- The `scai` CLI installed and available

## Required Connection Details

### IAM Provisioned Cluster (Recommended)

| Parameter | Required | Description |
|-----------|----------|-------------|
| `-s, --source-connection` | Yes | Friendly name for this connection |
| `--auth` | Yes | `iam-provisioned-cluster` |
| `--cluster-id` | Yes | Redshift cluster identifier |
| `--database` | Yes | Database name to connect to |
| `--region` | Yes | AWS region (e.g., `us-west-2`) |
| `--user` | Yes | Redshift database user |
| `--access-key-id` | Yes | AWS Access Key ID (prompted securely) |
| `--secret-access-key` | Yes | AWS Secret Access Key (prompted securely) |

### IAM Serverless

| Parameter | Required | Description |
|-----------|----------|-------------|
| `-s, --source-connection` | Yes | Friendly name for this connection |
| `--auth` | Yes | `iam-serverless` |
| `--workgroup` | Yes | Redshift Serverless workgroup name |
| `--database` | Yes | Database name to connect to |
| `--region` | Yes | AWS region (e.g., `us-west-2`) |
| `--access-key-id` | Yes | AWS Access Key ID (prompted securely) |
| `--secret-access-key` | Yes | AWS Secret Access Key (prompted securely) |

### Standard Auth

| Parameter | Required | Description |
|-----------|----------|-------------|
| `-s, --source-connection` | Yes | Friendly name for this connection |
| `--auth` | Yes | `standard` |
| `--host` | Yes | Redshift endpoint hostname |
| `--port` | No | Port number (default: 5439) |
| `--database` | Yes | Database name to connect to |
| `--user` | Yes | Redshift username |
| `--password` | Yes | Redshift password (prompted securely) |

## Workflow

### Step 1: Ask How to Provide Credentials

Ask the user:

> "I need the following to connect to Redshift:
> - **Cluster ID** or **Workgroup** (depending on auth method)
> - **Database name**
> - **Region** (IAM auth) or **Host** (standard auth)
> - **Username** (provisioned cluster and standard auth)
>
> How would you like to provide these? For security, enter the AWS keys or the password only in the masked prompt; do not send it in chat."

Options:
1. **1Password** - Credentials stored in 1Password vault
2. **Enter manually** - Provide values interactively

### Step 2: Route Based on Answer

| User says | Action |
|-----------|--------|
| "1Password" | Follow `../1PASSWORD.md` (Redshift section) |
| "Enter manually" | Proceed to Step 3 (manual entry) |
| Other credential manager | Check if `../references/<NAME>.md` exists; if not, ask user to explain their setup |

### Step 3: Add the Connection (Manual Entry)

**Interactive mode (recommended):**
```bash
scai connection add-redshift
```

The CLI prompts securely for the secrets these commands leave out: `--access-key-id` and
`--secret-access-key` for IAM auth, `--password` for standard auth. Never include them in the command line.

**IAM Provisioned Cluster:**
```bash
scai connection add-redshift \
  -s <CONNECTION_NAME> \
  --auth iam-provisioned-cluster \
  --user <USER> \
  --cluster-id <CLUSTER_ID> \
  --database <DATABASE> \
  --region <REGION>
```

**IAM Serverless:**
```bash
scai connection add-redshift \
  -s <CONNECTION_NAME> \
  --auth iam-serverless \
  --workgroup <WORKGROUP> \
  --database <DATABASE> \
  --region <REGION>
```

**Standard auth:**
```bash
scai connection add-redshift \
  -s <CONNECTION_NAME> \
  --auth standard \
  --host <HOST> \
  --port 5439 \
  --database <DATABASE> \
  --user <USERNAME>
```

When your `bash` has no terminal (the desktop app), that prompt cannot be answered. Get each secret with the
app's `request_secret` tool and follow the app's rule for filling it into the command: the secret goes in a
variable that opens the command, and the flag takes `"$VAR"`. A `<secret>` placeholder written as the flag's
own value is passed through as literal text, saved to `redshift.toml`, and every test then fails as an invalid
security token. Never ask for a secret in chat.

Connections require TLS by default for the connection test (`--ssl-mode Require`);
pass another Npgsql SSL mode only if the endpoint genuinely does not accept TLS.
`--ssl-mode` is stored in `redshift.toml` and honored by `scai connection test`;
data-migration / validation DEW configs do not yet emit `ssl_mode` for Redshift.

### Step 4: Save and Test Source Connection

Call the `configure` tool with `source_connection` set to `<CONNECTION_NAME>`. The MCP server runs `scai connection test` internally and only persists the connection if the test passes.

- **On success:** the response includes `connection_test: ok`.
- **On failure:** the tool returns an error containing the scai message. Surface it to the user, help them fix the issue, then re-run `configure(source_connection=<CONNECTION_NAME>)`. See `./references/REFERENCE.md` for detailed troubleshooting.

**Common errors:**
| Error | Cause | Solution |
|-------|-------|----------|
| `Operation timed out` | Network/firewall issue | Check VPN, security groups, firewall rules |
| `database "X" does not exist` | Wrong database name | Verify database name on cluster |
| `IAM authentication failed` | Invalid AWS credentials | Check access key ID and secret |

## CHECKPOINT

Confirm with user:
- [ ] `configure` returned `connection_test: ok`
- [ ] Connection appears in `scai connection list -l redshift --json`
- [ ] Source connection saved to session config

## On Completion

After the CHECKPOINT passes, tell the user:
> **Connection configured** — Successfully connected to Redshift using connection `<connection_name>`.

Then return to the calling skill.

## Security Rules

- **NEVER** log or display secrets (passwords, secret access keys) in plain text
- **NEVER** include secrets in command-line arguments that might be logged. Omit `--password`, `--access-key-id` and `--secret-access-key`; the CLI prompts for them securely in an interactive terminal.
- A credential manager helps only when it resolves the value inside the same command (1Password `op run`). Storing a secret elsewhere first does not, because `scai` reads credentials only from its own files under `~/.snowflake/scai/connections/`.

## Quick Reference

| Action | Command |
|--------|---------|
| Add connection (interactive) | `scai connection add-redshift` |
| Add IAM provisioned | `scai connection add-redshift -s NAME --auth iam-provisioned-cluster --cluster-id CLUSTER --database DB --region REGION --user USER` |
| Add IAM serverless | `scai connection add-redshift -s NAME --auth iam-serverless --workgroup WG --database DB --region REGION` |
| Add standard auth | `scai connection add-redshift -s NAME --auth standard --host HOST --database DB --user USER` |
| Test connection | `configure(source_connection=NAME)` (runs the test internally) |
| List connections | `scai connection list -l redshift --json` |
| Set default | `scai connection set-default -l redshift -s NAME` |
| Extract code | `scai code extract -s NAME --json` |
