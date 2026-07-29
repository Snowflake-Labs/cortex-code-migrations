# Data Migration Troubleshooting Reference

Common failure modes and their solutions when running data migration via `scai`.

---

## `cryptography` / `_rust.abi3.so` symbol not found in flat namespace

**Symptom:** `migrate_data`/`validate_data` fail (often `Error [DMG0011]: Data exchange agent failed: Could not parse orchestrator workflow config validation output`) with a Python traceback like:

```
ImportError: dlopen(.../data-migration-orchestrator/lib/pythonX.Y/site-packages/cryptography/hazmat/bindings/_rust.abi3.so, 0x0002):
  symbol not found in flat namespace '_OSSL_get_max_threads'
```

(`_DTLS_get_data_mtu` is the same class of error.) It also shows up as `scai data doctor` **DEW doctor** / **Orchestrator doctor** warnings. The MCP run gate now treats this signature as a **blocking** failure instead of a warning, so `migrate_data(mode="run")` returns it in `doctor_failures` with this remediation rather than dying mid-workflow.

**Cause:** The orchestrator/DEA run in bundled Python venvs under `~/.config/Snowflake Inc/SnowConvertDesktop/{data-migration-orchestrator,data-exchange-agent}/`, created by SnowConvert Desktop via `pip install`. `cryptography` is a transitive dependency. When pip installs it as a **source build (sdist)** instead of the self-contained binary wheel, `_rust.abi3.so` is linked to resolve OpenSSL symbols from an **external** OpenSSL at load time. If a different/older OpenSSL resolves first at runtime, the symbol lookup fails. The official `cryptography` wheels (maturin, e.g. `cp311-abi3-macosx_11_0_arm64`) instead **statically bundle** OpenSSL and link only `libSystem`/`libiconv` — those never hit this error. This is environment nondeterminism (Python version, available wheels), **not** an Apple-Silicon limitation: an arm64 machine that resolved the bundled wheel works fine.

**Diagnose:**
```bash
CFG="$HOME/.config/Snowflake Inc/SnowConvertDesktop"
PY="$CFG/data-migration-orchestrator/bin/python"
# Does it import?
"$PY" -c "import cryptography; from cryptography.hazmat.bindings._rust import openssl; print(cryptography.__version__)"
# Healthy: links only libSystem/libiconv (OpenSSL bundled). Broken: references an external libssl/libcrypto.
otool -L "$(find "$CFG/data-migration-orchestrator" -name _rust.abi3.so | head -1)"
```

**Fix (repair the venvs — force the binary wheel):**
```bash
CFG="$HOME/.config/Snowflake Inc/SnowConvertDesktop"
for env in data-migration-orchestrator data-exchange-agent; do
  "$CFG/$env/bin/python" -m pip install --force-reinstall --no-cache-dir \
    --only-binary=cryptography cryptography
done
```
Then re-run `scai data doctor` (or `migrate_data(mode="run")`). If pip reports no wheel is available for that platform/Python, that is the real problem — upgrade pip or use a Python version with a published `cryptography` wheel. Alternatively, delete the two venv directories and let SnowConvert Desktop recreate them, or reinstall SnowConvert Desktop.

**Durable fix:** SnowConvert Desktop pins `--only-binary=cryptography` when bootstrapping these venvs (`PythonPackageEnvironmentManager.BuildInstallArgs`), so pip can no longer source-build cryptography.

---

## "Found 0 pending workflows" in orchestrator logs

**Symptom:** You submitted a workflow via `scai data migrate create-workflow`, but the orchestrator service logs (`CALL SYSTEM$GET_SERVICE_LOGS(...)`) repeatedly show `Found 0 pending workflows`.

**Cause:** Affinity mismatch. The orchestrator service has a baked-in `affinity` value from when it was created, but the workflow was submitted without a matching affinity (or with `null`).

**Diagnosis:**
```sql
-- Check the orchestrator's affinity from service startup logs
CALL SYSTEM$GET_SERVICE_LOGS(
  'SNOWCONVERT_AI.DATA_MIGRATION.DATA_MIGRATION_SERVICE', '0', 'orchestrator', 50
);
-- Look for: "Orchestrator affinity: <value>"

-- Check the workflow's affinity
SELECT ID, NAME, STATUS, AFFINITY
FROM SNOWCONVERT_AI.DATA_MIGRATION.WORKFLOW
ORDER BY ID DESC LIMIT 5;
```

**Fix:**
1. Update the workflow's `AFFINITY` column to match the orchestrator's value:
   ```sql
   UPDATE SNOWCONVERT_AI.DATA_MIGRATION.WORKFLOW
   SET AFFINITY = '<orchestrator_affinity>'
   WHERE ID = <workflow_id>;
   ```
2. Or, set `affinity: <value>` in the workflow YAML before submitting.
3. Also set `affinity = "<value>"` in the worker's `[application]` section in `DataExchangeWorkerConfig.toml`.

---

## Worker claims tasks from old/wrong workflows

**Symptom:** The worker picks up tasks from a previous migration (e.g., Teradata data-validation tasks) and fails with errors like `Engine 'teradata' not found in source connections`.

**Cause:** Old workflows left pending/executing tasks in the `TASK_QUEUE` table. The worker claims tasks globally (filtered only by affinity), not scoped to a specific workflow.

**Diagnosis:**
```sql
SELECT WORKFLOW_ID, STATUS, COUNT(*)
FROM SNOWCONVERT_AI.DATA_MIGRATION.TASK_QUEUE
WHERE STATUS IN ('pending', 'executing', 'blocked')
GROUP BY WORKFLOW_ID, STATUS
ORDER BY WORKFLOW_ID;
```

**Fix:** Cancel stale tasks from old workflows:
```sql
UPDATE SNOWCONVERT_AI.DATA_MIGRATION.TASK_QUEUE
SET STATUS = 'cancelled'
WHERE WORKFLOW_ID != <your_workflow_id>
  AND STATUS IN ('pending', 'executing', 'blocked');
```

---

## "Table does not exist in the source database" / empty metadata

**Symptom:** The orchestrator logs `TableNotFoundError: Table '<db>.<schema>.<table>' does not exist in the source database`. The worker completed the metadata extraction task without errors, but no data was uploaded.

**Cause:** The worker's ODBC connection uses the `database` field from `DataExchangeWorkerConfig.toml` to set the active database. If this doesn't match the `source.databaseName` in the workflow YAML, queries against `information_schema.columns` and `SVV_TABLE_INFO` return zero rows (they are scoped to the connected database).

**Fix:** Ensure the `database` field in `[connections.source.*]` in `DataExchangeWorkerConfig.toml` matches the `source.databaseName` in `workflow-config.yaml`. Then delete the failed workflow/tasks and resubmit.

**Oracle:** `[connections.source.oracle].database` is the **service name** (from `scai connection add-oracle --service-name`), not a SQL Server–style database name. It must match `source.databaseName` in the workflow YAML the same way.

**Teradata:** `[connections.source.teradata].database` is the Teradata **database name** (from `scai connection add-teradata --database`). It must match `source.databaseName` in the workflow YAML. Teradata uses two-part names (`database.table`); align `databaseName` with the database that owns the table.

---

## `whereClauseCriteria` syntax error during extraction

**Symptom:** The extraction task fails with a SQL syntax error like `syntax error at or near "TOP"` (Redshift) or similar.

**Cause:** `whereClauseCriteria` is injected directly after `WHERE` in the extraction query:
```sql
SELECT ... FROM <table> WHERE <whereClauseCriteria>
```

Using `TOP 1000 1=1` (SQL Server syntax) or `LIMIT 1000` (Redshift syntax) is invalid inside a WHERE clause.

**Fix:** Use a valid WHERE predicate to limit rows:
- Filter on a key column: `"<primary_key> <= 1000"`
- **Oracle:** e.g. `"ROWNUM <= 1000"` (do not use `TOP` or `LIMIT` in `whereClauseCriteria`)
- **Teradata:** e.g. `"customer_id <= 1000"` (valid WHERE predicates only; do not use `TOP` or `LIMIT` here)
- Use a boolean condition: `"is_active = true"`
- Or remove `whereClauseCriteria` entirely and migrate the full table

---

## SPCS service privilege errors

**Symptom:** `scai data orchestrator setup` or `scai data migrate create-workflow` fails with privilege errors like "current role has no privileges" on `DATA_MIGRATION_SERVICE`.

**Cause:** The SPCS service was created by a different role (often `ACCOUNTADMIN`), and the current role lacks OPERATE/MONITOR privileges.

**Fix:** Have an admin grant the required privileges:
```sql
USE ROLE SYSADMIN; -- or whichever role owns the service

GRANT USAGE ON DATABASE SNOWCONVERT_AI TO ROLE <your_role>;
GRANT USAGE ON SCHEMA SNOWCONVERT_AI.DATA_MIGRATION TO ROLE <your_role>;
GRANT OPERATE, MONITOR ON SERVICE SNOWCONVERT_AI.DATA_MIGRATION.DATA_MIGRATION_SERVICE TO ROLE <your_role>;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA SNOWCONVERT_AI.DATA_MIGRATION TO ROLE <your_role>;
GRANT ALL PRIVILEGES ON ALL PROCEDURES IN SCHEMA SNOWCONVERT_AI.DATA_MIGRATION TO ROLE <your_role>;
GRANT ALL PRIVILEGES ON ALL STAGES IN SCHEMA SNOWCONVERT_AI.DATA_MIGRATION TO ROLE <your_role>;
GRANT ALL PRIVILEGES ON ALL FILE FORMATS IN SCHEMA SNOWCONVERT_AI.DATA_MIGRATION TO ROLE <your_role>;
GRANT ALL PRIVILEGES ON ALL VIEWS IN SCHEMA SNOWCONVERT_AI.DATA_MIGRATION TO ROLE <your_role>;
```

---

## Service stays SUSPENDED after `--start-service`

**Symptom:** `scai data migrate create-workflow --start-service` appears to succeed, but `SELECT SYSTEM$GET_SERVICE_STATUS(...)` returns `[]` (no running instances).

**Diagnosis:**
```sql
SELECT SYSTEM$GET_SERVICE_STATUS('SNOWCONVERT_AI.DATA_MIGRATION.DATA_MIGRATION_SERVICE');
-- Returns [] when suspended, or a JSON array with status when running
```

**Fix:** Manually resume the service:
```sql
ALTER SERVICE SNOWCONVERT_AI.DATA_MIGRATION.DATA_MIGRATION_SERVICE RESUME;
```

Then wait 30-60 seconds for the container to start and re-check the status.

---

## Task dependency and ordering anomalies

**Symptoms:** Tasks stuck in `blocked` while earlier phases appear done; extraction never starts; load tasks wait indefinitely.

**Diagnosis:**

```sql
-- Find blocked tasks and their scopes
SELECT ID, NAME, STATUS, SCOPE, SUCCESSOR_TASK_ID
FROM SNOWCONVERT_AI.DATA_MIGRATION.TASK_QUEUE
WHERE WORKFLOW_ID = <id> AND STATUS = 'blocked'
ORDER BY ID;

-- Find failed predecessors in the same table scope
SELECT ID, NAME, STATUS, LAST_ERROR_MESSAGE, SCOPE
FROM SNOWCONVERT_AI.DATA_MIGRATION.TASK_QUEUE
WHERE WORKFLOW_ID = <id>
  AND SCOPE LIKE 'Table[MY_DB.MY_SCHEMA.MY_TABLE]::%'
ORDER BY ID;
```

**Common causes:**
- A failed preprocessing or extraction task left successors permanently blocked
- Snowpipe setup raced ahead of target table creation (new-table migrations — orchestrator normally queues setup after DDL)
- Stale tasks from a previous workflow with the same affinity blocking worker capacity

**Fix:** Identify the earliest non-`completed` task in the scope chain, read `LAST_ERROR_MESSAGE`, fix the root cause, then cancel/re-run the workflow. See [Task model reference](./task-model-reference.md) for scope grammar and pause/cancel procedures.

---

## Per-task failure classification

When MCP `reports` are insufficient, query failed tasks directly:

```sql
SELECT NAME, EXECUTOR_TYPE, LAST_ERROR_MESSAGE, SCOPE, FAILURES
FROM SNOWCONVERT_AI.DATA_MIGRATION.TASK_QUEUE
WHERE WORKFLOW_ID = <id> AND STATUS = 'failed'
ORDER BY ID;
```

| `EXECUTOR_TYPE` | Typical failure categories |
|-----------------|----------------------------|
| `data-exchange-agent` | Source connectivity, ODBC/driver, invalid SQL, permission denied |
| `orchestrator` | Config validation, partition strategy, staged-data processing |
| `warehouse` | Snowflake DDL/DML errors, stage/path issues |

### Source-connectivity quick check

If metadata/schema extraction completes with **zero rows** but no worker error, compare worker TOML `[connections.source.*].database` against workflow `source.databaseName` (Oracle: service name; Teradata: database name). This is the most common silent failure mode.

---

## `POSSIBLE_MISMATCH` after validation completes

Hybrid L3 validation may stop early when `earlyStoppingForRowHashing` or `maxFailedRowsNumber` is reached. A workflow can finish with `POSSIBLE_MISMATCH` result codes — **do not treat as a clean pass**. Review L3 result tables and consider re-running with adjusted early-stop settings or narrower `sourceWhereClause`/`targetWhereClause` filters.

---

## Workflow finished but tables incomplete

**Symptom:** `progress.output.isFinished` is `true` (workflow status `Finished`) but work did not complete for every table:

| Job | Incomplete signal |
|-----|-------------------|
| **Migration** | `preprocessedTables < totalTables`, or any `tablePartitions[].hasBeenPreprocessed == false`, or `aggregatedCounts.failedPartitions > 0` |
| **Validation** | `validatedTables + failedTables < totalTables`, or any `tableStates[].status == "Pending"` |

**Meaning:** The orchestrator closed the workflow while one or more tables never finished. This is an **error**, not success — scai treats it as `HasErrors`.

**Do not assume** the only cause is “workers not processing.” Common causes include:

- Local worker not running, wrong affinity, or claiming stale tasks from another workflow
- Worker `database` / connection mismatch (tasks complete but produce no data)
- Tasks **failed** or **cancelled** in `TASK_QUEUE` while the workflow still marked finished
- SPCS orchestrator suspended or not picking up workflows

**Fix path (in order):**

1. **MCP / reports (no SQL):** Re-read the latest status response. Use `reports.files.errors` / `reports.files.progress` (migration) or `tableStates[].errorMessage` and `reports.files.data_validation_errors` (validation) for `LastErrorMessage` / task detail.
2. **Task queue:** Resolve `WORKFLOW_ID` from `WORKFLOW` (match `NAME` to `progress.output.workflowName`), then run the queries below. Look for tasks still `pending` / `executing` / `blocked` vs `failed` / `cancelled` / `completed`, and read `LAST_ERROR_MESSAGE`.
3. **Infrastructure:** If tasks are stuck pending with no errors, check worker process, affinity, stale `TASK_QUEUE` rows, and `SYSTEM$GET_SERVICE_STATUS` for the orchestrator — see sections above in this reference.

**Tell the user:** “Workflow finished but N table(s) never completed — checking task errors…” — then report what `reports` and (if needed) `TASK_QUEUE` show. Offer troubleshooting steps before suggesting re-run.

---

## Useful diagnostic queries

```sql
-- Check service status
SELECT SYSTEM$GET_SERVICE_STATUS('SNOWCONVERT_AI.DATA_MIGRATION.DATA_MIGRATION_SERVICE');

-- Read orchestrator logs (last 50 lines)
CALL SYSTEM$GET_SERVICE_LOGS(
  'SNOWCONVERT_AI.DATA_MIGRATION.DATA_MIGRATION_SERVICE', '0', 'orchestrator', 50
);

-- List recent workflows
SELECT ID, NAME, STATUS, AFFINITY, INITIATOR_ID, CREATION_TIME
FROM SNOWCONVERT_AI.DATA_MIGRATION.WORKFLOW
ORDER BY ID DESC LIMIT 10;

-- Check task status for a specific workflow
SELECT ID, NAME, EXECUTOR_TYPE, STATUS, FAILURES, LAST_ERROR_MESSAGE
FROM SNOWCONVERT_AI.DATA_MIGRATION.TASK_QUEUE
WHERE WORKFLOW_ID = <id>
ORDER BY ID;

-- Count active tasks by workflow
SELECT WORKFLOW_ID, STATUS, COUNT(*)
FROM SNOWCONVERT_AI.DATA_MIGRATION.TASK_QUEUE
WHERE STATUS NOT IN ('completed', 'failed', 'cancelled')
GROUP BY WORKFLOW_ID, STATUS
ORDER BY WORKFLOW_ID;
```

> **Task model:** For scope grammar, dependency chains, and pause/resume/cancel procedures, see [Task model reference](./task-model-reference.md).

> **Stopping the service when done:** to suspend the orchestrator, suspend the compute pool, and stop the local worker after a wave completes, follow [../../../../data-infrastructure/teardown/SKILL.md](../../../../data-infrastructure/teardown/SKILL.md). Don't run `ALTER SERVICE ... SUSPEND` ad-hoc — the teardown sub-skill verifies no in-flight workflows first.
