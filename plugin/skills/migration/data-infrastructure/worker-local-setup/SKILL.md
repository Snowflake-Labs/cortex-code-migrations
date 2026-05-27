---
name: worker-local-setup
description: Install and start the Data Exchange Worker on a user-managed machine (laptop, cloud VM, or on-prem server).
parent_skill: data-infrastructure-setup
license: Proprietary. See License-Skills for complete terms
---

# Worker Local Setup

Set up and run the Data Exchange Worker on whatever machine will execute it: a laptop, a cloud VM, an on-premises server, or one host per worker when scaling out. The steps are the same on each host.

## Prerequisites

<!-- WIP: SNOW-3550358 Prerequisites vary by execution strategy (e.g., ODBC driver for direct extraction, Docker for containerized mode, S3 access for Redshift UNLOAD). Document strategy-specific prerequisites here once finalized. -->

> **Note:** Specific prerequisites depend on your source database and extraction strategy. Ensure the host can reach both the source database and your Snowflake account (and meets any corporate firewall or proxy rules when applicable).

## Step 1 — Generate the Worker Config

> **Skip this step** for Iceberg migration strategies that don't use a Worker (`catalog_link`, `convert_to_managed`, `copy_files` with `sourceDataStage`).

If `.scai/settings/DataExchangeWorkerConfig.toml` already exists with no `<PLACEHOLDER>` tokens, report "Worker config already complete" and continue to Step 2.

Otherwise, run:

```bash
scai data worker generate-config .scai/settings/DataExchangeWorkerConfig.toml
```

This pre-fills `[connections.source.<engine>]` from the project's scai source connection (host, user, database, port, and engine-specific fields like SQL Server's `trust_server_certificate` and `encrypt`). Pass `--affinity <label>` if your workflow uses one. The CLI will prompt before overwriting an existing file; pass `-y` to overwrite without prompting.

After running, handle the result:

- **No placeholders remain** — show the user the pre-filled values from the scai connection (`[connections.source.*]` host, port, user, database) and ask them to confirm. Only edit if something is wrong; do **not** re-prompt for fields that already have real values.
- **Placeholders remain** — open the file and replace each `<PLACEHOLDER>` token. If the scai connection lacked a field (e.g., no `port`), ask the user for just that one field.

> The scai connection's `database` populates `[connections.source.*].database`. This value **must match** `source.databaseName` in the migration workflow YAML / validation JSON. A mismatch causes the orchestrator to report "table does not exist in the source database." If the user wants to migrate a different database than the one in their scai connection, update it here and use the same value in the workflow YAML.

See [`../references/worker-config-reference.md`](../references/worker-config-reference.md) for the field reference and advanced options (e.g., Redshift UNLOAD).

## Step 2 — Start the Worker

Run:

```bash
scai data worker start --local .scai/settings/DataExchangeWorkerConfig.toml
```

This command installs the worker if it is not already present, then starts it using the configuration in `.scai/settings/DataExchangeWorkerConfig.toml`.

## Step 3 — Verify the Worker Is Running

The CLI prints worker status on startup. Confirm the output shows the worker has connected to the orchestrator and is polling for tasks.

If the worker fails to start, check:
- Source database credentials in the TOML config
- Network connectivity to the source database from the host
- Snowflake connection details in `~/.snowflake/config.toml` (or `%USERPROFILE%\.snowflake\config.toml` on Windows)

## Done

The worker is running on the host. Return control to the parent skill.
