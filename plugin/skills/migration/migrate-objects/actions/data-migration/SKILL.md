---
name: data-migration-setup
description: Setup, run, and report on cloud data migration — workflow YAML, migrate_data run, poll, and end-of-run summary for the user.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# Data Migration Setup

One-time configuration for migrating data from a source database into Snowflake via the **scai CLI**, plus **run → poll → report** after `migrate_data(mode="run")`.

> **Supported sources**: SQL Server, Redshift, Oracle, Teradata, PostgreSQL
> **Supported targets**: Native Snowflake tables (default). **Iceberg** targets are **Redshift-only** (partial support) — see [Extraction strategies reference](./references/extraction-strategies-reference.md#iceberg-target-redshift-only--partial-support).

> **Run-only entry:** If you were routed here only to execute `migrateData` (registry task) and the workflow YAML already exists, skip Steps 1–2 and complete **Step 2a** (display the existing `workflow_path` and offer optional updates) before **Step 4**. You **must** complete **Steps 5–7** (poll, error-first migration report, teardown offer) before returning to the parent skill — even when the state machine invoked `migrate_data(mode="run")` without walking setup.

## Prerequisite

Load `../../../data-infrastructure/SKILL.md` first. It handles shared prerequisites, compute pool registration, and worker config (source host/port/credentials, source database, source schema). Return here after it completes.

---

## Step 1: Choose Migration Approach

### 1.A — Pick Tables to Migrate (`where`)

The `where` parameter is a **registry filter that selects which tables go into
the generated workflow**. Same syntax as `scai code deploy --where` (e.g.
`source.objectType = 'table' AND source.schema = 'sales'`,
`source.canonicalName IN ('dbo.customers', 'dbo.orders')`).

Decide the value in this order:

1. **You already know the tables.** If the parent skill or the current wave has
   already identified the tables, construct the `where` from that. For a wave's batch,
   the batch's `where` filter is typically reusable verbatim.
2. **Otherwise, ask the user.** Suggest options like "all tables in schema X"
   (`source.schema = 'X'`), "specific tables"
   (`source.canonicalName IN (...)`), or "all tables in scope" (omit `where`).
3. **If you're unsure of the registry filter syntax**, run `scai code where`
   to see the available columns and operators for this project, then
   construct the filter from the listed columns (`source.objectType`,
   `source.schema`, `source.canonicalName`, etc.).

Show the proposed `where` to the user and get confirmation before continuing.

### 1.B — Extraction mechanism and migration approach (state machine)

**Extraction mechanism** (how data leaves the source) is **not always ODBC**. PostgreSQL uses COPY; Oracle can use `DBMS_CLOUD`; Redshift and Teradata support server-side export to object storage. Before calling the state machine, read `source_language` from `configure()` and load [Extraction strategies reference](./references/extraction-strategies-reference.md) so you can explain options if the user asks.

Migration type, sync strategy, **extraction strategy**, and target table type are driven by the **`data-migration-setup` state machine**. Call `progress_setup(mode="data_migration")` in a loop until `completed` is true — follow each response's `next_prompt` (persist answers with `configure`) the same way as project setup in `setup/SKILL.md`.

The state machine routes by dialect:

| Source | Extraction prompt |
|--------|-------------------|
| SQL Server | Direct read (ODBC) — only option |
| PostgreSQL | Direct read (COPY) — only option |
| Oracle | Direct read (ODP.NET) or DBMS_CLOUD export |
| Redshift | ODBC or UNLOAD to S3; optional **Iceberg** target (partial) |
| Teradata | Direct read, TPT, or WRITE_NOS |

**Target table type:** the state machine asks **Native vs Iceberg** only for **Redshift**. Other dialects default to native — do not pass `target_table_type=iceberg` unless the source is Redshift.

After the machine completes, walk the user through **strategy-specific setup** from the extraction reference (worker TOML fields, `externalStage`, Oracle grants, S3/IAM, TTU, etc.) before generating YAML.

For **Preliminary** migrations, after YAML generation (Step 2a), add `whereClauseCriteria` per table with a valid WHERE predicate; see `./references/workflow-config-reference.md`.

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
> 1. **No — proceed**
> 2. **Yes — I want to change something** (tell me which table, section, or field names)

5. **If Yes:** apply the user's requested edits using `./references/workflow-config-reference.md` and [extraction-strategies-reference.md](./references/extraction-strategies-reference.md). Use `edit_hints` as a guide when the user is unsure what can be changed. Re-display the sections you changed. Repeat the question in step 4 until the user chooses **No — proceed** or says they are done editing.
6. **If No:** skip discretionary edits unless agent-only blockers remain (step 7).
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

## Step 2b: Doctor gate (automatic)

You no longer run doctor by hand here. `migrate_data(mode="run")` runs a `scai data doctor` check and **refuses to start** if any check fails, returning `doctor_failures`. Surface those to the user and fix them, or call `migrate_data(mode="run", skip_doctor=true)` only after the user explicitly accepts the failures. Resolve `partition_key_findings` during Step 2a (blockers or user-requested edits).

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

Returns immediately with `job_id` — migration runs in the background: orchestrator setup, local worker when configured, then `scai data migrate create-workflow`.

**When run succeeds**, show the user the `cost_reminder` from the response (or this note if absent):

> **Cost note:** The orchestrator and local worker are running. They can keep using Snowflake credits while idle (the worker polls the warehouse on an interval). When this wave is done, suspend the orchestrator, compute pool, and stop all workers — accept teardown when offered at the end. The local worker started via MCP stops when this Coco session ends; the orchestrator does not.

Retain `workflow_path` for the report in Step 6.

Track progress with `migration_status(mode="data_migration")`.

---

## Step 5: Poll for completion

Poll until the job is terminal:

```
migrate_data_status()
```

(or `migration_status(mode="data_migration")` — same JSON shape)

**While `status` is `"running"`:**

- Poll every 30–60 seconds, or when the user asks for an update.
- `progress` may be absent until `create-workflow` returns a workflow name; that is normal early in the run.
- On polls where you are **not** running a health check (Step 5.B), optionally share a one-line update from `progress.output` when present (e.g. `preprocessedTables`/`totalTables`, `aggregatedCounts.loadedPartitions`/`totalPartitions`).

### 5.B — Health monitoring (while polling)

No extra tools — derive health from consecutive `migrate_data_status()` responses. Keep the previous response in memory (at least `progress.output.aggregatedCounts`, `preprocessedTables`, `totalTables`, and `tablePartitions`).

**When to run:** every **2nd or 3rd** poll, or when the user asks for a health update. Skip until `progress.output` exists.

**Progress key:** `loadedPartitions` from `progress.output.aggregatedCounts` (fallback: sum of `tablePartitions[].loadedPartitions`). Record the poll time when this key last increased.

| Signal | Condition | Severity |
|--------|-----------|----------|
| Stall | `loadedPartitions` unchanged for **≥10 minutes** while `status` is `"running"` and `isFinished` is false | **Warning** |
| Stuck | Same unchanged for **≥20 minutes** | **Critical** |
| Partition failures | `aggregatedCounts.failedPartitions > 0` | **Warning** (immediate) |
| Preprocessing lag | `preprocessedTables < totalTables` and job has been running **≥15 minutes** | **Warning** |
| Partial table failure | Any `tablePartitions[]` with `failedPartitions > 0` or `hasBeenPreprocessed == false` while still running | **Warning** |

When **`reports`** is present, also scan `reports.files.errors` — any rows mean at least one task/partition has failed even if aggregate counters look healthy.

**What to tell the user** (short; do not block polling unless they ask to stop):

```markdown
**Migration health** — `<workflowName or "starting…">`
- Loaded partitions: <loaded>/<total> (<pct>%)
- **Warning:** No partition progress in <N> minutes.  <!-- stall -->
- **Critical:** No partition progress in <N> minutes.  <!-- stuck -->
- <N> table(s) with failed partitions: `t1`, `t2`
- Preprocessing incomplete: <preprocessed>/<total> tables
```

On **Warning** or **Critical**, point to [Troubleshooting Reference](./references/troubleshooting-reference.md) (stale `TASK_QUEUE` tasks, worker DB mismatch, affinity). Do **not** auto-cancel the workflow — offer: keep waiting, open troubleshooting, or pause/teardown if the user wants to stop cost.

Fold the worst severity seen during polling into Step 6 **Infrastructure** or **Load** only if it was never surfaced to the user.

**Stop polling when:**

- `status` is `"completed"` or `"failed"`, **and**
- `progress.output.isFinished` is `true` when `progress` is present.

A stall or stuck warning does **not** end the poll loop — only terminal `status` plus `isFinished` does.

If `status` is `"failed"` and top-level `error` is set, surface it under **Infrastructure** in `### Errors`.

### 5.C — Finished workflow with incomplete tables (anomaly)

After the terminal poll, if `progress.output.isFinished == true` **and** any of:

- `preprocessedTables < totalTables`
- any `tablePartitions[].hasBeenPreprocessed == false`
- `aggregatedCounts.failedPartitions > 0`

**Do not report success.** Treat as a failed/partial run (matches scai `HasErrors`).

1. Pull messages from `reports.files.progress` (`ExampleErrorMessage`) and `reports.files.errors` (`LastErrorMessage`, `TaskName`, `PartitionNumber`) — `progress.output` has no error text.
2. Classify tables with `hasBeenPreprocessed == false` under **Preprocessing**; failed partitions under **Load** or **Extraction** per task name.
3. If errors are missing or tasks look stuck, follow [Workflow finished but tables incomplete](./references/troubleshooting-reference.md#workflow-finished-but-tables-incomplete) — query `TASK_QUEUE` for terminal vs non-terminal tasks. Worker/orchestrator stall is **one** hypothesis (worker down, affinity, stale tasks, suspended service), not the only one.
4. Do **not** suggest re-run until prerequisites are identified.

---

## Step 6: Report — data migration summary

**Do not skip.** Present an **error-first** summary in chat (markdown). Build it from the final `migrate_data_status()` response (`progress`, `reports`) and classify failures — **not** a per-table results grid unless the user asks.

### 6.A — Read inputs

| Source | Fields |
|--------|--------|
| Status response (top level) | `status`, `error` (if failed before progress) |
| `progress.output` | `workflowName`, `isFinished`, `totalTables`, `preprocessedTables`, `aggregatedCounts`, `tablePartitions` (`hasBeenPreprocessed`, `failedPartitions`, `loadedPartitions`, `totalPartitions`) |
| **`reports`** | `files.progress` (`TableName`, `ExampleErrorMessage`, partition counts); `files.errors` (`TableName`, `TaskName`, `PartitionNumber`, `LastErrorMessage`, …) — PascalCase columns |
| Workflow YAML | Use only when suggesting fixes (sync, extraction, `whereClauseCriteria`, target) |

`reports` is attached by `migrate_data_status()` after `scai data migrate status` writes CSV under `reports/data-migration/workflow-<timestamp>/`. **`progress.output` has no error text** — use `reports.files` for messages.

### 6.B — Derive headline **Result** (header only)

Count tables from `progress.output.tablePartitions` when present:

| Outcome | **Result** line |
|---------|-----------------|
| All tables loaded, no failures | `Success — <N>/<N> tables loaded` |
| Some failures | `<N_ok>/<N_total> tables OK — <F> failed` |
| **Finished but incomplete** (Step 5.C) | `<N_ok>/<N_total> tables OK — <F> never completed` |
| Job `status` is `"failed"` or no table progress | `Failed — no tables processed` (or partial counts if available) |

**Never** use the all-success **Result** when Step 5.C applies — even if top-level MCP `status` is `"completed"`.

**Workflow** line: `` `progress.output.workflowName` `` when set; if the job failed before a workflow name exists, say so in **Result** and use top-level `error` under **Infrastructure**.

**Header shows only `Result` and `Workflow`** — do not put elapsed time, partition totals, config, workflow file path, or job id in the header.

### 6.C — Classify errors (fixed category order)

Assign each failed table to **one** category (first match wins). List categories **only when they have at least one error**, in this order:

| Order | Category | When |
|-------|----------|------|
| 1 | **Preprocessing** | `hasBeenPreprocessed` is false |
| 2 | **Extraction** | `TaskName` is `extract` (or extract-phase failure); source/read errors in `ExampleErrorMessage` / `LastErrorMessage` |
| 3 | **Load** | Load-phase failures, `failedPartitions` > 0 with load task, partial partition load (table-specific message) |
| 4 | **Infrastructure** | Top-level `error`, orchestrator/compute pool/worker failures before per-table progress |

**Message per table:** prefer `reports.files.progress[].ExampleErrorMessage`, else first `reports.files.errors[].LastErrorMessage` for that `TableName`. For load, you may add partition context (`loaded`/`total`, `PartitionNumber`) on the same bullet.

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
- <top-level or orchestrator error>

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

Before prompting, determine what this project actually runs (from infrastructure setup, `configure()` output, and `.scai/settings/cloud-migration.yaml`):

| Signal | Orchestrator | Worker |
|--------|--------------|--------|
| `compute_pool` configured (in configure / `cloud-migration.yaml`) | **SPCS** (`DATA_MIGRATION_SERVICE`) | — |
| No `compute_pool` — user chose **local orchestrator** in setup | **Local** (`scai data orchestrator start --local`) | — |
| `worker-spcs` / `scai data worker setup` completed | — | **SPCS DEW** |
| `worker-local-setup` or `migrate_data` started a local worker | — | **Local** (`scai data worker start --local`) |

Ask only about components that are **in use**. Then load `../../../data-infrastructure/teardown/SKILL.md` and run **applicable steps only** (skip SPCS orchestrator + pool steps when there is no compute pool; skip worker 4a or 4b per `scai data worker status` / setup path).

**Prompt variants** (default **Yes** to tear down what applies):

**SPCS orchestrator + local worker** (typical `migrate_data` MCP path when `compute_pool` is set):

> Suspend the SPCS orchestrator and compute pool to stop idle SPCS cost? Also stop the local worker if it is still running so the warehouse can auto-suspend.
>
> 1. **Yes (default)** — teardown (SPCS Steps 2–3 + local worker 4b as needed). The next `migrate_data()` / `validate_data()` auto-resumes the SPCS service.
> 2. **No, keep running** — next batch soon; avoids ~60s SPCS warm-up.

**SPCS orchestrator + SPCS worker:**

> Suspend the SPCS orchestrator, compute pool, and DEW worker service now?
>
> 1. **Yes (default)** — teardown Steps 2–3 + 4a.
> 2. **No, keep running**

**Local orchestrator + local worker** (no `compute_pool`):

> Stop the local orchestrator and local worker processes so nothing keeps polling Snowflake?
>
> 1. **Yes (default)** — teardown Step 2b + 4b (Ctrl+C / kill processes; `scai data orchestrator stop --local` is advisory only).
> 2. **No, keep running**

**Local worker only** (orchestrator already stopped / not applicable):

> Stop the local worker if it is still running so the warehouse can auto-suspend?
>
> 1. **Yes (default)** — teardown 4b only.
> 2. **No, keep running**

**Note:** A local worker started by `migrate_data()` / `validate_data()` through MCP stops when the MCP session ends. Step 4b still applies when the worker was started manually, the user chose **keep running** earlier, or you need to stop it before session end.

If the user picks **Yes** (or doesn't respond), load the teardown sub-skill, then return to the parent skill.

---

## Checklist

Shared infrastructure checklist is owned by `../../../data-infrastructure/SKILL.md`. Migration-specific items:

```
- [ ] Migration approach selected (including extraction mechanism for this dialect)
- [ ] Strategy-specific setup completed per extraction-strategies-reference.md
- [ ] Workflow YAML generated via migrate_data(mode="setup", ...) (or existing file reviewed at Step 2a)
- [ ] User saw workflow YAML and was offered optional field updates (Step 2a)
- [ ] User confirmed the final workflow YAML before run
- [ ] Partition-key findings resolved (or accepted) at Step 2a
- [ ] Target database and schema exist
- [ ] Iceberg prerequisites validated — if Redshift + `target_table_type=iceberg`
- [ ] migrate_data(mode="run") started
- [ ] Polled until job terminal and progress.output.isFinished (when progress present)
- [ ] Finished-but-incomplete anomaly checked (Step 5.C — do not report success if tables never preprocessed)
- [ ] Health monitoring run during poll when triggered (Step 5.B — stall/failure signals surfaced)
- [ ] Error-first data migration summary presented (Step 6 — Result + Workflow, Errors, Suggested fixes)
- [ ] Teardown offered when wave data work is done (Step 7)
```

Return control to the parent skill.

---

## Reference

- [Workflow Config Reference](./references/workflow-config-reference.md)
- [Extraction Strategies Reference](./references/extraction-strategies-reference.md)
- [Iceberg Setup Reference](./references/iceberg-setup-reference.md)
- [Troubleshooting Reference](./references/troubleshooting-reference.md)
- [Data Doctor reference](../../../data-infrastructure/references/data-doctor-reference.md)
- [Teardown (cost-saving suspend)](../../../data-infrastructure/teardown/SKILL.md)
