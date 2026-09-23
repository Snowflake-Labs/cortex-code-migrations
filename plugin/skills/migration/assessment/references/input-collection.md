# Assessment Input Collection

Read this file in full after scope confirmation and before dispatching any
sub-agent. Gather every applicable answer first. Sub-agents are non-interactive.

## Contents

- Data Lineage and Power BI inputs
- Waves and analysis depth
- Informatica target
- Discovery inputs
- Input snapshot

### 5.0 Data Lineage reporting-layer inputs

Ask only when Data Lineage is in scope whether the user wants to add or add
more reporting-layer files. The graph always runs from the registry; Power BI
`.pbit` files optionally enrich its Reports lane.

Inspect `<project_dir>/source/BI/PowerBI` first:

- Existing `.pbit`: report the count and ask whether to add more files/folders.
- None: ask for `.pbit` files or folders, or `no`.
- Any `.pbix`: explain that `.pbix` is a binary format the assessment
  **cannot** read. Ask for a Power BI template exported as
  `.pbit`. Never copy one in and never stage `.pbix`.

Accept files or directories; search directories recursively. Do not ask for a
report name, connection, database, registry path, CSV path, or output path.

When the user supplies paths, run:

```bash
uv run --project plugin/skills/migration/assessment \
  python plugin/skills/migration/assessment/data-lineage/scripts/stage_powerbi_inputs.py \
  --project-dir "<project_dir>" \
  --input "<path>" [--input "<path>" ...]
```

When the user says no but templates are already staged, run the helper without
`--input` to obtain the authoritative inventory.

Read `skipped[]` as well as `errors[]`:

- Report `.pbix` entries in `skipped[]` briefly.
- `"not-found"` or `"unreadable"` for a user-supplied path requires you to get a
  corrected path; do not silently continue.
- `errors[]` is never empty by accident. Every item requires resolution or
  explicit user agreement to omit
  that template. Do not proceed past it silently. Carry any omission into the
  final summary.
- `a different file already occupies both the preferred and the
  content-addressed destination name` requires you to rename the incoming file
  or remove the stale staged file.
- Incoming `[Errno 13]`, `[Errno 28]`, or similar means fix permissions or free
  space and rerun.
- An error reading a `.pbit` already under `source/BI/PowerBI` means it is
  missing from `pbit_files` and `pbit_count`. Fix its permissions, or delete
  and re-stage it. An already-staged template that errors is the easy one to
  miss because no newly supplied path failed.
- An error listing the staging directory invalidates the inventory; fix it
  before dispatch.
- A destination resolving outside the staging directory indicates a symlink
  escape. Do not work around it; the staging directory must be a real
  directory inside the project.

This helper is the only thing that copies Power BI inputs in this workflow.
Do not copy templates yourself. It never overwrites bytes that differ,
de-duplicates identical content, and gives collisions a deterministic
`<name>-<hash8>.pbit` name. Files already in the directory are inventoried,
never re-copied and never rewritten.

Record every returned `pbit_files[].path` as a project-relative path in
`data_lineage.staged_pbits`.

- `data_lineage.dispatch`: set `true` whenever Data Lineage is in scope, even
  when the list is empty, and dispatch `data-lineage`.
- When templates are staged, dispatch `data-lineage` first and alone, never in
  the same fan-out as another sub-skill. `scai assessment powerbi enrich`
  mutates the CUR; waves and object-exclusion patch those same units, so a
  same-turn fan-out is a lost-update race. Wait for Data Lineage to return,
  then dispatch the rest. With no templates, include `data-lineage` in the
  single-message fan-out: the child skips Power BI extraction and enrichment
  but still builds the graph from the registry.
- When the user excluded Data Lineage in Step 3, set
  `data_lineage.dispatch: false`, then synthesize:

```json
{"status":"skipped","output_json":null,"summary":"excluded Data Lineage in Step 3"}
```

### 5.1 Waves inputs

#### Waves

When Waves is in scope, ask these in order:

1. “The default wave size is 40–80 objects. Keep the defaults, or set custom
   min/max?” Record integer `partition_min_size` / `partition_max_size`.
2. “Any objects to push into the earliest waves? Provide patterns like
   `*Payroll*` or `dbo.Customer`, or say no.” Record a list of globs.
3. “Default is category-based (TABLE → VIEW → FUNCTIONS/PROCEDURES → ETL).
   Switch to dependency-based?” Record `category` or `dependency`.

### 5.2 Dynamic SQL review

When in scope ask once:

> Are you interested in Dynamic SQL code analysis? Each occurrence will be
> reviewed individually — pattern, complexity, migration considerations.

Map yes to `auto-review-all`, no to `generate-only`, and exclusion to `skip`.

### 5.3 ETL/SSIS review

When ETL CSVs are present and SSIS is in scope, always generate baseline JSON.
Ask once whether to add AI per-package classification, HTML summary, and effort:
yes → `auto-review-all`; no → `generate-only`; exclusion → `skip`.

Capture `etl_replatform_sources_path` from `migration_status` when available;
otherwise let the child auto-detect it.

### 5.3b Informatica PowerCenter target

When Informatica is in scope, ask exactly once and never default:

> Which conversion target for Informatica PowerCenter?
> 1. **dbt** — mappings become dbt models orchestrated by Snowflake Tasks
> 2. **scripting** — mappings become Snowflake Scripting procedures

Record `informatica.target` as `dbt` or `scripting`. Informatica always uses
`review_mode: auto-review-all`; do not ask the ETL analysis-depth question,
default to `generate-only`, or allow `skip` after Informatica is in scope.

### 5.4–5.6 No-input analyses

- Object exclusion needs no prompt.
- Effort estimate needs no prompt and supports SQL Server/Redshift only.
- Anti-patterns needs no prompt and is SQL Server-only.
- For unsupported dialects, do not dispatch; synthesize a skipped result.

### 5.7 Discovery (SQL Server and Teradata)

Discovery is in scope only for SQL Server or Teradata. For every other dialect,
ask nothing and synthesize a skipped result. On either supported dialect,
always ask; never search for files or answer for the user.

First explain what the dialect's Discovery report adds:

- **SQL Server:** Extended Events volume, duration mix, statement types,
  applications/users, long-running executions, and errors. It is not derived
  from converted code.
- **Teradata:** DBQL request volume, duration mix and percentiles, daily
  timeline, statement types, applications/users, touched databases,
  long-running requests, and errors versus aborts. Nothing is installed on
  Teradata and SnowConvert never connects to it.

Then ask the matching question, retaining its disclaimer and all choices.

**SQL Server:**

> Disclaimer: captured Extended Events data, including statement text, is used
> for reporting only. Statement text is read only to classify query type; it
> is not stored in the artifact or shown in the report.
>
> How do you want to handle Discovery?
> 1. Skip for this run
> 2. I have the `.xel`
> 3. Give me the SQL, I'll provide the files later

**Teradata:**

> Disclaimer: the metrics export is used for reporting only. No SQL text is
> read or stored—the report shows counts, durations, and names from the query
> log. Send only the metrics export; statement text is not accepted.
>
> How do you want to handle Discovery?
> 1. Skip for this run
> 2. I have the CSV export
> 3. Give me the SQL, I'll provide the file later

Map to `skip`, `have_extract`, or `later`.

- `skip`: empty paths; no SQL or collection steps.
- `have_extract`: collect absolute paths. For SQL Server, accept `.xel` files
  (a folder/glob only when it resolves to rollover files). For Teradata,
  accept uncompressed `.csv` metrics exports and reject statement text. Never
  copy, rename, or move inputs under the project. Empty paths are invalid; ask
  again or let the user choose skip/later.
- `later`: empty paths and do not dispatch. In the same turn, show the
  dialect-specific guidance and SQL below. The assessment continues now.

#### 5.7a `later` on SQL Server

Do not ask for a database name or number of days. Show this review guidance,
then paste
`workload-insights/references/create-extended-events-session.sql` unchanged:

> **Review the capture before running it.** SQL Server keeps no history of past
> queries, so nothing can be reported until a capture is running. This starter
> script creates a **SQL Server Extended Events** session for one database, but
> leaves it stopped. While it runs, it records each completed user statement
> and stored-procedure call that meets the duration filter — duration, CPU,
> reads, writes, rows, application, and user — plus errors at severity 11 or
> higher. Statement text is used only to classify the query type. Review every
> value, replace `YourDatabase` in all three predicates, and uncomment
> `STATE = START` only when you are ready to begin. The three events and their
> `ACTION` lists must stay or the report loses columns.
>
> **A DBA should own this capture.** Have a DBA set the values, confirm it is
> safe to run on this instance, and start it. Watch the server once it is
> running — CPU, disk space, and waits — and stop the session if anything
> degrades.
>
> This capture uses CPU and disk. It is reasonable on a typical host with the
> defaults below, but it is not free and can compete with the database if the
> settings are too aggressive. Do not switch `EVENT_RETENTION_MODE` to
> `NO_EVENT_LOSS` — that can stall user queries.
>
> **You can change these to fit the capture:**
>
> - **Session name** — default is `WorkloadReport_XE`. Change it if another
>   session already uses that name; keep the same name in create/start/stop.
> - **Duration threshold** — default is 0.5 seconds
>   (`[duration] >= 500000`, microseconds). Raise it to write less; lowering it
>   captures more and costs more CPU and disk.
> - **Filters** — default is one database, no system work, no SSMS/telemetry,
>   and errors at severity 11 or higher. Removing the database predicate traces
>   the whole instance and is usually too wide.
>
> **Set these carefully — they affect the database:**
>
> - **`filename`** — replace `<dedicated volume>` with a path on a volume that
>   has space and is not a data or log disk.
> - **`max_file_size`** (200 MB) and **`max_rollover_files`** (5) — together
>   cap disk at 1 GB. Confirm more than that is free before starting.
> - **`MAX_MEMORY`** (8,192 KB) — how much RAM the session may hold.
> - **`MAX_DISPATCH_LATENCY`** (30 seconds) — how soon events flush to disk.
> - **`STARTUP_STATE`** (OFF) — the session stays stopped after service restart.
> - **`MEMORY_PARTITION_MODE`** — unset for a typical host. On a busy many-core
>   server, consider `PER_CPU` and raise `MAX_MEMORY` to 16–32 MB first.

After the SQL, tell the user:

- `CREATE` leaves the session stopped; start it only when ready.
- Leave it under representative traffic. Around 30 days is useful, but a
  shorter window works.
- Copy every rollover `.xel`, then stop the session. Leaving it running
  continues to use CPU and disk.
- Re-run assessment, choose **I have the `.xel`**, and provide all files.
- This assessment continues now and does not wait for the capture.

Use skipped summary `capture SQL provided; re-run assessment with the .xel
files`. Do not model the capture as pending work or mention it again at
completion.

#### 5.7b `later` on Teradata

Do not ask for a database name, date range, or number of days. Show the three
steps below, then paste
`workload-insights/references/teradata-probe.sql` and
`workload-insights/references/teradata-fallback.sql` unchanged. Do not
summarize the SQL. This copy is shared with the HTML/dashboard empty state.

The SQL is delivered now during input gathering—never defer it, add it as a
later task, or mention it again after the normal skipped result.

> Disclaimer: the metrics file is used for reporting only. No SQL text is read
> or stored—the report shows counts, durations, and names from the query log.
>
> **This reads history DBQL already stored.** Nothing is installed on Teradata,
> no logging setting is changed, and SnowConvert never connects to it.
>
> **1. Find the query log you can read.** Run the probe statements one at a
> time, top to bottom. Keep the first that succeeds and reports rows.
>
> **2. Export the request metrics.** Point the `FROM` at the table kept in
> step 1 and replace both `YYYY-MM-DD HH:MM:SS` bounds with the window to
> cover—about 30 days gives a representative picture. **Have a DBA review
> this before you run it:** reading the query log uses CPU, I/O, and spool.
> Run it off-peak and start with a shorter window if the log is large. A DBA
> can use FastExport or TPT Export for large results; this moves rows faster
> but does not make the query cheaper and consumes a load-utility slot. Export
> CSV with column headers.
>
> **3. Re-run assessment** with
> `scai assessment workload-insights --input /path/to/querylogs.csv`.
> Repeat `--input` to merge split exports.

After the SQL, tell the user to re-run assessment later, choose **I have the
CSV export**, and provide its path. The current assessment does not wait.

Use skipped summary `probe and export SQL provided; re-run assessment with the
metrics file`. Do not model the export as pending work.

### 5.8 Snapshot the inputs

Keep this in working context only; never write it to disk:

```yaml
assessment_inputs:
  project_dir: <abs>
  output_dir_assessment: <project_dir>/assessment
  waves:
    partition_min_size: <int>
    partition_max_size: <int>
    prioritization_globs: [<glob>, ...]
    wave_ordering: category | dependency
  exclusion: {}
  effort_estimate: {}
  anti_patterns: {}
  workload_insights:
    mode: have_extract | skip | later
    input_paths: [<abs .xel path (SQL Server) or metrics CSV path (Teradata)>, ...]
  dynamic_sql:
    review_mode: generate-only | auto-review-all | skip
    output_dir: <project_dir>/assessment/json
  etl:
    review_mode: generate-only | auto-review-all | skip
    output_dir: <project_dir>/assessment/ssis
    etl_replatform_sources_path: <abs or empty>
  informatica:
    target: dbt | scripting
    review_mode: auto-review-all
  data_lineage:
    dispatch: true | false
    staged_pbits: [source/BI/PowerBI/<name>.pbit, ...]
    manifest_path: <project_dir>/artifacts/assessment/powerbi/manifest.json
```

After this snapshot, do not prompt again until failed sub-skills are surfaced.
