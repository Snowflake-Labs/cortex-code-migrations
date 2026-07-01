# Data Migration Troubleshooting Reference

Common failure modes and their solutions when running data migration via `scai`.

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

> **Stopping the service when done:** to suspend the orchestrator, suspend the compute pool, and stop the local worker after a wave completes, follow [../../../../data-infrastructure/teardown/SKILL.md](../../../../data-infrastructure/teardown/SKILL.md). Don't run `ALTER SERVICE ... SUSPEND` ad-hoc — the teardown sub-skill verifies no in-flight workflows first.
