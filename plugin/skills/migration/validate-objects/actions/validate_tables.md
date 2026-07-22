# Action: Validate Tables

Validate migrated table data between source and Snowflake using cloud validation — **setup → run → poll → report**.

> **Scope is set per call.** `validate_data(mode="run")` validates **every** table listed in the workflow file produced by setup. Pass a `where` filter to setup that matches exactly the tables you intend to validate.

> **Run-only entry:** If you were routed here only to execute `validateData` (registry task) and the workflow YAML already exists, skip Step 1 and complete **Step 2** (display the existing `workflow_path` and offer optional updates) before **Step 3**. You **must** complete **Steps 4–6** (poll, error-first validation report, teardown offer) before returning to the parent skill — even when the state machine invoked `validate_data(mode="run")` without walking setup.

## Step 1: Generate the validation workflow

Translate the user's choices into a `validate_data(mode="setup", ...)` call.

For the `where` filter, in order of preference:

1. **You already have the claimed object IDs** (e.g. from a `transition_status(status="begin", ...)` response). Use them verbatim — `where="id IN ('<id1>', '<id2>', ...)"`.
2. **Specific table names.** `where="source.canonicalName IN ('dbo.Customers', 'dbo.Orders')"`.
3. **A whole schema or wave.** `where="source.schema = 'dbo'"` or `where="planning.wave = 'wave_1'"`.
4. **All deployed tables.** Omit `where`. Only do this if the user explicitly asked to validate everything.

If you're unsure of the registry filter columns, run `scai code where` for the syntax reference.

```
validate_data(
  mode="setup",
  where="<registry filter>",
  schema_validation=true | false,    # optional; persisted as a session default
  metrics_validation=true | false,   # optional; scai default is false — pass true only if user wants metrics
  row_validation=true | false,       # optional; scai default is true
  continue_on_failure=true | false,  # optional; persisted as a session default
)
```

Do **not** prompt for `metrics_validation` unless the user asks for aggregate-statistics comparison. Omit the param to keep scai's default (`false`).

If setup returns `status: "error"` with a message about validation not being configured, load `../../setup/data-validation/SKILL.md` to complete the one-time infrastructure setup, then retry.

## Step 2: Display, optional edits, confirm

The setup response contains:

- `workflow_path` — `artifacts/data_validation/workflows/<hash>.yaml`. Same `where` always maps to the same file; distinct filters produce distinct files.
- `regenerated` — `false` means scai re-used an existing file.
- `defaults` — the merged session defaults applied to this call.
- `applied_overrides` — toggle values that were patched into `validation_configuration`.
- `edit_hints` — use as a guide when the user is unsure what can be changed.

1. Read `workflow_path`.
2. **Display** the workflow file to the user:
   - **Small/medium files** — show the full YAML in chat.
   - **Large files** — show the path, `validation_configuration`, `tables:` count, and table names; offer to show the full file or specific tables on request.
   - Note whether setup **reused** an existing file (`regenerated: false`).
3. **Summarize:** table count, effective validation toggles (`schema_validation`, `metrics_validation`, `row_validation`, `continue_on_failure`), and which levels will run (e.g. schema + row; metrics off unless enabled).
4. Ask verbatim:

> Here is the validation workflow at `<workflow_path>`.
>
> **Would you like to update any fields before we run?**
> 1. **No — proceed**
> 2. **Yes — I want to change something** (tell me which table, section, or field names)

5. **If Yes:** apply the user's requested edits using `../../setup/data-validation/references/workflow-config-reference.md` (e.g. `column_mappings`, `index_column_list`, `source_where_clause` (+ its pair `target_where_clause`), `target_database` / `target_schema` / `target_name`). Re-display the sections you changed. Repeat the question in step 4 until the user chooses **No — proceed** or says they are done editing.
6. **If No:** skip discretionary edits unless agent-only blockers remain (step 7).
7. **Agent-only blockers** — apply without re-prompting unless you need a value from the user:
   - When `row_validation` is on: ensure each table has usable `index_column_list` (and `target_index_column_list` when names differ) per `edit_hints`.
   - Verify `target_database` / per-table targets match the deployed Snowflake objects.
   - Tell the user what you changed and why before confirming.
8. Get **explicit confirmation** to run with the final workflow, then continue to Step 3.

**Optional — explain validation levels:** After step 4 (or while the user is reviewing), offer a brief explanation unless they are clearly repeating a prior run or only asked to execute:

> Would you like a quick explanation of what schema, row, and metrics validation mean before we run?

- **Yes** — summarize from [Validation levels reference](./references/validation-levels-reference.md) (setup toggles table); mention only levels that are **on** in this workflow, plus note that metrics is off by default when disabled.
- **No / skip** — continue the Step 2 flow.

Also answer ad-hoc questions about levels at any time using the same reference; do not block the run on the offer.

## Step 2b: Doctor gate (automatic)

You no longer run doctor by hand here. `validate_data(mode="run")` runs a `scai data doctor` check and **refuses to start** if any check fails, returning `doctor_failures`. Surface those to the user and fix them, or call `validate_data(mode="run", skip_doctor=true)` only after the user explicitly accepts the failures.

## Step 3: Run validation

```
validate_data(mode="run", workflow_path="<path from setup>")
```

On success, returns a `job_id` immediately — validation runs in the background via the SPCS validation service and a local Data Exchange Worker.

**Show the user the `cost_reminder` from the response** (or relay this if absent):

> **Cost note:** The orchestrator and local worker are running. They can keep using Snowflake credits while idle (the worker polls the warehouse on an interval). When this wave is done, suspend the orchestrator, compute pool, and stop all workers — accept teardown when offered at the end. The local worker started via MCP stops when this Coco session ends; the orchestrator does not.

Retain `workflow_path` for the report in Step 5.

---

## Step 4: Poll for completion

Poll until the job is terminal:

```
validate_data_status()
```

(or `migration_status(mode="summary")` for wave-level progress — per-table detail always comes from `validate_data_status`)

**While `status` is `"running"`:**

- Poll every 30–60 seconds, or when the user asks for an update.
- `progress` may be absent until `create-workflow` returns a workflow name; that is normal early in the run.
- Optionally share a one-line update from `progress.output` when present (e.g. `validatedTables`/`totalTables`, `failedTables`).

**Stop polling when:**

- `status` is `"completed"` or `"failed"`, **and**
- `progress.output.isFinished` is `true` when `progress` is present.

If `status` is `"failed"` and top-level `error` is set, surface it under **Execution** (or **Infrastructure** when no table progress exists).

### 4.B — Finished workflow with pending tables (anomaly)

After the terminal poll, if `progress.output.isFinished == true` **and** any of:

- `validatedTables + failedTables < totalTables`
- any `tableStates[].status == "Pending"`

**Do not report “Passed”.** Treat as failures (matches scai `HasErrors` — tables left pending when the workflow finished).

1. List pending tables under **Execution** as “never validated” — use `errorMessage` when set; otherwise `reports.files.data_validation_errors` or “Table not validated — check task errors”.
2. Pull detail from `reports.files` before guessing. Do **not** treat `metricsValidated: null` as failure when metrics was disabled.
3. If messages are thin, follow [Workflow finished but tables incomplete](../../migrate-objects/actions/data-migration/references/troubleshooting-reference.md#workflow-finished-but-tables-incomplete) — query `TASK_QUEUE` for the workflow. Worker/orchestrator issues are one cause, not the only one.
4. Do **not** suggest re-run until prerequisites are identified.

---

## Step 5: Report — data validation summary

**Do not skip.** Present an **error-first** summary in chat (markdown). Build it from `validate_data_status()` (`progress`, `reports`) — **not** a per-table results grid unless the user asks.

### 5.A — Read inputs

Read **`validation_configuration`** from the workflow YAML (or `defaults` / `applied_overrides` from setup) to know which levels ran: `schema_validation`, `metrics_validation`, `row_validation`.

| Source | Fields |
|--------|--------|
| Status response (top level) | `status`, `error` (if failed before progress) |
| Workflow toggles | `validation_configuration.metrics_validation` — when **false**, metrics were **not executed**; do not discuss or report them |
| `progress.output` | `workflowName`, `isFinished`, `totalTables`, `validatedTables`, `failedTables`, `tableStates` (`schemaValidated`, `metricsValidated`, `rowsValidated`, `status`, `errorMessage`) |
| **`reports.files`** | `schema_validation_results`, `metrics_validation_results` (only when metrics enabled), `row_validation_summary`, `row_validation_results`, `data_validation_errors`, `results` — PascalCase CSV columns |

`metricsValidated`: `true` = passed; `null` = not run (N/A); do **not** treat `null` as a metrics failure when `metrics_validation` was false in the workflow.

`reports` is attached by `validate_data_status()` after `scai data validate status` writes CSV under `reports/data-validation/workflow-<timestamp>/`.

### 5.B — Derive headline **Result** (header only)

| Outcome | **Result** line |
|---------|-----------------|
| All passed | `Passed — <N>/<N> tables OK` |
| Some failures | `<N_ok>/<N_total> tables OK — <F> failed` |
| **Finished but pending** (Step 4.B) | `<N_ok>/<N_total> tables OK — <F> never validated` |
| Job failed / no meaningful progress | `Failed — no tables validated` (adjust counts if partial) |

**Never** use the all-passed **Result** when Step 4.B applies — even if top-level MCP `status` is `"completed"`.

**Workflow** line: `` `progress.output.workflowName` ``.

**Header shows only `Result` and `Workflow`** — no elapsed time, check toggles, workflow file path, or job id in the header.

### 5.C — Classify errors (fixed category order)

List categories **only when they have at least one error** and that check **was enabled** in the workflow (except **Execution**, which applies whenever infra/runtime failed), always in this order:

| Order | Category | When to include | Sources |
|-------|----------|-----------------|---------|
| 1 | **Schema** | `schema_validation == true` | `schemaValidated == false`, `reports.files.schema_validation_results`, schema-related `errorMessage` |
| 2 | **Metrics** | **`metrics_validation == true` only** | `metricsValidated == false` (not `null`), `reports.files.metrics_validation_results` |
| 3 | **Row** | `row_validation == true` | `rowsValidated == false`, `row_validation_summary`, `row_validation_results`, `cell_validation_results` |
| 4 | **Execution** | always when applicable | `status == "Pending"` with `isFinished` (Step 4.B), `status == EXECUTION_ERROR`, `data_validation_errors`, connectivity/infra `errorMessage` |

**Never** add a **Metrics** subsection when `metrics_validation` was false — missing metrics CSV rows and `metricsValidated: null` are expected, not failures.

A table may appear in more than one category when multiple checks failed — place each issue under the appropriate category.

**Deduplicate within a category:** identical messages → one bullet + `- Affects: \`table1\`, \`table2\`, …`. Prefer concrete text from `reports.files` (e.g. `ColumnValidated`, `SourceValue`, `SnowflakeValue`) over generic `errorMessage` when available.

**Category gloss (optional, first use in this conversation):** When a category subsection appears under `### Errors`, you may add one short line under the header using the glosses in [Validation levels reference](./references/validation-levels-reference.md). Skip glosses if you already explained levels at Step 2 or the user declined.

### 5.D — Suggested fixes

Number fixes in the **same order** as **Errors** (skip categories that were disabled or had no errors): Schema → Metrics → Row → Execution. One item per error group when deduped. Prefer prerequisite actions over blind re-run — include workflow YAML mapping overrides, re-migration when data is wrong, and `../../data-infrastructure/SKILL.md` for execution/infra failures.

Do **not** include a per-table markdown table unless the user asks.

### 5.E — Template (present to the user)

**All passed:**

```markdown
## Data validation complete

**Result:** Passed — <N>/<N> tables OK
**Workflow:** `<workflowName>`

No validation mismatches or execution errors.
```

**Failures:**

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

Omit empty category subsections. On full success **and when Step 4.B does not apply**, omit `### Errors` and failure fixes. If the job failed before `progress`, use a **failed** title and put top-level `error` under **Execution**.

### 5.F — After failures (optional follow-up)

Do **not** prompt before presenting the Step 5 summary. **After** the error-first report, when there were validation failures, optionally offer:

> Want a brief explanation of what the Schema / Row / Execution sections mean, or help prioritizing fixes?

Use [Validation levels reference](./references/validation-levels-reference.md) for report-category definitions; focus on categories that actually appeared in `### Errors`. Skip this offer if you already explained levels at Step 2 and the user did not ask.

### 5.G — Offer re-validation when data mismatches remain

**After** the Step 5 summary (and optional 5.F follow-up), **before Step 6 (teardown)**, offer a retry menu when **all** of the following hold:

| Condition | Required? |
|-----------|-----------|
| `progress.output.isFinished == true` | Yes |
| `failedTables > 0` **or** Schema / Row / Metrics errors in `### Errors` | Yes |
| Step 4.B pending-tables anomaly | **No** — investigate first; do not offer re-validation |
| **Execution** failures only (infra, worker, orchestrator, connectivity) | **No** — fix via `../../data-infrastructure/SKILL.md` first |

Re-validation retries **failed partitions only** from the finished parent workflow — it is **not** a full re-run of every table. Chain resolution is automatic: pass the workflow name from the run that just finished (`progress.output.workflowName`).

Ask verbatim when eligible:

> Some tables still have validation failures. How would you like to proceed?
>
> 1. **Retry failed partitions only** (recommended when data fixes are done) — re-validation from workflow `<workflowName>`
> 2. **Apply fixes first** — edit workflow YAML / fix source data / re-migrate, then retry
> 3. **Re-run full validation** — `validate_data(mode="setup", where=...)` then `mode="run"` (new workflow, all tables in scope)
> 4. **Investigate further** — TASK_QUEUE, worker/orchestrator health (`../../data-infrastructure/SKILL.md`)
> 5. **Stop** — proceed to Step 6 (teardown)

**If the user picks option 1:**

```
validate_data(mode="revalidate", workflow_name="<progress.output.workflowName>")
```

Then repeat **Steps 4–5** (poll with `validate_data_status()`, present a new error-first report). Skip Step 6 teardown until the user picks **Stop** or all tables pass. Relay the `cost_reminder` from the revalidate response when infrastructure starts.

**If the user picks option 2:** guide fixes from `### Suggested fixes`, then offer this menu again when ready.

**If the user picks option 3:** return to Step 1 (setup) with a `where` filter scoped to failed tables when possible.

**If the user picks option 4 or 5:** continue to Step 6 when wave data work is done for this pass.

When all tables passed on the first run, skip 5.G and continue to Step 6.

---

## Step 6: Offer to Suspend Infrastructure (Cost Saving)

After presenting the summary, ask the user (default Yes):

> Suspend the orchestrator and compute pool now to stop accruing SPCS / warehouse cost? The local worker will keep polling until stopped separately.
>
> 1. **Yes (default)** — load `../../data-infrastructure/teardown/SKILL.md` to suspend the service, suspend the compute pool, and stop the local worker. The next `migrate_data()` / `validate_data()` call will auto-resume the service.
> 2. **No, keep running** — useful if you're starting the next wave immediately and want to avoid the ~60s warm-up.

If the user picks **Yes** (or doesn't respond), load the teardown sub-skill, then return to the parent skill.

---

## Checklist

```
- [ ] Validation workflow YAML generated via validate_data(mode="setup", ...) (or existing file reviewed at Step 2)
- [ ] User saw workflow YAML and was offered optional field updates (Step 2)
- [ ] User confirmed the final workflow YAML and validation toggles before run
- [ ] validate_data(mode="run") started
- [ ] Polled until job terminal and progress.output.isFinished (when progress present)
- [ ] Finished-but-pending anomaly checked (Step 4.B — do not report passed if tables still Pending)
- [ ] Error-first data validation summary presented (Step 5 — Result + Workflow, Errors, Suggested fixes)
- [ ] Re-validation menu offered when eligible (Step 5.G — before teardown, not on Step 4.B or execution-only failures)
- [ ] Teardown offered when wave data work is done (Step 6)
```

Return control to the parent skill (../SKILL.md).

## Reference

- [Validation levels reference](./references/validation-levels-reference.md) — what schema, metrics, row, and execution mean (setup + report)
- [Workflow Config Reference](../../setup/data-validation/references/workflow-config-reference.md)
- [Data validation setup](../../setup/data-validation/SKILL.md)
- [Migration troubleshooting (TASK_QUEUE, worker/orchestrator)](../../migrate-objects/actions/data-migration/references/troubleshooting-reference.md#workflow-finished-but-tables-incomplete)
- [Teardown (cost-saving suspend)](../../data-infrastructure/teardown/SKILL.md)
