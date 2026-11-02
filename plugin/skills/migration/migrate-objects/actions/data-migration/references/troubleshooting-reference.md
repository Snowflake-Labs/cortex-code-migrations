# Data Migration Troubleshooting Reference

`<metadata_database>` below is `.scai/config/plugin.yml` `metadata_database` (`SNOWCONVERT_AI` unless
overridden): this project's workflows, tasks and results live there, and `SNOWCONVERT_AI` may hold another
project's.

Common failure modes and their solutions when running data migration via `scai`.

---

## `cryptography` / `_rust.abi3.so` symbol not found in flat namespace

**Symptom:** `migrate_data` fails (often `Error [DMG0011]: Data exchange agent failed: Could not parse orchestrator workflow config validation output`) with a Python traceback like:

```
ImportError: dlopen(.../data-migration-orchestrator/lib/pythonX.Y/site-packages/cryptography/hazmat/bindings/_rust.abi3.so, 0x0002):
  symbol not found in flat namespace '_OSSL_get_max_threads'
```

(`_DTLS_get_data_mtu` is the same class of error.) `scai data doctor` reports it as a failing **DEW doctor** / **Orchestrator doctor** row, with the repair below as its suggestion, so `data_infrastructure(mode="up")` refuses with it in `doctor_failures` rather than letting the workflow die mid-run.

**Cause:** The orchestrator/DEA run in bundled Python venvs under `~/.config/Snowflake Inc/SnowConvertDesktop/{data-migration-orchestrator,data-exchange-agent}/`, created by the desktop app via `pip install`. `cryptography` is a transitive dependency. When pip installs it as a **source build (sdist)** instead of the self-contained binary wheel, `_rust.abi3.so` is linked to resolve OpenSSL symbols from an **external** OpenSSL at load time. If a different/older OpenSSL resolves first at runtime, the symbol lookup fails. The official `cryptography` wheels (maturin, e.g. `cp311-abi3-macosx_11_0_arm64`) instead **statically bundle** OpenSSL and link only `libSystem`/`libiconv` — those never hit this error. This is environment nondeterminism (Python version, available wheels), **not** an Apple-Silicon limitation: an arm64 machine that resolved the bundled wheel works fine.

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
Then re-run `scai data doctor` (or `migrate_data(mode="run")`). If pip reports no wheel is available for that platform/Python, that is the real problem — upgrade pip or use a Python version with a published `cryptography` wheel. Alternatively, delete the two venv directories and let the desktop app recreate them, or reinstall the app.

**Durable fix:** The desktop app pins `--only-binary=cryptography` when bootstrapping these venvs (`PythonPackageEnvironmentManager.BuildInstallArgs`), so pip can no longer source-build cryptography.

---

## "Found 0 pending workflows" in orchestrator logs

**Symptom:** You submitted a workflow via `scai data migrate create-workflow`, but the orchestrator service logs (`CALL SYSTEM$GET_SERVICE_LOGS(...)`) repeatedly show `Found 0 pending workflows`.

**Cause:** The orchestrator was given an affinity. An orchestrator without one claims every pending workflow, and scai never gives it one (`scai data orchestrator setup` / `start` and `data_infrastructure(mode="up")` leave `DATA_MIGRATION_ORCHESTRATOR_AFFINITY` unset). Only a hand-written service spec or environment that sets `DATA_MIGRATION_ORCHESTRATOR_AFFINITY` pins it, and then workflows of any other affinity stay `pending`.

**Diagnosis:**
```sql
-- Check the orchestrator's affinity from service startup logs
CALL SYSTEM$GET_SERVICE_LOGS(
  '<metadata_database>.DATA_MIGRATION.DATA_MIGRATION_SERVICE', '0', 'orchestrator', 50
);
-- Look for: "Orchestrator affinity: <value>". "None" means unset, so the cause is elsewhere.

-- Check the workflow's affinity
SELECT ID, NAME, STATUS, AFFINITY
FROM <metadata_database>.DATA_MIGRATION.WORKFLOW
ORDER BY ID DESC LIMIT 5;
```

**Fix:** remove `DATA_MIGRATION_ORCHESTRATOR_AFFINITY` from the orchestrator's spec or environment and restart. Confirm with the user first: `scai data orchestrator setup --compute-pool <pool> --yes` drops the Data Migration Service and rebuilds it from scai's spec, which cuts off any workflow that service is running and loses a hand-written image unless `--custom-image <image>` is passed again. Check that no workflow is `running`, and pass `--custom-image <image>` when the current spec used one. Do not rewrite the workflow's `AFFINITY` to the orchestrator's value: the workflow's affinity is what routes its tasks to the right worker, see the [Affinity Reference](../../../../data-infrastructure/references/affinity-reference.md).

If the log shows `Orchestrator affinity: None` and the workflow is no longer `pending` but its tasks never start, the mismatch is on the worker side: no running worker carries the workflow's affinity. Compare the workflow's `AFFINITY` with each worker's (`scai data worker list`, `[application].affinity` in `.scai/config/dew_configuration.toml`, or `AGENT_AFFINITY` in an SPCS / Kubernetes spec). A worker set up by hand with its own label does not claim workflows stamped with the project-default affinity; regenerate the workflow under the worker's label (`configure(affinity="<label>")`, then `migrate_data(mode="setup", where=…, force_regenerate=true)`).

---

## "Execution timeout exceeded (task ran for longer than N min)"

**Symptom:** A task fails (or is abandoned then fails after retries) with:
```text
Execution timeout exceeded (task ran for longer than 20 min).
```
Typically the task name is `Analyze boundaries: <table>`.

**Cause:** The orchestrator sets a wall-clock `EXECUTION_TIMEOUT_MINUTES` on **Analyze boundaries** DEA tasks (default **20**). `EXPIRE_LEASES` abandons the task when that limit is exceeded — even if the worker (local or SPCS) is still alive and refreshing its lease. This is **not** an SPCS container timeout.

**Diagnosis:**
```sql
SELECT ID, NAME, STATUS, EXECUTION_TIMEOUT_MINUTES, LAST_ERROR_MESSAGE, ABANDONMENTS
FROM <metadata_database>.DATA_MIGRATION.TASK_QUEUE
WHERE WORKFLOW_ID = <id>
  AND (NAME ILIKE 'Analyze boundaries%' OR LAST_ERROR_MESSAGE ILIKE '%Execution timeout%')
ORDER BY ID;
```

**Fix:** Raise the timeout in workflow YAML (per table or under `defaultTableConfiguration`), then resubmit:
```yaml
tables:
  - source: { ... }
    target: { ... }
    columnNamesToPartitionBy: [ ... ]
    executionTimeoutMinutes: 90   # > observed boundary-analysis duration
```
Also consider a cheaper partition key / larger partitions so NTILE boundary analysis finishes sooner. See [workflow-config-reference.md](./workflow-config-reference.md).

**Operational workaround** (in-flight workflow without resubmitting YAML): update `EXECUTION_TIMEOUT_MINUTES` on the `TASK_QUEUE` row and re-queue if already `failed`.

---

## Worker claims tasks from old/wrong workflows

**Symptom:** The worker picks up tasks from a previous migration (e.g., tasks from an earlier Teradata workflow) and fails with errors like `Engine 'teradata' not found in source connections`.

**Cause:** Old workflows left pending/executing tasks in the `TASK_QUEUE` table. The worker claims tasks globally (filtered only by affinity), not scoped to a specific workflow.

**Diagnosis:**
```sql
SELECT WORKFLOW_ID, STATUS, COUNT(*)
FROM <metadata_database>.DATA_MIGRATION.TASK_QUEUE
WHERE STATUS IN ('pending', 'executing', 'blocked')
GROUP BY WORKFLOW_ID, STATUS
ORDER BY WORKFLOW_ID;
```

**Fix:** Cancel stale tasks from old workflows:
```sql
UPDATE <metadata_database>.DATA_MIGRATION.TASK_QUEUE
SET STATUS = 'cancelled'
WHERE WORKFLOW_ID != <your_workflow_id>
  AND STATUS IN ('pending', 'executing', 'blocked');
```

---

## "Table does not exist in the source database" / empty metadata

**Symptom:** The orchestrator logs `TableNotFoundError: Table '<db>.<schema>.<table>' does not exist in the source database`. The worker completed the metadata extraction task without errors, but no data was uploaded.

**Cause:** The worker's ODBC connection uses the `database` field from the project's `.scai/config/dew_configuration.toml` (path relative to the SCAI project root) to set the active database. If this doesn't match the `source.databaseName` in the workflow YAML, queries against `information_schema.columns` and `SVV_TABLE_INFO` return zero rows (they are scoped to the connected database).

**Fix:** Ensure the `database` field in `[connections.source.*]` in the project's `.scai/config/dew_configuration.toml` matches the `source.databaseName` in `workflow-config.yaml`. Then delete the failed workflow/tasks and resubmit.

**Oracle:** `[connections.source.oracle].database` is the **service name** (from `scai connection add-oracle --service-name`), not a SQL Server–style database name. It must match `source.databaseName` in the workflow YAML the same way.

**Teradata:** `[connections.source.teradata].database` is the Teradata **database name** (from `scai connection add-teradata --database`). It must match `source.databaseName` in the workflow YAML. Teradata uses two-part names (`database.table`); align `databaseName` with the database that owns the table.

---

## No schema found at schema/ — Stage file not yet visible

**Symptom:** tables fail at `Resolve vector metadata: <table>` with `ValueError: No schema found at @<metadata_database>.DATA_MIGRATION.TASK_RESULTS/task_results/workflows/<w>/tables/<t>/schema/. Stage file not yet visible — DEA write may still be in-flight.` The worker's schema task completed without error, and the stage holds the table's `metadata` and `object_type` files but no `schema`.

**Cause:** the worker's schema query returned zero rows, and an empty result still completes the task. Despite the message, it is rarely a write still in flight. Zero rows says the query found nothing, not why. Check, in this order:
- **What the statement reads.** Current orchestrator builds qualify every SQL Server catalog with the table's own database (`FROM [<db>].INFORMATION_SCHEMA.COLUMNS`), so one connection reads tables in several databases on the same server. A logged statement that reads an unqualified `INFORMATION_SCHEMA.COLUMNS` filtered by `TABLE_CATALOG = '<db>'` comes from an older orchestrator build: it reads the database the connection opens (often `master`) and finds no columns there.
- **The names.** The database, schema or table in the workflow YAML doesn't match the source — the same family as [Table does not exist in the source database](#table-does-not-exist-in-the-source-database--empty-metadata).
- **Permissions.** The connection's login can't see the table's columns in the catalog views.

**Diagnose before any retry:**
1. In the worker's `data_exchange_agent.log` (under scai's `logs/data/`), find the failing table's schema task and copy its `statement`.
2. Run that statement with `query_source` on the same connection, and the same query with each catalog prefixed by the table's database (`[<db>].`). Rows from the second alone point at the statement; no rows from either point at the names or permissions.
3. Compare the database the connection opens (`scai connection list -l <dialect> --json`) with each table's `source.databaseName` in the workflow YAML.

**Fix:** show the user what you ran and what it returned. Wrong names or permissions: fix them, then delete the failed workflow and resubmit. An unqualified statement: say the worker is running older orchestrator code than the current build, with the statement as evidence, and that you haven't confirmed why; on SQL Server, `scai data migrate start --direct` runs the migration in-process with a locally installed orchestrator, without the shared service. Do **not** update, recreate or restart the shared orchestrator service to test the theory — it serves every project on the account — and do not re-run the unchanged workflow: it runs the same statement.

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

**Fix:** Have an admin grant `OPERATE` and `MONITOR` on the service, plus the metadata privileges. When `SHOW PROCEDURES LIKE 'GRANT%PRIVILEGES%' IN SCHEMA <metadata_database>.COMMON;` returns rows, the metadata privileges come from the [grant procedures](../../../../data-infrastructure/SKILL.md#grant-procedures) (ask before the orchestrator call: it moves ownership of the metadata objects to `<your_role>`):
```sql
USE ROLE SYSADMIN; -- or whichever role owns the service and has MANAGE GRANTS

GRANT OPERATE, MONITOR ON SERVICE <metadata_database>.DATA_MIGRATION.DATA_MIGRATION_SERVICE TO ROLE <your_role>;
CALL <metadata_database>.COMMON.GRANT_PRIVILEGES_TO_ORCHESTRATOR_ROLE('<your_role>', '<warehouse>');
```

With no rows (a metadata database deployed by an older orchestrator), grant them one by one:
```sql
USE ROLE SYSADMIN; -- or whichever role owns the service

GRANT USAGE ON DATABASE <metadata_database> TO ROLE <your_role>;
GRANT USAGE ON SCHEMA <metadata_database>.DATA_MIGRATION TO ROLE <your_role>;
GRANT OPERATE, MONITOR ON SERVICE <metadata_database>.DATA_MIGRATION.DATA_MIGRATION_SERVICE TO ROLE <your_role>;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA <metadata_database>.DATA_MIGRATION TO ROLE <your_role>;
GRANT ALL PRIVILEGES ON ALL PROCEDURES IN SCHEMA <metadata_database>.DATA_MIGRATION TO ROLE <your_role>;
GRANT ALL PRIVILEGES ON ALL STAGES IN SCHEMA <metadata_database>.DATA_MIGRATION TO ROLE <your_role>;
GRANT ALL PRIVILEGES ON ALL FILE FORMATS IN SCHEMA <metadata_database>.DATA_MIGRATION TO ROLE <your_role>;
GRANT ALL PRIVILEGES ON ALL VIEWS IN SCHEMA <metadata_database>.DATA_MIGRATION TO ROLE <your_role>;
```

---

## Insufficient privileges after a DMVF upgrade

**Symptom:** after the orchestrator upgrades its metadata schema, the orchestrator or a worker fails with "insufficient privileges" on a metadata object, and the upgrade log has a warning that names a `CALL <metadata_database>.COMMON.GRANT_…` statement.

**Cause:** the release changed grants that only a `MANAGE GRANTS` role can make (database, schema, warehouse, future, orchestrator or target grants). The upgrade re-grants recorded worker roles their object privileges itself, but it cannot run these, so it logs the call and finishes.

**Fix:** have the admin who first called the [grant procedures](../../../../data-infrastructure/SKILL.md#grant-procedures) run the logged `CALL` as written, then retry the run.

---

## Service stays SUSPENDED after `--start-service`

**Symptom:** `scai data migrate create-workflow --start-service` appears to succeed, but `SELECT SYSTEM$GET_SERVICE_STATUS(...)` returns `[]` (no running instances).

**Diagnosis:**
```sql
SELECT SYSTEM$GET_SERVICE_STATUS('<metadata_database>.DATA_MIGRATION.DATA_MIGRATION_SERVICE');
-- Returns [] when suspended, or a JSON array with status when running
```

**Fix:** Manually resume the service:
```sql
ALTER SERVICE <metadata_database>.DATA_MIGRATION.DATA_MIGRATION_SERVICE RESUME;
```

Then wait 30-60 seconds for the container to start and re-check the status.

---

## Task dependency and ordering anomalies

**Symptoms:** Tasks stuck in `blocked` while earlier phases appear done; extraction never starts; load tasks wait indefinitely.

**Diagnosis:**

```sql
-- Find blocked tasks and their scopes
SELECT ID, NAME, STATUS, SCOPE, SUCCESSOR_TASK_ID
FROM <metadata_database>.DATA_MIGRATION.TASK_QUEUE
WHERE WORKFLOW_ID = <id> AND STATUS = 'blocked'
ORDER BY ID;

-- Find failed predecessors in the same table scope
SELECT ID, NAME, STATUS, LAST_ERROR_MESSAGE, SCOPE
FROM <metadata_database>.DATA_MIGRATION.TASK_QUEUE
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
FROM <metadata_database>.DATA_MIGRATION.TASK_QUEUE
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

### Teradata Error 6701 / 5355 (mixed charsets)

**Symptom:** Extraction task fails on Teradata with Error **6701** or **5355** when the source table has columns in different character sets (for example LATIN + KANJISJIS + GRAPHIC in one row).

**Fix:** Ensure the workflow uses a current orchestrator build with charset-aware Teradata extraction (automatic `<charset>_TO_UNICODE` per column). If the customer still hits untranslatable-byte edge cases, set `onUntranslatable: substitute` (default) or `fail` for strict tables. See `dmvf/docs/data-migration-orchestrator/teradata-charset-extraction.md`.

### Teradata Error 6706 (untranslatable bytes, fail mode)

**Symptom:** Extraction fails with **6706** on a table configured with `onUntranslatable: fail`.

**Fix:** Expected behavior — the table contains bytes that cannot map to Unicode under the chosen charset translation. Either clean/source-fix the data, use `onUntranslatable: substitute` for lossy U+FFFD replacement, or scope `whereClauseCriteria` to exclude bad rows (if acceptable).

---

## Target has more/duplicate rows after re-running a migration

**Symptom:** Target row count exceeds source (or a prior migration run), or users report duplicate keys/rows after a second `migrate_data(mode="run")`.

**Cause:** The workflow used **non-incremental** sync (`sync_strategy=none`, no `synchronization` block, or `migration_type=full`/`preliminary` without watermark/checksum). Each run extracts and loads **all** matching rows again — `COPY INTO` appends to the target; the orchestrator does not deduplicate on full reload.

**Remediation (careful — do not destroy legitimate data):**

1. **Verify:** Compare source vs target row counts (and sample keys if available). Confirm whether extra rows came from a re-run vs pre-existing target data.
2. **A target this project loaded itself** (see *Clearing a bad load* in [SKILL.md](../SKILL.md)): in autonomous mode, clear and reload it without asking; interactive, propose the truncate and reload and run them once the user agrees.
3. **Any other target:** confirm with the user before any destructive action. It may hold rows that are expected or unrelated to this migration. Do not blindly `TRUNCATE` or bulk-`DELETE` it; if cleanup is required, scope it (for example delete rows loaded in a specific partition/window, or dedupe by primary key) only after explicit user approval.
4. **Going forward:** Add `synchronization.strategy: watermark` or `checksum` (with `watermarkColumn`, `checksumExpression`, and `primaryKeyColumns` as needed) so subsequent runs are incremental. See [workflow-config-reference.md](./workflow-config-reference.md#synchronizationstrategy).

---

## Workflow finished but tables incomplete

**Symptom:** `details.progress.output.isFinished` is `true` (workflow status `Finished`) but `preprocessedTables < totalTables`, or any `tablePartitions[].hasBeenPreprocessed == false`, or `aggregatedCounts.failedPartitions > 0`.

**Meaning:** The orchestrator closed the workflow while one or more tables never finished. This is an **error**, not success — scai treats it as `HasErrors`.

**Do not assume** the only cause is “workers not processing.” Common causes include:

- Local worker not running, wrong affinity, or claiming stale tasks from another workflow
- Worker `database` / connection mismatch (tasks complete but produce no data)
- Tasks **failed** or **cancelled** in `TASK_QUEUE` while the workflow still marked finished
- SPCS orchestrator suspended or not picking up workflows

**Fix path (in order):**

1. **MCP / reports (no SQL):** Re-read the latest status response. Use `details.reports.files.errors` / `details.reports.files.progress` for `LastErrorMessage` / task detail.
2. **Task queue:** Resolve `WORKFLOW_ID` from `WORKFLOW` (match `NAME` to `details.progress.output.workflowName`), then run the queries below. Look for tasks still `pending` / `executing` / `blocked` vs `failed` / `cancelled` / `completed`, and read `LAST_ERROR_MESSAGE`.
3. **Infrastructure:** If tasks are stuck pending with no errors, check worker process, affinity, stale `TASK_QUEUE` rows, and `SYSTEM$GET_SERVICE_STATUS` for the orchestrator — see sections above in this reference.

**Tell the user:** “Workflow finished but N table(s) never completed — checking task errors…” — then report what `reports` and (if needed) `TASK_QUEUE` show. Offer troubleshooting steps before suggesting re-run.

---

## Useful diagnostic queries

```sql
-- Check service status
SELECT SYSTEM$GET_SERVICE_STATUS('<metadata_database>.DATA_MIGRATION.DATA_MIGRATION_SERVICE');

-- Read orchestrator logs (last 50 lines)
CALL SYSTEM$GET_SERVICE_LOGS(
  '<metadata_database>.DATA_MIGRATION.DATA_MIGRATION_SERVICE', '0', 'orchestrator', 50
);

-- List recent workflows
SELECT ID, NAME, STATUS, AFFINITY, INITIATOR_ID, CREATION_TIME
FROM <metadata_database>.DATA_MIGRATION.WORKFLOW
ORDER BY ID DESC LIMIT 10;

-- Check task status for a specific workflow
SELECT ID, NAME, EXECUTOR_TYPE, STATUS, FAILURES, LAST_ERROR_MESSAGE
FROM <metadata_database>.DATA_MIGRATION.TASK_QUEUE
WHERE WORKFLOW_ID = <id>
ORDER BY ID;

-- Count active tasks by workflow
SELECT WORKFLOW_ID, STATUS, COUNT(*)
FROM <metadata_database>.DATA_MIGRATION.TASK_QUEUE
WHERE STATUS NOT IN ('completed', 'failed', 'cancelled')
GROUP BY WORKFLOW_ID, STATUS
ORDER BY WORKFLOW_ID;
```

> **Task model:** For scope grammar, dependency chains, and pause/resume/cancel procedures, see [Task model reference](./task-model-reference.md).

---

## Source overloaded or too many concurrent extractions/loads

**Symptom:** Migration is slow; source DBA reports connection pressure; many extraction/load tasks run at once; customer wants to throttle without stopping workers entirely.

**Cause:** Default parallelism (`max_parallel_tasks` per worker × number of workers) may exceed what the source can sustain.

**Fix path (prefer in order):**

1. **Rate limiting (advanced):** Insert rules into `DATA_MIGRATION.RATE_LIMIT` to cap concurrent tasks by scope pattern — see [Advanced operations reference](../../../../data-infrastructure/references/advanced-operations-reference.md#rate-limiting-protect-source-or-shared-resources). This is metadata SQL, not workflow YAML.
2. Lower `max_parallel_tasks` in worker TOML (per-machine parallelism).
3. Reduce worker count or pause workers during peak source hours.

Do **not** suggest orchestrator polling-interval env vars as a throttle mechanism.

---

## Tasks stay pending on trial / non-hybrid metadata accounts

**Symptom:** Workers are running, source is healthy, but `TASK_QUEUE` rows remain `pending`; adding more workers does not help or makes it worse.

**Cause:** Snowflake account lacks **Hybrid Table** support — orchestrator metadata fell back to **standard/`TRANSIENT`** tables. Task claiming uses a slower, contention-sensitive path; **too many workers** compete for the same queue rows.

**Agent guidance:**

1. Confirm metadata mode (trial account, `Unsupported feature 'HYBRID TABLE'` at bootstrap, or `SNOWFLAKE_USE_HYBRID_TABLES=0`).
2. **Reduce** worker count and `max_parallel_tasks` before adding more infrastructure — see [Metadata storage mode reference](../../../../data-infrastructure/references/metadata-storage-mode-reference.md).
3. Distinguish from source overload ([rate limiting](../../../../data-infrastructure/references/advanced-operations-reference.md#rate-limiting-protect-source-or-shared-resources)) and missing workers (affinity mismatch).

---

## Incremental sync or checksum did not detect a column change

**Symptom:** Customer edited data (especially in `text`/`ntext`/`image`, LOBs, floats, spatial, or high-precision timestamps) but the next incremental migration run did not re-process the partition; checksum unchanged.

**Cause:** Built-in **partition checksums** exclude or normalize some types before hashing. A custom `checksumExpression` only reflects that SQL aggregate. **Watermark** sync ignores columns that are not the watermark.

**Agent guidance:**

1. Confirm sync strategy (`checksum` vs `watermark`) and whether the changed column is in the checksum input.
2. Explain using the skipped/lossy type table — see [Advanced operations reference](../../../../data-infrastructure/references/advanced-operations-reference.md#checksum--incremental-sync--types-that-may-not-trigger-re-sync).
3. Offer remediation: one-time **full** run; custom **`checksumExpression`**; switch to **watermark** if appropriate.

---

## Extra / unexpected tables in the migration workflow

**Symptom:** The user asked to migrate N specific tables, but the workflow YAML
(or Snowflake `TABLE_METADATA` / `TABLE_PROGRESS`) shows additional tables —
often a name that shares a prefix with a requested table (e.g.
`SNAPM_EDB_MODEL_GROUPING_SWTCH` alongside `SNAPM_EDB_MODEL_GROUPING`).

**Cause (usual):** The registry `where` used substring / `ILIKE '%…%'` matching,
or setup **reused** an older broader workflow YAML. SnowConvert does **not**
auto-include SQL Server SWITCH / partition staging siblings.

**Diagnosis:**
1. Open `artifacts/data_migration/workflows/<hash>.yaml` and list every
   `tables[].source.tableName`.
2. Check the `where` shown at setup / stored under plugin config.
3. Note whether setup reported `workflow_reused`.

**Fix:**
1. Rebuild with an **exact** filter, e.g.
   `source.objectType = 'table' AND source.canonicalName IN ('dbo.T1', 'dbo.T2')`.
2. Pass `force_regenerate=true` on `migrate_data(mode="setup")` so a stale YAML
   is not reused.
3. Re-confirm the `tables:` list with the user before `mode="run"`.

> **Stopping the service when done:** to suspend the orchestrator, suspend the compute pool, and stop the local worker after a wave completes, follow [../../../../data-infrastructure/teardown/SKILL.md](../../../../data-infrastructure/teardown/SKILL.md). Don't run `ALTER SERVICE ... SUSPEND` ad-hoc — the teardown sub-skill verifies no in-flight workflows first.
