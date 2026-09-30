# Extraction strategies by source dialect

**Extraction strategy** controls *how* data leaves the source system. It is separate from **migration type** (preliminary / incremental / full) and **sync strategy** (none / checksum / watermark).

The `data-migration-setup` state machine (`progress_setup(mode="data_migration")`) presents methods in
preferred order. Selecting one is explicit confirmation that its listed prerequisites can be met; if
not, walk down to the next option. Never infer a server-side method from table size.

After the user chooses, persist it as `data_migration_extraction_strategy` and pass
`extraction_strategy=` to `migrate_data(mode="setup", ...)`. Setup writes
`defaultTableConfiguration.extraction`; a server/cloud method also needs `external_stage=` the first
time it is applied (later calls inherit the stage already recorded in the workflow).
`odbc`, `bcp`, `pg_copy`, and `tpt` are worker methods under workflow strategy `regular`.

**`odbc` vs `regular`.** `odbc` is the explicit "plain driver read" choice and turns the dialect's
worker bulk flag **off**. Bare `regular` is the legacy value from before this ladder existed — it
means "whatever the worker's config already enables" and deliberately leaves the bulk flags alone, so
projects configured earlier keep their behavior. Prefer `odbc` when the user actually rules bulk out.

---

## SQL Server (`SqlServer`)

| Strategy | How data moves | When to use |
|----------|----------------|-------------|
| **`cet_as`** (preferred) | SQL Server CETAS → Azure Blob → Snowflake external stage | SQL Server 2022+ / compatible SKU with CETAS objects ready |
| **`cloud_direct`** | Worker streams Parquet to object storage → Snowflake external stage | Azure SQL Database, or SQL Server Iceberg when CETAS is unavailable; write credentials + matching stage ready |
| **`bcp`** (worker method; workflow `regular`) | Worker runs **BCP** for **bulk** extraction → Snowflake internal stage | `bcp` on worker PATH + `use_bcp = true` |
| **`odbc`** | Data Exchange Worker reads via **Microsoft ODBC Driver** → Snowflake internal stage | Fallback |

**Setup required**

- [worker-local-setup/SKILL.md](../../../../data-infrastructure/worker-local-setup/SKILL.md) — ODBC driver pre-flight (`odbcinst -q -d`)
- Worker TOML `[connections.source.sqlserver]` — standard host/port/database/credentials from `scai data worker generate-config`
- CETAS: external data source + Parquet format + matching Snowflake external stage
- BCP: Worker TOML `use_bcp = true`; workflow `extraction.strategy: regular`. There is no fallback when `bcp` is missing—the task fails. BCP always uses the worker's field/row terminators and UTF-8. It covers **bulk `data_movement` only**; other task types read over ODBC regardless, so the driver still has to be present.
- ODBC: Worker TOML `use_bcp = false`; workflow `extraction.strategy: regular`

Azure SQL Database does not support CETAS: use `cloud_direct` when its object-store prerequisites are
ready, otherwise `odbc`. SQL Server Iceberg requires `cet_as` or `cloud_direct`, never a worker read.

---

## PostgreSQL (`Postgresql`)

| Strategy | How data moves | When to use |
|----------|----------------|-------------|
| **`pg_copy`** (preferred worker method; workflow `regular`) | Worker runs `psql \copy` | `use_copy = true`; `psql` on PATH preferred |
| **`odbc`** | Worker reads through PostgreSQL ODBC | Only to rule COPY out; `use_copy = false` |

**Setup required**

- COPY: TOML `use_copy = true`. `psql` on the worker `PATH` is **preferred, not required** — when it
  is missing the worker logs and falls back to the ODBC parquet reader on its own. `use_copy = true`
  is the DEA default, so this is also what an unconfigured worker does.
- ODBC: TOML `use_copy = false` and a PostgreSQL ODBC driver on the worker. This removes the COPY
  fast path *and* its automatic fallback, so pick it only when COPY must be ruled out.
- Both write workflow YAML `extraction.strategy: regular`

---

## Oracle (`Oracle`)

| Strategy | How data moves | When to use |
|----------|----------------|-------------|
| **`dbms_cloud`** (preferred) | Oracle runs **`DBMS_CLOUD.EXPORT_DATA`** to HTTPS object storage → Snowflake **external stage** | Grants, credential/ACL, and matching stage ready |
| **`regular`** | Worker reads via **Oracle ODP.NET** (`Oracle.ManagedDataAccess`) → Snowflake internal stage | Fallback |

**Setup — `regular`**

- Worker TOML `[connections.source.oracle]` — `database` = **service name** (same as scai connection)
- Workflow: `extraction.strategy: regular`

**Setup — `dbms_cloud`**

- Oracle DBA: `EXECUTE` on `DBMS_CLOUD`, credential via `DBMS_CLOUD.CREATE_CREDENTIAL` for the target bucket/prefix
- Worker TOML under `[connections.source.oracle]`:
  - `dbms_cloud_credential_name` — credential object name in Oracle
  - `dbms_cloud_file_uri_prefix` — `https://` URI prefix for exported objects (e.g. S3 bucket path)
- Workflow YAML:
  ```yaml
  extraction:
    strategy: dbms_cloud
    externalStage: MY_DB.MY_SCHEMA.S3_EXTERNAL_STAGE
  ```
- Snowflake external stage must point at the same object-storage prefix Oracle writes to

See DMVF doc `dmvf/data-exchange-agent/docs/oracle-dbms-cloud-local-setup.md` for local dev details.

---

## Redshift (`Redshift`)

| Strategy | How data moves | When to use |
|----------|----------------|-------------|
| **`unload`** (preferred) | Redshift **`UNLOAD`** to **S3** → Snowflake **external stage** | IAM, bucket/prefix, worker fields, and matching stage ready |
| **`regular`** | Worker reads via **ODBC** → Snowflake internal stage | Fallback |

**Setup — `regular`**

- Worker TOML `[connections.source.redshift]` — standard ODBC connection fields

**Setup — `unload`**

- Worker TOML adds:
  ```toml
  unload_s3_bucket = "my-migrations-bucket"
  unload_iam_role_arn = "arn:aws:iam::123456789012:role/MyRole"
  ```
- Workflow YAML:
  ```yaml
  extraction:
    strategy: unload
    externalStage: MY_DB.MY_SCHEMA.S3_EXTERNAL_STAGE
  ```
- IAM role must trust Redshift and allow writes to the bucket; Snowflake stage uses the same S3 path

See [worker-config-reference.md](../../../../data-infrastructure/references/worker-config-reference.md#advanced-redshift-unload).

### Iceberg target (Redshift only — partial support)

**`target_table_type=iceberg` is only supported for Redshift sources today.** Other dialects should use `native` (default). Do not offer Iceberg unless `source_language` is Redshift and the user explicitly wants it.

Iceberg is a **target** choice (`tableType: iceberg` + `icebergConfig`), separate from extraction. Supported paths:

| Path | Extraction | `migrationStrategy` | Worker? |
|------|------------|---------------------|---------|
| Redshift native tables → Snowflake Iceberg | `unload` (typical) | `copy_files` | UNLOAD on Redshift; Snowflake loads from stage |
| Redshift / Glue Iceberg tables → Snowflake Iceberg | none (metadata only) | `catalog_link` or `convert_to_managed` | Often **no worker** — orchestrator issues Snowflake DDL |

Prerequisites and AWS/Snowflake setup: [iceberg-setup-reference.md](./iceberg-setup-reference.md). Workflow fields and type mappings: [workflow-config-reference.md](./workflow-config-reference.md#icebergconfig). Orchestrator detail: `dmvf/docs/data-migration-orchestrator/iceberg-migration-support.md`.

---

## Teradata (`Teradata`)

| Strategy | How data moves | When to use |
|----------|----------------|-------------|
| **`write_nos`** (preferred) | Teradata **`WRITE_NOS`** → cloud storage → Snowflake external stage | NOS + matching-stage prerequisites ready |
| **`tpt`** (worker method; workflow `regular`) | **Teradata Parallel Transporter** on worker → Snowflake internal stage | TTU/tbuild + `tpt_*` ready |
| **`odbc`** | Worker reads via **`teradatasql`** or Teradata ODBC → Snowflake internal stage | Fallback |

**Setup — `odbc`**

- Worker TOML `[connections.source.teradata]` — `database` matches workflow `source.databaseName`
- LDAP: `authentication = "LDAP"` when scai connection uses `--auth ldap`
- Sets `use_tpt_for_bulk = false`. The DEA default is `true`, so this is an explicit opt-out.

**Setup — `tpt`**

- Teradata **TTU** installed on worker host (`tbuild` available)
- Optional TOML: `tpt_delimiter`, `tpt_max_sessions`
- Workflow: `extraction.strategy: regular`; TPT is enabled only by worker `use_tpt_for_bulk` + `tpt_*` config

**Setup — `write_nos`**

- TOML `write_nos_*` fields under `[connections.source.teradata]` (see worker-config reference)
- Workflow:
  ```yaml
  extraction:
    strategy: write_nos
    externalStage: MY_DB.MY_SCHEMA.TD_NOS_STAGE
  ```

See DMVF docs: `teradata-odbc-extraction.md`, `tpt-extraction.md`, `write-nos-extraction.md` under `dmvf/docs/data-migration-orchestrator/`.

---

## Azure Synapse (`synapse`)

1. **`cet_as`** (preferred): CETAS to Azure Blob; requires external data source, Parquet format, and a
   Snowflake external stage on the same prefix.
2. **`regular`**: ODBC fallback.

Synapse has **no BCP** path.

## BigQuery (`BigQuery`)

1. **`export_data`** (preferred): BigQuery `EXPORT DATA` to GCS; requires source and Snowflake service
   accounts plus a matching Snowflake external stage.
2. **`regular`**: worker BigQuery client fallback.

## DB2 (`Db2`)

1. **`cloud_direct`** (preferred): worker streams Parquet to object storage; requires write credentials
   plus a matching Snowflake external stage.
2. **`regular`**: `ibm_db` worker fallback.

---

## After choosing a strategy

1. Selection is user attestation: prerequisites are expected, not live-probed by the wizard.
2. `migrate_data(mode="setup")` writes the normalized workflow strategy. A server/cloud method needs
   `external_stage` the first time it is applied; later calls inherit the stage already recorded in
   the workflow, so a plain re-run does not have to replay it. Setup then runs Data Doctor for evidence.
3. `data_infrastructure(mode="up")` applies the worker flag for an explicit `bcp` / `pg_copy` / `tpt` /
   `odbc` choice. It leaves the flags alone for legacy `regular` and for server/cloud methods (where
   they are inert), and reports a warning rather than refusing to start if the TOML has no matching
   connection table.
4. `migrate_data(mode="run")` validates the final YAML and fails closed when an external stage is
   missing; create-workflow/start run Doctor gates again.

> Setup owns `defaultTableConfiguration.extraction.strategy`: re-running it re-applies the persisted
> method over a hand-edit. Change the method with `extraction_strategy=`, not by editing the YAML.
