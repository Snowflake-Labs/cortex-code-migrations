---
name: convert
description: Convert extracted source code to Snowflake SQL using SnowConvert. Transforms SQL Server, Redshift, Oracle, or Teradata code to Snowflake-compatible syntax. Triggers: convert, snowconvert, transform code, convert to snowflake.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# Code Conversion

Convert extracted source code to Snowflake SQL using SnowConvert.

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

- If **yes** — ask for the filesystem path where the ETL code is located. Store this path for Step 3.
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

### Step 5: Review ETL Conversion Results (if ETL code was included)

If ETL code was included in the conversion, review the ETL-specific reports generated in `reports/SnowConvert/`.

**5a. Count ETL objects processed**

Run inline Python to parse `reports/SnowConvert/ETL.Elements.*.csv` and print a summary:

```python
import csv, glob

files = sorted(glob.glob("reports/SnowConvert/ETL.Elements.*.csv"))
if not files:
    print("No ETL.Elements CSV found.")
else:
    # Use the latest report (highest timestamp in filename)
    latest_file = files[-1]
    with open(latest_file, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print("ETL.Elements CSV is empty.")
    else:
        tech = rows[0].get("Technology", "Unknown")
        if tech == "Ssis":
            pkgs = set(
                r.get("FullName", "")
                for r in rows
                if r.get("Subtype", "") == "Package"
            )
            print(f"SSIS packages processed: {len(pkgs)}")
        elif tech == "InformaticaPowerCenter":
            wf = sum(
                1 for r in rows
                if r.get("Subtype", "") == "Workflow"
            )
            print(f"Informatica workflows processed: {wf}")
        else:
            print(f"Unknown ETL technology: {tech}")
```

Present the printed output to the user as the ETL elements summary.

**5b. Review ETL issues**

Run inline Python to parse `reports/SnowConvert/ETL.Issues.*.csv` and print issues grouped by code:

```python
import csv, glob

files = sorted(glob.glob("reports/SnowConvert/ETL.Issues.*.csv"))
if not files:
    print("No ETL.Issues CSV found.")
else:
    # Use the latest report (highest timestamp in filename)
    latest_file = files[-1]
    with open(latest_file, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print("No ETL issues found.")
    else:
        grouped = {}
        for r in rows:
            code = r.get("Code", r.get("IssueCode", "Unknown"))
            desc = r.get("Description", r.get("Title", ""))
            grouped.setdefault(code, {"description": desc, "count": 0})
            grouped[code]["count"] += 1
        print(f"{'Code':<20} {'Description':<60} {'Count':>5}")
        print("-" * 87)
        for code, info in sorted(grouped.items(), key=lambda x: -x[1]["count"]):
            print(f"{code:<20} {info['description'][:60]:<60} {info['count']:>5}")
```

Present the printed output to the user as the ETL issues summary table.

**5c. Point out converted ETL output location**

Tell the user:
> "The converted ETL code is available in the `artifacts/ETL/` directory of your project. This contains the Snowflake-compatible output (tasks, dbt models, etc.) generated from your SSIS/Informatica packages."

**5d. Generate ETL_Migration_Next_Steps.md**

Generate `artifacts/ETL/ETL_Migration_Next_Steps.md` to give the user a ready-to-use reference for fixing ETL packages.

Build the file content using data already available from Steps 5a and 5b:
- **Package list + platform**: from `reports/SnowConvert/ETL.Elements.*.csv` (packages where `Subtype` = `Package` for SSIS, `Workflow` for Informatica)
- **Issue counts per package**: from `reports/SnowConvert/ETL.Issues.*.csv`, grouped by package
- **Package folder paths**: `artifacts/ETL/<package_name>/` — use absolute paths
- **Source file paths**: resolve from the ETL source path the user provided in Step 2 — search for `.dtsx` (SSIS) or `.xml` (Informatica) files matching each package name. Use absolute paths.

**Sort the packages table by EWI count descending** (most issues first).

Write the file with this structure:

```markdown
# ETL Migration Next Steps

SnowConvert converted your ETL packages but likely left unresolved EWIs (conversion gaps).
Use the **migrate-etl-package** skill to fix these through a phase-based TDD workflow.

This file lists the packages that should go through the fixer and the prompts to invoke it.

**Platform:** <PLATFORM> | **Packages:** <COUNT> | **Total issues:** <TOTAL_ISSUES>

## Packages

| # | Package | Issues | Package Folder | Source File |
|---|---------|--------|----------------|-------------|
| 1 | <name> | <n> | <absolute_path_to_artifacts/ETL/name> | <absolute_path_to_source_file> |
| ... | ... | ... | ... | ... |

## How to Run migrate-etl-package

### Primary prompt

​```
/migration migrate-etl-package "<PACKAGE_FOLDER>" "<SOURCE_FILE>"
​```

### Fallback prompt

​```
/migration Read and follow ./migrate-objects/actions/migrate-etl-package/SKILL.md

Package folder: <PACKAGE_FOLDER>
Source file: <SOURCE_FILE>
​```

Replace `<PACKAGE_FOLDER>` and `<SOURCE_FILE>` with values from the Packages table above.
```

Tell the user:
> "Created `artifacts/ETL/ETL_Migration_Next_Steps.md` with a list of all converted packages and ready-to-use prompts for the migrate-etl-package fixer."

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

## Next Steps

**If ETL code was included in Step 2:**

> **Tip:** Your converted ETL packages likely contain unresolved EWIs (conversion gaps).
> Use the **migrate-etl-package** skill to fix these. See
> `artifacts/ETL/ETL_Migration_Next_Steps.md` for the full package list and ready-to-use prompts.

After successful conversion: go back to the calling skill.
