---
name: assessment
description: Analyzes workloads to be migrated to Snowflake using SnowConvert assessment reports. Routes to specialized sub-skills for high-quality assessments. Use this skill when user wants to do an assessment of their code or ETL workload, waves generation, object exclusion, effort estimates, anti-patterns, workload insights (SQL Server), sql dynamic and/or ETL analysis (SSIS)
version: 0.1.0
license: Proprietary. See License-Skills for complete terms
---

# Assessment

## On Entry

Tell the user:
> **Migration Assessment** — I'll analyze your converted code to generate a migration plan: dependency waves, object categorization, dynamic SQL patterns, and a summary report. This helps us prioritize what to migrate first.

End-to-end migration assessment. The user only needs to point at the source — this skill detects the project state and, if needed, drives the migration setup (connect → init → register → convert) so that the SnowConvert reports the assessment depends on are produced automatically. The user is **never** asked for SnowConvert report paths, registry paths, or output directories.

**One exception:** SQL Server **Workload Insights** uses Query Store data, which
nothing in the conversion pipeline produces. Step 4 first explains what
Workload Insights adds, then lets the user skip it, provide CSV path(s) now, or
take the enable/extract SQL and provide the CSV on a later assessment run. Any
CSV filename works and the file stays in place.

> "I want to assess my workload" → the user provides a source → assessment runs end-to-end. Nothing else is requested.

## Step 0: Configure Session

Call the `configure` MCP tool with `project_dir` (use the current directory, or ask the user if ambiguous). Assessment needs no Snowflake connection — `scai assessment` runs entirely off the local project — so don't ask for one here; the setup machine asks after assessment, only if the user goes on to object migration. Other settings are filled in by sub-skills as the workflow progresses.

## Step 1: Verify Prerequisites

If you arrived here directly (not through the setup state machine), call `progress_setup()` first. If it returns a `next_task` other than `runAssessment` (or `completed: true` with assessment already done), follow the engine — finish that setup step, then re-enter assessment when `progress_setup()` routes here.

## Step 2: Auto-Detect SnowConvert Outputs

Resolve all inputs from `project_dir`. Do not prompt the user.

| Input | Resolution |
|-------|------------|
| SCAI project root | `project_dir` (contains `.scai/` and the registry — required by `scai assessment waves`) |
| SnowConvert reports dir | `<project_dir>/reports/SnowConvert/` |
| Issues CSV | `<project_dir>/reports/SnowConvert/Issues.*.csv` (latest timestamp) |
| ETL Elements / Issues CSVs | `<project_dir>/reports/SnowConvert/ETL.Elements.*.csv` and `ETL.Issues.*.csv` (only if present — drives whether SSIS analysis is included) |
| Assessment output dir | `<project_dir>/assessment/` (created by `scai assessment waves`; fall back to creating if missing for other sub-skills) |

Selection rules:
- **Wave generation is always driven by `scai assessment waves`** — it reads the registry from the current project folder and writes `<project_dir>/assessment/waves_analysis_*.json`. There is no CSV fallback for wave creation.
- The multi-tab HTML report (`scai assessment report`) takes `--project-dir` (the scai project root) and auto-discovers everything it needs: `registry/`, `reports/`, `assessment/waves_analysis_*.json`, and the exclusion / dynamic-SQL JSONs. The registry is **required** — without it the report cannot enrich the waves JSON (which emits UUIDs) with canonical names, categories, file paths, and conversion status.
- If the registry or reports are missing after a successful-looking convert, re-run `../convert/SKILL.md` once and stop if it still produces nothing.

## Step 3: Confirm Scope (single, short)

Show one compact confirmation that lists what will run. This is the **only** confirmation between source-question and execution.

```
I will run:
1. Waves (dependency analysis + deployment partitioning)
2. Anti-Patterns  (SQL Server only)
3. Effort Estimates  (SQL Server and Redshift only)
4. Workload Insights  (SQL Server only)
5. Dynamic SQL Patterns
6. ETL/SSIS Assessment  (only if present)
7. Informatica Assessment  (only if present)
8. HTML Report

Proceed with all, or pick a subset?
```

Wait for "yes" or a subset selection, then run. Do not re-prompt for files or directories at any later point.

**Note:** "Proceed with all" includes the Workload Insights **intake step**, but Workload Insights itself runs only when a CSV is supplied. Declining or deferring it does not remove any other selected assessment. "Proceed with all" is **not** the last prompt: Step 4 collects every input the in-scope sub-skills need so they can run as non-interactive sub-agents. After Step 4 the assessment becomes hands-off until results are surfaced in Step 8.

## Step 4: Gather Sub-Skill Inputs (single batch)

Collect **every** answer the in-scope sub-skills need **before** dispatching anything. Sub-agents run non-interactively. Hold the answers in an in-message `assessment_inputs` block in your working context (do not write it to disk) — it is the source of truth for the context blocks emitted in Step 5.

For sub-skills excluded by the Step 3 scope answer, skip the corresponding inputs and do not dispatch in Step 5.

### 5.1 Waves inputs (always required when waves is in scope)

Ask the three Required User Interactions from `waves-generator/SKILL.md` here, in this order:

1. **Partition size** — "The default wave size is 40-80 objects. Keep the defaults, or set custom min/max?" Record `partition_min_size` (int) and `partition_max_size` (int).
2. **Prioritization** — "Any objects to push into the earliest waves? Provide patterns like `*Payroll*` or `dbo.Customer`, or say no." Record `prioritization_globs` (list of strings; empty if none).
3. **Wave ordering** — "Default is category-based (TABLE → VIEW → FUNCTIONS/PROCEDURES → ETL). Switch to dependency-based?" Record `wave_ordering` (`category` or `dependency`).

### 5.2 Dynamic SQL review (when in scope)

Ask once:

> "Are you interested in Dynamic SQL code analysis? Each occurrence will be reviewed individually — pattern, complexity, migration considerations. (yes / no)"

Map the answer to `dynamic_sql.review_mode`:
- `yes` → `auto-review-all` — generate, then loop and update each occurrence
- `no` → `generate-only` — generate the JSON for report visibility only; no per-occurrence review

### 5.3 ETL/SSIS review (when ETL is detected)

When ETL/SSIS is in scope and `ETL.*.csv` files are present, **always generate** the JSON — it gives the user visibility into their packages: component counts, control flow / data flow DAGs, and a baseline migration view in the report. Do not ask about that step.

Beyond the baseline, ask once whether to run the deeper AI package analysis:

> "I detected SSIS packages in this project. The assessment will give you visibility into them — component counts, control/data flow DAGs, and a baseline migration view in the report.
>
> Optionally, I can run an AI-driven per-package analysis that adds package classification (Ingestion / Transformation / Export / Orchestration / Hybrid), an AI HTML summary, and effort estimates. It takes more time, but runs in the background as a sub-agent in parallel with the other assessments — it doesn't block anything else. Run the AI analysis? (yes / no)"

Map the answer to `etl.review_mode`:
- `yes` → `auto-review-all` — generate, then per-package AI classification + AI HTML summary
- `no` → `generate-only` — generate the JSON for report visibility only; no AI analysis

Capture `etl_replatform_sources_path` from `migration_status` if available (otherwise leave blank for sub-agent auto-detection).

### 5.3b Informatica PowerCenter target (when Informatica is in scope)

When Informatica PowerCenter sources are detected (use MCP `migration_status` to check project config), ask **once**:

> "Which conversion target for Informatica PowerCenter?
> 1. **dbt** — mappings convert to dbt models orchestrated by Snowflake Tasks
> 2. **scripting** — mappings convert to Snowflake stored procedures (Snowflake Scripting)
>
> Choose 1 or 2:"

This prompt is **MANDATORY** — do not skip or default. Record `informatica.target` as `"dbt"` or `"scripting"`.


### 5.4 Object exclusion (no inputs)

No prompts. Note the sub-skill is in scope.

### 5.5 Effort estimate (no inputs)

No prompts. Note the sub-skill is in scope.

### 5.6 Anti-patterns (SQL Server only, no inputs)

No prompts. In scope **only when the project's source dialect is SQL Server** — `scai assessment anti-patterns` self-gates and aborts (error `ASM0024`) on other dialects. For non-SQL-Server projects, treat it as out of scope and synthesize a `"skipped"` result in Step 6.

### 5.7 Workload Insights (SQL Server only)

In scope **only when the project's source dialect is SQL Server** — `scai assessment workload-insights` self-gates and aborts (error `ASM0034`) on other dialects. For non-SQL-Server projects, ask **nothing** here, treat it as out of scope, and synthesize a `"skipped"` result in Step 6.

First say this, as a plain message, before you ask anything:

> **Workload Insights** summarizes the SQL activity SQL Server recorded in Query Store: execution volume, statement mix, busiest modules, and costly or occasionally slow query shapes. It is not derived from the converted source. You run the extract we provide and save that result as a CSV. This is optional — you can skip it, or take the SQL now and attach the CSV on a later run.

Then ask this. The disclaimer line and **all three options, in this order and
with these labels**, must appear in the question itself — never summarize the
disclaimer away, and never drop, merge, or reword an option. Option 3 is the
whole reason a user without a CSV can still get Workload Insights:

> Disclaimer: Query Store data, and everything derived from it in this report, is used for reporting purposes only.
>
> How do you want to handle Workload Insights?
>
> 1. Skip for this run
> 2. I have the CSV
> 3. Give me the SQL, I'll provide the CSV later

Map the answers to `workload_insights.mode`: `skip` | `have_extract` | `later`.

**1 — `skip`.** Record empty `days` and `input_paths`, paste no SQL, and continue gathering any remaining assessment inputs.

**2 — `have_extract`.** Ask for one or more paths: one CSV per database, or a single concatenated file. Any filename works. Resolve each answer to an absolute path and record them in `input_paths`. Leave `days` empty. Do **not** `cp` the file, `mkdir` a folder for it, or otherwise move it under the project — `scai` reads it in place. Do **not** ask days-back: the CSV already carries `first_seen` / `last_seen`. If no usable path is supplied, do not dispatch; ask for a path or let the user switch to `skip` / `later`.

**3 — `later`.** Ask this verbatim, offering exactly these two answers — do not
retitle the question or add other preset windows:

> **Extract window**
>
> How many days back should the extract cover?
>
> 1. 30 days (recommended)
> 2. A different number of days

If they pick 2, ask for the number. Validate the answer is an integer `> 0` and re-ask if it is not. Record it as `workload_insights.days` and leave `input_paths` empty. Then, in this same turn, in this order:

- Show this disclaimer verbatim **before** any SQL:

  > Disclaimer: Query Store data, and everything derived from it in this report, is used for reporting purposes only.
- Paste the enable SQL from `workload-insights/references/enable-query-store.sql`, substituting `STALE_QUERY_THRESHOLD_DAYS = <days>` with the window they just chose so cleanup does not drop that range. Tell users whose Query Store is already on to skip that `ALTER`.
- Paste the extract SQL from `workload-insights/references/extract.sql` with `DECLARE @Days int = <days>` filled in from their answer.
- Tell the user to run the database under real traffic, execute the extract **inside each user database** they care about (Query Store is per database — there is no instance-wide extract), save the result as a CSV **with headers included** (`sqlcmd`, or SSMS with headers turned on), one file per database or concatenated, and return on a later assessment run.
- Explicitly say the current assessment will continue now and will not wait for the capture window.

### 5.8 Snapshot the inputs

Lay out the resolved values in your working context like this (text only — do not write to disk):

```
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
    days: <int or empty>
    input_paths: [<abs>, ...]
  dynamic_sql:
    review_mode: generate-only | auto-review-all | skip
    output_dir: <project_dir>/assessment/json
  etl:
    review_mode: generate-only | auto-review-all | skip
    output_dir: <project_dir>/assessment/ssis
    etl_replatform_sources_path: <abs or empty>
  informatica:
    target: dbt | scripting
```

After Step 4 completes, do **not** prompt the user again until Step 8.

## Step 5: Parallel Sub-Agent Dispatch

In a **single message**, fire one Task tool call per in-scope sub-skill. Do not dispatch sequentially. After dispatching, end your turn — sub-agents run on their own and return results back to this conversation.

Each Task call uses the prompt template for its sub-skill below. Substitute every `<placeholder>` with the value from the `assessment_inputs` snapshot in Step 4. Use absolute paths only.

> **Important:** Do **not** dispatch any sub-skill that is out of scope (per Step 3) or whose `review_mode` is `skip`. The parent synthesizes a `"skipped"` result for those in Step 6.

### 6.1 waves-runner prompt

```
Read and follow plugin/skills/migration/assessment/waves-generator/SKILL.md.
You are running in sub-agent mode — do NOT ask the user any questions.

Context (from parent):
- project_dir: <abs_path>
- partition_min_size: <int>
- partition_max_size: <int>
- prioritization_globs: <list or empty>
- wave_ordering: category | dependency
- output_dir: <project_dir>/assessment

Steps:
1. Call configure() with project_dir above. Snowflake credentials are not needed for waves generation.
2. Run `scai assessment waves` from <project_dir>, passing every required
   input as a flag derived from partition_min_size, partition_max_size,
   prioritization_globs (one --prioritize per glob), and wave_ordering
   (--no-category-waves only when wave_ordering = dependency). If the CLI
   still requests TTY input, fail fast and report the missing flag — do not
   block on stdin.
3. Locate the timestamped waves_analysis_*.json the CLI wrote.

Report back JSON only:
{
  "sub_skill": "waves-generator",
  "status": "ok" | "error",
  "output_json": "<abs_path>" | null,
  "summary": "<one-line counts: partitions, sccs, objects>",
  "error": "<message>" | null
}
```

### 6.2 exclusion-runner prompt

```
Read and follow plugin/skills/migration/assessment/object_exclusion_detection/SKILL.md.
You are running in sub-agent mode — do NOT ask the user any questions.

Context (from parent):
- project_dir: <abs_path>

Steps:
1. Call configure() with project_dir above. Snowflake credentials are not needed for object exclusion.
2. Run `scai assessment object-exclusion` from <project_dir>.
3. Locate the timestamped object_exclusion_analysis_*.json the CLI wrote under <project_dir>/artifacts/assessment.

Report back JSON only:
{
  "sub_skill": "object-exclusion-detection",
  "status": "ok" | "error",
  "output_json": "<abs_path>" | null,
  "summary": "<one-line counts: temp/staging, deprecated, testing, duplicates>",
  "error": "<message>" | null
}
```

### 6.2b effort-estimate-runner prompt

```
Read and follow plugin/skills/migration/assessment/effort-estimate/SKILL.md.
You are running in sub-agent mode — do NOT ask the user any questions.

Context (from parent):
- project_dir: <abs_path>

Steps:
1. Call configure() with project_dir above. Snowflake credentials are not needed for effort estimate analysis.
2. Run `scai assessment effort-estimate` from <project_dir>.
3. Locate the timestamped effort-estimates-*.json the CLI wrote under
   <project_dir>/artifacts/assessment/. If the CLI aborts because the
   source dialect is unsupported (error ASM0031), report status "skipped"
   with that reason — do NOT treat it as an error.

Report back JSON only:
{
  "sub_skill": "effort-estimate",
  "status": "ok" | "skipped" | "error",
  "output_json": "<abs_path>" | null,
  "summary": "<one-line: ddl_objects, total_fde_hours>",
  "error": "<message>" | null
}
```

### 6.3 dynamic-sql-runner prompt

```
Read and follow plugin/skills/migration/assessment/analyzing-sql-dynamic-patterns/SKILL.md.
You are running in sub-agent mode — do NOT ask the user any questions.

Context (from parent):
- project_dir: <abs_path>
- output_dir: <project_dir>/assessment/json
- review_mode: generate-only | auto-review-all

Steps:
1. Call configure() with project_dir above. Snowflake credentials are not needed for dynamic-SQL analysis.
2. Run:
     scai assessment sql-dynamic generate \
       --project-dir <project_dir> \
       --output <output_dir>/sql_dynamic_analysis.json
3. If review_mode = auto-review-all, follow the skill's per-occurrence
   review loop until `stats` shows zero PENDING records. Each update is a
   single-record call with its own analysis (no batching, no copy/paste).
4. Locate the analysis JSON.

Report back JSON only:
{
  "sub_skill": "analyzing-sql-dynamic-patterns",
  "status": "ok" | "error",
  "output_json": "<abs_path>" | null,
  "summary": "<one-line: total occurrences, REVIEWED, PENDING>",
  "error": "<message>" | null
}
```

### 6.4 etl-runner prompt

```
Read and follow plugin/skills/migration/assessment/etl-assessment/SKILL.md.
You are running in sub-agent mode — do NOT ask the user any questions.

Context (from parent):
- project_dir: <abs_path>
- output_dir: <project_dir>/assessment/ssis
- etl_replatform_sources_path: <abs or empty>
- review_mode: generate-only | auto-review-all

Steps:
1. Call configure() with project_dir above. Snowflake credentials are not needed for SSIS analysis.
2. Locate ETL.Elements.*.csv and ETL.Issues.*.csv under
   <project_dir>/reports/SnowConvert/. If etl_replatform_sources_path is
   empty, auto-detect per the skill's Step 1.
3. Run (from the project root):
     scai assessment etl generate
   This writes etl_assessment_analysis_<timestamp>.json and dag_model_<timestamp>.json
   to <output_dir>.
4. Render DAG HTMLs from the newest dag_model_*.json (conditional, per the skill's Step 2).
5. If review_mode = auto-review-all, follow the skill's Step 3 + Step 4
   to classify each package and produce ai_ssis_summary.html
6. Locate etl_assessment_analysis_<timestamp>.json under <output_dir>.

Report back JSON only:
{
  "sub_skill": "etl-assessment",
  "status": "ok" | "error",
  "output_json": "<abs_path>" | null,
  "summary": "<one-line: total packages, classified, pending>",
  "error": "<message>" | null
}
```

### 6.4b informatica-runner prompt

```
Read and follow plugin/skills/migration/assessment/informatica-assessment/SKILL.md.
You are running in sub-agent mode — do NOT ask the user any questions.

Context (from parent):
- project_dir: <abs_path>
- output_dir: <project_dir>/assessment/informatica
- informatica_target: dbt | scripting
- review_mode: generate-only | auto-review-all

Steps:
1. Call configure() with project_dir above and etl_informatica_target=<informatica_target>.
   Snowflake credentials are not needed for Informatica analysis.
2. Locate ETL.Elements.*.csv and ETL.Issues.*.csv under
   <project_dir>/reports/SnowConvert/.
3. Run the skill's Step 2 (generate JSON) and Step 3 (analyze workflows)
   following informatica-assessment/SKILL.md instructions.
   Use informatica_target to frame all analysis in the correct mode.
4. If review_mode = auto-review-all, analyze each workflow per Step 3
   and produce the AI summary per Step 4.
5. Locate informatica_assessment_analysis_<timestamp>.json under <output_dir>.

Report back JSON only:
{
  "sub_skill": "informatica-assessment",
  "status": "ok" | "error",
  "output_json": "<abs_path>" | null,
  "summary": "<one-line: total workflows, classified, pending, target=dbt|scripting>",
  "error": "<message>" | null
}
```

### 6.5 anti-patterns-runner prompt

Dispatch **only when the project's source dialect is SQL Server** (otherwise synthesize a `"skipped"` result in Step 6).

```
Read and follow plugin/skills/migration/assessment/anti-patterns/SKILL.md.
You are running in sub-agent mode — do NOT ask the user any questions.

Context (from parent):
- project_dir: <abs_path>

Steps:
1. Call configure() with project_dir above. Snowflake credentials are not needed for anti-patterns analysis.
2. Run `scai assessment anti-patterns` from <project_dir>. It writes
   artifacts/assessment/anti-patterns-<timestamp>.json under the project root.
   If the CLI aborts because the project is not SQL Server (error ASM0024),
   report status "skipped" with that reason — do NOT treat it as an error.
3. Locate the timestamped anti-patterns-*.json under
   <project_dir>/artifacts/assessment/.

Report back JSON only:
{
  "sub_skill": "anti-patterns",
  "status": "ok" | "skipped" | "error",
  "output_json": "<abs_path>" | null,
  "summary": "<one-line: buckets, distinct flags, code units affected>",
  "error": "<message>" | null
}
```

### 6.6 workload-insights-runner prompt

Dispatch **only** when all three hold: the project's source dialect is SQL
Server, `workload_insights.mode == have_extract`, and
`workload_insights.input_paths` is non-empty. In every other case (other
dialect, `skip`, `later`, or no paths collected), do **not** dispatch —
synthesize a `"skipped"` result with `output_json: null` in Step 6. For
`later`, use `summary: "deferred — extract SQL provided; re-run assessment with
the CSV"`. For `skip`, use `summary: "skipped by user"`. A skipped Workload
Insights result does not affect any other assessment result or report
generation.

```
Read and follow plugin/skills/migration/assessment/workload-insights/SKILL.md.
You are running in sub-agent mode — do NOT ask the user any questions.

Context:
- project_dir: <abs_path>
- input_paths: <abs csv paths>

Steps:
1. configure() with project_dir. No Snowflake credentials.
2. Run `scai assessment workload-insights --input <path> [--input <path>…]` from project_dir, adding exactly one `--input <path>` argument per context path (absolute).
3. Return JSON only {sub_skill, status, output_json, summary, error}.
   ASM0034 → skipped. Do not rewrite KPI fields in the JSON.
   Do not copy the CSV into the project.
```

A large-extract warning on stdout is **not** a failure: the command still writes the JSON and exits 0, so that run is `"ok"`.

### 6.7 Common rules for every dispatch

1. **One message, multiple Task calls.** Send all in-scope dispatches in a single tool-use turn so the framework can run them in parallel.
2. **Absolute paths only** in every context block.
3. **Sub-agent calls `configure()` itself** — do not assume MCP state is inherited.
4. **Each sub-agent writes only its own output JSON** — no edits to the registry, source SQL, or other sub-agents' artifacts.
5. **JSON return only** — free-form text in the report is harder to consume reliably.

End your turn after the dispatch message.

## Step 6: Wait + Verify Outputs

Each Task return contains a single JSON object: `{sub_skill, status, output_json, summary, error}`. Collect all returns. **A failing sub-agent does not block the others.**

For every dispatched sub-skill, validate:

| Check | Action on failure |
|---|---|
| Task returned a JSON object | Mark sub-skill as failed with `error: "no response"` |
| `status == "ok"` (or `"skipped"` for skip dispatches) | Mark as failed with the returned `error` text |
| `output_json` path exists on disk | Mark as failed with `error: "claimed JSON not found"` |
| `output_json` file is non-empty (size > 0) | Mark as failed with `error: "JSON empty"` (do NOT schema-validate) |

For sub-skills excluded by the Step 3 scope (or set to `review_mode: skip` in Step 4), synthesize `{status: "skipped", output_json: null, summary: "<reason>"}` so Step 8 has a complete row for every sub-skill.

Build a `results` table indexed by sub-skill name (`waves-generator`, `object-exclusion-detection`, `effort-estimate`, `anti-patterns`, `workload-insights`, `analyzing-sql-dynamic-patterns`, `etl-assessment`, `informatica-assessment`). Carry it into Step 7 and Step 8.

## Step 7: Generate Unified HTML Report

**First, resolve the report name.** A generated report gets shared outside the team, so it has to
say which customer or project it belongs to. Check whether this project already has a name:

```bash
uv run --project plugin/skills/migration/assessment \
  python plugin/skills/migration/assessment/scripts/metadata_tools.py \
  --project-dir "<project_dir>" --show-assessment-name
```

It prints three lines:

```
assessmentName: (unset)
projectName:    beverage
resolved:       beverage
```

- `assessmentName` is anything other than `(unset)` → **do not ask.** Go straight to the generator.
- Otherwise ask once, offering `projectName` as the default:

  > **What would you like to name this assessment report?** This will be visible in the report
  > (e.g., Customer or Project name) `[default: beverage]`

  Then store the answer:

```bash
uv run --project plugin/skills/migration/assessment \
  python plugin/skills/migration/assessment/scripts/metadata_tools.py \
  --project-dir "<project_dir>" --set-assessment-name "<answer>"
```

**Name rules:**
1. If `--set-assessment-name` exits non-zero, warn and continue anyway — the report still renders
   from `projectName`.

**Then run `scai assessment report`** with `--project-dir` and **pass flags for ssis or informatica if they apply** from the `results` table:

```bash
scai assessment report \
  --project-dir "<project_dir>" \
  --output "<project_dir>/assessment/multi_report.html" \
  [--ssis-json "<path>" if etl-assessment succeeded] \
  [--informatica-json "<path>" if informatica-assessment succeeded]
```

**Rules:**
1. Always pass `--project-dir` — it auto-discovers waves, exclusion, dynamic-SQL, anti-patterns, registry, and reports directories
2. **Explicitly pass `--ssis-json`** if the `etl-assessment` sub-skill in the `results` table has `status == "ok"` and a valid `output_json` path
3. **Explicitly pass `--informatica-json`** if the `informatica-assessment` sub-skill in the `results` table has `status == "ok"` and a valid `output_json` path
4. Do **not** write custom HTML

If the report command fails, record the failure and proceed to Step 8 anyway — the user still needs the status table.

## Step 8: Surface Results + Retry

Print a status table from the `results` collected in Step 6, one line per sub-skill, in this order: `waves-generator`, `object-exclusion-detection`, `effort-estimate`, `anti-patterns`, `workload-insights`, `analyzing-sql-dynamic-patterns`, `etl-assessment`.

Format:

```
waves-generator                  ok      <output_json basename>   (<summary>)
object-exclusion-detection       ok      <output_json basename>   (<summary>)
effort-estimate                  ok      <output_json basename>   (<summary>)
anti-patterns                    ok      <output_json basename>   (<summary>)
workload-insights                skip    <reason>
analyzing-sql-dynamic-patterns   FAIL    <error message>
etl-assessment                   skip    <reason>

Multi-tab report:  <abs path to multi_report.html>   (or "FAILED — see error above")
```

If any sub-skill failed, ask:

> "Retry failed sub-skills? Successful JSONs will be reused — only the failed runs re-fire. (yes / no)"

On `yes`: re-fire **only** the failed sub-skills using the same single-message Task fan-out as Step 5. Reuse the `assessment_inputs` snapshot from Step 4 — do not re-prompt the user. After the retries return, re-run Step 6 verification, regenerate the report (Step 7), and re-print the status table.

Each retry produces a fresh timestamped JSON; old runs are not deleted (this supports diffs across runs).

After retries complete (or if no retry was requested), proceed to [On Completion](#on-completion).

## Prerequisites

Handled automatically by Steps 0–3. The skill assumes:
- `scai` CLI is installed and available on `PATH` — used by `setup`, `convert`, and `scai assessment waves`.
- Python 3.11+ and `uv` are available for the HTML report generator and the remaining assessment scripts (install `uv` per https://docs.astral.sh/uv/getting-started/installation/ — `brew install uv` on macOS, `winget install astral-sh.uv` on Windows, or `pip install uv` anywhere).

## Example Prompts

Help users get the best results by understanding what they can ask:

### Starting an Assessment
- "Run a quick assessment of my migration"
- "I need a comprehensive assessment with all analyses"
- "Generate deployment waves for my SQL migration"

### Customizing Wave Generation
- "I want a maximum of N objects per wave"
- "Create smaller waves with 20-30 objects each"
- "Prioritize all Payroll-related objects in Wave 1"
- "Put all Customer* objects in the earliest waves"
- "Use dependency-based ordering instead of category-based"

### Iterative Refinement (After Initial Results)
- "Show me which objects have circular dependencies"
- "Regenerate waves with smaller batch sizes"
- "What objects are blocking the migration?"

### Working with Reports
- "Generate the HTML report"
- "Show me a summary of the assessment"
- "How many objects are flagged for exclusion?"
- "What's the breakdown by schema?"

### Specific Analyses
- "Identify temporary and staging objects"
- "Find deprecated objects that can be excluded"
- "Analyze Dynamic SQL patterns in my codebase"
- "Assess my SSIS packages for migration complexity"

## Critical Rules

**Follow instructions of each sub-skill:** Read the sub-skill first before executing any command.

**NO CUSTOM SCRIPTS:** Only execute existing scripts within sub-skills. Do not create automation, batch processing tools, or bash loops.

**🚫 NEVER WRITE CUSTOM HTML REPORTS:** When delivering results to users, you MUST use `scai assessment report`. Do NOT write HTML manually under any circumstances. See [Report Generation](#report-generation) section.

**USER CONFIRMATION:** Stop at mandatory checkpoints in sub-skills for user input.

**DATA-DRIVEN:** All assessments based on SnowConvert registry (JSON), CSV outputs and source code.

## Intent Detection & Routing

Detect user intent and load the appropriate sub-skill:

**Deployment Waves** - Analyze dependencies and create deployment sequence:
- Triggers: "deployment waves", "migration waves", "dependency analysis", "deployment sequence", "wave planning"
- Load: `waves-generator/SKILL.md`

**Object Exclusion** - Identify objects to exclude from migration:
- Triggers: "temporary objects", "staging objects", "deprecated", "exclude objects", "test objects", "cleanup"
- Load: `object_exclusion_detection/SKILL.md`

**Effort Estimates** - Generate migration effort estimates from SnowConvert reports:
- Triggers: "effort estimate", "effort estimates", "migration effort", "FDE hours", "how long will migration take"
- Load: `effort-estimate/SKILL.md`

**Anti-Patterns** - Surface migration converns from existing SnowConvert findings (SQL Server only):
- Triggers: "anti-patterns", "anti patterns", "risk analysis", "performance risks", "collation risks", "semantic risks", "architecture blockers"
- Load: `anti-patterns/SKILL.md`

**Workload Insights** - Summarize SQL activity recorded in Query Store (SQL Server only):
- Triggers: "workload insights", "query logs"
- Needs a Query Store CSV the customer exports themselves (any filename). No CSV yet → Step 4 § 5.7 hands them the SQL and the assessment continues without it.
- Load: `workload-insights/SKILL.md`

**Dynamic SQL Analysis** - Classify and score Dynamic SQL patterns:
- Triggers: "dynamic sql", "sql dynamic patterns"
- Supports: SQL Server, Redshift, Oracle, and Teradata migrations
- Load: `analyzing-sql-dynamic-patterns/SKILL.md`

**ETL/SSIS Assessment** - Analyze SSIS packages for migration complexity:
- Triggers: "ssis", "etl packages", "ssis analysis"
- Load: `etl-assessment/SKILL.md`

**Informatica Power Center Assessment** - Analyze Informatica workflows/mappings for migration complexity:
- Triggers: "informatica", "power center", "powercenter", "informatica assessment", "informatica analysis"
- Load: `informatica-assessment/SKILL.md`

**Data Migration & Validation readiness** - Explain how the workload's data moves to Snowflake and how it gets validated:
- Triggers: "data migration", "data validation", "move the data", "data type coverage", "unsupported types", "table inventory", "validation divergence", "topology"
- No sub-skill to load and no `scai assessment` command: the multi-report's **Data Migration & Validation** tab already answers this. It is computed from the Code Unit Registry by `scripts/snowconvert_reports/data_migration_readiness.py` (with `data_types_scan.py` for types found in captured DDL and `type_coverage.py` for per-dialect coverage), and rendered by `scripts/data_migration_report/`.
- Reviewed inventory SQL exists only for SQL Server and Redshift (`scripts/data_migration_report/sql/`). Other dialects get a gather checklist — do not invent queries for them.

**Testing readiness** - Explain what can be tested today and what each object still needs first:
- Triggers: "testing", "test readiness", "can I test", "output testing", "what's ready to test", "testing ladder"
- No sub-skill to load and no `scai assessment` command: the multi-report's **Testing** tab already answers this. It is computed from the Code Unit Registry by `scripts/snowconvert_reports/testing_readiness.py` and rendered by `scripts/testing_report/`.
- Both readiness ladders state a no-source-code precondition. ETL units terminate at `stabilization`, all other code units at `testing` — never read `testing.status` for an ETL unit.

**Multiple Assessments** - Load all applicable sub-skills if request requires comprehensive analysis.

## Running Scripts
When running any scripts in any of the above skills, make sure to do all of the following:

- **Wave generation** is executed via `scai assessment waves`. It must be run from inside the SCAI project directory so that it can read the registry.
- **Multi-tab HTML report** is executed via `scai assessment report`.
- **All other Python scripts** in this skill and its sub-skills (ETL analysis, etc.) must be run with `uv run --project <DIRECTORY THIS SKILL.md file is in> python <DIRECTORY THIS SKILL.md file is in>/scripts/script_name.py`.
- Do not `cd` into another directory to run Python scripts, but run them from whatever directory you're already in. When `scai assessment waves` needs the project directory, `cd` into it only for that single invocation.

**WHY:** This maintains your current working context and prevents path confusion. When using `uv run --project`, you must provide absolute paths for BOTH the `--project` flag AND the script itself. Just run the script the way the skill says. Do not question it by running --help or reading the script.

<!-- DEPRECATED in favor of Steps 5-9 (sub-agent dispatch). Will be removed one release after sub-agent rollout stabilizes. See dev/assessment-subagent-dispatch-design.md §11.2 Phase 3.

## Assessment Integration

### Complete Migration Assessment Workflow

The user has already confirmed scope in **Step 4**. Do **not** re-prompt for confirmation here — execute the agreed sequence directly.

**Sequence:**

1. **Waves Generation** (First)
   - **MANDATORY:** Load `waves-generator/SKILL.md` and complete its **Required User Interactions** (partition size, prioritization, wave-ordering strategy) before running the command. These prompts are required even on the end-to-end path — do **not** skip them.
   - Then run `scai assessment waves` from inside the SCAI project directory, passing `--min-size`, `--max-size`, `--prioritize`, `--no-category-waves` derived from the user's answers.
   - The command builds the dependency graph from the registry, validates §15 invariants, and writes `<project_dir>/assessment/waves_analysis_<timestamp>.json`
   - Generate wave-based migration plan

2. **Object Exclusion Analysis** (Second)
   - Identify objects that don't need migration
   - Reduce scope before dependency analysis
   - Generate cleanup recommendations

3. **Dynamic SQL Pattern Analysis** (Third)
   - Classify Dynamic SQL patterns
   - Identify migration complexity and blockers

4. **ETL/SSIS Assessment** (Fourth - if applicable)
   - Analyze SSIS packages individually
   - Understand control flow and data flow pipelines
   - Classify packages and estimate migration effort

5. **Generate Multi-Tab Report** (FINAL - REQUIRED)
   - Use `scai assessment report` - see [Report Generation](#report-generation) section
   - Pass all available JSON outputs from previous steps
   - 🚫 Do NOT write custom HTML - the script handles all formatting

-->

## Tools

### `scai assessment report`

**Description**: Generates unified multi-tab HTML report combining Object Exclusion, Dynamic SQL Analysis, Waves, and SSIS Assessment reports.

**Location**: `scai assessment report`

**When to use**: After completing any requested assessment(s) (1, 2, 3, or all) to deliver results in a consistent format, or whenever the user requests a combined HTML report.

<!-- DEPRECATED in favor of Steps 5-9 (sub-agent dispatch). Will be removed one release after sub-agent rollout stabilizes. See dev/assessment-subagent-dispatch-design.md §11.2 Phase 3.

## Completing the Assessment Analysis

### ⚠️ MANDATORY STOPPING POINT: After Initial Assessment

After generating the initial assessment (Object Exclusion, Dynamic SQL JSON, Waves, SSIS), you **MUST** ask the user about completing each analysis that has pending items:

#### Dynamic SQL Analysis Completion

```
Assessment data has been generated. The Dynamic SQL analysis contains X occurrences 
that are currently in PENDING status and need individual review.

Would you like to complete the Dynamic SQL analysis?
- This involves reviewing each Dynamic SQL occurrence individually
- Each occurrence will be classified, scored for complexity, and documented
- Estimated time: varies based on occurrence count and code complexity

Options:
1. Yes - Complete the full analysis (review all Dynamic SQL occurrences)
2. No - Stop here with the current data (report will show PENDING status)
```

**If user selects Yes:**
- Load the `analyzing-sql-dynamic-patterns/SKILL.md` sub-skill
- Follow the workflow to review each occurrence
- Update each record with: status=REVIEWED, category, complexity, notes
- Continue until `stats` command shows 0 PENDING records
- Then proceed to the next analysis or report generation

**If user selects No:**
- Report will show Dynamic SQL occurrences with PENDING status
- User can complete the analysis later

#### SSIS/ETL Analysis Completion

If SSIS packages are present, also ask:

```
The SSIS/ETL analysis contains X packages that are currently unclassified 
and need individual review.

Would you like to complete the SSIS analysis?
- This involves reviewing each SSIS package individually
- Each package will be classified (Ingestion, Transformation, Export, etc.)
- AI analysis and migration effort estimates will be documented

Options:
1. Yes - Complete the full SSIS analysis (review all packages)
2. No - Stop here with the current data (report will show unclassified packages)
```

**If user selects Yes:**
- Load the `etl-assessment/SKILL.md` sub-skill
- Use `pending` command to list unclassified packages
- Use `package <path>` to view package details
- Use `update <path> --ai-status DONE --classification <type> --ai-analysis "<notes>" --effort <hours>` to classify each package
- Classification options: Ingestion, Transformation, Export, Orchestration, Hybrid
- Continue until `stats` command shows "No pending packages found"
- Then proceed to report generation

**If user selects No:**
- Report will show SSIS packages as unclassified
- User can complete the analysis later

**IMPORTANT:** Do NOT skip these checkpoints. The assessment is not complete until all Dynamic SQL occurrences AND all SSIS packages have been reviewed OR the user explicitly chooses to defer each.

-->

## Report Generation

<!-- DEPRECATED in favor of Steps 5-9 (sub-agent dispatch). Will be removed one release after sub-agent rollout stabilizes. See dev/assessment-subagent-dispatch-design.md §11.2 Phase 3.

### ⚠️ CRITICAL: Multi-Tab HTML Report Generator

**⚠️ MANDATORY: Check for Incomplete Analysis Before Report Generation**

Before generating the report, you **MUST** check for incomplete analysis and warn the user:

1. **Check Dynamic SQL status:**
   ```bash
   scai assessment sql-dynamic stats <path/to/sql_dynamic_analysis.json>
   ```

2. **Check SSIS status** using the scai assessment etl command:
   ```bash
   scai assessment etl stats
   ```
   
   Note: The `stats` command reads the JSON produced by `scai assessment etl generate` and auto-detects the file from project context.

**If there are PENDING Dynamic SQL records OR unclassified SSIS packages**, present this warning:

```
⚠️ WARNING: Incomplete Analysis Detected

The assessment contains unanalyzed items:
- Dynamic SQL: X of Y occurrences are PENDING (not reviewed)
- SSIS/ETL: X of Y packages are unclassified

Generating the report now will show these items as incomplete/unanalyzed.

Options:
1. Generate report anyway (items will show as PENDING/Unclassified)
2. Complete the analysis first (recommended for final deliverables)

Which option would you like?
```

Wait for user response before proceeding.

**⚠️ MANDATORY STOPPING POINT**: After checking analysis status, confirm with user:

```
I will generate a multi-tab HTML report including:
- Object Exclusion Report (if available)
- Dynamic SQL Analysis Report (if available) [X/Y reviewed]
- Waves Deployment Report (if available)
- SSIS Assessment Report (if available) [X/Y classified]

Output file size: typically 5-10MB due to interactive content.

Proceed with report generation? (Yes/No)
```

Wait for approval.

-->

**MANDATORY:** When users request an assessment report (even if it’s only one sub-assessment), a migration report, or a combined HTML report—or when you have completed the requested assessment(s) and are ready to deliver results—you **MUST** use `scai assessment report`. This is the **ONLY** approved method for generating consolidated assessment reports.

**DO NOT:**
- Write custom HTML reports manually
- Use individual sub-skill report generators in isolation
- Create new report generation scripts

**Usage (recommended — single `--project-dir` argument):**
```bash
scai assessment report \
  --project-dir "path/to/<projectRoot>" \
  --output "path/to/<projectRoot>/assessment/multi_report.html"
```

When `--project-dir` is provided, the command auto-discovers:

- `<projectRoot>/registry/` — registry JSONs (REQUIRED for object enrichment: names, categories, files, status, missing-deps, direct dep counts)
- `<projectRoot>/reports/` — SnowConvert CSVs (for EWI/FDM/PRF counts and severity)
- `<projectRoot>/artifacts/assessment/object_exclusion_analysis_*.json` — exclusion JSON (latest timestamp)
- `<projectRoot>/assessment/json/sql_dynamic_analysis.json` — dynamic-SQL JSON
- `<projectRoot>/assessment/waves_analysis_*.json` — waves JSON (latest timestamp)

Explicit per-source flags (below) override auto-discovery. The individual flags are only needed when you want to mix-and-match sources from non-standard locations.

**Usage with explicit paths (advanced):**
```bash
scai assessment report \
  --project-dir "path/to/<projectRoot>" \
  --waves-json "path/to/waves_analysis_TIMESTAMP.json" \
  --exclusion-json "path/to/object_exclusion.json" \
  --dynamic-sql-json "path/to/sql_dynamic_analysis.json" \
  --snowconvert-reports-dir "path/to/reports" \
  --ssis-json "path/to/ssis/etl_assessment_analysis.json" \
  --output "path/to/multi_report.html"
```

**IMPORTANT:** Always pass `--project-dir` even when providing explicit flags — the registry at `<projectRoot>/registry/` is required to enrich the waves JSON (which now emits UUIDs; canonical names, categories, file paths, and status come from the registry). Without `--project-dir` (or an equivalent `--registry-dir`), the dependencies table will show UUIDs and every row will have category "UNKNOWN".

**Parameters:**
- `--project-dir` **(recommended)**: Path to the scai project root. Auto-discovers registry, SnowConvert reports, and assessment artifacts. Use this alone in the common case.
- `--waves-json`: Path to waves analysis JSON file (output from `scai assessment waves`, e.g. `waves_analysis_<timestamp>.json`). Auto-discovered from `<projectRoot>/assessment/` when `--project-dir` is provided.
- `--registry-dir`: Path to SnowConvert registry directory containing `*.json` entries. Auto-discovered from `<projectRoot>/registry/` when `--project-dir` is provided.
- `--exclusion-json`: Path to object exclusion JSON file. Auto-discovered.
- `--dynamic-sql-json`: Path to dynamic SQL analysis JSON file. Auto-discovered.
- `--snowconvert-reports-dir`: Path to SnowConvert Reports directory containing `TopLevelCodeUnits.*.csv` and `ObjectReferences.*.csv`. Auto-discovered.
- `--ssis-json`: Path to SSIS assessment JSON file (etl_assessment_analysis.json from ETL assessment). **MUST be explicitly passed when the etl-assessment sub-skill succeeds.**
- `--informatica-json`: Path to Informatica Power Center assessment JSON file (informatica_assessment_analysis.json from Informatica assessment). **MUST be explicitly passed when the informatica-assessment sub-skill succeeds.**
- `--output`: Output HTML file path (required)

**Note:** At least one data source parameter must be provided. If only partial assessment was completed, provide only the available data sources.

**SSIS Report Generation:** When SSIS packages are analyzed using the ETL assessment sub-skill, you **MUST explicitly pass `--ssis-json`** with the path to `etl_assessment_analysis.json` returned by the sub-skill in Step 7.

**Informatica Report Generation:** When Informatica workflows are analyzed using the Informatica assessment sub-skill, you **MUST explicitly pass `--informatica-json`** with the path to `informatica_assessment_analysis.json` returned by the sub-skill in Step 7.

## Report Styling

When generating HTML reports, see `STYLES.md` for styling specifications.

## Success Criteria

An assessment is complete when:
- All requested analyses have completed without errors
- For Dynamic SQL: All occurrences have status `REVIEWED` (no `PENDING` records)
- Reports generated successfully with all requested data sources ** using `scai assessment report` (NOT custom HTML) **
- User has reviewed and approved findings

### Pre-Completion Checklist

Before marking assessment as complete, verify:

```
□ Did I use `scai assessment report` for the final report?
□ Did I pass all available JSON files to the command?
□ Did I avoid writing any custom HTML?
```

If any answer is "No", go back and use the correct script.

## Sub-Skill Documentation

- `waves-generator/SKILL.md` - Algorithm details, partition creation
- `object_exclusion_detection/SKILL.md` - Pattern definitions, naming conventions
- `effort-estimate/SKILL.md` - FDE hour estimates from SnowConvert reports (SQL Server, Redshift)
- `anti-patterns/SKILL.md` - Curated SnowConvert issue-code catalog → customer-facing risk buckets (SQL Server only)
- `workload-insights/SKILL.md` - Query Store CSV extract → workload volume, statement mix, busiest modules, costly and slow shapes (SQL Server only; any CSV filename works); `references/` holds the extract and enable SQL the parent pastes
- `analyzing-sql-dynamic-patterns/SKILL.md` - Pattern classification, complexity scoring
- `etl-assessment/SKILL.md` - SSIS package analysis, control flow, data flow pipelines

The **Data Migration & Validation** and **Testing** tabs have no sub-skill and nothing to dispatch: both are computed inside the report generator from the `--registry-dir` it already requires, so they render in every report without a runner, a CLI command, or an artifact of their own. Their logic lives in `scripts/snowconvert_reports/{data_migration_readiness,data_types_scan,type_coverage,testing_readiness,conversion_status}.py`; their customer-facing copy lives in `scripts/data_migration_report/content.py` and `scripts/testing_report/content.py`, which are the files to read (or change) when answering a wording question.

## On Completion

Present the closing message with: **opening line** (`migration_status.in_scope` objects in `wave_count` waves), **summary table** (Register, Convert, ETL conversion, Waves, Object exclusion, Dynamic SQL, SSIS/Informatica analysis, Missing objects — pull from `migration_status` and Code Unit Registry), **key findings** (2–4 bullets interpreting the data: heavy staging footprint ≥30%, unresolved external refs, conversion friction, ETL risk, circular dependencies — only when triggers fire), **report path** (platform-specific open command for `<project_dir>/assessment/multi_report.html`), and **next-steps menu**:

> What would you like to do?
> 1. **Review the report** — open HTML or ask any questions
> 2. **Modify the assessment** — re-run with changed parameters
> 3. **Move on to migration** — set up the Snowflake target and start Phase 2

Mark option **(1)** as `(recommended)` when `missing > 0`, otherwise **(3)**. Wait for response.

If `configure` reported a dashboard URL at session start, add one line before the menu:
> The dashboard at `<url>` shows the same picture live as you migrate.

Skip it if no URL came back (the user opted out, or the port was busy) — never guess one.

On **(3)**, the user has just answered the setup machine's `continueToMigration`
gate, so **submit it rather than letting the gate ask again**:

```
progress_setup(answers={"continue_to_migration": "true"})
```

Act on that response as `setup/SKILL.md` describes — it walks git, the Snowflake
target and the testing choice. Calling a bare `progress_setup()` here instead
makes the machine put the same question to the user a second time. The same
applies later: if the user reviews the report and *then* says to move on, submit
the answer with that call. Do not load `../migrate-objects/SKILL.md` directly
from here; it has no Snowflake target configured yet.
