---
name: snowconvert-assessment
description: Analyzes workloads to be migrated to Snowflake using SnowConvert assessment reports. Routes to specialized sub-skills for high-quality assessments. Use this skill when user wants to do an assessment of their code or ETL workload, waves generation, object exclusion, sql dynamic and/or ETL analysis (SSIS)
version: 0.1.0
license: Proprietary. See License-Skills for complete terms
---

# SnowConvert Assessment

**⚠️ MANDATORY WELCOME - DO NOT SKIP**: You MUST ALWAYS present this welcome message when user invokes this skill. This applies even if the user provides specific instructions, paths, or detailed requests. NEVER skip directly to running analysis. Show this welcome FIRST, then confirm their request.

---

**Welcome to the SnowConvert Assessment Skill!**

I can help you analyze your migration workload and create deployment plans.

**What you can do:**
- 📊 **View Reports** - After analysis, I'll generate an interactive HTML report
- 🔄 **Iterate & Refine** - Ask me to adjust reports based on your project references
- 🎯 **Set Goals Upfront** - Tell me your preferences (e.g., "I want 5 waves" or "prioritize Payroll objects")

---

**⚠️ MANDATORY CONFIRMATION - DO NOT SKIP**: After showing the welcome message, you MUST confirm with the user before proceeding. Even if the user already specified what they want, acknowledge their request and confirm the details. Present:

```
I understand you'd like to [summarize user's request if they provided one].

Before I proceed, let me confirm the details:

**Please provide:**
- Path to your SnowConvert project's output (containing either a `registry/` folder with JSON files, and/or CSV reports)
- Output directory for assessment results
- Any specific goals or preferences, for example:
  - "Run a full assessment with all analyses"
  - "Do only dependencies assessment"
  - "Do only ETL analysis"

Ready to proceed?
```

**CRITICAL**: 
- NEVER skip the welcome message, even if user provides detailed instructions
- NEVER start running analysis without showing welcome + confirmation first
- ALWAYS wait for user to confirm "yes" or select an option before proceeding
- If user already specified details, acknowledge them but still confirm before running

---

## Prerequisites

Before using this skill:
- **SnowConvert outputs** from a completed assessment, in one of these formats:
  - **Registry (preferred):** A `registry/` directory containing JSON files (one per database object). This is the newer, richer format produced by recent SnowConvert CLI versions.
  - **CSV (legacy):** Traditional CSV report files:
    - `ObjectReferences.csv` (for dependency analysis)
    - `TopLevelCodeUnits.csv` (for object metadata)
- **Issues.csv** is always required for Dynamic SQL analysis (not included in registry)
- **ETL.Elements.csv** and **ETL.Issues.csv** are always required for SSIS/ETL assessment (not included in registry)
- **Python 3.11+** installed
- **uv package manager** installed (`brew install uv` or `pip install uv`)

> **Note:** Scripts require explicit paths. The skill will inspect the SnowConvert output directory and pass explicit `--registry-dir` and/or `--reports-dir` paths to scripts. Registry is preferred when available; CSV is used as supplement or fallback.

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

**⚠️ MANDATORY STOPPING POINT**: Before starting comprehensive assessment:

Present to user:
```
I will run the following assessments in sequence:
1. Dependency Analysis and Wave Generation
2. Object Exclusion Analysis
3. Dynamic SQL Pattern Analysis
4. ETL/SSIS Assessment (if SSIS packages present)
5. Generate Multi-Tab HTML Report using generate_multi_report.py

Proceed with comprehensive assessment? (Yes/No)
```

Wait for explicit approval. Do NOT proceed without confirmation.

**Upon approval, follow this sequence:**

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

1. **Check Dynamic SQL status** using the matching helper script:
   ```bash
   # Registry-first mode (preferred when registry is available)
   uv run --project <SKILL_DIRECTORY>/analyzing-sql-dynamic-patterns \
     python <SKILL_DIRECTORY>/analyzing-sql-dynamic-patterns/scripts/sql_dynamic_analyzer_registry_helper.py \
     stats <path/to/sql_dynamic_analysis.json>

   # CSV fallback mode
   uv run --project <SKILL_DIRECTORY>/analyzing-sql-dynamic-patterns \
     python <SKILL_DIRECTORY>/analyzing-sql-dynamic-patterns/scripts/sql_dynamic_analyzer_helper.py \
     stats <path/to/sql_dynamic_analysis.json>
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