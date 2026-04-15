# Worker Configuration Reference (TOML)

## Configuration Sections

| Section | Property | Type | Description |
|---------|----------|------|-------------|
| Top Level | `selected_task_source` | String | Always `"snowflake_stored_procedure"` |
| `[application]` | `max_parallel_tasks` | Integer | Max tasks processed in parallel (threads) |
| `[application]` | `task_fetch_interval` | Integer | Interval (seconds) between task fetch attempts |
| `[application]` | `affinity` | String | Affinity group to match with workflow affinity |
| `[connections.source.*]` | N/A | Object | Source system connection config. Requires ODBC driver. |
| `[connections.source.*]` | `database` | String | **Must match** `source.databaseName` in the workflow YAML. The worker uses this database for ODBC queries. A mismatch causes empty metadata/schema extraction. |
| `[connections.target.snowflake_connection_name]` | `connection_name` | String | Connection name from `~/.snowflake/config.toml` |

## SQL Server Source Template

```toml
selected_task_source = "snowflake_stored_procedure"

[application]
max_parallel_tasks = 4
task_fetch_interval = 30

[task_source.snowflake_stored_procedure]
connection_name = "<snowflake_connection_name>"

[connections.source.sqlserver]
username = "<username>"
password = "<password>"
database = "<database_name>"
host = "<host>"
port = 1433

[connections.target.snowflake_connection_name]
connection_name = "<snowflake_connection_name>"
```

## Redshift Source Template (IAM Auth)

```toml
selected_task_source = "snowflake_stored_procedure"

[application]
max_parallel_tasks = 4
task_fetch_interval = 30

[task_source.snowflake_stored_procedure]
connection_name = "<snowflake_connection_name>"

[connections.source.redshift]
username = "<username>"
database = "<database_name>"
auth_method = "iam-provisioned-cluster"
cluster_id = "<cluster_id>"
region = "<region>"
access_key_id = "<access_key_id>"
secret_access_key = "<secret_access_key>"
# unload_s3_bucket = "my-migrations-bucket"
# unload_iam_role_arn = "arn:aws:iam::123456789012:role/MyRole"

[connections.target.snowflake_connection_name]
connection_name = "<snowflake_connection_name>"
```

## Redshift Source Template (Standard Auth)

```toml
selected_task_source = "snowflake_stored_procedure"

[application]
max_parallel_tasks = 4
task_fetch_interval = 30

[task_source.snowflake_stored_procedure]
connection_name = "<snowflake_connection_name>"

[connections.source.redshift]
username = "<username>"
password = "<password>"
database = "<database_name>"
host = "<host>"
port = 5439
auth_method = "standard"

[connections.target.snowflake_connection_name]
connection_name = "<snowflake_connection_name>"
```

## Advanced: Redshift UNLOAD

For large Redshift tables, use the `unload` extraction strategy. This writes query results directly to an S3 bucket instead of downloading to the worker machine.

Worker TOML with UNLOAD S3 details:
```toml
[connections.source.redshift]
# ... standard redshift connection fields ...
unload_s3_bucket = "my-migrations-bucket"
unload_iam_role_arn = "arn:aws:iam::123456789012:role/MyRole"
```

Corresponding workflow YAML:
```yaml
extraction:
  strategy: unload
  externalStage: MY_DB.MY_SCHEMA.S3_EXTERNAL_STAGE
```

## Managing Workers

- Increase `max_parallel_tasks` for more parallelism on a single machine — no need to run multiple workers on the same machine.
- Network bandwidth is shared between threads of a worker.
- Keep a low worker count to avoid overloading your source system.
- Stop workers during peak source system usage to avoid disrupting existing operations.

## Note: Iceberg Migrations and Workers

The Worker TOML configuration **does not change** for Iceberg migrations. However, most Iceberg strategies bypass the Data Exchange Agent (Worker) entirely:

| Iceberg Strategy | Worker Involved? | Reason |
|------------------|------------------|--------|
| `catalog_link` | No | Pure DDL — no data extraction |
| `convert_to_managed` | No | Pure DDL — no data extraction |
| `copy_files` with `sourceDataStage` | No | Schema inferred from Parquet via `INFER_SCHEMA`; data copied server-side |
| `copy_files` without `sourceDataStage` | **Yes** | Worker extracts schema from source database (e.g. `SVV_EXTERNAL_COLUMNS` for Redshift) |

If your workflow contains **only** Iceberg tables using `catalog_link`, `convert_to_managed`, or `copy_files` with `sourceDataStage`, you do **not** need to start a Worker.
