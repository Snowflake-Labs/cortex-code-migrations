---
name: data-migration-setup
description: Setup, run, and report on cloud data migration — workflow YAML, migrate_data run, background Monitor, and end-of-run summary for the user.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# Data Migration Setup

One-time configuration for migrating data from a source database into Snowflake via the **scai CLI**, plus **run → monitor → report** after `migrate_data(mode="run")`.

> **Always use the official tooling.** Run data migration through `migrate_data(mode="setup")` / `migrate_data(mode="run")` (backed by `scai data migrate`). **Never** suggest ad-hoc scripts to extract, copy, or load data outside the DMVF task pipeline.

> **Supported sources**: SQL Server, Azure Synapse, Redshift, Oracle, Teradata, PostgreSQL, BigQuery, DB2
> **Supported targets**: Native Snowflake tables (default), or a Snowflake-managed **Iceberg** table for a
> **fully relational** source object only — see [Extraction strategies reference](./references/extraction-strategies-reference.md#iceberg-target-relational-sources-only) and Step 3a.

> **Run-only entry:** routed here only to execute `migrateData` with an existing workflow YAML, skip Steps 1–2, complete **Step 2a** for the existing `workflow_path`, then **Steps 4–6**, and return the result to the parent. Per-object subagents do not manage shared infrastructure or teardown.

## Prerequisite

Load `../../../data-infrastructure/SKILL.md` first (shared prerequisites, compute pool, worker config), then return here.

---

## Step 1: Choose Migration Approach

### 1.A — Pick Tables to Migrate (`where`)

`where` is a **registry filter selecting the workflow's tables** (`scai code where` lists the syntax). For named tables **always** use an exact filter — `source.canonicalName IN ('dbo.CUSTOMERS', 'dbo.ORDERS')` — never `ILIKE '%…%'`, which pulls in prefix siblings such as a `…_SWTCH` staging table.

Use the tables the parent skill or wave already identified (a batch's `where` only if it is already exact); otherwise ask the user (a schema, specific tables, or all in scope — omit `where`).

After generating the YAML, **read its `tables:` list** and confirm the count and names with the user; if it has more tables than requested, fix the `where` (with `force_regenerate=true`): SnowConvert does not auto-add SWITCH siblings.

### 1.B — Migration strategy (captured at setup)

The migration type, extraction mechanism and target table type are chosen **once during setup** by the `dataStrategy` task ([`setup/data-strategy/SKILL.md`](../../../setup/data-strategy/SKILL.md)) and are **already set**: do not re-ask them. A change, or a strategy that is unexpectedly unset, goes back to the main agent, which owns setup. Strategy prerequisites: [Extraction strategies reference](./references/extraction-strategies-reference.md).

A bounded smoke test the customer asks for is `preflight: true` at Step 2a ([preflight](../../../data-infrastructure/references/advanced-operations-reference.md#preflight-workflows-bounded-migration-dry-run)). Native targets must already be deployed: preflight copies their structure. It is not Preliminary sampling, `scai data doctor`, or full validation.

### 1.C — Confirm

Confirm tables (`where`), type, sync, extraction and target with the user in a short block (on a small default run, the Step 2a one-line summary is the confirmation). For a server/cloud extraction method, collect the fully-qualified Snowflake external stage now unless the workflow already records one; if it is not ready, return to the ladder and choose the next method.

> **Before run, confirm the unload stage is on the external volume.** `DESC STAGE` URL is where the
> parquets land. `DESC EXTERNAL VOLUME` `STORAGE_BASE_URL` must be that same location, or a parent of it.
> Otherwise the load lists nothing and the partition completes with 0 rows. Steps: [object-store path restrictions](../../../data-infrastructure/references/object-store-path-restrictions.md).

---

## Step 2: Generate the Workflow YAML

```
migrate_data(
  mode="setup",
  where=<table-selection filter from 1.A, or omit to include all tables in scope>,
  migration_type="preliminary" | "incremental" | "full",
  sync_strategy="none" | "full-replace" | "checksum" | "watermark",
  extraction_strategy="odbc" | "bcp" | "pg_copy" | "tpt" | "unload" |
                      "write_nos" | "dbms_cloud" | "cet_as" | "export_data" |
                      "cloud_direct",   # "regular" = legacy "leave the worker as-is"
  external_stage="<DB.SCHEMA.STAGE>",  # server/cloud methods, first application only
  target_table_type="native" | "iceberg",  # iceberg: relational sources only (never an Iceberg source)
)
```

The same `where` maps to the same `artifacts/data_migration/workflows/<hash>.yaml`, and **re-running setup reuses it** (edits survive) unless `force_regenerate=true` (old file kept as `.yaml.bak`). Setup fills a missing `source.databaseName` / `target.databaseName`. Change the extraction strategy with `extraction_strategy=`, not by editing the YAML.

> **Duplicate data on re-run:** `full`, `preliminary`, and `sync_strategy=none` reload every row, so a re-run **appends duplicates**. `full-replace` deletes the target partition first; `watermark` / `checksum` sync by row ([SynchronizationStrategy](./references/workflow-config-reference.md#synchronizationstrategy)). Walkers use `full-replace` (Iceberg stays `none`: the orchestrator rejects `full-replace`, and a second `none` run fails while the table exists). Interactively, `run` refuses native `none` with no recorded choice (`reason: "sync_strategy_not_chosen"`): ask `full-replace` or `none`, say what each does to existing rows, and record it with `migrate_data(mode="setup", where=..., sync_strategy=...)`. Never choose for them.

> **Clearing a bad load.** Compare target and source row counts first. A target **this project loaded itself** was created by this project's `deploy` and loaded only by its `migrate_data` runs.
>
> - **Autonomous mode** (`subagent_mode`): repair it without asking. The walker reopens `migrateData` through `task_invalidator`; the orchestrator `reset`s a parked object and later-sends the walker ([autonomous](../../autonomous/SKILL.md), 2e). The re-run replaces the rows (`full-replace` deletes them; Iceberg on `none` must be cleared first, [RUN.md](./RUN.md)), checks the count, and `note`s the repair. Never hand the user a truncate or a reload of such a table.
> - **Interactive:** propose the reload and run it after the user agrees. Native: `TRUNCATE`. Iceberg: `DROP ICEBERG TABLE`, because `none` fails while the table exists ([RUN.md](./RUN.md)).
>
> Any other target may hold expected rows: **never** `TRUNCATE` or bulk-`DELETE` it without explicit user confirmation, in either mode (autonomous: escalate). Prefer `full-replace` or incremental sync afterward.

### Step 2a: Display, optional edits, confirm

1. Read `workflow_path`.
2. **Display** the workflow: the full YAML for a small or medium file; for a large one the path, `tables:` count, `defaultTableConfiguration` and table names, with the rest on request. Say whether setup reused the file (`workflow_reused`).
3. **Summarize:** table count, type, sync, extraction, target, and any `partition_key_findings`, `doctor_findings` and `computed_column_findings`. Resolve `doctor_findings.failures` with the user before run (`warnings` are advisory; `doctor_note` means the doctor could not run). **Incremental with no `sync_strategy`:** recommend one [per table](./references/workflow-config-reference.md#recommending-a-strategy-per-table) and confirm each.
4. **Small default run: do not ask.** Skip the question in step 5 when **both** hold:
   - the user said to go with the defaults (or just to run it), **or** `.scai/config/plugin.yml` records `data_orchestrator_placement: direct` (a small SQL Server source);
   - there are no `doctor_findings.failures`, no `Partition prune:` finding, no sync strategy still to choose, no unapplied user-requested edit, and no agent-only blocker (step 8) that needs a value from the user.

   Apply the step 8 edits, show one line in place of the YAML (`Migrating <N> tables (<type>, <sync>, <extraction>, <target>) — <workflow_path>`, plus any step 8 edits and doctor warnings), and continue to Step 3 without waiting for a confirmation. The user can still ask for changes at any time.
5. Otherwise ask verbatim:

> Here is the migration workflow at `<workflow_path>`.
>
> **Would you like to update any fields before we run?**
> 1. **Proceed**
> 2. **Change something** (tell me which table, section, or field names)

6. **If the user chooses "Change something":** apply the edits per [Common edit scenarios](./references/workflow-config-reference.md#common-edit-scenarios) and `edit_hints`, re-display what changed, and repeat step 5 until the user chooses **Proceed**.
7. **If the user chooses "Proceed":** skip discretionary edits unless agent-only blockers remain (step 8). A `partition_key_findings` row whose label starts with `Partition prune:` is not an agent-only edit: show the physical column and the leading `columnNamesToPartitionBy` entry, and wait for the user to confirm before changing the YAML or calling `migrate_data(mode="run")`. Adding workers does not fix a leading column the source cannot prune.
8. **Agent-only blockers** — apply without re-prompting unless you need a value from the user:
   - Resolve `partition_key_findings` other than a `Partition prune:` row (confirm that in step 7) and `columnNamesToPartitionBy` per `edit_hints`. An omitted key is allowed (the orchestrator infers one, or extracts a small table whole); a table that fails naming `columnNamesToPartitionBy` needs a key, never `[]`. Prefer an explicit key for large tables, by dialect as in [Partition sizing and key selection](./references/workflow-config-reference.md#partition-sizing-and-key-selection); for low-cardinality prune columns, a [composite key](./references/workflow-config-reference.md#composite-partition-keys).

     **Show the table's columns first**, in the message before you write `columnNamesToPartitionBy`: the pick, why it beats the others, and the columns (from DDL or `query_source`; wide tables: candidates only, the rest on request), per [Showing the columns behind a key](./references/workflow-config-reference.md#showing-the-columns-behind-a-key).
   - Resolve `computed_column_findings` (SQL Server COMPUTED columns): drop each listed column from the table's column list / `columnNameMappings`; the target column is redefined or recomputed post-migration.
   - **Preliminary type:** add `whereClauseCriteria: "<row predicate>"` per table or in `defaultTableConfiguration` when missing.
   - Required **extraction strategy** fields (`extraction.strategy`, `externalStage`, worker TOML cross-refs for `unload` / `write_nos` / `dbms_cloud` / `tpt`).
   - **Iceberg target:** ask the user for every `<PLACEHOLDER>` setup left in `icebergConfig` ([IcebergConfig](./references/workflow-config-reference.md#icebergconfig)); `run` refuses the workflow until none is left.
   - Tell the user what you changed and why before confirming.
9. Unless step 4 applies, get **explicit confirmation** to run with the final workflow, then continue to Step 3.

#### Never write `columnNamesToPartitionBy: []`

An explicit `[]` turns partitioning off: the whole table moves as one long serial unit, however large. Write it only when the user **explicitly** asks for a single partition after hearing that cost, and never in `defaultTableConfiguration` (every table without its own key) unless they asked for exactly that.

---

## Step 2b: Doctor gate (ran at infrastructure bring-up)

`scai data doctor` runs in `data_infrastructure(mode="up")`, not on `run`. Fix `doctor_failures` from `up` before dispatching (`skip_doctor=true` only once the user explicitly accepts them).

## Step 3: Create Target Database

Run `CREATE DATABASE IF NOT EXISTS <target_db>;` and `CREATE SCHEMA IF NOT EXISTS <target_db>.<target_schema>;`.

## Step 3a: Iceberg targets only

Run both [Iceberg target gates](./references/iceberg-target-gates.md) before Step 4: a fully relational source (else **do not continue**), and `check_iceberg_targets` clear (never auto-drop a table).

---

## Step 4: Run migration

```
migrate_data(mode="run", workflow_path="<path from setup>")
```

Returns `job_id` at once: the run is **dispatched** to the shared orchestrator + worker (on a `direct` project it is synchronous and its `status` is the result: skip Step 5; see [RUN.md](./RUN.md)). An infrastructure remediation from `run` goes back to the main agent; a per-object task never starts, repairs or reconfigures it.

The `data_infrastructure(mode="up")` response carries a `cost_reminder`: **relay the reminder to the user verbatim**.

---

## Step 5: Wait for completion with Monitor

Start the **Monitor** tool (`persistent: true`) with `monitor.watch_command` from the run response, verbatim, from the project root; its cursor prevents replays and gaps. Its `terminal` event carries the authoritative result under `detail.completion`.

**Arming Monitor ends your turn.** Say one plain line (you'll report back when
the job finishes or hits trouble) and stop: the event wakes you. Between arming
Monitor and its event, run **zero** Bash commands.

**Never wait with Bash** — no `sleep`, shell polling loop, `/loop` or cron.
If the watch is lost, re-arm with `job_status(job_id, monitor=true)`. Short
sleeps (1–3s) after killing a process are the only allowed exception, and
that ceiling holds whatever the reason. A refused `scai connection test` is
retried immediately, not after a pause — retry once and report what it said.
Reading `.scai/monitor/relay.jsonl` is not a reason to sleep either: the
relay's event is what wakes you.

**Never declare the job done from a target `SELECT` / `COUNT(*)` or the CSVs
under `reports/data-migration/`**: neither carries job state. If you skipped Monitor, arm it now.

### 5.A — On a Monitor event

- **`terminal`:** read `detail.completion` (`verdict`, `terminal`, `failed`, `summary`, `report_row_counts`, optional `failures` / `stale_reports`); do not call `job_status` merely to confirm it. Step 5.C if `failed`, then **Step 6**.
- **`failure` / `relay_error`:** warnings — surface them and keep watching.
- **`stalled`:** see 5.B. A healthy run is silent; `job_status(job_id=<monitor.job_id>, details=true)` answers a user who asks.

**`job_status` reads `stalled` after a session restart:** see [the restart steps](./references/background-monitoring.md#stalled-after-a-session-restart).

### 5.B — Health monitoring (while waiting)

On a `stalled` or `failure` event, call `job_status(job_id, details=true)` and `data_infrastructure(mode="status")` once each and follow [Health monitoring](./references/background-monitoring.md#health-monitoring): it maps `detail.stall_reason` to a severity and an action. Never answer a stall with "still running" alone, do **not** auto-cancel or re-dispatch, and keep watching: only a `terminal` event ends monitoring.

### 5.C — Finished workflow with incomplete tables (anomaly)

On a failed completion, call `job_status(job_id, details=true)` once. A finished workflow (`isFinished`) with `preprocessedTables < totalTables` or `aggregatedCounts.failedPartitions > 0` is **not a success**.

1. Messages are in `details.reports.files.progress` (`ExampleErrorMessage`) and `.errors` (`LastErrorMessage`, `TaskName`); `details.progress.output` has none.
2. Unpreprocessed tables go under **Preprocessing**, failed partitions under **Load** or **Extraction** by task name.
3. Missing errors or stuck tasks: [Workflow finished but tables incomplete](./references/troubleshooting-reference.md#workflow-finished-but-tables-incomplete). A worker/orchestrator stall is one hypothesis, not the only one.
4. Reproduce the failing step against the source before naming a cause: run the task's `statement` from the worker's `data_exchange_agent.log` with `query_source`, on the same connection. An empty result shows only that the query found nothing: check the statement itself, the database it reads and the connection's permissions before naming a cause — see [No schema found](./references/troubleshooting-reference.md#no-schema-found-at-schema--stage-file-not-yet-visible). Confirm a version theory with a read-only check before acting on it. Never run `scai data orchestrator update`, or recreate or restart the shared service or worker, to test a theory: they serve every project on the account.
5. Do **not** suggest re-run until prerequisites are identified. An unchanged re-run is not a diagnostic: it fails the same way.

If the job **failed**, do not re-run it or change Snowflake with `sql_execute`: `migration_status(mode="next_task", object_ids=["<id>"])` sends a failed load (`error=sql`) to `applyRules` → `fixCode`. Fix the `snowflake/` file and **deploy**; a live `ALTER` / `DROP` / `CREATE` outside it is overwritten, and a `note` (a judgment already made in the file, whose inverse you can name) is no substitute for the fix.

---

## Step 6: Report — data migration summary

**Do not skip.** Present an **error-first** summary in chat, headed only by `Result` (from `detail.completion`) and `Workflow`; no per-table grid unless the user asks.

**All succeeded** — no `### Errors` section, then return control to the parent skill:

```markdown
## Data migration complete

**Result:** Success — <N>/<N> tables loaded
**Workflow:** `<workflowName>`

No errors.
```

**Failures:** load [Migration report reference](./references/migration-report-reference.md) for the error categories (Preprocessing → Extraction → Load → Infrastructure), suggested fixes, the failure template and the next-step question. Never jump to a re-run.

---

## Step 7: Offer to tear down infrastructure (cost saving)

When the wave's data work is done, offer once (default **Yes**):

> Tear down the shared data infrastructure to stop idle cost? Bring it back for the next wave with
> `data_infrastructure(mode="up")` (dispatch does not auto-resume).
>
> 1. **Yes (default)** — call `data_infrastructure(mode="down")`.
> 2. **No, keep running** — next batch soon; avoids the ~60s SPCS warm-up.

On **Yes** (or no response), call `data_infrastructure(mode="down")` and relay its actions. Load `../../../data-infrastructure/teardown/SKILL.md` **only** for a cross-machine `TASK_QUEUE` check, a process started outside MCP, or a `partial` SPCS privilege failure.

---

Return control to the parent skill.

## Reference

[Workflow config](./references/workflow-config-reference.md), [extraction strategies](./references/extraction-strategies-reference.md), [Iceberg setup](./references/iceberg-setup-reference.md), [background monitoring](./references/background-monitoring.md), [task model](./references/task-model-reference.md), [troubleshooting](./references/troubleshooting-reference.md), [advanced operations](../../../data-infrastructure/references/advanced-operations-reference.md), [data doctor](../../../data-infrastructure/references/data-doctor-reference.md).
