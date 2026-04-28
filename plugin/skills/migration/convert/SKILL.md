---
name: convert
description: Convert extracted source code to Snowflake SQL using SnowConvert. Transforms SQL Server, Redshift, Oracle, or Teradata code to Snowflake-compatible syntax. Triggers: convert, snowconvert, transform code, convert to snowflake.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# Code Conversion

## On Entry

Tell the user:
> **Code Conversion** — I'll run SnowConvert to transform your source SQL into Snowflake-compatible syntax. This is an automated conversion — we'll review the results and address any issues afterward.

## Prerequisites

- Migration project initialized (`scai init`)
- Source code extracted in `source/` directory
- At least one `.sql` file in `source/`

## Workflow

### Step 1: Verify Source Code Exists

```bash
# Check for source files
find source/ -name "*.sql" | head -10
```

If no files found, run extraction first: `scai code extract -s <CONNECTION_NAME>`

### Step 2: Check for ETL Code

Ask the user:

> "Do you have any ETL code (SSIS or Informatica Power Center) that should be included in the conversion?"

- If **yes** — ask which platform (SSIS or Informatica).
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
    > Output: `./exports/<workflow_name>.xml` — one file per workflow.

    Then ask with `ask_user_question`:
    - "I already exported using this guide — proceed"
    - "I exported another way, but I'd like to proceed anyway"
    - "Let me re-export first — I'll provide the path when ready"

    On "re-export first", stop and wait for the user to return with the path. On either "proceed" option, continue to the filesystem path prompt below.
  - **If SSIS**, no extraction-guide prompt is needed — proceed directly to the filesystem path prompt below.
  - **After platform handling**, ask for the filesystem path where the ETL code is located. Store this path for Step 3.
- If **no** — proceed to Step 3 without the ETL flag.

### Step 3: Run Conversion

**Without ETL code:**
```bash
scai code convert
```

**With ETL code:**
```bash
scai code convert --etl-replatform-sources-path <ETL_PATH>
```

**With detailed EWI output (add `--show-ewis` to either variant):**
```bash
scai code convert --show-ewis
scai code convert --etl-replatform-sources-path <ETL_PATH> --show-ewis
```

### Step 4: Review Results

Conversion produces:
- **Converted code** in `snowflake/`
- **Reports** in `reports/SnowConvert/`
- **Logs** in `logs/`

**Key metrics to check:**
- Files Processed
- Code Units Converted (LOC)
- Conversion Errors (should be 0)
- EWIs (Early Warning Issues) - especially high/critical

### Conversion Options

| Option | Description |
|--------|-------------|
| `-x, --show-ewis` | Show detailed EWI breakdown |
| `--overwrite-working-directory` | Overwrite output files in `snowflake/` and registry |
| `--etl-replatform-sources-path <PATH>` | Path to ETL code (SSIS or Informatica) for conversion |

**Example with options:**
```bash
scai code convert --database MY_DB --customschema MY_SCHEMA --show-ewis
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
- `SSC-EWI-0030` - Dynamic SQL (requires manual review)
- `SSC-FDM-*` - Functional differences (behavior may differ)
- `SSC-PRF-*` - Performance remarks (optimization suggested)

## Output Structure

```
snowflake/
└── <database>/
    └── <schema>/
        ├── table/
        ├── view/
        ├── procedure/
        └── function/
artifacts/
└── ETL/                              # Converted ETL code (tasks, dbt models, etc.)
    └── <package_name>/
        ├── <package_name>.sql        # Snowflake tasks
        └── <data_pipeline>/
            └── models/               # dbt models (staging, intermediate, marts)
reports/
├── SnowConvert/
│   ├── TopLevelCodeUnits.*.csv
│   ├── Issues.*.csv
│   ├── ObjectReferences.*.csv
│   ├── Assessment.*.json
│   ├── ETL.Elements.*.csv            # ETL elements processed (packages, tasks, data flows)
│   └── ETL.Issues.*.csv              # ETL-specific conversion issues
├── ArrangeReports/
└── GenericScanner/
logs/
```

## CHECKPOINT

Confirm with user:
- [ ] Conversion completed without errors
- [ ] Review EWI summary (especially high/critical count)
- [ ] Converted files appear in `snowflake/`
- [ ] If ETL code was included: ETL packages processed successfully, ETL issues reviewed, and converted ETL code appears in `artifacts/ETL/`

## On Completion

After the CHECKPOINT passes, tell the user:
> **Conversion complete** — <files_processed> files converted to Snowflake SQL. <ewi_count> EWIs found (<critical_count> critical, <high_count> high). Converted code is in `snowflake/`.
> Next, we'll run an assessment to plan your migration.

Then return to the calling skill.
