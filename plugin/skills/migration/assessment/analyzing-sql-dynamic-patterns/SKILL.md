---
name: sql-dynamic-pattern-analyzer
description: Analyzes Dynamic SQL occurrences from SnowConvert issues, classifies patterns, scores complexity, provides migration considerations. Use for analyzing dynamic SQL patterns in SQL Server or Redshift to Snowflake migrations. Supports both platforms with platform-specific pattern definitions.
parent_skill: assessment
license: Proprietary. See License-Skills for complete terms
---

# Analyzing SQL Dynamic Patterns

Analyzes Dynamic SQL occurrences from SnowConvert issues, classifies patterns, add complexity, provides migration considerations to Snowflake. Supports both **SQL Server** and **Amazon Redshift** source platforms.

## Critical Rules

**NO CUSTOM SCRIPTS:** ONLY use the approved helper scripts:
- `scripts/sql_dynamic_analyzer_registry_helper.py` when `registry/` is available
- `scripts/sql_dynamic_analyzer_helper.py` for CSV fallback
Never create bash loops, automation scripts, or batch processing tools.

**NO BATCH UPDATES:** Each `update` command processes **ONE** record with **ONE** unique analysis.
- Do **not** “walk IDs” sequentially (e.g., 15, 16, 17, …) as a batch just because they are adjacent.
- Do **not** use bash loops / one-liners (e.g., `for id in ...; do python ... update ...; done`) to apply updates across many records.
- Do **not** copy/paste the same notes across multiple IDs; even within the same code unit, each occurrence must have its own specific rationale.

**CODE-UNIT-BASED WORKFLOW:** Use `show-file` to view all occurrences within a code unit (procedure/function). Analyze each code unit separately by reading its source code.
- The generated `sql_dynamic_analysis.json` stores the **full code unit text inside each record’s `metadata`** (e.g., `metadata.procedure`, plus location context like `metadata.filename` and `metadata.code_unit_start_line`). Treat the JSON as the “source bundle” for analysis.

**QUALITY OVER SPEED:** This work is often fast, but do not “rush” by batching, reusing notes, or skipping code review. Total time depends on the number of occurrences and how complex the code units are; aim for consistent, defensible analyses.

## Source Platform Detection

**CRITICAL FIRST STEP:** Before analyzing Dynamic SQL patterns, determine the source platform:

**Detection Methods:**
1. **Check TopLevelCodeUnits.csv**: Look at the `SourceLanguage` column (e.g., "Transact" for SQL Server, "RedShift" for Redshift)
2. **Examine code syntax**:
   - **SQL Server indicators**: `sp_executesql`, `EXEC(@sql)`, `QUOTENAME()`, `sys.*` catalog views
   - **Redshift indicators**: `EXECUTE ... USING`, `QUOTE_IDENT()`, `QUOTE_LITERAL()`, `pg_catalog.*`, `plpgsql` functions
3. **Review source file extensions**: `.sql`, `.prc`, `.fnc` (check content for platform-specific syntax)

**Pattern File Selection:**
- **SQL Server → Snowflake**: Use `reference/PATTERNS_TRANSACT.md`
- **Redshift → Snowflake**: Use `reference/PATTERNS_REDSHIFT.md`

⚠️ **IMPORTANT**: Always confirm the source platform with the user if unclear. The pattern definitions differ significantly between platforms.

## Prerequisites

Before running this analysis, choose one mode:

1. **Registry-only mode (preferred)**
   - `registry/` directory containing SnowConvert JSON objects
   - Use `scripts/sql_dynamic_analyzer_registry_helper.py`
   - No CSV report inputs required

2. **CSV fallback mode**
   - `Issues.csv` (required)
   - `TopLevelCodeUnits.csv` or `--registry-dir` supplement
   - Source code directory (`--source-dir`)
   - Use `scripts/sql_dynamic_analyzer_helper.py`

## Workflow

Follow these steps for the workflow:

1. **Generate:**
   - Registry-only (preferred): `generate --registry-dir /path/to/output/registry`
   - CSV fallback: `generate Issues.csv --top-level-code-units TopLevelCodeUnits.csv --source-dir /path/to/source`

   → Creates sql_dynamic_analysis.json with metadata and code
2. **Show file:** `show-file --id N` → View all occurrences within the code unit containing record N
3. **Analyze:** Review the procedure code (stored in metadata), classify patterns
4. **Update:** `update --id N --status REVIEWED --category "X" --complexity "Y" --notes "Z"` → For each occurrence in that code unit
5. **Track:** `stats` → Check progress
6. **Repeat:** Steps 2-4 for next code unit until ALL rows have status 'REVIEWED'

### 1. Generate JSON

Generate `sql_dynamic_analysis.json` containing dynamic SQL occurrences grouped by procedure.

**Registry-only command (preferred):**
```bash
python scripts/sql_dynamic_analyzer_registry_helper.py generate \
  --registry-dir path/to/output/registry \
  --output sql_dynamic_analysis.json
```

**CSV fallback command:**
```bash
python scripts/sql_dynamic_analyzer_helper.py generate Issues.csv \
  --top-level-code-units TopLevelCodeUnits.csv \
  --source-dir path/to/source \
  --output sql_dynamic_analysis.json
```

**What This Creates:**
- JSON file with code units (procedures/functions) as top-level groups
- Each code unit contains metadata (name, location, full procedure code)
- Each code unit lists all dynamic SQL occurrences within it
- All occurrences start with status `PENDING` - ready for analysis

### 2. View Code Units

View all occurrences grouped by code unit (procedure/function) to organize your analysis.

```bash
python scripts/sql_dynamic_analyzer_registry_helper.py show-file sql_dynamic_analysis.json --id N
```

**What This Shows:**
- The code unit in the file containing record N
- For each code unit: start line in the file, lines of code and number of occurrences.
- All record IDs within each code unit with their line where the dynamic sql happens, status (PENDING/REVIEWED), categories and complexity.

**How to view the procedure/function code (recommended):**

```bash
# Include procedure code for each code unit shown in the file output
python scripts/sql_dynamic_analyzer_registry_helper.py show-file sql_dynamic_analysis.json --id N --include-code
```

**Analysis Approach:**
1. Use `show-file` to view all code units in a file
2. Select one code unit to analyze
3. Review the procedure code output (from `show-file --include-code`)
4. **Open** `reference/PATTERNS_[DIALECT].md` (selected in [Source Platform Detection](#source-platform-detection)) and classify the dynamic SQL patterns you see
5. Update each occurrence individually
6. Move to next code unit

### 3. Classify Pattern & Analyze

**Reference per dialect (must-read):**
- **SQL Server migrations**: `reference/PATTERNS_TRANSACT.md` for ALL pattern definitions
- **Redshift migrations**: `reference/PATTERNS_REDSHIFT.md` for ALL pattern definitions

⚠️ **Select the correct patterns file based on your source platform** (see [Source Platform Detection](#source-platform-detection))

**Process:**
1. Read ALL pattern definitions from the appropriate PATTERNS file
2. Compare the source code against EACH pattern
3. Identify ALL patterns that apply (multiple patterns can apply to one occurrence)
4. Collect analysis information for notes (see guidelines below)
5. List patterns as pipe-separated values in the `--category` field

**Analysis Guidelines:**

While analyzing the code, collect the following information:

**generated_sql:**
- Extract the actual SQL string that would be executed at runtime
- Include the dynamic SQL construction logic to show what gets generated
- Use representative values for variables where applicable
- Provide a complete best-effort SQL statement; avoid ellipses (...) or vague/incomplete output

**sql_classification:**
- Classify the type of SQL operation: DQL (SELECT), DML (INSERT/UPDATE/DELETE), DDL (CREATE/ALTER/DROP), DCL (GRANT/REVOKE), TCL (COMMIT/ROLLBACK), or UNKNOWN
- This helps prioritize migration based on SQL operation type
- **Pattern tagging is separate**: use the dialect-appropriate `reference/PATTERNS_[DIALECT].md` to choose pattern names and record them in `--category` (pipe-separated). Do not infer patterns from `sql_classification`.

**justification (notes field):**
- Explain why this occurrence was classified into each identified pattern
- Reference specific code elements that demonstrate the pattern(s)
- Provide context about what the dynamic SQL accomplishes
- Minimum length: 40+ words; write full sentences (no terse bullets)
- Avoid “similar to occurrence ##”; restate the needed context explicitly

**complexity (notes field):**
- Identify technical factors that affect migration difficulty
- Document any deviations from the base pattern complexity score
- Focus on observable code characteristics
- Minimum length: 30+ words; write full sentences (no terse bullets)
- Avoid “similar to occurrence ##”; restate the needed context explicitly

**migration_considerations (notes field):**
- Recommend Snowflake-specific migration approaches
- Identify alternative implementation strategies where applicable
- Estimate migration effort based on code complexity
- Minimum length: 40+ words; write full sentences (no terse bullets)
- Avoid “similar to occurrence ##”; restate the needed context explicitly

### 4. Score Complexity

**Scale:** low (0-30), medium (31-60), high (61-85), critical (86-100)

**Base Scoring:**
- Each pattern in the dialect-appropriate `PATTERNS_[DIALECT].md` has a default risk level, effort estimation, and complexity score
- Start with the base score from the identified pattern(s)

**Process:**
1. Review base complexity from pattern definition in the selected `PATTERNS_[DIALECT].md`
2. Analyze actual code context thoroughly
3. Apply override **only if** code materially differs from pattern baseline
4. Document override reasoning in notes under `COMPLEXITY` section

### 5. Update CSV

```bash
python scripts/sql_dynamic_analyzer_registry_helper.py update \
  sql_dynamic_analysis.json \
  --id <id> \
  --line <line_number> \
  --status REVIEWED \
  --category "Pattern-Name | Additional-Pattern" \
  --complexity medium \
  --generated-sql "CREATE TABLE dbo.TempTable (ID INT, Name VARCHAR(100))" \
  --sql-classification "DDL" \
  --notes '{
    "justification": "Line X uses dynamic SQL to construct table names based on user input variables...",
    "complexity": "- Deep concatenation chains (5+ levels)\n- No input validation detected\n- Cross-schema dynamic references",
    "migration_considerations": "- Recommend using Snowflake IDENTIFIER() function\n- Implement input validation before migration\n- Estimated effort: 4-6 hours per occurrence"
  }'
```

**Command Syntax:**
- First positional argument is the JSON file path
- `--id` is required to specify which record to update
- `--line` is supported in **registry mode** and should be set after reviewing procedure code
- At least one of `--line`, `--status`, `--category`, `--complexity`, `--notes`, `--generated-sql`, or `--sql-classification` must be provided

**Registry Mode Line Instruction (Required):**
- Registry-generated records start with `line = 0`.
- After analysis, update each reviewed occurrence with `--line <line_number>` based on `show-code-unit` / `show-file --include-code` output.
- Keep `line = 0` only if source text is unavailable or line cannot be reliably determined.

**Notes Format:**
- Use JSON with three required keys: `justification`, `complexity`, `migration_considerations`
- Escape quotes and newlines as needed for bash
- Use `\n` for line breaks within multi-line fields
- Single-quote the entire JSON to avoid bash interpretation issues

### 7. Monitor Progress

Check analysis progress at any time:

```bash
python scripts/sql_dynamic_analyzer_registry_helper.py stats sql_dynamic_analysis.json
```

**Important Notes:**
- Total time depends on the number of occurrences and code-unit complexity.
- **DO NOT attempt to accelerate or batch process** — focus on consistent, defensible analyses.

## Notes Structure

Each update must include notes in **JSON format** with 3 required keys:

```json
{
  "justification": "Why this is dynamic SQL, what it does, context",
  "complexity": "Technical factors affecting migration difficulty",
  "migration_considerations": "Snowflake-specific recommendations, alternatives, effort estimate"
}
```

**Formatting:**
- Use `\n` for line breaks within multi-line fields
- Keep content factual and based on code analysis
- Avoid generic statements; be specific to the analyzed code

## Reference Files

- `reference/SQL_DYNAMIC_ANALYSIS_REGISTRY.md` - Registry-only helper commands (preferred)
- `reference/SQL_DYNAMIC_ANALYSIS_CSV.md` - CSV fallback helper commands
- `reference/PATTERNS_TRANSACT.md` - Pattern definitions for SQL Server migrations
- `reference/PATTERNS_REDSHIFT.md` - Pattern definitions for Redshift migrations

**Platform Selection Guide:**
- Use `PATTERNS_TRANSACT.md` for SQL Server → Snowflake migrations
- Use `PATTERNS_REDSHIFT.md` for Redshift → Snowflake migrations