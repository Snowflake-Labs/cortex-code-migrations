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

```bash
# Check for source files
find source/ -name "*.sql" | head -10
```

If no files are found, load `../register-code-units/SKILL.md`.

### Step 2: Check for ETL Code

Ask the user via `ask_user_question` (`multiSelect = false`):

> "Do you have any ETL code (SSIS or Informatica Power Center) to include in the conversion?"
>
> 1. **Yes**
> 2. **No**

- If **Yes**, ask which platform (SSIS or Informatica).
  - **If Informatica**, present this recommendation before asking for the path:
    > For the smoothest Informatica migration, we recommend exporting your workflows using Snowflake's official DDL Export Script. This produces one XML file per workflow in a consistent format that SnowConvert and the downstream `migrate-etl-package` skill are designed to read.
    >
    > **Extraction guide:** https://github.com/Snowflake-Labs/SC.DDLExportScripts/blob/main/ETL/Informatica%20PowerCenter/README.md
    >
    > Summary:
    > 1. `pmrep connect -r <repo> -d <domain> -n <user> -x <password>`
    > 2. `python export_all_workflows.py --folder-name "<folder_name>"`
    > 3. `pmrep cleanup`
    >
    > Output: `./exports/<workflow_name>.xml`, one file per workflow.

    Then ask with `ask_user_question`:
    - "I already exported using this guide; proceed"
    - "I exported another way, but I'd like to proceed anyway"
    - "Let me re-export first; I'll provide the path when ready"

    On "re-export first", stop and wait for the user to return with the path. On either "proceed" option, continue to the filesystem path prompt below.
  - **If SSIS**, no extraction-guide prompt is needed, proceed directly to the filesystem path prompt below.
  - **After platform handling**, ask for the filesystem path where the ETL code is located. Store this path for Step 4.
- If **no**, proceed to Step 3; no `<ETL_PATH>` will be set.

### Step 3: Check for Power BI Reports

Ask the user:

> "Do you have Power BI reports (`.pbit` files) you'd like to repoint to Snowflake?"

If **yes**, load `../powerbi-repointing/SKILL.md`. It collects `PBIT_PATH` and tells you to append `--powerbi-repointing <PBIT_PATH>` to the convert command in Step 4. Return here when complete.

If **no**, proceed to Step 4. `PBIT_PATH` remains unset; do not pass `--powerbi-repointing` to scai.

### Step 4: Run Conversion

Before running, tell the user what the conversion will cover: mention ETL if `ETL_PATH` was set, and Power BI repointing if `PBIT_PATH` was set.

Always include `--json` so the agent can parse the result envelope. Append `--etl-replatform-sources-path <ETL_PATH>` and/or `--powerbi-repointing <PBIT_PATH>` only if those paths were set.

**No ETL:**
```bash
scai code convert --json
```

**With ETL:**
```bash
scai code convert --etl-replatform-sources-path <ETL_PATH> --json
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

For Power BI options, see `../powerbi-repointing/SKILL.md`.

**Example with options:**
```bash
scai code convert --database MY_DB --customschema MY_SCHEMA --json
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
artifacts/
├── ETL/                               # Converted ETL code (tasks, dbt models, etc.)
│   └── <package_name>/
│       ├── <package_name>.sql         # Snowflake tasks
│       └── <data_pipeline>/
│           └── models/                # dbt models (staging, intermediate, marts)
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
- [ ] If ETL code was included: ETL packages processed successfully, ETL issues reviewed, and converted ETL code appears in `artifacts/ETL/`
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

Then return to the calling skill.
