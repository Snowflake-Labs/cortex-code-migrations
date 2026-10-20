---
name: worker-local-setup
description: Install and start the Data Exchange Worker on a user-managed machine (laptop, cloud VM, or on-prem server).
parent_skill: data-infrastructure-setup
license: Proprietary. See License-Skills for complete terms
---

# Worker Local Setup

Set up and run the Data Exchange Worker on whatever machine will execute it: a laptop, a cloud VM, an on-premises server, or one host per worker when scaling out. The steps are the same on each host.

## Prerequisites

> **Note:** Ensure the host can reach both the source database and your Snowflake account (and meets any corporate firewall or proxy rules when applicable).

Prerequisites depend on the **source dialect** and the **extraction strategy** chosen in data migration setup. Load [extraction-strategies-reference.md](../../migrate-objects/actions/data-migration/references/extraction-strategies-reference.md) for the full matrix; complete the matching section below before Step 1.

### SQL Server — `regular` (ODBC)

The Data Exchange Worker connects to SQL Server via the Microsoft ODBC Driver. Before starting the worker, verify it is installed.

**On Linux**, run, with the absolute directory of this `SKILL.md` and the migration project directory:

```bash
python3 "<worker_local_setup_skill_dir>/scripts/install_odbc_user.py" --check --project-dir "<project_dir>"
```

Do not use `odbcinst -q -d` for this on Linux: once a user-level install (route 1 below) exists, its `odbcinst` wrapper lists the driver for every project, whether or not the worker would find it. The check validates the user-level install for this project when there is one, and otherwise asks the system's own `odbcinst`. It needs Python 3.8 or newer; on RHEL 8 see route 1 for what to use in place of `python3`. With no Python 3.8+ at all there can be no user-level install, so check the system with `odbcinst -q -d 2>/dev/null | grep -i "ODBC Driver"` instead.

- `OK:` (exit 0): the driver is present and the worker will find it — continue to Step 1.
- A `FAILED:` line saying the `.env` does not point the worker at the install: run route 1's install for this project (no new licence question if the user already accepted it).
- A `FAILED:` line saying a variable is already set in the environment: the real environment beats `.env`, so the user must set it as the line says where it is defined, then restart the app.
- Any other `FAILED:` line: the driver is missing or broken; continue below.

**On macOS**, run:

```bash
odbcinst -q -d 2>/dev/null | grep -i "ODBC Driver"
```

If it returns a driver name (e.g. `[ODBC Driver 18 for SQL Server]`), the driver is present — continue to Step 1.

**Otherwise** the driver is missing. **Do not start the local worker.** Never run `sudo` or an interactive installer yourself.

**Do not abandon orchestrator placement.** Missing ODBC is a worker-host problem. If the parent skill has not brought the shared orchestrator up yet, **return to** [`../SKILL.md`](../SKILL.md): keep the **SPCS** recommendation, confirm the compute pool, and call `data_infrastructure(mode="up", compute_pool="<POOL>", start_worker=false)`. Then tell the user to install ODBC and resume the worker later.

**On Linux**, ask the user whether they have `sudo` on this machine, then offer these routes, the user-level install first when they have no `sudo`:

1. **Install it for this user, without root** (Debian, Ubuntu, RHEL and its rebuilds). Tell the user the driver is Microsoft's, licensed under <https://aka.ms/odbc18eula>, and ask whether they accept it. Only after they say yes, run, with the absolute directory of this `SKILL.md` and the migration project directory:
   ```bash
   python3 "<worker_local_setup_skill_dir>/scripts/install_odbc_user.py" --accept-eula --project-dir "<project_dir>"
   ```
   It needs Python 3.8 or newer. On RHEL 8 and its rebuilds `python3` is 3.6 or absent: use `python3.11`, `python3.12` or `python3.9` if one is installed, or `uv run --no-project --python 3.12 python` in place of `python3` if `uv` is on `PATH`; with neither, offer route 2 or 3. The same goes for the `--check` pre-flight above.
   It downloads unixODBC and `msodbcsql18` as the user, unpacks them under `~/.local/share/scai/odbc`, and writes `ODBCSYSINI` and `LD_LIBRARY_PATH` to `<project_dir>/.env`, which `scai` loads and the worker inherits. It also writes `odbcinst`/`isql` wrappers to `~/.local/bin`. It ends `OK: the driver loads.` (exit 0) on success: pass every `WARNING:` line on to the user. A warning that `LD_LIBRARY_PATH` is already set means the user must change it where it is defined and restart the app, because the real environment beats `.env`. Then continue to Step 1. On `FAILED:` (exit 1), tell the user the reason and offer route 2 or 3.
2. **Install it with `sudo`, run by the user:** Microsoft's [Linux install steps](https://learn.microsoft.com/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server) for their distribution (`msodbcsql18` and `unixodbc`).
3. **Run the worker on SPCS** instead of this machine: [`../worker-spcs/SKILL.md`](../worker-spcs/SKILL.md).

After a user-level install, if `scai data worker start` still fails its doctor with "unixODBC manager not installed", the installed worker predates the doctor check that reads pyodbc and is looking for `odbcinst` on `PATH`. Ask the user to add `~/.local/bin` to `PATH` (logging out and back in does it on Ubuntu and Debian once the directory exists) and restart the app.

**On macOS**, tell the user:

> The Data Exchange Worker requires the Microsoft ODBC Driver for SQL Server to connect to your source database. Please install it and then resume.
>
> **macOS — Homebrew (recommended):**
> ```bash
> brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
> brew update
> HOMEBREW_ACCEPT_EULA=Y brew install msodbcsql18
> ```
> The `brew tap` step may ask you to confirm adding a third-party repository — this is expected.
>
> **macOS — without Homebrew:**
> Download and install the `.pkg` from the [Microsoft ODBC Driver download page](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server). Choose the macOS package matching your architecture (`arm64` for Apple Silicon, `x86_64` for Intel).
>
> **After installing**, verify with:
> ```bash
> odbcinst -q -d | grep -i "ODBC Driver"
> ```
> Then resume the setup.

Once the user confirms the driver is installed, re-run the check and continue.

### PostgreSQL — `pg_copy` or `odbc`

For selected method `pg_copy`, `use_copy = true` (the DEA default); `psql` on the worker `PATH` is
preferred but not required, because the worker falls back to the ODBC parquet reader on its own when
it is missing. For selected method `odbc`, `use_copy = false` and the PostgreSQL ODBC driver is then
mandatory. Either way the workflow strategy stays `regular` — do not describe COPY as a workflow
extraction strategy.

### SQL Server — `bcp`

`use_bcp = true`; verify `bcp` is on the worker `PATH`, because there is no fallback. BCP covers bulk
`data_movement` only, so the ODBC pre-flight above still applies. Workflow strategy remains `regular`.
For selected method `odbc`, `use_bcp = false` and only the ODBC pre-flight matters.

### Oracle — `regular` (ODP.NET)

No SQL Server ODBC check. Ensure the worker can reach Oracle with the service name in TOML `database` (same as scai connection).

### Oracle — `dbms_cloud`

Configure `dbms_cloud_credential_name` and `dbms_cloud_file_uri_prefix` in `[connections.source.oracle]` after generate-config. Oracle must grant `EXECUTE` on `DBMS_CLOUD` and a credential for the HTTPS prefix. Set `extraction.strategy: dbms_cloud` and `externalStage` in workflow YAML. See extraction-strategies reference and `dmvf/data-exchange-agent/docs/oracle-dbms-cloud-local-setup.md`.

### Redshift — `unload`

Add `unload_s3_bucket` and `unload_iam_role_arn` to `[connections.source.redshift]`. Set `extraction.strategy: unload` and `externalStage` in workflow YAML.

### Teradata — `tpt`

Install Teradata TTU on the worker host (`tbuild`) and configure the required `tpt_*` TOML fields.
Workflow strategy is `regular`; `tpt` is the persisted worker method, not a canonical DMO strategy.
`use_tpt_for_bulk` defaults to `true`, so only the explicit `odbc` method turns TPT off.

### Teradata — `write_nos`

Configure `write_nos_*` fields in `[connections.source.teradata]`. Set `extraction.strategy: write_nos` and `externalStage` in workflow YAML.

## Step 1 — Generate the Worker Config

> **Skip this step** for Iceberg migration strategies that don't use a Worker (`catalog_link`, `convert_to_managed`, `copy_files` with `sourceDataStage`).

If the project's `.scai/config/dew_configuration.toml` (path relative to the SCAI project root) already exists with no `<PLACEHOLDER>` tokens, report "Worker config already complete" and continue to Step 2.

Otherwise, run:

```bash
scai data worker generate-config
```

Run inside the project (no path argument) — scai writes the project-default `.scai/config/dew_configuration.toml`.

This pre-fills `[connections.source.<engine>]` from the project's scai source connection (host, user, database, port, and engine-specific fields like SQL Server's `trust_server_certificate` and `encrypt`, Teradata `authentication = "LDAP"` when `--auth ldap`, or Azure Synapse `mode = "azure_ad"` when `--auth service-principal`). The CLI will prompt before overwriting an existing file; pass `-y` to overwrite without prompting.

> **Affinity:** when this flow is driven through the plugin, `data_infrastructure(mode="up")` generates this config. With no explicit override, scai applies the same stable project default used by workflow generation. If `configure(affinity="<label>")` set an override, the plugin passes that label to both generators and regenerates a stale DEW config whose affinity differs. When running `generate-config` yourself, omit `--affinity` to use the project default or pass the same explicit `--affinity <label>` as the workflow. See the [Affinity Reference](../references/affinity-reference.md).

After running, handle the result:

- **No placeholders remain** — show the user the pre-filled values from the scai connection (`[connections.source.*]` host, port, user, database) and ask them to confirm. Only edit if something is wrong; do **not** re-prompt for fields that already have real values.
- **Placeholders remain** — open the file and replace each `<PLACEHOLDER>` token. If the scai connection lacked a field (e.g., no `port`), ask the user for just that one field.

> The scai connection populates `[connections.source.*].database`. This value **must match** `source.databaseName` in the migration workflow YAML / validation JSON. A mismatch causes the orchestrator to report "table does not exist in the source database." If the user wants to migrate a different database than the one in their scai connection, update it here and use the same value in the workflow YAML.
>
> **Oracle:** `database` in the worker TOML is the Oracle **service name** (from `--service-name` on `scai connection add-oracle`), not a SQL Server–style database name. Use the same service name in workflow YAML `source.databaseName`.
>
> **Teradata:** `database` in the worker TOML is the Teradata **database name** (from `--database` on `scai connection add-teradata`). Use the same value in workflow YAML `source.databaseName`. For LDAP connections, confirm `authentication = "LDAP"` is present when the scai connection uses `--auth ldap`.
>
> **Azure Synapse:** scai `--auth service-principal` becomes worker `mode = "azure_ad"` with `client_id` / `client_secret` — not `mode = "service_principal"`. `interactive` cannot start a worker (headless). Confirm `mode` after generate-config. See [Azure Synapse auth modes](../references/worker-config-reference.md#azure-synapse-auth-modes).
>
> **PostgreSQL:** `data_infrastructure(mode="up")` applies the selected method after generation:
> `pg_copy` → `use_copy = true` (psql preferred, ODBC fallback automatic); `odbc` → `use_copy = false`
> and an ODBC driver is then required. Legacy `regular` leaves the flag as generated. The `database`
> field is the actual PostgreSQL database name.

See [`../references/worker-config-reference.md`](../references/worker-config-reference.md) for the field reference and advanced options (e.g., Redshift UNLOAD, Teradata TPT / WRITE_NOS).

## Step 2 — Start the Worker

Run:

```bash
scai data worker start --local
```

This command installs the worker if it is not already present, then starts it using the project-default configuration at `.scai/config/dew_configuration.toml`.

Use the status printed by this command. **Never add a Bash `sleep` or shell
polling loop after startup**; if startup does not report a healthy worker,
diagnose that result directly.

Tell the user:

> **Cost note:** The local Data Exchange Worker polls Snowflake on an interval and can accrue warehouse credits even when no migration tasks are running. Stop the worker when data work for this wave is done (teardown skill), or when ending the session if it was started outside MCP.

## Step 3 — Verify the Worker Is Running

The CLI prints worker status on startup. Confirm the output shows the worker has connected to the orchestrator and is polling for tasks.

If the worker fails to start, check:
- **SQL Server only:** ODBC driver installed (`odbcinst -q -d | grep -i "ODBC Driver"`, or `install_odbc_user.py --check` after a user-level install) — if missing, follow the pre-flight instructions in the Prerequisites section above
- Source database credentials in the TOML config
- Network connectivity to the source database from the host
- Snowflake connection details in `~/.snowflake/config.toml` (or `%USERPROFILE%\.snowflake\config.toml` on Windows)

## Done

The worker is running on the host. Return control to the parent skill, which runs Level 1 Data Doctor before proceeding.
