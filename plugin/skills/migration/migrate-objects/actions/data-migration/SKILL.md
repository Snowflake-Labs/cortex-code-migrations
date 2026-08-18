---
name: data-migration-setup
description: Setup, run, and report on cloud data migration — workflow YAML, migrate_data run, background Monitor (or poll fallback), and end-of-run summary for the user.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# Data Migration Setup

One-time configuration for migrating data from a source database into Snowflake via the **scai CLI**, plus **run → monitor → report** after `migrate_data(mode="run")` (passive Monitor — always prefer it; active polling only when Monitor cannot be invoked).

> **Always use the official tooling.** Run data migration through `migrate_data(mode="setup")` / `migrate_data(mode="run")` (backed by `scai data migrate`). **Never** suggest writing ad-hoc scripts to extract, copy, or load data outside the DMVF task pipeline — the orchestrator handles partitioning, retries, incremental sync, and load orchestration.

> **Supported sources**: SQL Server, Redshift, Oracle, Teradata, PostgreSQL
> **Supported targets**: Native Snowflake tables (default). **Iceberg** targets are **Redshift-only** (partial support) — see [Extraction strategies reference](./references/extraction-strategies-reference.md#iceberg-target-redshift-only--partial-support).

> **Run-only entry:** If you were routed here only to execute `migrateData` (registry task) and the workflow YAML already exists, skip Steps 1–2 and complete **Step 2a** (display the existing `workflow_path` and offer optional updates) before **Step 4**. You **must** complete **Steps 5–7** (background monitor or poll fallback, error-first migration report, teardown offer) before returning to the parent skill — even when the state machine invoked `migrate_data(mode="run")` without walking setup.

## Prerequisite

Load `../../../data-infrastructure/SKILL.md` first. It handles shared prerequisites, compute pool registration, and worker config (source host/port/credentials, source database, source schema). Return here after it completes.

---

## Step 1: Choose Migration Approach

### 1.A — Pick Tables to Migrate (`where`)

The `where` parameter is a **registry filter that selects which tables go into
the generated workflow**. Same syntax as `scai code deploy --where` (e.g.
`source.objectType = 'table' AND source.schema = 'sales'`,
`source.canonicalName IN ('dbo.customers', 'dbo.orders')`).

#### Exact table selection (required when the user lists specific tables)

When the user names specific tables, **always** use an exact filter — never
substring / `ILIKE '%…%'`:

```
source.objectType = 'table' AND source.canonicalName IN (
  'dbo.CURR_EDB_MODEL_AUCTION_HISTORY',
  'dbo.SNAPM_EDB_MODEL_GROUPING'
)
```

**Why:** Substring filters (and the old `ILIKE '%name%'` pattern) can silently
include sibling tables whose names share a prefix — for example selecting
`SNAPM_EDB_MODEL_GROUPING` would also match `SNAPM_EDB_MODEL_GROUPING_SWTCH`
(a customer SWITCH staging table). That is unexpected for change-control
workflows. Prefer `IN (...)` or equality (`source.canonicalName = '…'` /
`source.name = '…'`).

After generating the workflow YAML, **read the `tables:` list** and confirm the
count and names with the user before running. If the YAML has more tables than
requested, stop and fix the `where` (or pass `force_regenerate=true` after
correcting it) — do not invent explanations like “partition switch auto-include”
(SnowConvert does not auto-add SWITCH siblings).

Decide the value in this order:

1. **You already know the tables.** If the parent skill or the current wave has
   already identified the tables, construct an **exact** `where` from that
   (`source.canonicalName IN (...)`). For a wave's batch, the batch's `where`
   filter is typically reusable verbatim **only if** it is already exact.
2. **Otherwise, ask the user.** Suggest options like "all tables in schema X"
   (`source.schema = 'X'`), "specific tables"
   (`source.canonicalName IN (...)`), or "all tables in scope" (omit `where`).
3. **If you're unsure of the registry filter syntax**, run `scai code where`
   to see the available columns and operators for this project, then
   construct the filter from the listed columns (`source.objectType`,
   `source.schema`, `source.canonicalName`, etc.).

Show the proposed `where` **and the resulting table names** to the user and get
confirmation before continuing.

### 1.B — Migration strategy (captured at setup)

The migration strategy — **migration type, sync strategy, extraction mechanism, and target table type** — is chosen **once during setup** by the `dataStrategy` task (executor [`setup/data-strategy/SKILL.md`](../../../setup/data-strategy/SKILL.md)) and committed to the git main branch, so by the time you dispatch it is **already set**. Do not re-ask it here.

**Fallback only** — if the strategy is unset (e.g. a project set up before setup-phase capture): run the `data-migration-setup` wizard as a catch-up — `progress_setup(mode="data_migration")` in a loop until `completed` (idempotent; a no-op once the keys exist). Extraction is **not always ODBC** (PostgreSQL COPY; Oracle ODP.NET/DBMS_CLOUD; Redshift ODBC/UNLOAD + optional Iceberg; Teradata direct/TPT/WRITE_NOS) and each strategy has worker/infra prerequisites (worker TOML fields, `externalStage`, Oracle grants, S3/IAM, TTU) — see [Extraction strategies reference](./references/extraction-strategies-reference.md) for the per-dialect matrix. `target_table_type=iceberg` is Redshift-only.

For **Preliminary** migrations, after YAML generation (Step 2a) add `whereClauseCriteria` per table with a valid WHERE predicate; see `./references/workflow-config-reference.md`.

### 1.C — Confirm

```
Migration approach:
  Tables (where): <registry filter or "all in scope">
  Type:           <from machine>
  Sync:           <from machine, or none for preliminary/full>
  Extraction:     <from machine — e.g. regular, unload, dbms_cloud, tpt, write_nos>
  Target:         <from machine>
```

Confirm strategy-specific prerequisites from [extraction-strategies-reference.md](./references/extraction-strategies-reference.md) are met (or planned) before Step 2.

---

## Step 2: Generate the Workflow YAML

Workflow YAML generation is owned by the `migrate_data` MCP tool.

Translate the user's choices from Step 1 into the call:

```
migrate_data(
  mode="setup",
  where=<table-selection filter from 1.A, or omit to include all tables in scope>,
  migration_type="preliminary" | "incremental" | "full",
  sync_strategy="none" | "checksum" | "watermark",
  extraction_strategy="regular" | "unload" | "tpt" | "write_nos" | "dbms_cloud",
  target_table_type="native" | "iceberg",  # iceberg: Redshift sources only
)
```

Notes:

- **`target_table_type=iceberg`** — Redshift only. Use `native` for SQL Server, PostgreSQL, Oracle, and Teradata.
- `where` is forwarded to `scai data migrate generate-config --where` as a
  **table-selection filter** (registry syntax). It controls which tables show
  up in the generated `tables:` list. Row-level filtering for the Preliminary
  type is a separate YAML edit (`whereClauseCriteria`) applied in Step 2a.
- The tool writes the YAML to `artifacts/data_migration/workflows/<hash>.yaml`.
  Same `where` always maps to the same file. **Re-running setup reuses the
  existing file** (preserves your edits). Pass `force_regenerate=true` only
  when you intentionally want a fresh file from scai (previous file copied to
  `.yaml.bak`).
- On first generation, the MCP server fills missing `source.databaseName` (from
  the scai source connection), `target.databaseName` (from
  `configure(snowflake_database=...)`), and Oracle `columnNamesToPartitionBy`
  (`ROWID`) when the CLI left them empty.

### Step 2a: Display, optional edits, confirm

1. Read `workflow_path`.
2. **Display** the workflow file to the user:
   - **Small/medium files** — show the full YAML in chat.
   - **Large files** — show the path, `tables:` count, `defaultTableConfiguration`, and table names; offer to show the full file or specific tables on request.
   - Note whether setup **reused** an existing file (`workflow_reused`) or regenerated it.
3. **Summarize:** table count, `migration_type`, sync strategy, extraction strategy, `target_table_type`, and any `partition_key_findings` from setup.
4. Ask verbatim:

> Here is the migration workflow at `<workflow_path>`.
>
> **Would you like to update any fields before we run?**
> 1. **Proceed**
> 2. **Change something** (tell me which table, section, or field names)

5. **If the user chooses "Change something":** apply the user's requested edits using `./references/workflow-config-reference.md` and [extraction-strategies-reference.md](./references/extraction-strategies-reference.md). Use `edit_hints` as a guide when the user is unsure what can be changed. Re-display the sections you changed. Repeat the question in step 4 until the user chooses **Proceed** or says they are done editing.

   **Common scenarios → fields to edit:**

   | User goal | Workflow fields |
   |-----------|-----------------|
   | Incremental sync | `synchronization.strategy`, `watermarkColumn`, `trackModifications`, `trackDeletions`, `primaryKeyColumns` |
   | Limit rows (preliminary) | `whereClauseCriteria` |
   | Reduce source locking | `queryModifiers` (or worker TOML `query_modifiers`) |
   | Large table performance | `columnNamesToPartitionBy`, `targetPartitionSizeMb` / `targetPartitionSizeRows`, `executionTimeoutMinutes` (Analyze boundaries only; default 20) |
   | Column rename/type map | `columnNameMappings`, `columnTypeMappings` |
   | Server-side export | `extraction.strategy`, `externalStage` + worker TOML (UNLOAD/WRITE_NOS/DBMS_CLOUD) |
   | Iceberg target | `target.tableType`, `target.icebergConfig`, `migrationStrategy` |

   For stalled or partially finished runs, see [Task model reference](./references/task-model-reference.md) and [Troubleshooting reference](./references/troubleshooting-reference.md).

6. **If the user chooses "Proceed":** skip discretionary edits unless agent-only blockers remain (step 7).
7. **Agent-only blockers** — apply without re-prompting unless you need a value from the user:
   - Resolve `partition_key_findings` and required `columnNamesToPartitionBy` per `edit_hints` (empty `[]` finishes the workflow without moving data; SQL Server / Redshift need an explicit PK or partition column; Oracle defaults to `ROWID`; PostgreSQL: monotonic integer PK or timestamp — avoid `ctid`).
   - **Preliminary type:** add `whereClauseCriteria: "<row predicate>"` per table or `defaultTableConfiguration` when missing.
   - Required **extraction strategy** fields (`extraction.strategy`, `externalStage`, worker TOML cross-refs for `unload` / `write_nos` / `dbms_cloud` / `tpt`).
   - **Redshift Iceberg** (`target_table_type=iceberg`): required fields from [iceberg-setup-reference.md](./references/iceberg-setup-reference.md).
   - Tell the user what you changed and why before confirming.
8. Get **explicit confirmation** to run with the final workflow, then continue to Step 3.

> `columnNamesToPartitionBy` is **required** by the CLI validator for all configs.

> **Affinity matching** — If the orchestrator logs show "Found 0 pending workflows," the service likely has a baked-in affinity that doesn't match. See [Troubleshooting Reference](./references/troubleshooting-reference.md) for diagnosis and fix.

---

## Step 2b: Doctor gate (ran at infrastructure bring-up)

The `scai data doctor` gate runs during `data_infrastructure(mode="up")` (the prerequisite in Step 4), **not** on `migrate_data(mode="run")` — dispatch is pure. If `up` reported `doctor_failures`, surface them and fix them (or re-run `data_infrastructure(mode="up", skip_doctor=true)` only after the user explicitly accepts the failures) before dispatching. Resolve `partition_key_findings` during Step 2a (blockers or user-requested edits).

---

## Step 3: Create Target Database

```sql
CREATE DATABASE IF NOT EXISTS <target_db>;
CREATE SCHEMA IF NOT EXISTS <target_db>.<target_schema>;
```

---

## Step 4: Run migration

```
migrate_data(mode="run", workflow_path="<path from setup>")
```

Returns immediately with `job_id` — migration is **dispatched** in the background via `scai data migrate create-workflow` against the already-running shared orchestrator + worker.

**Prerequisite:** the shared infrastructure must already be up. If you have not done so this session, run `data_infrastructure(mode="up")` once first — it brings up the orchestrator + worker (SPCS when a `compute_pool` is configured, otherwise local), runs the doctor gate, and returns the `cost_reminder` to relay. If infrastructure is not up, `migrate_data(mode="run")` returns a `remediation` pointing at `data_infrastructure(mode="up")` — bring it up and retry.

The `execution` field (`"local"` | `"cloud"`) and `cost_reminder` are on the `data_infrastructure(mode="up")` response — **relay the reminder to the user verbatim**. If absent, use the note that matches the `execution` field:

> **Cost note (cloud):** The SPCS orchestrator and local worker are running and shared across every dispatch this session; they can keep using Snowflake credits while idle (the worker polls the warehouse on an interval). When you are done, tear the infrastructure down — `data_infrastructure(mode="down")` for the local worker, and the teardown skill to suspend the SPCS orchestrator and compute pool. The local worker stops when this session ends; the SPCS orchestrator does not.
>
> **Cost note (local):** A local orchestrator and worker run for this session, shared across every dispatch, and stop when the session ends or you call `data_infrastructure(mode="down")`. Source extraction still runs SQL against your warehouse while active.

Retain `workflow_path` for the report in Step 6.

After run starts, go to **Step 5** (do not busy-poll every 30–60s unless you are on the fallback path).

---

## Step 5: Wait for completion (Monitor, or poll fallback)

Load [Background monitoring](./references/background-monitoring.md) and follow it. Summary below; the reference is authoritative for capability checks, event phases, and crash fallback.

**Status tool** (both paths):

```
job_status(job_id="<JOB_ID>")                 # cheap summary
job_status(job_id="<JOB_ID>", details=true)   # + full progress and failure reports
```

`job_id` is `monitor.job_id` from the `migrate_data(mode="run")` response. `details` may report `details_unavailable` until `create-workflow` returns a workflow name; that is normal early in the run.

### 5.A — Choose path

**Always prefer Monitor when it can be invoked.** Polling is never the better choice while Monitor is available — one relay poller serves every watcher, it wakes you on trouble and not only on completion, and it spends no tool call per check.

| Condition | Path |
|-----------|------|
| Monitor tool can be invoked — **the default** | **Background** — Phases A–D in the reference |
| Monitor genuinely unavailable (absent from the tool list, or invoking it fails) | **Fallback** — active poll below |

If you are unsure whether Monitor is available, **try it** rather than defaulting to the poll. Calling `job_status(job_id)` because the user asked for an update is not the polling path and is always fine.

**One completion owner:** only the background Monitor path **or** the fallback poll may present Step 6 — never both.

### 5.A.1 — Background path (always use this when Monitor is available)

1. **Phase A — Monitor:** Start the **Monitor** tool (`persistent: true`) with `monitor.watch_command` from the run response, verbatim, from the project root. No wait for a workflow name, and no hand-built command — the cursor baked into it is what prevents replays and gaps.
2. **Phase B — Monitor fire:** Branch on the event's `phase`. `failure` / `stalled` / `relay_error` are warnings — surface them and keep watching. On `terminal`: `job_status(job_id, details=true)` once → Step 5.C if needed → **Step 6**.

**No progress loop.** Do not start `/loop` or a cron to poll for progress. The relay emits a `stalled` event once a job has gone **30 minutes** without changing, so a quiet job reports itself. A healthy run is silent by design — progress lands in the log, and `job_status` reads it whenever the user asks.

The watch fires only on terminal, first failure, a 30-minute stall, or relay error — not on ordinary progress, which changes on nearly every poll. It exits by itself on its job's terminal record.

Tell the user once that you'll report back when the job finishes or hits trouble.

**If the watch goes silent,** re-arm with `job_status(job_id, monitor=true)` — it returns a fresh cursor and watch command and restores the relay's poller if it was lost. With no progress loop there is no second timer cross-checking the watch, so this is the recovery path after a compaction, a session restart, or an answer that looks stale.

### 5.A.2 — Fallback path (last resort — only when Monitor cannot be invoked)

Poll until the job is terminal:

- Call `job_status(job_id)` repeatedly until `terminal` is `true` (or when the user asks for an update). A natural gap between turns is enough — **do not insert your own timer**.
- On polls where you are **not** running a health check (Step 5.B), optionally share a one-line update from `summary`, or from `details.progress.output` when you pass `details=true` (e.g. `preprocessedTables`/`totalTables`, `aggregatedCounts.loadedPartitions`/`totalPartitions`).

**Never wait with `bash sleep` (or by tailing worker logs) for migrate progress.** That burns wall-clock and skips the status tool. The only allowed wait signals are Monitor (preferred) or another `job_status` call. Short `sleep` after killing a process (1–3s) is fine; multi-tens-of-seconds sleeps to "give the workflow time" are not.

**Stop when** `terminal` is `true`.

Then Step 5.C → Step 6.

### 5.B — Health monitoring (while waiting)

On the background path the relay emits a `stalled` event when counters stop moving, so you do not compute stalls yourself — warn the user and keep watching.

On the fallback path, derive health from consecutive `job_status(job_id, details=true)` responses. Keep the previous response in memory (at least `details.progress.output.aggregatedCounts`, `preprocessedTables`, `totalTables`, and `tablePartitions`).

**When to run:**

- **Background path:** the relay reports stalls itself; check health when it fires an event or the user asks.
- **Fallback path:** every **2nd or 3rd** poll, or when the user asks. Skip until `details.progress.output` exists.

**Progress key:** `loadedPartitions` from `details.progress.output.aggregatedCounts` (fallback: sum of `tablePartitions[].loadedPartitions`). Record the poll/tick time when this key last increased.

| Signal | Background (relay events) | Fallback (30–60s poll) | Severity |
|--------|---------------------------|-------------------------|----------|
| Stall | `stalled` event | `loadedPartitions` unchanged **≥10 minutes** | **Warning** |
| Stuck | a second `stalled` event, or one still standing when you next look | unchanged **≥20 minutes** | **Critical** |
| Partition failures | `failure` event, or `failed: true` on any event | `aggregatedCounts.failedPartitions > 0` | **Warning** (immediate) |
| Preprocessing lag | `preprocessedTables < totalTables` and running **≥30 minutes** | running **≥15 minutes** | **Warning** |
| Partial table failure | Any `tablePartitions[]` with `failedPartitions > 0` or `hasBeenPreprocessed == false` while still running | same | **Warning** |

When **`reports`** is present, also scan `details.reports.files.errors` — any rows mean at least one task/partition has failed even if aggregate counters look healthy.

**What to tell the user** (short; do not block waiting unless they ask to stop):

```markdown
**Migration health** — `<workflowName or "starting…">`
- Loaded partitions: <loaded>/<total> (<pct>%)
- **Warning:** No partition progress in <N> minutes.  <!-- stall -->
- **Critical:** No partition progress in <N> minutes.  <!-- stuck -->
- <N> table(s) with failed partitions: `t1`, `t2`
- Preprocessing incomplete: <preprocessed>/<total> tables
```

On **Warning** or **Critical**, point to [Troubleshooting Reference](./references/troubleshooting-reference.md) (stale `TASK_QUEUE` tasks, worker DB mismatch, affinity). Do **not** auto-cancel the workflow — offer: keep waiting, open troubleshooting, or pause/teardown if the user wants to stop cost.

Fold the worst severity seen while waiting into Step 6 **Infrastructure** or **Load** only if it was never surfaced to the user.

A stall or stuck warning does **not** end monitoring — only a `terminal` event (or a fallback poll seeing `terminal: true`) does.

When a job fails before a workflow exists, the failure text is in the job's `summary` — surface it under **Infrastructure** in `### Errors`.

### 5.C — Finished workflow with incomplete tables (anomaly)

After the terminal status (Monitor fire + confirm, or fallback poll), if `details.progress.output.isFinished == true` **and** any of:

- `preprocessedTables < totalTables`
- any `tablePartitions[].hasBeenPreprocessed == false`
- `aggregatedCounts.failedPartitions > 0`

**Do not report success.** Treat as a failed/partial run (matches scai `HasErrors`).

1. Pull messages from `details.reports.files.progress` (`ExampleErrorMessage`) and `details.reports.files.errors` (`LastErrorMessage`, `TaskName`, `PartitionNumber`) — `details.progress.output` has no error text.
2. Classify tables with `hasBeenPreprocessed == false` under **Preprocessing**; failed partitions under **Load** or **Extraction** per task name.
3. If errors are missing or tasks look stuck, follow [Workflow finished but tables incomplete](./references/troubleshooting-reference.md#workflow-finished-but-tables-incomplete) — query `TASK_QUEUE` for terminal vs non-terminal tasks. Worker/orchestrator stall is **one** hypothesis (worker down, affinity, stale tasks, suspended service), not the only one.
4. Do **not** suggest re-run until prerequisites are identified.

---

## Step 6: Report — data migration summary

**Do not skip.** Present an **error-first** summary in chat (markdown). Build it from the final `job_status(job_id, details=true)` response (`details.progress`, `details.reports`) and classify failures — **not** a per-table results grid unless the user asks.

### 6.A — Read inputs

| Source | Fields |
|--------|--------|
| Job entry (top level) | `status`, `terminal`, `failed`, `summary` (carries the failure text when the job died before a workflow existed) |
| `details.progress.output` | `workflowName`, `isFinished`, `workflowStatus`, `totalTables`, `preprocessedTables`, `aggregatedCounts`, `tablePartitions` (`hasBeenPreprocessed`, `failedPartitions`, `loadedPartitions`, `totalPartitions`) |
| **`details.reports`** | `files.progress` (`TableName`, `ExampleErrorMessage`, partition counts); `files.errors` (`TableName`, `TaskName`, `PartitionNumber`, `LastErrorMessage`, …) — PascalCase columns |
| Workflow YAML | Use only when suggesting fixes (sync, extraction, `whereClauseCriteria`, target) |

`details` is attached by `job_status(job_id, details=true)`, which runs `scai data migrate status` (writing CSV under `reports/data-migration/workflow-<timestamp>/`) and parses it. **`details.progress.output` has no error text** — use `details.reports.files` for messages.

### 6.B — Derive headline **Result** (header only)

Count tables from `details.progress.output.tablePartitions` when present:

| Outcome | **Result** line |
|---------|-----------------|
| All tables loaded, no failures | `Success — <N>/<N> tables loaded` |
| Some failures | `<N_ok>/<N_total> tables OK — <F> failed` |
| **Finished but incomplete** (Step 5.C) | `<N_ok>/<N_total> tables OK — <F> never completed` |
| Job `failed` is true or no table progress | `Failed — no tables processed` (or partial counts if available) |

**Never** use the all-success **Result** when Step 5.C applies — even if the job reached `terminal` without `failed`.

**Workflow** line: `` `details.progress.output.workflowName` `` when set; if the job failed before a workflow name exists, say so in **Result** and use the job's `summary` under **Infrastructure**.

**Header shows only `Result` and `Workflow`** — do not put elapsed time, partition totals, config, workflow file path, or job id in the header.

### 6.C — Classify errors (fixed category order)

Assign each failed table to **one** category (first match wins). List categories **only when they have at least one error**, in this order:

| Order | Category | When |
|-------|----------|------|
| 1 | **Preprocessing** | `hasBeenPreprocessed` is false |
| 2 | **Extraction** | `TaskName` is `extract` (or extract-phase failure); source/read errors in `ExampleErrorMessage` / `LastErrorMessage` |
| 3 | **Load** | Load-phase failures, `failedPartitions` > 0 with load task, partial partition load (table-specific message) |
| 4 | **Infrastructure** | Top-level `error`, orchestrator/compute pool/worker failures before per-table progress |

**Message per table:** prefer `details.reports.files.progress[].ExampleErrorMessage`, else first `details.reports.files.errors[].LastErrorMessage` for that `TableName`. For load, you may add partition context (`loaded`/`total`, `PartitionNumber`) on the same bullet.

**Deduplicate:** when two or more tables share the same normalized message in a category, emit **one** bullet with the message and a line `- Affects: \`table1\`, \`table2\`, …`. Use a single table name in the bullet only when the failure is table-specific (e.g. one load timeout with partition detail).

### 6.D — Suggested fixes

Number fixes in the **same category order** as **Errors** (Preprocessing → Extraction → Load → Infrastructure). One numbered item per error group (not per table when deduped). Each item must be a **concrete prerequisite action** (edit worker TOML, fix workflow YAML, cancel stale tasks, grant privileges, etc.) — not “re-run and hope.” Tie actions to:

- [Troubleshooting Reference](./references/troubleshooting-reference.md) for worker/orchestrator/partition issues
- YAML / TOML edits: `whereClauseCriteria`, partitions, `source.databaseName`, extraction strategy, worker connection fields — as required by the error category
- **Re-run only as a follow-up:** mention `migrate_data(mode="run", workflow_path=...)` in `### Suggested fixes` only when prerequisites are clear, or label it “after the steps above” — do not list re-run as the first or only fix
- After all tables succeed → offer [validation](../../../validate-objects/actions/validate_tables.md) for the same scope

Do **not** include a per-table markdown table unless the user asks for a full audit.

### 6.E — Template (present to the user)

**All succeeded** — no `### Errors` section:

```markdown
## Data migration complete

**Result:** Success — <N>/<N> tables loaded
**Workflow:** `<workflowName>`

No errors. You can run validation for this scope or continue the wave.
```

**Failures:**

```markdown
## Data migration — completed with errors

**Result:** <N_ok>/<N_total> tables OK — <F> failed
**Workflow:** `<workflowName>`

### Errors

**Preprocessing**
- <message>
  - Affects: `<table>`, …

**Extraction**
- <shared message>
  - Affects: `<table>`, …

**Load**
- `<table>` — <message> (<loaded>/<total> partitions failed if relevant)

**Infrastructure**
- <job summary or orchestrator error>

### Suggested fixes

1. **Preprocessing (<tables>)** — …
2. **Extraction (<tables>)** — …
3. **Load (<table>)** — …
4. **Infrastructure** — …
```

Omit empty category subsections. If every table completed **and Step 5.C does not apply**, omit `### Errors` and `### Suggested fixes` failure content. If the job failed before `progress` existed, use the **failed** title, minimal **Result**, and a single **Infrastructure** error + fix.

**After the summary:**

- **All tables succeeded** — offer validation for this scope or continuing the wave.
- **Any failures** — do **not** jump to re-run. Summarize the prerequisite actions from `### Suggested fixes`, then **ask the user** how to proceed, for example:
  1. Apply fixes (YAML/TOML/config) — you or the user edits files; confirm when done
  2. Re-run the same workflow — only after prerequisites are done or the user explicitly accepts re-run without fixes (e.g. transient infra)
  3. Narrow scope — adjust `where` / workflow YAML and run setup + run for failed tables only
  4. Investigate further — troubleshooting reference, logs, health signals from Step 5.B
  5. Stop — proceed to Step 7 (teardown) without re-running

Then continue to Step 7 (teardown offer) when wave data work is done for this pass.

---

## Step 7: Offer to tear down infrastructure (cost saving)

When the wave's data work is done, offer to tear down idle infrastructure to save cost (default **Yes**), then **delegate** — do **not** re-derive what is running here:

- **Local** orchestrator/worker this session started → `data_infrastructure(mode="down")`.
- **SPCS** orchestrator / compute pool / DEW worker (or any mixed setup) → load [`../../../data-infrastructure/teardown/SKILL.md`](../../../data-infrastructure/teardown/SKILL.md); it owns the "what's running" detection (its *Which steps apply* table) and runs only the applicable steps.

Nothing auto-resumes — dispatch is pure, so bring infrastructure back for the next wave with `data_infrastructure(mode="up")`. (A local worker started via MCP also stops when the session ends.)

If the user picks **Yes** (or doesn't respond), run the teardown, then return to the parent skill.

---

## Checklist

Shared infrastructure checklist is owned by `../../../data-infrastructure/SKILL.md`. Migration-specific items:

```
- [ ] Migration strategy set (captured at setup via dataStrategy; fallback wizard only if unset)
- [ ] Strategy-specific worker/infra prerequisites met per extraction-strategies-reference.md
- [ ] Workflow YAML generated via migrate_data(mode="setup", ...) (or existing file reviewed at Step 2a)
- [ ] User saw workflow YAML and was offered optional field updates (Step 2a)
- [ ] User confirmed the final workflow YAML before run
- [ ] Partition-key findings resolved (or accepted) at Step 2a
- [ ] Target database and schema exist
- [ ] Iceberg prerequisites validated — if Redshift + `target_table_type=iceberg`
- [ ] migrate_data(mode="run") started
- [ ] Monitor used (the default); active polling only if Monitor could not be invoked (Step 5)
- [ ] Waited until the job reported a `terminal` event
- [ ] Finished-but-incomplete anomaly checked (Step 5.C — do not report success if tables never preprocessed)
- [ ] Health monitoring run while waiting when triggered (Step 5.B — stall/failure signals surfaced)
- [ ] Error-first data migration summary presented (Step 6 — Result + Workflow, Errors, Suggested fixes)
- [ ] Teardown offered when wave data work is done (Step 7)
```

Return control to the parent skill.

---

## Reference

- [Background monitoring](./references/background-monitoring.md)
- [Workflow Config Reference](./references/workflow-config-reference.md)
- [Task Model Reference](./references/task-model-reference.md)
- [Extraction Strategies Reference](./references/extraction-strategies-reference.md)
- [Iceberg Setup Reference](./references/iceberg-setup-reference.md)
- [Troubleshooting Reference](./references/troubleshooting-reference.md)
- [Data Doctor reference](../../../data-infrastructure/references/data-doctor-reference.md)
- [Teardown (cost-saving suspend)](../../../data-infrastructure/teardown/SKILL.md)
