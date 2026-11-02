# Database Manifest Reference

The conversion writes `database-manifest.json`. It is the contract between the converted SQL and whatever loads the tables. Read it. The landing names in it are the names the SQL already uses.

## Where it sits

Prefer the newest run folder:

```
artifacts/database-ingestion/<conversion-run>/database-manifest.json
```

Otherwise `artifacts/database-ingestion/database-manifest.json`, then `database-manifest.json` under the ETL output root.

`schemaVersion` `1.0` is the shape below.

## What to report

| Row | Recognize it by | Show |
|---|---|---|
| Snapshot | `ingestion.state` is `ingestion` and `ingestion.mode` is `snapshot` | Source identity, and `ingestion.landing` as `database.schema.table` |
| Change Tracking | `ingestion.mode` is `sqlServerChangeTracking` and `ingestion.state` is `ingestion` | Source identity and `ingestion.landing`. The table name is the source table name. |
| CDC | `ingestion.mode` is `sqlServerCdc` and `ingestion.state` is `ingestion` | Same as Change Tracking. |
| Rejected | `ingestionConfiguration.state` is `rejected` | `validationErrors`, verbatim |
| Unresolved | `resolutionState` is `requiresMapping` | `id` and `unresolvedReason` when present. No landing name. |
| Excluded | `ingestion.state` is `excluded` | The rule id. No landing name. |

Source identity is the manifest's server or connection, database, schema, and table. A missing `ingestion.landing` means the manifest did not record a destination.

## Generated Openflow snapshot files

Written under the ETL output's `openflow/` directory when a snapshot config was applied:

```
SnowConvert Database Landing.json
SnowConvert Database Tables NNN.json
```

`NNN` is one file per source server and database, numbered from `001`.

The flow ships with these parameter-context values empty:

- `SNOWFLAKE_ACCOUNT`
- `SNOWFLAKE_AUTHENTICATION_STRATEGY`
- `SNOWFLAKE_ROLE`
- `SNOWFLAKE_USER`
- `SNOWFLAKE_WAREHOUSE`
- per source group: `SOURCE_JDBC_DRIVER`, `SOURCE_JDBC_DRIVER_CLASS`, `SOURCE_JDBC_URL`, `SOURCE_USER`, `SOURCE_PASSWORD`, `SOURCE_TABLE_MAPPING`

The Snowflake connection service is the credential service. It sits outside the parameter context. `SOURCE_PASSWORD` is filled in Openflow, not in the migration project and not in the landing plan.
