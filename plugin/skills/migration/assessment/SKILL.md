---
name: assessment
description: Analyzes workloads to be migrated to Snowflake using SnowConvert assessment reports. Routes to specialized sub-skills for high-quality assessments. Use this skill when user wants to do an assessment of their code or ETL workload, waves generation, object exclusion, sql dynamic and/or ETL analysis (SSIS)
version: 0.1.0
license: Proprietary. See License-Skills for complete terms
---

# Assessment

## On Entry

Tell the user:
> **Migration Assessment** — I'll analyze your converted code to generate a migration plan: dependency waves, object categorization, dynamic SQL patterns, and a summary report. This helps us prioritize what to migrate first.

End-to-end migration assessment. The user only needs to point at the source — this skill detects the project state and, if needed, drives the migration setup (connect → init → register → convert) so that the SnowConvert reports the assessment depends on are produced automatically. The user is **never** asked for CSV paths, registry paths, or output directories.

> "I want to assess my workload" → the user provides a source → assessment runs end-to-end. Nothing else is requested.

## Step 0: Configure Session

Call the `configure` MCP tool with `project_dir` (use the current directory, or ask the user if ambiguous). If `snowflake_connection` is not set, ask which Snowflake connection to use and call `configure` again. Other settings are filled in by sub-skills as the workflow progresses.

## Step 1: Detect State

Call `migration_status`. Use `routing` from the returned JSON to decide what to do — do **not** ask the user for paths or files.

| Routing condition | Next action |
|-------------------|-------------|
| `routing.project_exists` = false | Go to **Step 2 — Bootstrap** |
| `routing.registered` = false | Go to **Step 2 — Bootstrap** |
| `routing.converted` = false | Go to **Step 2 — Bootstrap** |
| `routing.converted` = true | Skip to **Step 3 — Auto-Detect Inputs** |

## Step 2: Bootstrap (only if not yet converted)

Assessment requires SnowConvert reports. The conversion is what produces them (`TopLevelCodeUnits.*.csv`, `ObjectReferences.*.csv`, `Issues.*.csv`, `ETL.*.csv`, and the `registry/`). Do **not** prompt the user for any of those files — bootstrap will create them.

Ask the user the **single source question** and nothing else:

> "To assess your workload I need to first set up the migration project.
>
> What is your source?
> 1. Use an existing scai connection (I'll list the configured ones)
> 2. Create a new connection (SQL Server or Redshift)
> 3. A folder of local `.sql` files I should register as-is"

Then load `../setup/SKILL.md` and let it drive bootstrap end-to-end. The setup skill handles connect → `scai init` → register → `scai code convert`. Do not duplicate any of its prompts here.

When setup returns:
1. Call `migration_status` again.
2. Verify `routing.converted` is now true.
3. If conversion did not complete, surface the failure and stop — assessment cannot run without reports. Do not fall back to asking the user for files.

## Step 3: Auto-Detect SnowConvert Outputs

Resolve all inputs from `project_dir`. Do not prompt the user.

| Input | Resolution |
|-------|------------|
| SnowConvert reports dir | `<project_dir>/reports/SnowConvert/` |
| Registry dir (preferred when present) | First match of `<project_dir>/output/registry/`, `<project_dir>/reports/SnowConvert/registry/`, `<project_dir>/registry/` containing `*.json` entries |
| Issues CSV | `<project_dir>/reports/SnowConvert/Issues.*.csv` (latest timestamp) |
| ETL Elements / Issues CSVs | `<project_dir>/reports/SnowConvert/ETL.Elements.*.csv` and `ETL.Issues.*.csv` (only if present — drives whether SSIS analysis is included) |
| Assessment output dir | `<project_dir>/assessment/` (create if missing) |

Selection rules:
- If a `registry/` directory with JSON entries is found, use **registry mode** and pass `--registry-dir`. Pass `--snowconvert-reports-dir` as well — the multi-report needs CSV-only fields.
- If only CSVs are present, use **CSV mode** and pass `--reports-dir` / `--snowconvert-reports-dir`.
- If neither is present after a successful-looking convert, re-run `../convert/SKILL.md` once and stop if it still produces nothing.

## Step 4: Confirm Scope (single, short)

Show one compact confirmation that lists what will run. This is the **only** confirmation between source-question and execution.

```
I will run:
1. Waves (dependency analysis + deployment partitioning)
2. Object Exclusion
3. Dynamic SQL Patterns
4. ETL/SSIS Assessment  (only if present)
5. HTML Report

Proceed with all, or pick a subset?
```

Wait for "yes" or a subset selection, then run. Do not re-prompt for files or directories at any later point.

## Prerequisites

Handled automatically by Steps 0–3. The skill assumes:
- `scai` CLI is installed (used by `setup` and `convert`).
- Python 3.11+ and `uv` are available for assessment scripts (`brew install uv` or `pip install uv`).

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
- "Move dbo.CriticalTable to Wave 1"
- "Relocate all reporting procedures to Wave 5"
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

**🚫 NEVER WRITE CUSTOM HTML REPORTS:** When delivering results to users, you MUST use `generate_multi_report.py` from `scripts/`. Do NOT write HTML manually under any circumstances. See [Report Generation](#report-generation) section.

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

**Dynamic SQL Analysis** - Classify and score Dynamic SQL patterns:
- Triggers: "dynamic sql", "sql dynamic patterns"
- Supports: SQL Server and Redshift migrations
- Load: `analyzing-sql-dynamic-patterns/SKILL.md`

**ETL/SSIS Assessment** - Analyze SSIS packages for migration complexity:
- Triggers: "ssis", "etl packages", "ssis analysis"
- Load: `etl-assessment/SKILL.md`

**Multiple Assessments** - Load all applicable sub-skills if request requires comprehensive analysis.

## Running Scripts
When running any scripts in any of the above skills, make sure to do all of the following:

When running python scripts, use `uv run --project <DIRECTORY THIS SKILL.md file is in> python <DIRECTORY THIS SKILL.md file is in>/scripts/script_name.py` to run them.
Do not `cd` into another directory to run them, but run them from whatever directory you're already in. 

**WHY:** This maintains your current working context and prevents path confusion. When using `uv run --project`, you must provide absolute paths for BOTH the `--project` flag AND the script itself. Just run the script the way the skill says. Do not question it by running --help or reading the script.

## Assessment Integration

### Complete Migration Assessment Workflow

The user has already confirmed scope in **Step 4**. Do **not** re-prompt for confirmation here — execute the agreed sequence directly.

**Sequence:**

1. **Waves Generation** (First)
   - Analyze remaining objects' dependencies
   - Create deployment waves with proper ordering
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
   - Use `generate_multi_report.py` script - see [Report Generation](#report-generation) section
   - Pass all available JSON outputs from previous steps
   - 🚫 Do NOT write custom HTML - the script handles all formatting

## Tools

### generate_multi_report.py

**Description**: Generates unified multi-tab HTML report combining Object Exclusion, Dynamic SQL Analysis, Waves, and SSIS Assessment reports.

**Location**: `scripts/generate_multi_report.py`

**When to use**: After completing any requested assessment(s) (1, 2, 3, or all) to deliver results in a consistent format, or whenever the user requests a combined HTML report.

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

## Report Generation

### ⚠️ CRITICAL: Multi-Tab HTML Report Generator

**⚠️ MANDATORY: Check for Incomplete Analysis Before Report Generation**

Before generating the report, you **MUST** check for incomplete analysis and warn the user:

1. **Check Dynamic SQL status:**
   ```bash
   scai assessment sql-dynamic stats <path/to/sql_dynamic_analysis.json>
   ```

2. **Check SSIS status** using the ETL analyzer:
   ```bash
   uv run --project <SKILL_DIRECTORY>/etl-assessment \
     python -m scai_assessment_analyzer etl <path/to/etl_assessment_analysis.json> stats
   ```

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

**MANDATORY:** When users request an assessment report (even if it’s only one sub-assessment), a migration report, or a combined HTML report—or when you have completed the requested assessment(s) and are ready to deliver results—you **MUST** use `generate_multi_report.py`. This is the **ONLY** approved method for generating consolidated assessment reports.

**DO NOT:**
- Write custom HTML reports manually
- Use individual sub-skill report generators in isolation
- Create new report generation scripts

**Script Location:** `scripts/generate_multi_report.py`

**Usage with uv:**
```bash
uv run --project <SKILL_DIRECTORY> \
  python <SKILL_DIRECTORY>/scripts/generate_multi_report.py \
  --exclusion-json "path/to/assessment/object_exclusion.json" \
  --dynamic-sql-json "path/to/assessment/json/sql_dynamic_analysis.json" \
  --waves-analysis-dir "path/to/waves/dependency_analysis_TIMESTAMP" \
  --snowconvert-reports-dir "path/to/results/conversions/CONVERSION_ID/Reports" \
  --ssis-json "path/to/ssis/etl_assessment_analysis.json" \
  --output "path/to/assessment/multi_report.html"
```

**Note**: Replace `<SKILL_DIRECTORY>` with the absolute path to this skill directory.

**Parameters:**
- `--exclusion-json`: Path to object exclusion JSON file (output from object exclusion detection)
- `--dynamic-sql-json`: Path to dynamic SQL analysis JSON file (from json/ subdirectory)
- `--waves-analysis-dir`: Path to waves dependency analysis directory (contains deployment_partitions.json)
- `--registry-dir`: Path to SnowConvert registry directory containing `*.json` entries
- `--snowconvert-reports-dir`: Path to SnowConvert Reports directory containing `TopLevelCodeUnits.*.csv` and `ObjectReferences.*.csv` (CSV supplement/fallback when needed)
- `--ssis-json`: Path to SSIS assessment JSON file (etl_assessment_analysis.json from ETL assessment)
- `--output`: Output HTML file path (required)

**Note:** At least one data source parameter must be provided. If only partial assessment was completed, provide only the available data sources.

**SSIS Report Generation:** When SSIS packages are analyzed using the ETL assessment sub-skill, the resulting `etl_assessment_analysis.json` file should be provided via `--ssis-json` to include the SSIS tab in the unified report.

## Report Styling

When generating HTML reports, see `STYLES.md` for styling specifications.

## Success Criteria

An assessment is complete when:
- ✅ All requested analyses have completed without errors
- ✅ For Dynamic SQL: All occurrences have status `REVIEWED` (no `PENDING` records)
- ✅ Reports generated successfully with all requested data sources ** using `generate_multi_report.py` (NOT custom HTML) **
- ✅ User has reviewed and approved findings

### Pre-Completion Checklist

Before marking assessment as complete, verify:

```
□ Did I use generate_multi_report.py for the final report?
□ Did I pass all available JSON files to the script?
□ Did I avoid writing any custom HTML?
```

If any answer is "No", go back and use the correct script.

## Sub-Skill Documentation

- `waves-generator/SKILL.md` - Algorithm details, partition creation
- `object_exclusion_detection/SKILL.md` - Pattern definitions, naming conventions
- `analyzing-sql-dynamic-patterns/SKILL.md` - Pattern classification, complexity scoring
- `etl-assessment/SKILL.md` - SSIS package analysis, control flow, data flow pipelines

## On Completion

Tell the user:
> **Assessment complete** — Generated a migration report with <N> deployment waves covering <M> objects. The report is at `<report_path>`. Key findings: <top 2-3 findings from the report, e.g., "12 objects with critical EWIs, 3 waves planned, 5 objects flagged for exclusion">.

Then return to the calling skill.
