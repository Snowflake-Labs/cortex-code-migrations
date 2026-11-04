# Validation report: failures and re-validation

Loaded from [validate_tables.md](../validate_tables.md) Step 5 when the run had failures. The headline (5.A, 5.B) and the all-passed template stay in that file.

## 5.C — Classify errors (fixed category order)

List categories **only when they have at least one error** and that check **was enabled** in the workflow (except **Execution**, which applies whenever infra/runtime failed), always in this order:

| Order | Category | When to include | Sources |
|-------|----------|-----------------|---------|
| 1 | **Schema** | `schema_validation == true` | `schemaValidated == false`, `details.reports.files.schema_validation_results`, schema-related `errorMessage` |
| 2 | **Metrics** | **`metrics_validation == true` only** | `metricsValidated == false` (not `null`), `details.reports.files.metrics_validation_results` |
| 3 | **Row** | `row_validation == true` | `rowsValidated == false`, `row_validation_summary`, `row_validation_results`, `cell_validation_results` |
| 4 | **Execution** | always when applicable | `status == "Pending"` with `isFinished` (Step 4.B), `status == EXECUTION_ERROR`, `data_validation_errors`, connectivity/infra `errorMessage` |

**Never** add a **Metrics** subsection when `metrics_validation` was false — missing metrics CSV rows and `metricsValidated: null` are expected, not failures.

A table may appear in more than one category when multiple checks failed — place each issue under the appropriate category.

**Deduplicate within a category:** identical messages → one bullet + `- Affects: \`table1\`, \`table2\`, …`. Prefer concrete text from `details.reports.files` (e.g. `ColumnValidated`, `SourceValue`, `SnowflakeValue`) over generic `errorMessage` when available.

**Category gloss (optional, first use in this conversation):** When a category subsection appears under `### Errors`, you may add one short line under the header using the glosses in [Validation levels reference](./validation-levels-reference.md). Skip glosses if you already explained levels at Step 2 or the user declined.

## 5.D — Suggested fixes

Number fixes in the **same order** as **Errors** (skip categories that were disabled or had no errors): Schema → Metrics → Row → Execution. One item per error group when deduped. Prefer prerequisite actions over blind re-run — include workflow YAML mapping overrides, re-migration when data is wrong, and [data-infrastructure](../../../data-infrastructure/SKILL.md) for execution/infra failures.

Do **not** include a per-table markdown table unless the user asks.

## 5.E — Failure template

```markdown
## Data validation — passed with failures

**Result:** <N_ok>/<N_total> tables OK — <F> failed
**Workflow:** `<workflowName>`

### Errors

**Schema**
<!-- optional one-line gloss: column definition mismatches, not cell values -->
- `<table>` — <column/type mismatch or message>
- <shared message>
  - Affects: `<table>`, …

**Metrics**
<!-- omit entire Metrics subsection when metrics_validation was false -->
- <message>
  - Affects: `<table>`, …

**Row**
<!-- optional one-line gloss: specific cell values differ on matched keys -->
- <message>
  - Affects: `<table>`, …

**Execution**
<!-- optional one-line gloss: infra/runtime, not a data comparison -->
- <message>
  - Affects: `<table>`, …

### Suggested fixes

1. **Schema (<tables>)** — …
2. **Metrics (<tables>)** — …  <!-- omit when metrics_validation was false -->
3. **Row (<tables>)** — …
4. **Execution (<tables>)** — …
```

Omit empty category subsections. On full success **and when Step 4.B does not apply**, omit `### Errors` and failure fixes. If the job failed before any progress existed, use a **failed** title and put the job's `summary` under **Execution**.

## 5.F — After failures (optional follow-up)

Do **not** prompt before presenting the Step 5 summary. **After** the error-first report, when there were validation failures, optionally offer:

> Want a brief explanation of what the Schema / Row / Execution sections mean, or help prioritizing fixes?

Use [Validation levels reference](./validation-levels-reference.md) for report-category definitions; focus on categories that actually appeared in `### Errors`. Skip this offer if you already explained levels at Step 2 and the user did not ask.

## 5.G — Offer re-validation when data mismatches remain

**After** the Step 5 summary (and optional 5.F follow-up), **before Step 6 (teardown)**, offer a retry menu when **all** of the following hold:

| Condition | Required? |
|-----------|-----------|
| `details.progress.output.isFinished == true` | Yes |
| `failedTables > 0` **or** Schema / Row / Metrics errors in `### Errors` | Yes |
| Step 4.B pending-tables anomaly | **No** — investigate first; do not offer re-validation |
| **Execution** failures only (infra, worker, orchestrator, connectivity) | **No** — fix via [data-infrastructure](../../../data-infrastructure/SKILL.md) first |

A table whose validation finished with mismatches reads `validateData` as `failed` with `error: "data"`, and the walk stops there (errored, not the SQL fix loop). Usually the data or mapping is what differs, not the converted SQL; schema (L1) differences can still need a DDL fix (option 2). Do not run `sqlFixLoop`, and do not `reset` the task to re-dispatch the same workflow. Resolve it through this menu.

Re-validation retries **failed partitions only** from the finished parent workflow — it is **not** a full re-run of every table. Chain resolution is automatic: pass the workflow name from the run that just finished (`details.progress.output.workflowName`).

By default, schema-failed tables **reuse** the parent's partition metadata and re-run only their failing data partitions (schema is **not** re-checked, so a table whose only failure was schema is skipped). If the failures were schema/target-definition issues you have since fixed and want re-checked, add **`recheck_schema=true`** — it re-runs the full pipeline for schema-failed tables. Leave it off for data-mismatch retries.

Ask verbatim when eligible:

> Some tables still have validation failures. How would you like to proceed?
>
> 1. **Retry failed partitions only** (recommended when data fixes are done) — re-validation from workflow `<workflowName>`
> 2. **Apply fixes first** — edit workflow YAML / fix source data / re-migrate, then retry
> 3. **Re-run full validation** — `validate_data(mode="setup", where=...)` then `mode="run"` (new workflow, all tables in scope)
> 4. **Investigate further** — TASK_QUEUE, worker/orchestrator health ([data-infrastructure](../../../data-infrastructure/SKILL.md))
> 5. **Accept the differences** — record that these tables are done as they are
> 6. **Stop** — proceed to Step 6 (teardown)

**If the user picks option 1:**

```
validate_data(mode="revalidate", workflow_name="<details.progress.output.workflowName>")
```

Add `recheck_schema=true` when the fixes were to schema / target definitions and you want schema re-checked (otherwise schema-failed tables re-run only their failing data partitions and are not schema-checked).

Then repeat **Steps 4–5** (background Monitor, then present a new error-first report). Skip Step 6 teardown until the user picks **Accept** or **Stop**, or all tables pass. Relay the `cost_reminder` from the revalidate response when infrastructure starts.

**If the user picks option 2:** guide fixes from `### Suggested fixes`, then offer this menu again when ready.

**If the user picks option 3:** return to Step 1 (setup) with a `where` filter scoped to failed tables when possible.

**If the user picks option 5:** record the decision in two calls, scoped with `where` to the accepted tables. First `transition_status(status='escalate', task='validateData', cause='data', asks=[…], where=…)`, with asks naming the tables and mismatched levels. Then `transition_status(status='answer', task='validateData', resolution='mark_done', reason="<the user's words>", where=…)`, and follow the `next` it returns. Until the answer is recorded, the tables stay parked as needing a human decision.

**If the user picks option 4 or 6:** continue to Step 6 when wave data work is done for this pass.

When all tables passed on the first run, skip 5.G and continue to Step 6.
