# Talend Element Types

Component kinds and their Snowflake/dbt equivalents. The component kind comes from `node/@componentName`
(e.g. `tMap`, `tMSSqlInput`, `tSendMail`) — the trailing `_N` in `elementParameter/@name="UNIQUE_NAME"`
is the instance suffix, not part of the kind.

## Convertible components (have a dbt/SQL equivalent)

| Component | Snowflake / dbt equivalent | Notes |
|-----------|---------------------------|-------|
| `t*Input` (`tOracleInput`, `tMysqlInput`, `tMSSqlInput`, `tDBInput`, ...) | dbt source, or a staging model selecting from it | The `QUERY` `elementParameter` decides the column set |
| `t*Output` (`tMysqlOutput`, `tMSSqlOutput`, `tDBOutput`, ...) | materialized model (table), or a `MERGE`/incremental model | `TABLE_ACTION`/`DATA_ACTION` decide full-refresh vs. incremental |
| `tMap` | `SELECT` with `CASE`/`COALESCE`/joins | Read `nodeData/outputTables/mapperTableEntries/@expression`, not `elementParameter` |
| `tFilterRow` | `WHERE` predicate | Filter condition is an `elementParameter`, evaluated per input row |
| `tAggregateRow` | `GROUP BY` with aggregates | Group-by fields plus aggregate functions, same shape as Alteryx's `Summarize` |
| `tUniqRow` | `QUALIFY ROW_NUMBER() OVER (PARTITION BY key)` | Needs a deterministic order to be reproducible |
| `tSortRow` | `ORDER BY` | Ordering alone is not durable in a table materialization |
| `tJoin` | `JOIN` | Join keys are listed in the component's `elementParameter` table |
| `tUnite` | `UNION ALL` | |
| `tConvertType` | explicit `::TYPE` cast | |
| `tReplace` / `tExtractDelimitedFields` / `tExtractRegexFields` / `tExtractJSONFields` | string functions, `SPLIT`, `PARSE_JSON` | |
| `tNormalize` / `tDenormalize` / `tPivot` / `tUnpivot` | `LATERAL FLATTEN`, `PIVOT`/`UNPIVOT` | |
| `tSCD` / `tMysqlSCD` (and other `t*SCD`) | dbt `snapshot` | See `tool-guide.md` |
| `tChangeDataCapture` | dbt `snapshot`, or an incremental model keyed on a change column | |
| `tFileInputDelimited` / `tFileInputExcel` / `tFileInputJSON` / `tFileInputXML` / `tFileInputParquet` | dbt source over an external stage + external table | The file itself is out of dbt's reach; see "Components with no SQL equivalent" for the stage/COPY INTO step |

## Components with no SQL equivalent

These have no dbt/Snowflake representation and must be classified as external dependencies rather
than approximated. Recommended remediation target by category (from
`component-references/infrastructure/not-convertible.md` in the Talend-to-dbt reference):

| Category | Components (non-exhaustive) | Recommended target |
|----------|------------------------------|---------------------|
| File operations | `tFileList`, `tFileCopy`, `tFileDelete`, `tFileExist`, `tFileRename`, `tFileUnarchive`, `tDirectoryCreate`, `tFileProperties`, `tFileMove` | Snowflake Tasks + Streams, or Airflow/Dagster |
| API / HTTP | `tHttpRequest`, `tREST`, `tSOAP`, `tWebService`, `tFileFetch`, `tSalesforceInput`/`Output`, `tSAPInput`, `tNetsuiteInput`, `tMarketoInput` | Fivetran, Airbyte, or Openflow (Snowflake-native) |
| Messaging | `tKafkaInput`/`Output`, `tJMSInput`/`Output`, `tActiveMQInput`, `tRabbitMQInput` | Snowpipe Streaming, or the platform's native Kafka connector |
| Email / FTP | `tSendMail`, `tFTPGet`, `tFTPPut`, `tSFTP` | Orchestrator-native notification/transfer step (Airflow, Dagster) |
| Cloud storage | `tAmazonS3Input`/`Output`, `tAzureBlobInput`/`Output`, `tGoogleStorageInput`/`Output` | Snowflake external stages + external tables |
| Control flow | `tRunIf`, `tLoop`, `tForEach`, `tParallelize`, `tSleep`, `tFlowToIterate` (unless it feeds a dbt macro jinja loop) | Orchestrator DAG (dbt `ref()` graph for data dependencies; Airflow/Dagster for the rest) |
| Orchestration | `tRunJob` | Not a data-flow node — states a `ref()`/`depends_on` edge, not a model; see `workflow-guide.md` |
| Custom code | `tJavaRow` / `tJava` / `tGroovy` | Flag for manual UDF review — arbitrary Java/Groovy has no general SQL translation |
| Monitoring / logging | `tStatCatcher`, `tFlowMeter`/`tFlowMeterCatcher`, `tLogCatcher`, `tLogRow`, `tChronometerStart`/`Stop`, `tMsgBox`, `tWarn`, `tDie` | Always ignore — no dbt equivalent; use dbt test results / Elementary / Snowflake alerts if monitoring is still wanted |
| Database admin | `tDBConnection`/`tMSSqlConnection`/`tOracleConnection`/`tPostgresqlConnection`, `tDBClose`, `tDBCommit`/`tMSSqlCommit`, `tDBRollback`/`tMSSqlRollback`, `tDBTableCreate`, `tDBSP`, `tDBBulkExec` | Handled by dbt profiles / Snowflake; no per-job equivalent |
| Assertions | `tAssert`, `tAssertCatcher`, `tSchemaComplianceCheck` | dbt tests (schema tests in `_models.yml`, or a singular test for `tAssert`) |
| Variables | `tSetGlobalVar` | `{{ var() }}` only if the value is actually read in SQL downstream; otherwise ignore |
| Pre/post hooks | `tPrejob` / `tPostjob` | dbt `on-run-start` / `on-run-end` hooks — ONLY if they execute SQL; file/email side effects are out of scope |

This is remediation guidance, not automatic conversion: none of the components above gets a
generated model. The table names where the *capability* moves, not a code path SnowConvert or
the AI-First producer will emit for it.

## Reading a converted element

For a unit converted through the AI-First path:

- `ETL.Elements.FullName` is the bare digit-suffixed node id extracted from
  `elementParameter/@name="UNIQUE_NAME"` (e.g. `tMap_2` → element id `2`), and `Category` is
  `source`, `transformation`, or `target`.
- `ETL.Issues.ComponentFullName` states the same element as the emitted dbt model name (`m_2`).
  The two reports spell one fact two ways; when correlating them, normalize to the bare digit
  token (see `_digit_tokens` in `scan_unit.py`).
- The remediation brief states elements as bare ids in `element_ids` and the generated files in
  `models`, so it joins directly against `ETL.Elements`.
