# L3 pushdown extract — platforms, stage SQL, worker TOML

Companion to [l3-pushdown/SKILL.md](../l3-pushdown/SKILL.md). Use this when the user **has** object storage, or when data migration already landed on an external stage (reuse without asking).

L3 for non-Snowflake sources is always signature extract → pushdown compare. `extraction.strategy` only changes **transport**. Snowflake→Snowflake does **not** use this file.

Worker field details also live in [worker-config-reference.md](../../../data-infrastructure/references/worker-config-reference.md) and DM [extraction-strategies-reference.md](../../../migrate-objects/actions/data-migration/references/extraction-strategies-reference.md).

## Platform → strategy

Prefer the **native server-side export** when the user’s bucket matches the dialect. Otherwise use **`cloud_direct`** (worker streams Parquet to S3, GCS, or Azure Blob). Those object-store paths are the preferred L3 extract when a bucket exists. Without a bucket, extract goes worker → Snowflake internal stage (same checks). If they do not have a bucket yet, wait — do not default to the worker-only extract unless they explicitly choose to continue without one. Never say strategy enum names to the user, and never describe the no-bucket path as slow.

| Source | Ask them about | If yes, prefer | Worker extras | If bucket is a different cloud |
|--------|----------------|----------------|---------------|--------------------------------|
| Redshift | **S3** bucket + IAM role Redshift can `UNLOAD` to | `unload` | `unload_s3_bucket`, `unload_iam_role_arn`, optional `unload_s3_prefix` | `cloud_direct` |
| BigQuery | **GCS** bucket | `export_data` | `export_data_gcs_bucket`, `export_data_gcs_prefix` | `regular` only if no GCS (`cloud_direct` is not on BigQuery) |
| Oracle | Object storage Oracle `DBMS_CLOUD` can write (usually **S3** HTTPS) | `dbms_cloud` | `dbms_cloud_credential_name`, `dbms_cloud_file_uri_prefix` | `cloud_direct` |
| Teradata | **S3 / Azure / GCS** Teradata `WRITE_NOS` can address | `write_nos` | `write_nos_location_scheme`, `write_nos_location_host`, auth (`write_nos_function_mapping` or access keys) | `cloud_direct` |
| PostgreSQL | **Any** of S3, GCS, Azure Blob | `cloud_direct` | `[connections.target.s3]` / `.gcs` / `.blob` | n/a |
| SQL Server | Azure Blob (CETAS) or any cloud (`cloud_direct`) | `cet_as` on SQL Server 2022+ / Managed Instance; else `cloud_direct` | `cet_as_external_data_source`, `cet_as_file_format` **or** target cloud section | `cloud_direct` |
| Azure Synapse | **Azure Blob** | `cet_as` | same `cet_as_*` keys | `cloud_direct` |
| Db2 | **Any** of S3, GCS, Azure Blob | `cloud_direct` | target cloud section | n/a |
| Snowflake | — | **Skip** (in-warehouse L3) | no worker | — |

Do not set a strategy the platform does not support (parser rejects it). Examples: Redshift + `write_nos`, BigQuery + `cloud_direct`.

## Workflow YAML

Under the generated validation workflow (`validationConfiguration`, not `defaultTableConfiguration`):

```yaml
validationConfiguration:
  schemaValidation: true
  metricsValidation: false
  rowValidation: true
  extraction:
    strategy: unload          # see table above
    externalStage: MY_DB.MY_SCHEMA.L3_EXT_STAGE
```

| Field | Required when | Notes |
|-------|----------------|-------|
| `extraction.strategy` | Always if not `regular` | `regular` \| `unload` \| `write_nos` \| `dbms_cloud` \| `cet_as` \| `export_data` \| `cloud_direct` |
| `extraction.externalStage` | Every strategy except `regular` | Three-part Snowflake stage name. Leading `@` optional. Must cover the object-store prefix. |

`tpt` is a DM alias for Teradata worker TPT; orchestrator treats it as `regular`. Do not use `tpt` to mean object-store pushdown (`write_nos` or `cloud_direct` instead).

## Worker TOML snippets

Restart the worker after edits (`data_infrastructure` / `scai data worker start`).

`scai data worker generate-config` typically writes `[connections.source.<engine>]` as `connection_name = "…"` and hydrates that name from `~/.snowflake/snowct/<engine>.toml` at start. Extra dump keys placed **next to** `connection_name` in `.scai/config/dew_configuration.toml` are dropped. Do **one** of:

1. **Named connection** — keep `connection_name` and add the dump keys (`unload_*`, `export_data_*`, `write_nos_*`, `dbms_cloud_*`, `cet_as_*`) on that connection in `~/.snowflake/snowct/<engine>.toml`.
2. **Inline** — remove `connection_name` and write the full worker source section in `.scai/config/dew_configuration.toml` (worker key names from [worker-config-reference.md](../../../data-infrastructure/references/worker-config-reference.md), plus the dump keys below).

`[connections.target.s3]` / `.gcs` / `.blob` are not name-hydrated; those stay in the project worker file.

The snippets below are the dump keys only. Put them on the snowct connection or on an inlined worker source section, not beside `connection_name`.

### Redshift `unload`

```toml
[connections.source.redshift]
# … generated host/credentials …
unload_s3_bucket = "my-migrations-bucket"
unload_iam_role_arn = "arn:aws:iam::123456789012:role/RedshiftUnloadRole"
# unload_s3_prefix = "dv-signatures"
```

IAM role must trust Redshift and allow `s3:PutObject` (and abort multipart) on the prefix.

### BigQuery `export_data`

```toml
[connections.source.bigquery]
# … project_id / credentials_file …
export_data_gcs_bucket = "my-migrations-bucket"
export_data_gcs_prefix = "dv-signatures"
export_data_file_format = "parquet"
export_data_overwrite = true
```

The BigQuery job identity needs create-object on the prefix. Snowflake’s GCS service account needs list + get. Full walkthrough: `dmvf/docs/data-migration-orchestrator/example-workflow-files/setup-bigquery-gcs-storage.md`.

### Oracle `dbms_cloud`

```toml
[connections.source.oracle]
# … generated …
dbms_cloud_credential_name = "AWS_S3_CRED"
dbms_cloud_file_uri_prefix = "https://my-migrations-bucket.s3.us-east-1.amazonaws.com/dv-signatures"
```

Oracle needs `EXECUTE` on `DBMS_CLOUD` and a credential for that URI. See `dmvf/data-exchange-agent/docs/oracle-dbms-cloud-local-setup.md`.

### Teradata `write_nos`

```toml
[connections.source.teradata]
# … generated …
write_nos_location_scheme = "/s3/"          # or /az/ or /gs/
write_nos_location_host = "my-migrations-bucket.s3.amazonaws.com"
# write_nos_location_container = "dv-signatures"
write_nos_function_mapping = "MY_NOS_MAPPING"   # preferred over inline keys
```

### SQL Server / Synapse `cet_as`

```toml
[connections.source.sqlserver]   # or [connections.source.azure_synapse]
cet_as_external_data_source = "MyBlobDataSource"
cet_as_file_format = "PARQUET_FF"
# cet_as_path_prefix = "dv-signatures"
```

CETAS is rejected on Azure SQL Database. Fall back to `cloud_direct`.

### `cloud_direct` (PostgreSQL, Db2, and fallback for others)

Configure **one** landing cloud. If several sections are present, the worker prefers S3, then GCS, then Blob unless the workflow sets `storageBackend`.

```toml
[connections.target.s3]
bucket_name = "my-migrations-bucket"
# prefix = "dv-signatures"
# profile_name = "my-profile"

# [connections.target.gcs]
# bucket_name = "my-gcs-bucket"
# prefix = "dv-signatures"

# [connections.target.blob]
# container_name = "my-container"
# connection_string = "DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net"
```

Stage `URL` must be the same bucket/container + prefix. Snowflake often shows GCS as `gcs://` while workers use `gs://`; treat them as the same bucket.

## Snowflake external stage SQL

Replace names, locations, and the integration. Run as a role that can create integrations (often `ACCOUNTADMIN`), then grant to the orchestrator role.

### S3

```sql
CREATE STORAGE INTEGRATION IF NOT EXISTS l3_s3_int
  TYPE = EXTERNAL_STAGE
  STORAGE_PROVIDER = 'S3'
  ENABLED = TRUE
  STORAGE_AWS_ROLE_ARN = '<aws-role-arn-that-trusts-snowflake>'
  STORAGE_ALLOWED_LOCATIONS = ('s3://my-migrations-bucket/dv-signatures/');

DESC STORAGE INTEGRATION l3_s3_int;
-- Use STORAGE_AWS_IAM_USER_ARN + STORAGE_AWS_EXTERNAL_ID in the AWS trust policy.

GRANT USAGE ON INTEGRATION l3_s3_int TO ROLE <orchestrator_role>;

CREATE STAGE IF NOT EXISTS MY_DB.MY_SCHEMA.L3_EXT_STAGE
  URL = 's3://my-migrations-bucket/dv-signatures/'
  STORAGE_INTEGRATION = l3_s3_int
  FILE_FORMAT = (TYPE = PARQUET);

GRANT READ ON STAGE MY_DB.MY_SCHEMA.L3_EXT_STAGE TO ROLE <orchestrator_role>;
```

### GCS

```sql
CREATE STORAGE INTEGRATION IF NOT EXISTS l3_gcs_int
  TYPE = EXTERNAL_STAGE
  STORAGE_PROVIDER = 'GCS'
  ENABLED = TRUE
  STORAGE_ALLOWED_LOCATIONS = ('gcs://my-migrations-bucket/dv-signatures/');

DESC STORAGE INTEGRATION l3_gcs_int;
-- Grant roles/storage.objectViewer on the bucket to STORAGE_GCS_SERVICE_ACCOUNT.

CREATE STAGE IF NOT EXISTS MY_DB.MY_SCHEMA.L3_EXT_STAGE
  URL = 'gcs://my-migrations-bucket/dv-signatures/'
  STORAGE_INTEGRATION = l3_gcs_int
  FILE_FORMAT = (TYPE = PARQUET);
```

### Azure Blob

```sql
CREATE STORAGE INTEGRATION IF NOT EXISTS l3_azure_int
  TYPE = EXTERNAL_STAGE
  STORAGE_PROVIDER = 'AZURE'
  ENABLED = TRUE
  AZURE_TENANT_ID = '<tenant-id>'
  STORAGE_ALLOWED_LOCATIONS = ('azure://myaccount.blob.core.windows.net/my-container/dv-signatures/');

DESC STORAGE INTEGRATION l3_azure_int;
-- Consent the AZURE_CONSENT_URL; grant Snowflake’s app read on the container.

CREATE STAGE IF NOT EXISTS MY_DB.MY_SCHEMA.L3_EXT_STAGE
  URL = 'azure://myaccount.blob.core.windows.net/my-container/dv-signatures/'
  STORAGE_INTEGRATION = l3_azure_int
  FILE_FORMAT = (TYPE = PARQUET);
```

Copy `externalStage: MY_DB.MY_SCHEMA.L3_EXT_STAGE` into the validation workflow. The integration name is **not** a workflow field.

## Alignment check

Writer destination and stage URL must share the same prefix:

| Strategy | Writer path | Stage `URL` |
|----------|-------------|-------------|
| `unload` | `s3://{unload_s3_bucket}/{unload_s3_prefix}/` | same |
| `export_data` | `gs://{export_data_gcs_bucket}/{export_data_gcs_prefix}/` | `gcs://…` equivalent |
| `dbms_cloud` | `dbms_cloud_file_uri_prefix` | S3 (or matching) URL for that prefix |
| `write_nos` | WRITE_NOS location host + container | matching cloud URL |
| `cet_as` | external data source location + `cet_as_path_prefix` | matching Azure URL |
| `cloud_direct` | `[connections.target.*]` bucket/container + prefix | matching URL |

Misalignment looks like empty `LIST` / `MissingSignatureExtractError`, not a data mismatch.

## Rollback

Set `extraction.strategy: regular` and remove `externalStage` (or leave it unused). No redeploy. Worker TOML extras can stay; `regular` ignores them.
