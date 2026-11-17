# Assessment Input Collection

Read this file in full after scope confirmation and before dispatching any
sub-agent. Gather every applicable answer first. Sub-agents are non-interactive.

## Contents

- Data Lineage and Power BI inputs
- Business use cases and analysis depth
- Conversion issues
- Informatica target
- Discovery inputs
- Input snapshot

### 5.0 Data Lineage reporting-layer inputs

Data Lineage always runs from the registry. Power BI `.pbit` files optionally
enrich its Reports lane. Do not ask whether to add more: registration already
collected that intent and staged the files.

Inspect `<project_dir>/source/BI/PowerBI` first:

- Existing `.pbit`: inventory it with the helper below.
- None: continue with registry-only Data Lineage.
- Any `.pbix`: explain in the final input summary that `.pbix` is unsupported
  and was not staged. Never copy or stage `.pbix`.

Do not ask for a report name, connection, database, registry path, CSV path,
Power BI path, or output path.

Run:

```bash
uv run --project plugin/skills/migration/assessment \
  python plugin/skills/migration/assessment/data-lineage/scripts/stage_powerbi_inputs.py \
  --project-dir "<project_dir>"
```

Read `skipped[]` as well as `errors[]`:

- Report `.pbix` entries in `skipped[]` briefly.
- `errors[]` is never empty by accident. Every item requires resolution or
  explicit user agreement to omit
  that template. Do not proceed past it silently. Carry any omission into the
  final summary.
- `a different file already occupies both the preferred and the
  content-addressed destination name` requires you to rename the incoming file
  or remove the stale staged file.
- An error reading a `.pbit` already under `source/BI/PowerBI` means it is
  missing from `pbit_files` and `pbit_count`. Fix its permissions, or delete
  and re-stage it. An already-staged template that errors is the easy one to
  miss because no newly supplied path failed.
- An error listing the staging directory invalidates the inventory; fix it
  before dispatch.
- A destination resolving outside the staging directory indicates a symlink
  escape. Do not work around it; the staging directory must be a real
  directory inside the project.

This helper only inventories files registration already staged. Do not copy
templates during assessment.

Record every returned `pbit_files[].path` as a project-relative path in
`data_lineage.staged_pbits`.

- `data_lineage.dispatch`: always set `true`, even when the list is empty, and
  dispatch `data-lineage`.
- When templates are staged, dispatch `data-lineage` first and alone, never in
  the same fan-out as another sub-skill. `scai assessment powerbi enrich`
  mutates the CUR; object-exclusion and wave planning patch those same units, so a
  same-turn fan-out is a lost-update race. Wait for Data Lineage to return,
  then dispatch the rest. With no templates, include `data-lineage` in the
  single-message fan-out: the child skips Power BI extraction and enrichment
  but still builds the graph from the registry.
- Always set `data_lineage.dispatch: true`.

### 5.1 Business use cases

Waves need nothing from the user. Business use cases always run, after the other analyses.
`scai assessment waves` assigns every deployable object a wave number and rank
in category packs of about 100–200 objects. Use cases stay a catalog until a
later change rewrites waves for a selected use case. **Do not ask for a wave size, prioritization
patterns or a wave ordering.** An `assessment_options` value from an older
session may still carry `custom_wave_size`, `prioritize` or
`dependency_order`; ignore those tokens.

The converted code alone produces a catalog. Three optional inputs make it more
complete by showing what runs and what is read, so use cases are confirmed
instead of proposed from structure: the scheduler that runs the ETL, SQL Server
Agent jobs, and query logs. Ask each question that applies once, with the other
input questions. They are optional: never block the assessment on them, never
search for files, and never answer for the user. Skipping, or choosing later, is
not a failure: the report lists the input as not provided and says what it would
add.

For every file the user provides, record its absolute path and nothing else.
Never copy, rename or move it under the project, and do not read it here: the
business use cases agent reads it in place. Do not repeat these questions
at completion; the results summary already names what was and was not provided.

#### 5.1a Scheduler (when Informatica is in scope)

Ask only when Informatica is in scope (5.3b). Ask even if SSIS is also in scope.

> Disclaimer: the export is read only to see which workflows run, how often and
> in what order. Commands, passwords and connection strings are not copied into
> any result.
>
> A scheduler export shows which Informatica workflows really run, so use cases
> can be confirmed against live jobs instead of proposed from structure. Do you
> have the scheduler that runs them (Control-M job definitions, a crontab,
> Autosys, Airflow DAGs)?
> 1. Skip for this run
> 2. I have the files
> 3. Tell me what to ask for, I'll provide them later

Map to `skip`, `have_files` or `later`.

- `have_files`: collect absolute paths of the export files or a folder of them.
  Empty paths are invalid; ask again or let the user choose skip/later.
- `later`: in the same turn say: "Ask the scheduler's owner for the job
  definitions of the folders that run these workflows, as XML or JSON, with each
  job's name, what it runs, its schedule, the jobs it waits for, and whether it
  is held or disabled. Remove passwords and connection strings first; the
  assessment does not need them. Re-run assessment and choose **I have the
  files**." The assessment continues now and does not wait.

#### 5.1b SQL Server Agent jobs (when SSIS is in scope)

Ask only when SSIS is in scope (5.3a).

> Disclaimer: the export is read only to see which packages run and when.
> Commands, passwords and connection strings are not copied into any result.
>
> SQL Server Agent jobs show which SSIS packages run, on what schedule, and
> whether the job is enabled, so use cases can be confirmed against live jobs.
> How do you want to handle them?
> 1. Skip for this run
> 2. I have the job scripts or the query result
> 3. Give me the query, I'll provide the file later

- `have_files`: collect absolute paths of job scripts (`.sql` from SSMS, Script
  Job as CREATE) or the CSV from the query.
- `later`: paste `business-use-cases/references/sql-agent-jobs.sql` unchanged,
  then say: "Have a DBA review and run it; it only reads `msdb`. Export the
  result as CSV with headers and blank any `command` value that holds a secret.
  Re-run assessment and choose **I have the job scripts or the query result**."
  The assessment continues now and does not wait.

#### 5.1c Query logs (every dialect)

Ask for every dialect.

> Disclaimer: the summary is used to see which objects are read. No statement
> text is needed, and none is stored.
>
> Query logs show which tables and views are still read, by how many users and
> when last, the strongest sign that an outcome is real and still used. The full
> log is not needed: one row per object is enough, with its name and any of
> reads, distinct users and last access. Do you have an object usage summary?
> 1. Skip for this run
> 2. I have the file
> 3. Tell me where to get it, I'll provide it later

The Discovery exports (5.7) are not a usage summary: they hold no object names.
Do not offer them here.

- `have_files`: collect absolute paths of the summary (CSV or similar). Reject a
  raw log that is statement text only; ask for the aggregate instead.
- `later`: in the same turn say: "The source depends on the database: for
  Teradata, the DBQL object table aggregated by object; for SQL Server, index
  usage statistics (they reset when the instance restarts) or an Extended Events
  capture summarized by object; for Redshift, scan history aggregated by table.
  Have a DBA run it off-peak and export aggregates only: no statement text and
  no user names, only a count of users. Re-run assessment and choose **I have the
  file**." The assessment continues now and does not wait.

### 5.2 Dynamic SQL review

Use `auto-review-all` when `assessment_options` contains `deep_dynamic_sql`;
otherwise use `generate-only`. Do not ask again.

### 5.2b Conversion issues

Set `run: true` when `assessment_conversion_issues` is `yes`; otherwise
`run: false`. Do not ask again: the assessment card (in AIM, its second
question; on the CLI, the Step 3 scope call) already asked it. Do not run it
because it appeared in the scope list.

Do not dispatch when `run` is false; synthesize a skipped result. A yes still requires the child to research every summary row and rerun with `--updates` before the report is generated. Do not ask the user to write the problem or the fix.

### 5.3 ETL/SSIS review

A project has one ETL platform: SSIS when its ETL sources are `.dtsx`
packages, Informatica PowerCenter when they are PowerCenter `.xml` exports.
Collect inputs for that platform only; the assessment runs one
`scai assessment etl generate` for it.

For SSIS, always generate baseline JSON. Use
`auto-review-all` when `assessment_options` contains `ssis`; otherwise use
`generate-only`. Do not ask again.

Leave `etl_replatform_sources_path` empty unless the user named the ETL source
directory (SSIS, Informatica, or any other ETL platform); the child auto-detects
`<project_dir>/source/_etl/`.

### 5.3a SSIS target

When SSIS (`.dtsx`) is in scope, first look for a target the project already recorded: `etl_ssis_target` restored by `configure` (which also derives `scripting` when project.yml's `etl_scripting_platforms` lists `ssis`). If one exists, reuse it, tell the user which target the assessment will frame, and do not ask, so a re-assessment never contradicts an earlier conversion. Otherwise ask exactly once and never default:

> Which conversion target for SSIS?
> 1. **dbt** — data flows become dbt models orchestrated by Snowflake Tasks
> 2. **scripting** — data flows become Snowflake Scripting procedures, stabilized before deploy

Record `ssis.target` as `dbt` or `scripting`. Pass it to the SSIS child as `ssis_target`. The review-mode rule in 5.3 is unchanged.

### 5.3b Informatica PowerCenter target

When Informatica is in scope, first look for a target the project already recorded: `etl_informatica_target` restored by `configure`. If one exists, reuse it, tell the user which target the assessment will frame, and do not ask, so a re-assessment never contradicts an earlier one. Otherwise ask exactly once and never default:

> Which conversion target for Informatica PowerCenter?
> 1. **dbt** — mappings become dbt models orchestrated by Snowflake Tasks
> 2. **scripting** — mappings become Snowflake Scripting procedures

Record `informatica.target` as `dbt` or `scripting`. When you asked for it, call `configure(etl_informatica_target=<target>)` at once, because `scai assessment etl generate` reads the target from `.scai/config/plugin.yml` and uses `dbt` without it. Then read `etl_informatica_target` from `<project_dir>/.scai/config/plugin.yml`: a session whose `subagent_mode` latch makes `configure` attach-only reports it not applied and leaves it unwritten. If the file does not record the chosen target, do not dispatch the Informatica children. Fail the Informatica row with `error: "Informatica target not recorded: plugin.yml has <stored or none>, expected <target>"`, and tell the user how to record it: end the subagent session with `configure(subagent_mode=false)` (this takes the project out of autonomous mode, and is allowed only when no walkers are running and no claims are open), then call `configure(etl_informatica_target=<target>)`. Pass the target to every Informatica child as `informatica_target`. Informatica always reviews every workflow
(`review_mode: auto-review-all`); do not ask the ETL analysis-depth question,
default to `generate-only`, or allow `skip` after Informatica is in scope.

### 5.4–5.6 No-input analyses

- Object exclusion needs no prompt.
- Effort estimate needs no prompt and supports the dialects
  `effort-estimate/SKILL.md` lists: SQL Server, Redshift, Teradata and Oracle.
- Anti-patterns needs no prompt and supports SQL Server, Redshift, Oracle, and Teradata.
- For unsupported dialects, do not dispatch; synthesize a skipped result.

### 5.7 Discovery (SQL Server, Teradata, and Redshift)

Discovery is in scope only when `assessment_options` contains `discovery` and
the dialect is SQL Server, Teradata, or Redshift. Otherwise ask nothing and
synthesize a skipped result. When selected, ask once; never search for files
or answer for the user.

First explain what the dialect's Discovery report adds:

- **SQL Server:** Extended Events volume, duration mix, statement types,
  applications/users, long-running executions, and errors. It is not derived
  from converted code.
- **Teradata:** DBQL request volume, duration mix and percentiles, daily
  timeline, statement types, applications/users, touched databases,
  long-running requests, and errors versus aborts. Nothing is installed on
  Teradata and nothing connects to it.
- **Redshift:** `SYS_QUERY_HISTORY` request volume, duration mix and
  percentiles, daily timeline, statement types, databases and users,
  long-running requests, and outcomes. Redshift has no application dimension.

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

**Redshift:**

> Disclaimer: the metrics export is used for reporting only. It contains
> query metadata, not SQL text or error messages.
>
> How do you want to handle Discovery?
> 1. Skip for this run
> 2. I have the CSV export
> 3. Give me the SQL, I'll provide the file later

Map to `skip`, `have_extract`, or `later`.

- `skip`: empty paths; no SQL or collection steps.
- `have_extract`: collect absolute paths. For SQL Server, accept `.xel` files
  (a folder/glob only when it resolves to rollover files). For Teradata,
  accept uncompressed `.csv` metrics exports and reject statement text. For
  Redshift, accept uncompressed `.csv` metrics exports and reject statement
  text. Never copy, rename, or move inputs under the project. Empty paths
  are invalid; ask again or let the user choose skip/later.
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
> no logging setting is changed, and nothing connects to it.
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

#### 5.7c `later` on Redshift

Paste
`workload-insights/references/redshift-sys-query-history.sql` unchanged. Do not
summarize the SQL. This copy is shared with the HTML/dashboard empty state.

The SQL is delivered now during input gathering—never defer it, add it as a
later task, or mention it again after the normal skipped result.

> Disclaimer: the metrics file is used for reporting only. It contains query
> metadata, not SQL text or error messages.
>
> **1. Export the query history.** Run this from a SQL client or the Redshift
> Query Editor. Redshift keeps `SYS_QUERY_HISTORY` for only **7 days**, so one
> export covers at most the last week. For a longer window, schedule the same
> `UNLOAD` to run at least weekly or enable Redshift's AWS-native system-view
> stream. **Have a DBA review and run this.** Redshift system views show only
> the current user's activity unless the account is a SUPERUSER or holds
> `SYSLOG ACCESS UNRESTRICTED`, so run by anyone else the export succeeds and
> silently covers one user. The `UNLOAD` also writes to an S3 bucket under an
> IAM role — both belong to whoever administers the cluster. The nine columns
> are the whole extract: no query text, no error messages, no query hashes.
>
> **2. Re-run assessment** with
> `scai assessment workload-insights --input /path/to/querylogs.csv`.
> Repeat `--input` to merge split exports.

After the SQL, tell the user to re-run assessment later, choose **I have the
CSV export**, and provide its path. The current assessment does not wait.

Use skipped summary `extract SQL provided; re-run assessment with the Redshift
metrics file`. Do not model the export as pending work.

### 5.8 Snapshot the inputs

Keep this in working context only; never write it to disk:

```yaml
assessment_inputs:
  project_dir: <abs>
  output_dir_assessment: <project_dir>/assessment
  business_use_cases:
    context:                          # include only the kinds that were asked
      scheduler:                      # Informatica in scope
        mode: have_files | skip | later
        paths: [<abs path>, ...]
      agent_jobs:                     # SSIS in scope
        mode: have_files | skip | later
        paths: [<abs path>, ...]
      usage:                          # every dialect
        mode: have_files | skip | later
        paths: [<abs path>, ...]
  exclusion: {}
  effort_estimate: {}
  anti_patterns: {}
  workload_insights:
    mode: have_extract | skip | later
    input_paths: [<abs .xel path (SQL Server) or metrics CSV path (Teradata/Redshift)>, ...]
  dynamic_sql:
    review_mode: generate-only | auto-review-all | skip
    output_dir: <project_dir>/assessment/json
  conversion_issues:
    run: true | false
  etl:
    review_mode: generate-only | auto-review-all | skip
    output_dir: <project_dir>/artifacts/assessment/etl
    etl_replatform_sources_path: <abs or empty>
  informatica:
    target: dbt | scripting
    output_dir: <project_dir>/artifacts/assessment/etl
    review_mode: auto-review-all
  data_lineage:
    dispatch: true | false
    staged_pbits: [source/BI/PowerBI/<name>.pbit, ...]
    manifest_path: <project_dir>/artifacts/assessment/powerbi/manifest.json
```

After this snapshot, do not prompt again until failed sub-skills are surfaced.
