# Data Validation Troubleshooting Reference

Validation-specific failure modes. Worker, orchestrator, SPCS, affinity, and `TASK_QUEUE` issues are shared with data migration: see the [DMVF troubleshooting reference](../../../migrate-objects/actions/data-migration/references/troubleshooting-reference.md).

---

## `POSSIBLE_MISMATCH` after validation completes

Hybrid L3 validation may stop early when `earlyStoppingForRowHashing` or `maxFailedRowsNumber` is reached. A workflow can finish with `POSSIBLE_MISMATCH` result codes — **do not treat as a clean pass**. Review L3 result tables and consider re-running with adjusted early-stop settings or narrower `sourceWhereClause`/`targetWhereClause` filters.

> **Data validation is read-only** — re-running a DV workflow compares source and target; it does not move or duplicate data on either side.

---

## Validation workflow finished but tables incomplete

**Symptom:** `details.progress.output.isFinished` is `true` (workflow status `Finished`) but `validatedTables + failedTables < totalTables`, or any `tableStates[].status == "Pending"`.

**Meaning:** The orchestrator closed the workflow while one or more tables never finished. This is an **error**, not success.

**Fix path:**

1. **MCP / reports (no SQL):** Re-read the latest status response. Use `tableStates[].errorMessage` and `details.reports.files.data_validation_errors` for task detail.
2. **Task queue and infrastructure:** follow [Workflow finished but tables incomplete](../../../migrate-objects/actions/data-migration/references/troubleshooting-reference.md#workflow-finished-but-tables-incomplete) — the causes (worker not running, affinity, stale tasks, suspended orchestrator) and `TASK_QUEUE` queries are the same.

---

## Incremental validation did not detect a column change

**Symptom:** Customer edited data but the next incremental validation run did not re-process the partition.

**Cause:** DM partition checksums and DV L3 row-hash use **different** pipelines; built-in checksums exclude or normalize some types (see [checksum types that may not trigger re-sync](../../../data-infrastructure/references/advanced-operations-reference.md#checksum--incremental-sync--types-that-may-not-trigger-re-sync)).

**Remediation:** a one-time full validation run, or **DV L3** with `validationCustomNormalizationRules` when the issue is compare semantics.
