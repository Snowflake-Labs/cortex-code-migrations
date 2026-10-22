---
name: code-conversion-only
description: Convert local source code to Snowflake SQL for code-conversion-only source systems such as Sybase IQ, Spark SQL, Databricks SQL, Greenplum, Netezza, Vertica, and Hive. Optionally repoints Power BI reports. Use when configure returns project_type code_conversion_only for these sources.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# Code Conversion Only

## Not the right skill for ETL

If the user's local files are ETL — SSIS `.dtsx`, Informatica PowerCenter XML repo
export, Talend jobs, Alteryx `.yxmd`, Informatica Cloud / IICS mappings, DataStage
`.dsx`, Pentaho `.ktr` / `.kjb`, Azure Data Factory pipelines, or any other ETL
platform — this is **not** the skill to run. `code-conversion-only` is for the SQL
dialects listed in the table below (Sybase, Spark, Databricks, Greenplum, Netezza,
Vertica, Hive, DB2, and legacy PostgreSQL / BigQuery / Azure Synapse projects).
Do not set `project_type: code_conversion_only` for an ETL migration; the CLI's `code_conversion_only` project type has no ETL step and would silently drop those files.
Leave this skill and follow **setup → register local ETL → convert** — the convert
skill's Step 4 handles native SSIS / Informatica PowerCenter and Step 4.5 handles
every other ETL platform through AI-First. Stay here only when the user has one of
the SQL dialects in the table below.

## On Entry

Tell the user:
> **Code Conversion Only** — I'll walk you through adding local source files, converting them to Snowflake SQL, and choosing what to do next with the converted output.

Guide users through SnowConvert's code-conversion-only path. This path uses local source files, not live source extraction.

## Supported Sources

If `configure()` does not already have source_language configured, use the CLI dialect directly for `configure(source_language=...)`.

| User-facing source | `configure(source_language=...)` / CLI dialect |
|--------------------|-----------------------------------------------|
| Sybase IQ | `Sybase` |
| Spark SQL | `Spark` |
| Databricks SQL | `Databricks` |
| BigQuery | `BigQuery` |
| PostgreSQL | `Postgresql` |
| Greenplum | `Greenplum` |
| Netezza | `Netezza` |
| Vertica | `Vertica` |
| Hive | `Hive` |
| IBM DB2 | `Db2` |

If the user says "PostgreSQL & Based Languages" but does not specify one, ask whether they mean PostgreSQL, Greenplum, or Netezza.

> **Note on PostgreSQL, IBM DB2, BigQuery, and Azure Synapse:** New PostgreSQL, DB2, BigQuery, and Azure Synapse projects default to `project_type: full_migration` and are routed through `setup/SKILL.md`. They appear in this skill only for **legacy** projects whose `project.yml` already has `project_type: code_conversion_only` persisted from before full-pipeline support shipped. If you reach this skill for PostgreSQL, DB2, BigQuery, or Azure Synapse, the legacy project configuration is being honored.

## Workflow

### Step 1: Confirm Project Routing

If `routing.converted = true` (from `configure()`), tell the user conversion output already exists in `snowflake/` and offer:

1. **Review converted output and reports**
2. **Re-run conversion**

Only continue to Step 2 if the user chooses to re-run conversion or source files are missing.

If the source system was not already selected by the calling skill, ask the user which supported source they are converting and map it using the table above.

If no project directory is configured, ask where to create/use the project.

Call the `configure` tool with:

```text
configure(project_dir="<PROJECT_DIR>", source_language="<SOURCE_KEY>")
```

Present the returned `user_overview` and `routing` metadata. Confirm it shows `project_type: code_conversion_only`.

### Step 2: Add Local Source Files

Check whether source files are already present in the project `source/` directory.

If no source files are present, ask:

> "Where are your source SQL/code files located? Please provide the full path to the directory or file."

Then run from the project directory:

```bash
scai code add -i <INPUT_PATH> --skip-split --json
```

If the user explicitly wants to replace existing source files, add `--overwrite`.
If the import times out, runs in the background or fails, handle it as
[add-code-units Step 3](../register-code-units/add-code-units/SKILL.md#if-the-import-times-out-or-runs-in-the-background)
says before you go on.

### Step 3: Check for ETL Code

Any ETL imported by `scai code add` lands in `source/_etl/`. That is where `convert` reads it from.

Check whether `source/_etl/` exists and contains ETL files — `.dtsx` for SSIS, `.xml` for Informatica PowerCenter (use whichever portable form fits the host).

- If it is **missing or empty**, there is no ETL to convert; proceed to Step 4.
- If it contains **SSIS** (`.dtsx`), follow [../convert/references/ssis-target.md](../convert/references/ssis-target.md) before any dbt question. It asks dbt or Snowflake Scripting, sets `SSIS_SCRIPTING_MODE` for Step 5 when Snowflake Scripting is chosen, and loads `../dbt-consolidation/SKILL.md` for dbt; then proceed to Step 4.
- If it contains **Informatica** PowerCenter XML, ask the remaining ETL questions up front, in one sequence, before running the conversion:
    1. Conversion target, via `ask_user_question` (`multiSelect = false`):
       > "How should Informatica mappings be converted?
       > 1. **dbt**: each mapping becomes a dbt model orchestrated by Snowflake Tasks.
       > 2. **Snowflake Scripting** (Preview): each mapping becomes a standalone Snowflake stored procedure the Task graph calls. Stabilization and deploy are skipped for this preview flavor."
       Do not label either option recommended.
    2. If the answer is **dbt** and SSIS is absent or chose Snowflake Scripting, load `../dbt-consolidation/SKILL.md`. For Informatica with no dbt SSIS it asks one question: consolidate dbt projects and models by folder, or generate 1 project per mapping. Return here when complete. When SSIS also chose dbt, the SSIS bullet above loads `dbt-consolidation` once after both answers.
    3. If the answer is **Snowflake Scripting**, set `SCRIPTING_MODE = true` for Step 5. Do **not** load `dbt-consolidation`.

    Persist the choice with the MCP `configure` tool: `etl_informatica_target = "dbt"` or `"scripting"`.

These questions are still required for both SSIS and Informatica: the conversion target is not something `scai code add` can infer from the imported files. Ask them on every conversion, re-runs included — `scai code convert` defaults to dbt for SSIS, so a missing flag in Step 5 silently changes the output.

### Step 4: Check for Power BI Reports

Ask the user:

> "Do you have Power BI reports (`.pbit` files) you'd like to repoint to Snowflake?"

If **yes**, load `../powerbi-repointing/SKILL.md`. It collects `PBIT_PATH` and tells you to append `--powerbi-repointing <PBIT_PATH>` to the convert command in Step 5. Return here when complete.

If **no**, proceed to Step 5. `PBIT_PATH` remains unset; do not pass `--powerbi-repointing` to scai.

### Step 5: Convert

Before running, tell the user what the conversion will cover. If `PBIT_PATH` was set, mention Power BI repointing. If `SCRIPTING_MODE` or `SSIS_SCRIPTING_MODE` was set, mention the Snowflake Scripting target and that stabilization and deploy are not part of that preview. The generated procedures and Task graph are under `snowflake/_etl/`.

Always include `--json` so the agent can parse the result envelope. Start from the base command and append one flag per decision already recorded in the steps above — nothing else:

```bash
scai code convert --json
```

| Append | When |
|--------|------|
| `--informatica-to-snowflake-scripting` | `SCRIPTING_MODE` was set in Step 3 (Informatica target is Snowflake Scripting) |
| `--ssis-to-snowflake-scripting` | `SSIS_SCRIPTING_MODE` was set in Step 3 (SSIS target is Snowflake Scripting) |
| `--consolidate-dbt-projects` | `CONSOLIDATE_DBT_PROJECTS` was set by `../dbt-consolidation/SKILL.md` (SSIS dbt, or Informatica dbt) |
| `--powerbi-repointing <PBIT_PATH>` | `PBIT_PATH` was set in Step 4 |

The two Informatica flags are mutually exclusive — they come from the same single-select answer, so at most one can apply. The SSIS scripting flag and the SSIS dbt-consolidation flags come from the SSIS answer, so a scripting SSIS convert does not also pass a consolidation flag. Either platform's choice combines with `--powerbi-repointing` and with the other platform's choice. If none of the conditions hold, run the base command as-is.

Substitute `<PBIT_PATH>` with the actual folder path you stored. Do not emit literal placeholder tokens to the shell.

Per-EWI details (code, description, severity) are in the latest `Issues.*.csv`. Find that file in `<project_dir>/.scai/reports/SnowConvert/` first; if it is not there, use `<project_dir>/reports/SnowConvert/` then `<project_dir>/Reports/SnowConvert/`. Do not use a leftover older folder when `.scai` already has the file. Read those CSVs in Step 6 for **Review EWIs** or **Resolve EWIs with Cortex Code**; do not send the user to browse them.

For Power BI output paths and the CHECKPOINT addendum, see `../powerbi-repointing/SKILL.md`.

### Conversion Options

| Option | Description |
|--------|-------------|
| `-x, --show-ewis` | Show detailed EWI breakdown |
| `--overwrite-working-directory` | Overwrite output files in `snowflake/` and registry |
| `--informatica-to-snowflake-scripting` | Convert Informatica mappings to standalone Snowflake stored procedures (Snowflake Scripting) instead of dbt projects. Preview flavor. |
| `--ssis-to-snowflake-scripting` | Convert SSIS data flows to standalone Snowflake stored procedures (Snowflake Scripting) instead of dbt projects. Preview flavor; stabilization and deploy are not part of this flow. |

For dbt consolidation options, see `../dbt-consolidation/SKILL.md`.
For Power BI options, see `../powerbi-repointing/SKILL.md`.

### Step 6: Ask the user

After conversion, ask:

> "What would you like to do next?"
> 1. **Review converted output** — inspect `snowflake/`, conversion reports via AIM Assessment, conversion logs, and (if Power BI repointing ran) `artifacts/repointing_output/` and `snowflake/power_bi_sql_queries/`
> 2. **Review EWIs** — summarize conversion issues and identify high-priority items
> 3. **Resolve EWIs with Cortex Code** — work through selected converted files/issues and apply fixes
> 4. **Add more source files and re-run conversion** — return to Step 2
> 5. **Stop here** — leave the converted output ready for manual review

If the user chooses **Resolve EWIs with Cortex Code**, inspect the latest conversion issue reports and converted files, then help fix the selected EWIs directly in the project. Keep the work scoped to code conversion output unless the user explicitly asks to move into deployment or broader migration workflows.

## Rules

1. Do not set up a source database connection for this path.
2. Do not route to data migration, data validation, assessment, or migrate-objects unless the user explicitly asks.
3. Do not use `scai code extract`; conversion-only sources use local files.
4. Preserve the CLI project type value `code_conversion_only`; do not introduce another project-type spelling.
