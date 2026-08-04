---
name: convert
description: Convert source code to Snowflake SQL using SnowConvert. Transforms full-migration sources and code-conversion-only sources to Snowflake-compatible syntax, and optionally repoints Power BI reports. Triggers: convert, snowconvert, transform code, convert to snowflake, power bi.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# Code Conversion

## On Entry

Tell the user:
> **Code Conversion.**
>
> Here's what I'll do:
> 1. Run SnowConvert against your source SQL files, which transforms each one into Snowflake SQL syntax.
> 2. Generate reports flagging anything that needs manual review (EWIs, FDMs, performance remarks, out-of-scope items).
> 3. Save converted code under `snowflake/` and reports under `reports/SnowConvert/`.

Convert source code to Snowflake SQL using SnowConvert.

## Prerequisites

- Migration project initialized (`scai init`)
- Source code present in the project `source/` directory, either from extraction or `scai code add`

## Workflow

### Step 1: Verify Source Code Exists

Confirm `source/` contains `.sql` files (use whichever portable form fits the host).

If no files are found, the setup state machine should have already routed back to `register-code-units` before you got here. If somehow you arrived with an empty `source/`, return to the parent setup skill so it can re-query `progress_setup()`.

### Step 2: Check for ETL Code

Ask the user via `ask_user_question` (`multiSelect = false`):

> "Do you have any ETL code (SSIS or Informatica Power Center) to include in the conversion?"
>
> 1. **Yes**
> 2. **No**

- If **Yes**, ask which platform (SSIS or Informatica), then ask for the filesystem path where the ETL code is located. Store it as `<ETL_PATH>` for Step 4.
  - **If Informatica**, ask the remaining ETL questions up front, in one sequence, before running the conversion:
    1. Conversion target, via `ask_user_question` (`multiSelect = false`):
       > "How should Informatica mappings be converted?
       > 1. **dbt** (default): each mapping becomes a dbt model orchestrated by Snowflake Tasks. Supports ETL stabilization and deploy.
       > 2. **Snowflake Scripting** (preview): each mapping becomes a standalone Snowflake stored procedure the Task graph calls. Stabilization and deploy are skipped for this preview flavor."
    2. If the answer is **dbt**, also ask (`multiSelect = false`): "Consolidate dbt model chains to reduce the number of generated model files?". On yes, set `CONSOLIDATE_DBT = true` for Step 4.
    3. If the answer is **Snowflake Scripting**, set `SCRIPTING_MODE = true` for Step 4.

    Persist the choice with the MCP `configure` tool: `etl_informatica_target = "dbt"` or `"scripting"`. When the target is Snowflake Scripting, the `--informatica-to-snowflake-scripting` convert flag in Step 4 additionally records the project-level `etl_target` in `project.yml` that gates the scripting-preview routing.
  - **If SSIS**, no conversion-target prompt is needed.
- If **no**, proceed to Step 3; no `<ETL_PATH>` will be set.

### Step 3: Check for Power BI Reports

Ask the user:

> "Do you have Power BI reports (`.pbit` files) you'd like to repoint to Snowflake?"

If **yes**, load `../powerbi-repointing/SKILL.md`. It collects `PBIT_PATH` and tells you to append `--powerbi-repointing <PBIT_PATH>` to the convert command in Step 4. Return here when complete.

If **no**, proceed to Step 4. `PBIT_PATH` remains unset; do not pass `--powerbi-repointing` to scai.

### Step 4: Run Conversion

Before running, tell the user what the conversion will cover: mention ETL if `ETL_PATH` was set, and Power BI repointing if `PBIT_PATH` was set.

Always include `--json` so the agent can parse the result envelope. Append `--etl-replatform-sources-path <ETL_PATH>` and/or `--powerbi-repointing <PBIT_PATH>` only if those paths were set. If `SCRIPTING_MODE` was set (Informatica to Snowflake Scripting), also append `--informatica-to-snowflake-scripting`. If `CONSOLIDATE_DBT` was set (Informatica to dbt), also append `--consolidate-dbt-model-chains`.

**No ETL:**
```bash
scai code convert --json
```

**With ETL:**
```bash
scai code convert --etl-replatform-sources-path <ETL_PATH> --json
```

**With ETL, Snowflake Scripting (Informatica preview):**
```bash
scai code convert --etl-replatform-sources-path <ETL_PATH> --informatica-to-snowflake-scripting --json
```

Substitute the bracketed tokens with the actual paths you stored. Do not emit literal `<ETL_PATH>` or `<PBIT_PATH>` to the shell.

### Step 5: Review Results

Conversion produces:
- **Converted code** in `snowflake/`
- **Reports** in `reports/SnowConvert/`
- **Logs** in `logs/`

**Key metrics to check:**
- Files Processed
- Code Units Converted (LOC)
- Conversion Errors (should be 0)
- EWIs (Early Warning Issues), especially high/critical

### Conversion Options

| Option | Description |
|--------|-------------|
| `-x, --show-ewis` | Show detailed EWI breakdown |
| `--overwrite-working-directory` | Overwrite output files in `snowflake/` and registry |
| `--etl-replatform-sources-path <PATH>` | Path to ETL code (SSIS or Informatica) for conversion |
| `--informatica-to-snowflake-scripting` | Convert Informatica mappings to standalone Snowflake stored procedures (Snowflake Scripting) instead of dbt projects. Preview flavor; ETL stabilization and deploy are skipped for these units. |

For Power BI options, see `../powerbi-repointing/SKILL.md`.

**Example with options:**
```bash
scai code convert --show-ewis --overwrite-working-directory --json
```

## Understanding EWIs

EWIs (Early Warning Issues) indicate conversion items needing attention:

| Severity | Action Required |
|----------|----------------|
| **Critical** | Must fix before deployment |
| **High** | Should fix, may cause runtime errors |
| **Medium** | Review recommended |
| **Low** | Minor issues, optional fixes |

**Common EWI codes:**
- `SSC-EWI-0030`: Dynamic SQL (requires manual review)
- `SSC-FDM-*`: Functional differences (behavior may differ)
- `SSC-PRF-*`: Performance remarks (optimization suggested)

## Output Structure

```
snowflake/
├── <database>/
│   └── <schema>/
│       ├── table/
│       ├── view/
│       ├── procedure/
│       └── function/
└── _etl/                              # Converted ETL code (Task graph + stored procedures for scripting; dbt models for dbt)
    └── <package_name>/
        ├── <package_name>.sql         # Snowflake Task graph
        └── <data_pipeline>/
            └── models/                # dbt models (staging, intermediate, marts) when target is dbt
reports/
├── SnowConvert/
│   ├── TopLevelCodeUnits.*.csv
│   ├── Issues.*.csv
│   ├── ObjectReferences.*.csv
│   ├── Assessment.*.json
│   ├── ETL.Elements.*.csv             # ETL elements processed (packages, tasks, data flows)
│   └── ETL.Issues.*.csv               # ETL-specific conversion issues
├── ArrangeReports/
└── GenericScanner/
logs/
```

For Power BI output paths, see `../powerbi-repointing/SKILL.md`.

## CHECKPOINT

Confirm with user:
- [ ] Conversion completed without errors
- [ ] Review EWI summary (especially high/critical count)
- [ ] Converted files appear in `snowflake/`
- [ ] If ETL code was included: ETL packages processed successfully, ETL issues reviewed, and converted ETL code appears under `snowflake/_etl/`
- [ ] If Power BI reports were included, follow the CHECKPOINT addendum in `../powerbi-repointing/SKILL.md`

## On Completion

After the CHECKPOINT passes, tell the user. Fill placeholders from the JSON envelope returned by `scai code convert --json`.

> **Conversion complete.** `<filesProcessed>` files / `<codeUnitsConverted>` code units converted in `<duration>`.
>
> Issues found: `<total>` instances total
>  • EWIs: `<ewi.total>` instances across `<ewi.unique>` codes (`<critical>` critical, `<high>` high, `<medium>` medium, `<low>` low)
>  • FDMs (functional differences): `<fdm.total>` instances *(omit line if 0)*
>  • PRFs (performance remarks): `<prf.total>` instances *(omit line if 0)*
>  • OOS (out-of-scope): `<oos.total>` instances *(omit line if 0)*
>
> *If `etlReplatforming` is present:* ETL: `<etl.processedFiles>` files, `<etl.totalIssues>` issues.
> Critical EWIs require manual fix before deploy. Reports in `reports/SnowConvert/`.
>
> Next, we'll run an assessment to plan your migration: dependency waves, object categorization, and a deployment plan.

*If `SCRIPTING_MODE` was set*, also tell the user:
> Informatica mappings were converted to Snowflake Scripting stored procedures (preview). **ETL Stabilization is not supported for Snowflake Scripting conversions (dbt only)**, and deploy is not part of this preview flow - both are skipped for these ETL units. The generated procedures and Task graph are under `snowflake/_etl/` for review.

Then return to the calling skill.
