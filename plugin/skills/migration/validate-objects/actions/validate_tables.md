# Action: Validate Tables

Validate migrated table data between source and Snowflake using cloud validation — **setup → run → monitor → report**.

> **Always use the official tooling.** Run validation through `validate_data(mode="setup")` / `validate_data(mode="run")` (backed by `scai data validate`). **Never** suggest ad-hoc scripts to compare source and target data outside the DMVF validation pipeline.

> **Scope is set per call.** `validate_data(mode="run")` validates **every** table listed in the workflow file produced by setup. Pass a `where` filter to setup that matches exactly the tables you intend to validate.

> **Run-only entry:** If you were routed here only to execute `validateData` (registry task) and the workflow YAML already exists, skip Step 1 and complete **Step 2** (display the existing `workflow_path`; offer updates unless step 4 applies) before **Step 3**. Complete **Steps 4–5** (background Monitor and error-first validation report), then return the result to the parent. Per-object subagents do not manage shared infrastructure or teardown.

## Step 1: Choose validation approach + generate workflow

### 1.A — Validation mode and sync (captured at setup)

Validation mode (full or incremental) and sync strategy (none, checksum or watermark) are **captured once at setup** (checksum works on every platform, Oracle included) by the `dataStrategy` task (executor [`../../setup/data-strategy/SKILL.md`](../../setup/data-strategy/SKILL.md)) and committed, so they are **already set** when you dispatch — do not re-ask. If they are unexpectedly missing or the user requests a change, return to the main agent; it owns the setup change and redispatch.

For **watermark**, ask which column to use (`watermarkColumn`, e.g. `UPDATED_AT`) before editing YAML. Remind the user that the **first** incremental run still validates everything (establishes the sync baseline); later unchanged runs skip validation.

### 1.B — Generate the validation workflow

For a Snowflake-source project, omit `where`.
`scai data validate generate-config` writes a Snowflake-to-Snowflake template
from project metadata. Read that template, ask for the source and target fully
qualified object names and any mappings needed, and fill the YAML before
running. Do not query or require the Code Unit Registry.

For the `where` filter, in order of preference:

1. **You already have the claimed object IDs** (e.g. from a `transition_status(status="begin", ...)` response). Use them verbatim — `where="id IN ('<id1>', '<id2>', ...)"`.
2. **Specific table names.** `where="source.canonicalName IN ('dbo.Customers', 'dbo.Orders')"`.
3. **A whole schema or wave.** `where="source.schema = 'dbo'"` or `where="planning.wave = 'wave_1'"`.
4. **All deployed tables.** Omit `where`. Only do this if the user explicitly asked to validate everything.

`scai code where` lists the filter syntax.

```
validate_data(
  mode="setup",
  where="<registry filter>",
  validation_type="full" | "incremental",   # from state machine; persisted
  sync_strategy="none" | "checksum" | "watermark",  # from state machine; persisted
  schema_validation=true,            # optional; false is refused — L1 is always required
  metrics_validation=true | false,   # optional; scai default is false — pass true only if user wants metrics
  row_validation=true | false,       # optional; scai default is true
  continue_on_failure=true | false,  # optional; this call only, never saved
)
```

Do **not** prompt for `metrics_validation` unless the user asks for aggregate-statistics comparison. Omit the param to keep scai's default (`false`).

**"Full" ≠ metrics on.** `validation_type=full` (vs incremental) only means re-validate the whole table — it does **not** mean enable L2 metrics. Keep `metrics_validation` / `metricsValidation` **false** unless the user explicitly asked for metrics / aggregate statistics.

Setup patches known `validation_configuration` toggles and, when mode/sync are known, `defaultTableConfiguration.synchronization.strategy`. For watermark, still edit `watermarkColumn` (and ensure partition columns) per `edit_hints` before run.

If setup returns `status: "error"` with a message about validation not being configured, load `../../setup/data-validation/SKILL.md` to complete the one-time infrastructure setup, then retry.

## Step 2: Display, optional edits, confirm

The setup response carries `workflow_path` (`artifacts/data_validation/workflows/<hash>.yaml`; the same `where` always maps to the same file), `regenerated` (`false` = reused), `defaults` (what this call applied; toggles and `target_schema` are never saved, so pass them again on the next setup that needs them), `applied_overrides` / `applied_synchronization`, and `edit_hints` (what can be changed).

1. Read `workflow_path`.
2. **Display** the workflow: the full YAML for a small or medium file; for a large one the path, `validationConfiguration`, sync block, `tables:` count and names, with the rest on request. Say when setup **reused** an existing file.
3. **Summarize:** table count, validation mode/sync, effective validation toggles (`schema_validation`, `metrics_validation`, `row_validation`, `continue_on_failure`), which levels will run (e.g. schema + row; metrics off unless enabled), `partition_key_findings`, and `doctor_findings`.
   - Setup runs `scai data doctor --config <workflow_path> --analyze-partition-keys`, as migration setup does. Resolve `doctor_findings.failures` (this workflow or its infrastructure) with the user before run; `warnings` are advisory; `doctor_note` means the doctor could not run.
4. **Small default run: do not ask.** Skip the question in step 5 when **both** hold:
   - the user said to go with the defaults (or just to run it), **or** `.scai/config/plugin.yml` records `data_orchestrator_placement: direct` (a small SQL Server source);
   - there are no `doctor_findings.failures`, no `Partition prune:` finding, no unapplied user-requested edit, and no agent-only blocker (step 8) that needs a value from the user.

   Apply the step 8 edits, show one line in place of the YAML (`Validating <N> tables (<mode>, <sync>, <levels on>) — <workflow_path>`, plus any step 8 edits and doctor warnings), run the pre-run check (step 10) and go to **Step 3** without waiting for a confirmation. The user can still ask for changes at any time.
5. Otherwise ask verbatim:

> Here is the validation workflow at `<workflow_path>`.
>
> **Would you like to update any fields before we run?**
> 1. **Proceed**
> 2. **Change something** (tell me which table, section, or field names)

6. **If the user chooses "Change something":** apply the user's requested edits using `../../setup/data-validation/references/workflow-config-reference.md` (camelCase keys). Its [Common edit scenarios](../../setup/data-validation/references/workflow-config-reference.md#common-edit-scenarios) table maps a user goal to the fields. Re-display the sections you changed. Repeat the question in step 5 until the user chooses **Proceed** or says they are done editing.
7. **If the user chooses "Proceed":** skip discretionary edits unless agent-only blockers remain (step 8). A `partition_key_findings` row whose label starts with `Partition prune:` is not discretionary and not an agent-only edit: show the physical column and the leading `columnNamesToPartitionBy` entry, and wait for the user to confirm before changing the YAML or calling `validate_data(mode="run")`. Early stopping and extra workers do not fix a leading column the source cannot prune.
8. **Agent-only blockers** — apply without re-prompting unless you need a value from the user:
   - When `row_validation` is on: ensure each table has usable `indexColumnList` (and `targetIndexColumnList` when names differ) per `edit_hints`.
   - When incremental **watermark**: ensure `watermarkColumn` is set on `defaultTableConfiguration.synchronization` (or per table).
   - When incremental: ensure partition columns (`columnNamesToPartitionBy`) are present.
   - Verify `targetDatabase` / per-table targets match the deployed Snowflake objects.
   - **L3 extract (non-Snowflake sources, `rowValidation` on):** if `validationConfiguration.extraction` is missing, load [../../setup/data-validation/l3-pushdown/SKILL.md](../../setup/data-validation/l3-pushdown/SKILL.md) and complete it before run (reuse DM object storage without asking; on a small default run continue without a bucket; otherwise bucket question / wait / continue without). Skip for Snowflake-source workflows. Do not dispatch `validate_data(mode="run")` while they are waiting on a bucket. Never say strategy enum names to the user.
   - Tell the user what you changed and why before confirming.
9. **Apply user-requested edits before run (hard gate).** If the user already asked to change the workflow (turn metrics off, narrow tables, etc.), those edits are **not optional**:
   - Write them into `workflow_path`, re-display the changed sections, and only then accept “Proceed” / confirmation to run.
   - **Do not** call `validate_data(mode="run")` while a user-requested edit is still unapplied.
   - **Never flip metrics on for "Full" mode** (Step 1.B): leave `metricsValidation: false` as setup wrote it unless the user asked for metrics.
10. **Pre-run verification (hard gate).** Before calling `validate_data(mode="run")`, **re-read `workflow_path`** and confirm every user-requested edit from steps 6/9 is actually written to the file, `metricsValidation` matches the agreed value, and (for non-Snowflake L3) object-store strategies include `extraction.externalStage`. If a requested edit is missing, apply it now; do not run until the on-disk YAML matches what the user asked for. `validate_data(mode="check", workflow_path=...)` must pass (fix `errors`, `doctor_failures`). Unless step 4 applies, get **explicit confirmation** to run with the final workflow and continue to Step 3. Run's `config_check.drift` not `unchanged`: tell the user.

**Do not weaken L3 heuristically.** Do not infer exclusions from column names or source/target type pairs. Validate the configured columns and report mismatches. Any deterministic normalization or exclusion belongs in product configuration, not agent guesswork. One such exclusion is built in: L3 leaves source LOB columns out unless `includeLobColumnsInRowValidation` is `true`. If the user asks why a LOB column has no L3 result, say so, and offer the key; do not turn it on unasked.

When the user asks what schema, row and metrics validation mean, answer from [Validation levels reference](./references/validation-levels-reference.md), naming only the levels that are on in this workflow. Do not block the run on it.

## Step 2b: Doctor gate (ran at infrastructure bring-up)

`scai data doctor` runs in `data_infrastructure(mode="up")`, not on `run`. Do not repair or bypass `doctor_failures` here: return the exact remediation to the main agent.

## Step 3: Run validation

```
validate_data(mode="run", workflow_path="<path from setup>")
```

On success, returns a `job_id` immediately. Validation runs in the background
through the orchestrator.
On a `direct` project the call is synchronous instead (see [RUN.md](./RUN.md),
*Interactive*): its `status` is the result, so skip Step 4.

**Show the user the `cost_reminder` from the response** (or relay this if absent):

> **Cost note:** The orchestrator and local worker are running. They can keep using Snowflake credits while idle (the worker polls the warehouse on an interval). When this wave is done, suspend the orchestrator, compute pool, and stop all workers — accept teardown when offered at the end. The local worker started via MCP stops when this Coco session ends; the orchestrator does not.

Keep `workflow_path` for Step 5.

---

## Step 4: Wait for completion with Monitor

Start the **Monitor** tool (`persistent: true`) with `monitor.watch_command` from the run response, verbatim, from the project root; its cursor prevents replays and gaps.

**Arming Monitor ends your turn.** Say one plain line (you'll report back when
validation finishes or hits trouble) and stop: the event wakes you. Between
arming Monitor and its event, run **zero** Bash commands.

**Never wait with Bash** — no `sleep`, shell polling loop, `/loop` or cron. If the watch is lost, recover it with
`job_status(job_id, monitor=true)`; do not compensate with `sleep`.

**Never read the reports by hand.** Do not `cat` / `grep` / `head` the CSVs
under `reports/data-validation/` or query the target with `sql_execute` to
decide whether validation finished or passed: they may be mid-write, and the
relay distills them into `detail.completion`.

A healthy run is silent: the watch fires only on `terminal`, a first `failure`, `stalled` or `relay_error`. When the user asks how it is going, `job_status(job_id=<monitor.job_id>, details=true)` names the tables in flight, and `migration_status(mode="summary")` gives wave-level progress ([Per-table progress narration](./references/background-monitoring.md#per-table-progress-narration-all-paths)).

### 4.A — On a Monitor event

- **`terminal`:** read `detail.completion` (`verdict`, `terminal`, `failed`, `summary`, `report_row_counts`, optional `failures` / `stale_reports`). It is authoritative; do not call `job_status` merely to confirm it. Step 4.B if `failed`, then **Step 5**.
- **`failure` / `relay_error`:** warnings — surface them and keep watching.
- **`stalled`:** diagnose before you keep watching, per [Health monitoring](./references/background-monitoring.md#health-monitoring): one `job_status(job_id, details=true)` and one `data_infrastructure(mode="status")`, then act on the `detail.stall_reason`. Never answer a stall with "still running" alone, and do **not** auto-cancel or re-dispatch the workflow. Only a `terminal` event ends monitoring.

**`job_status` reads `stalled` after a session restart:** see [the restart steps](./references/background-monitoring.md#stalled-after-a-session-restart).

### 4.B — Finished workflow with pending tables (anomaly)

If `detail.completion.failed == true`, call `job_status(job_id, details=true)` once. When `details.progress.output.isFinished == true` but `validatedTables + failedTables < totalTables` or any `tableStates[].status == "Pending"`, **do not report “Passed”**: follow [Validation workflow finished but tables incomplete](./references/troubleshooting-reference.md#validation-workflow-finished-but-tables-incomplete).

---

## Step 5: Report — data validation summary

**Do not skip.** Present an **error-first** summary in chat, its headline from
the terminal event's `detail.completion`; on failure, `job_status(job_id,
details=true)` gives deeper classification. No per-table grid unless the user asks.

That chat summary is the validation report. Do not write `migration-validation-report.html`, or HTML carrying `<meta name="snowflake-source" content="cortex-agent-authored">` presented as the AIM validation report (an agent-written page is not it); a hook rejects both.

### 5.A — Read inputs

Read **`validationConfiguration`** from the workflow YAML (or `defaults` / `applied_overrides` from setup) to know which levels ran: `schemaValidation`, `metricsValidation`, `rowValidation`. When `metricsValidation` is **false**, metrics were **not executed**; do not discuss or report them. `metricsValidated`: `true` = passed; `null` = not run (N/A), never a metrics failure.

### 5.B — Derive headline **Result** (header only)

| Outcome | **Result** line |
|---------|-----------------|
| All passed | `Passed — <N>/<N> tables OK` |
| Some failures | `<N_ok>/<N_total> tables OK — <F> failed` |
| **Finished but pending** (Step 4.B) | `<N_ok>/<N_total> tables OK — <F> never validated` |
| Job failed / no meaningful progress | `Failed — no tables validated` (adjust counts if partial) |

**Never** use the all-passed **Result** when Step 4.B applies — even if the job reached `terminal` without `failed`. **Workflow** line: `` `details.progress.output.workflowName` ``. **Header shows only `Result` and `Workflow`** — no elapsed time, check toggles, workflow file path, or job id.

### 5.C — Template (present to the user)

**All passed:**

```markdown
## Data validation complete

**Result:** Passed — <N>/<N> tables OK
**Workflow:** `<workflowName>`

No validation mismatches or execution errors.
```

**Failures:** load [Validation report reference](./references/validation-report-reference.md) and follow it: errors by category in a fixed order (Schema → Metrics → Row → Execution), suggested fixes, the failure template, and then — before Step 6 — the [re-validation menu](./references/validation-report-reference.md#5g--offer-re-validation-when-data-mismatches-remain) when it is eligible. If the job failed before any progress existed, use a **failed** title and put the job's `summary` under **Execution**. When all tables passed on the first run, continue to Step 6.

---

## Step 6: Offer to Suspend Infrastructure (Cost Saving)

This step belongs to the main agent that owns the wave/session, never a
per-object subagent. A per-object subagent returns its Step 5 report and stops.

After every active slot has returned and the wave's data work is complete, the
main agent offers to tear down the shared infrastructure to save idle cost — a
single prompt regardless of placement (default **Yes**):

> Tear down the shared data infrastructure now to stop accruing SPCS / warehouse cost? Bring it back for the next wave with `data_infrastructure(mode="up")` (dispatch does not auto-resume).
>
> 1. **Yes (default)** — call `data_infrastructure(mode="down")`.
> 2. **No, keep running** — useful if you're starting the next wave immediately and want to avoid the ~60s warm-up.

On **Yes** (or no response), call `data_infrastructure(mode="down")` and relay the returned `execution` + `orchestrator`/`worker` actions. Load `../../data-infrastructure/teardown/SKILL.md` **only** for what the tool can't cover: the cross-machine `TASK_QUEUE` check before suspending shared SPCS, a local process started outside MCP (Ctrl+C / `pkill`), or a `partial` payload with an SPCS privilege failure. Then return to the parent skill.

---

## Checklist

```
- [ ] Workflow generated (Step 1) and shown with the update question, or summarized in one line on a small default run (Step 2)
- [ ] On-disk YAML re-read, matches every requested edit, and passes mode="check" before run (Step 2, step 10)
- [ ] Monitor armed with the run's watch command; stalls diagnosed; verdict read from `terminal.detail.completion` (Step 4)
- [ ] Finished-but-pending anomaly checked (Step 4.B — never "passed" with tables still Pending)
- [ ] Error-first summary presented; re-validation menu offered when eligible, before teardown (Step 5)
- [ ] Teardown offered when wave data work is done (Step 6)
```

Return control to the parent skill (../SKILL.md).

## Reference

- When the customer asks: [Advanced operations reference](../../data-infrastructure/references/advanced-operations-reference.md) — rate limiting, re-validation (`validate_data(mode="revalidate")`), custom L3 normalization, checksum/sync blind spots
- [Incremental validation](../../setup/data-validation/references/workflow-config-reference.md#incremental-validation-synchronization) and the rest of the [Workflow Config Reference](../../setup/data-validation/references/workflow-config-reference.md)
- [Background monitoring](./references/background-monitoring.md), [Validation report reference](./references/validation-report-reference.md), [Validation levels reference](./references/validation-levels-reference.md)
- [Task model reference](./references/task-model-reference.md) and [Troubleshooting reference](./references/troubleshooting-reference.md) — stalled or partially finished runs
- [Data validation setup](../../setup/data-validation/SKILL.md), [Teardown](../../data-infrastructure/teardown/SKILL.md)
