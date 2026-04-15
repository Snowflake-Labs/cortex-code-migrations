---
name: object-exclusion-detection
description: Analyze SnowConvert reports for naming conventions to identify temporary/staging objects, deprecated/legacy objects, testing objects, and duplicate objects. Detects objects based on naming patterns, schema membership, version analysis, and file occurrence with integrated file path guidance for production versions.
parent_skill: assessment
license: Proprietary. See License-Skills for complete terms
---

# Object Exclusion Detection

This skill analyzes SnowConvert report data to identify temporary/staging objects, deprecated/legacy objects, testing objects, and duplicate objects based on naming conventions, schema membership, pattern detection, and file occurrence analysis. Features version analysis that automatically identifies production versions of objects with deprecated/backup/versioned variants, providing inline guidance with complete file paths. This helps with migration planning by identifying objects that may not need migration, should be prioritized for deprecation, require review due to testing-related naming patterns, or have duplicate definitions across multiple files.

## When to Use This Skill

Use this skill when:
- You have SnowConvert reports from a migration assessment
- You need to identify temporary/staging objects for cleanup review
- You need to identify deprecated/legacy objects for migration planning
- You want to identify testing objects (test, fake, mock, demo, sample patterns) for review
- You need to find duplicate objects (same object defined in multiple source files)
- You want to reduce migration scope by identifying objects that can be excluded
- You need to identify production versions of objects with multiple variants (v1, v2, backup, etc.)
- You need detailed pattern matching information and file paths for each object

## Prerequisites

Before using this skill:
1. Have SnowConvert outputs from a completed assessment:
   - **Registry (preferred):** use `scripts/analyze_naming_conventions_registry.py` with `--registry-dir`
   - **CSV (fallback):** use `scripts/analyze_naming_conventions.py` with `--reports`
2. Reports should be from a completed SnowConvert assessment run
3. (Optional) Object dependency input for dependency-aware analysis:
   - Registry includes dependencies automatically
   - CSV: `ObjectReferences.*.csv` in the reports directory

> **Explicit paths**:
> - Registry mode: `--registry-dir`
> - CSV mode: `--reports`

## Analysis Mode

This skill uses pattern-based analysis:

### Pattern-Based Analysis
- Uses predefined regex patterns to match naming conventions
- Fast and deterministic
- Good for codebases with standard naming conventions
- Includes version analysis to identify production versions

## Dependency Analysis

Dependency-aware analysis is available in both modes:
- Registry mode reads dependencies from registry.
- CSV mode reads dependencies from `ObjectReferences.*.csv` in the reports directory.

### What It Analyzes
1. **Per-Object Dependency Details**: Each categorized object includes:
   - `depends_on`: List of objects this object references/calls
   - `depended_by`: List of objects that reference/call this object
   - Category classification for each dependency (normal, deprecated, temp_staging, testing, external)

2. **Potentially Normal Objects**: Deprecated-looking objects that are heavily referenced
   - Objects with `_old`, `_bak` patterns but referenced by 3+ normal objects
   - May be incorrectly classified - requires manual review
   - Example: `util_old_format` referenced by 10 production procedures

3. **Called-By Information**: Shows which objects reference each deprecated object
   - Helps understand impact of excluding deprecated objects
   - Identifies callers that may break if deprecated object is removed

## Analysis Capabilities

This skill performs comprehensive analysis for four categories:

### Temporary & Transient Objects Detection

**Naming Pattern Detection:**
- Objects with explicit naming patterns: `tmp_`, `temp_`, `staging_`, `work_`, `_tmp`, `_temp`, `_staging`, `_work`
- Objects containing "staging" or "stg" anywhere in the name (e.g., `VLStaging_source`)
- Additional patterns: `scratch`, `interim`, `landing`, `#`, `##`, `t_`

**Schema-Based Detection:**
- **All objects in dedicated temp/staging schemas** (STAGING, STG, TEMP, TMP, WORK, WRK) are automatically included
- Ensures comprehensive coverage of staging area objects
- Can be configured to exclude schema-based detection (use `--exclude-staging-schema` flag)

### Deprecated Code Indicators Detection

**Naming Pattern Detection:**
- Objects with `_old`, `_backup`, `_archive` suffixes
- **Date-based backup patterns**: `_bak_YYYYMMDD`, `_old_YYYY`, `_old_YYYYMMDD`, `_backup_YYYYMMDD`
- Backup patterns anywhere in name: `_bak_` (e.g., `original_slow_bak_`)
- "Original" + "bak" combinations (e.g., `original_slow_bak_`)
- Duplicate objects with version numbers (`proc_v1`, `proc_v2`, `proc_v3`)
- Copy patterns: `_copy`, `_copy\d+`

**Version Analysis:**
- Automatically identifies production versions of objects with multiple variants
- Groups related objects (e.g., `MyProc`, `MyProc_v1`, `MyProc_v2`, `MyProc_bak`)
- Determines which version is production based on:
  - Base name without suffixes/version numbers (highest priority)
  - Excludes test/fake/demo variants
  - Excludes backup/archive/old variants
  - Uses version numbers to determine latest (_v3 > _v2 > _v1)
  - Uses date stamps to determine most recent
- Provides inline guidance in HTML report with complete file paths

**False Positive Reduction:**
- Excludes utility/helper functions (`old_to_new`, `old_to_`, `new_to_old` patterns)
- Excludes legacy mapping/nodes structures that are still in use
- Schema-aware detection: prefix patterns only applied to non-utility schemas or tables

### Testing Objects Detection (Naming-Based)

**Test/Fake Pattern Detection:**
- Objects with `_test`, `_fake`, `_demo`, `_sample`, `_dummy`, `_mock` patterns
- Supports both suffix (`_test$`) and infix (`_test_`) patterns
- Supports prefix patterns (`test_`, `fake_`, etc.)

**Human-Readable Reasons:**
- Provides clear reasons for why each object is identified as testing-related
- Example: "Contains 'test' pattern", "Contains 'mock' pattern"

### Duplicate Objects Detection (File-Based)

**What Are Duplicates:**
- Objects with the same `full_name` (e.g., `dbo.GetData`) defined in multiple source files
- Example: `dbo.MyProc` exists in both `MyProc.sql` and `MyProc_backup.sql`

**Primary Version Selection:**
- Automatically picks the recommended "primary" version to migrate
- Selection criteria:
  1. Objects without deprecated/backup patterns (highest priority)
  2. Higher version numbers (_v3 > _v2 > _v1)
  3. Shorter filename (tie-breaker)

**Duplicate Metadata:**
- `is_duplicate`: Boolean flag indicating if this is a duplicate entry
- `is_primary`: Boolean flag indicating if this is the recommended version
- `primary_file`: For duplicates, shows which file is the primary version
- `all_files_for_object`: List of all files containing this object
- `version_suggestion`: Recommendation on which file to use

**Dependency Warnings:**
- Duplicates that are referenced by other objects are flagged with `has_dependency_warning`
- Shows `depended_by` list of objects that reference the duplicate

## How to Use This Skill

### Basic Usage

To analyze SnowConvert reports for naming conventions:

```bash
# Registry mode (preferred)
python scripts/analyze_naming_conventions_registry.py \
  --registry-dir /path/to/project/Converted/output/registry \
  --output-dir ./analysis-output

# CSV-only (backward compatibility)
python scripts/analyze_naming_conventions.py \
  --reports /path/to/Reports/SnowConvert \
  --output-dir ./analysis-output
```

### Command-Line Options

**Registry analyzer** (`scripts/analyze_naming_conventions_registry.py`)

| Argument | Short | Required | Default | Description |
|----------|-------|----------|---------|-------------|
| `--registry-dir` | - | Yes | - | Path to SnowConvert registry directory |
| `--output-dir` | `-d` | Yes | - | Output directory for results (creates timestamped subdirectory) |
| `--exclude-staging-schema` | - | No | False | Exclude objects in Staging/Temp schemas (only match explicit naming patterns) |
| `--help` | `-h` | No | - | Show help message |

**CSV analyzer** (`scripts/analyze_naming_conventions.py`)

| Argument | Short | Required | Default | Description |
|----------|-------|----------|---------|-------------|
| `--reports` | `-r` | Yes | - | Path to SnowConvert Reports directory |
| `--output-dir` | `-d` | Yes | - | Output directory for results (creates timestamped subdirectory) |
| `--exclude-staging-schema` | - | No | False | Exclude objects in Staging/Temp schemas (only match explicit naming patterns) |
| `--help` | `-h` | No | - | Show help message |

### Example

```bash
# Basic analysis
python scripts/analyze_naming_conventions.py \
  -r /path/to/project/Converted/Reports/SnowConvert \
  -d ./analysis-output
```

### Output Files

The tool generates a timestamped directory with multiple analysis files:

```
./analysis-output/
└── exclusion_analysis_YYYYMMDD_HHMMSS/
    ├── naming_conventions.json       # Full analysis results in JSON format
    └── analysis_summary.txt          # Quick summary for reference
```

For example, if you run:
```bash
python scripts/analyze_naming_conventions.py \
  -r /path/to/Reports \
  -d ./analysis-output
```

This will generate:
- `exclusion_analysis_YYYYMMDD_HHMMSS/naming_conventions.json` (JSON data)
- `exclusion_analysis_YYYYMMDD_HHMMSS/analysis_summary.txt` (Text summary)

**Note**: To generate an HTML report, use the assessment multi-report tool:
```bash
python ../scripts/generate_multi_report.py \
  --exclusion-json ./analysis-output/exclusion_analysis_*/naming_conventions.json \
  --output exclusion_report.html
```

The HTML report includes:
- **Modern Professional UI**: Snowflake-inspired color scheme with clean, enterprise-grade design
- **Interactive filtering** by category (All, Temporary/Staging, Deprecated, Testing, Duplicates)
- **Statistics overview** with color-coded cards, counts, and percentages
- **Visual charts** (schema distribution) showing distribution
- **Integrated version analysis**: Production version guidance directly inline with deprecated objects
- **Complete file paths**: Shows exact file location for production versions
- **Dependency details**: Shows what each object depends on and what depends on it
- **Duplicate resolution**: Shows primary version recommendation and all files for each duplicate
- **Detailed object listings** with pattern matching information and version badges
- **CSV/Excel export**: Download filtered object lists for further analysis

## Output Format

The analysis produces detailed JSON output with version analysis and dependency information:

```json
{
  "summary": {
    "report_directory": "/path/to/project/Converted/Reports/SnowConvert",
    "total_objects_found": 733,
    "temp_staging_objects_count": 156,
    "deprecated_legacy_objects_count": 4,
    "testing_objects_count": 29,
    "objects_by_schema": [
      {"schema": "DW", "object_count": 217},
      {"schema": "REP", "object_count": 149},
      {"schema": "Staging", "object_count": 139}
    ],
    "objects_with_multiple_versions": 4,
    "has_dependency_data": true,
    "potentially_normal_objects_count": 2
  },
  "temporary_staging_objects": [
    {
      "name": "CC_Fact_tmp",
      "full_name": "DW.CC_Fact_tmp",
      "schema": "DW",
      "type": "TABLE",
      "source": "SnowConvert Report",
      "file": "DW.CC_Fact_tmp.Table.sql",
      "report_file": "TopLevelCodeUnits.NA.csv",
      "matched_patterns": ["_tmp$"],
      "dependencies": {
        "depends_on": [],
        "depends_on_count": 0,
        "depended_by": [{"full_name": "DW.LoadFacts", "category": "normal"}],
        "depended_by_count": 1
      }
    }
  ],
  "deprecated_legacy_objects": [
    {
      "name": "CC_Analytics_GetData_bak_20231009",
      "full_name": "DW.CC_Analytics_GetData_bak_20231009",
      "schema": "DW",
      "type": "PROCEDURE",
      "source": "SnowConvert Report",
      "file": "DW.CC_Analytics_GetData_bak_20231009.StoredProcedure.sql",
      "report_file": "TopLevelCodeUnits.NA.csv",
      "matched_patterns": ["_bak_\\d{6,8}$"],
      "production_version": "DW.CC_Analytics_GetData",
      "production_name": "CC_Analytics_GetData",
      "production_file": "DW.CC_Analytics_GetData.StoredProcedure.sql",
      "dependencies": {
        "depends_on": [{"full_name": "DW.SomeTable", "category": "normal"}],
        "depends_on_count": 1,
        "depended_by": [],
        "depended_by_count": 0
      }
    }
  ],
  "testing_objects": [
    {
      "name": "Entity5Level_fake_",
      "full_name": "Staging.Entity5Level_fake_",
      "schema": "Staging",
      "type": "VIEW",
      "source": "SnowConvert Report",
      "file": "Staging.Entity5Level_fake_.View.sql",
      "report_file": "TopLevelCodeUnits.NA.csv",
      "matched_patterns": ["_fake_"],
      "testing_reason": "Contains 'fake' pattern",
      "dependencies": {
        "depends_on": [],
        "depends_on_count": 0,
        "depended_by": [],
        "depended_by_count": 0
      }
    }
  ],
  "dependency_analysis": {
    "potentially_normal_objects": {
      "dbo.util_old_format": {
        "normal_dependent_count": 8,
        "normal_dependents": ["dbo.Proc1", "dbo.Proc2", "..."],
        "total_dependent_count": 10,
        "validation_message": "⚠️ This object is referenced by 8 normal objects. Review to confirm it should be deprecated."
      }
    },
    "has_dependency_data": true,
    "description": "Analysis of objects based on their dependency relationships. Dependency details are included in each object."
  },
  "version_analysis": {
    "objects_with_versions": [
      {
        "base_name": "cc_analytics_getdata",
        "schema": "DW",
        "type": "PROCEDURE",
        "production_version": "CC_Analytics_GetData",
        "production_full_name": "DW.CC_Analytics_GetData",
        "production_file": "DW.CC_Analytics_GetData.StoredProcedure.sql",
        "deprecated_versions": [
          {
            "name": "CC_Analytics_GetData_bak_20231009",
            "full_name": "DW.CC_Analytics_GetData_bak_20231009",
            "file": "DW.CC_Analytics_GetData_bak_20231009.StoredProcedure.sql"
          }
        ],
        "total_versions": 2
      }
    ],
    "total_object_groups": 4,
    "description": "Groups of objects with multiple versions. The production_version is the object that should be migrated."
  },
  "naming_pattern_definitions": {
    "temporary_staging_patterns": [...],
    "deprecated_legacy_patterns": [...],
    "exclusion_patterns": [...],
    "staging_schemas": ["STAGING", "STG", "TEMP", "TMP", "WORK", "WRK"]
  }
}
```

## Integration with Migration Assessment

This skill integrates with migration assessment workflows:

### Use Cases

1. **Migration Scope Reduction**: Identify temporary/staging objects that may not need migration
2. **Deprecation Planning**: Identify deprecated objects that should be marked for removal rather than migration
3. **Testing Object Review**: Identify test, fake, mock, demo, or sample objects that may need review
4. **Cleanup Review**: Generate lists of objects for cleanup before or after migration
5. **Pattern Analysis**: Understand naming conventions in your codebase

### Integration with Reports

The output can be integrated into migration assessment reports:

```python
# Use naming convention analysis in assessment reports
import json
import glob

# Find the latest analysis
json_files = glob.glob('./analysis-output/exclusion_analysis_*/naming_conventions.json')
latest = sorted(json_files)[-1]

with open(latest, 'r') as f:
    naming_data = json.load(f)

# Extract temporary/staging objects for cleanup review
temp_objects = naming_data['temporary_staging_objects']
print(f"Found {len(temp_objects)} temporary/staging objects")

# Extract deprecated objects for migration planning
deprecated_objects = naming_data['deprecated_legacy_objects']
print(f"Found {len(deprecated_objects)} deprecated/legacy objects")
```

## Pattern Definitions

### Temporary/Staging Patterns

The analyzer detects objects matching these patterns:
- Prefix patterns: `^temp_`, `^tmp_`, `^staging_`, `^stg_`, `^work_`, `^wrk_`, `^t_`, `^#`, `##`
- Suffix patterns: `_temp$`, `_tmp$`, `_staging$`, `_stg$`, `_work$`, `_wrk$`
- Contains patterns: `staging`, `\bstg\b`, `scratch`, `interim`, `landing`

### Deprecated/Legacy Patterns

The analyzer detects objects matching these patterns:
- Suffix patterns: `_old$`, `_bak$`, `_backup$`, `_archive$`, `_archived$`, `_deprecated$`, `_obsolete$`
- Version patterns: `_v\d+$` (e.g., `proc_v1`, `proc_v2`)
- Date-based patterns: `_bak_\d{6,8}$`, `_old_\d{4}$`, `_old_\d{6,8}$`, `_backup_\d{6,8}$`
- Backup patterns: `_bak_`, `original.*bak`, `original_slow`
- Copy patterns: `_copy$`, `_copy\d+$`

### Testing Patterns

The analyzer detects objects matching these patterns:
- Test/Fake patterns: `_test$`, `_test_`, `_fake$`, `_fake_`, `^test_`, `^fake_`
- Demo/Sample patterns: `_demo$`, `_demo_`, `_sample$`, `_sample_`, `^demo_`, `^sample_`
- Dummy/Mock patterns: `_dummy$`, `_dummy_`, `_mock$`, `_mock_`, `^dummy_`, `^mock_`

### Exclusion Patterns

Objects matching these patterns are excluded from deprecated detection:
- `^old_to_new`, `^old_to_`, `^new_to_old` (conversion utilities)
- `legacy_.*_nodes`, `legacy_.*_mapping` (legacy structures still in use)

## Performance Considerations

- **Large codebases**: Analysis may take several minutes for thousands of files
- **Memory usage**: ~100MB RAM per 10,000 SQL files
- **Processing speed**: Processes files sequentially; can be optimized with multiprocessing for very large codebases

## Best Practices

- Run analysis on converted SQL code (post-SnowConvert) for accurate object extraction
- Review results manually to ensure accuracy
- Use `--exclude-staging-schema` if staging schemas contain permanent objects
- Combine with other analysis tools for comprehensive migration assessment
- Cache results for large codebases to avoid re-analysis

## Limitations

- **SQL Dialect**: Assumes T-SQL syntax; may require adjustments for other dialects
- **Object Extraction**: Relies on CREATE statements or filename patterns; may miss dynamically created objects
- **Pattern Matching**: Pattern-based detection may miss edge cases; manual review recommended
- **Comment Analysis**: ASCII art detection is font-specific; may not detect all ASCII art variations
- **Schema Detection**: Schema extraction from filenames assumes standard naming convention (Schema.ObjectName.Type.sql)

## Examples

### Example 1: Basic Analysis

```bash
python scripts/analyze_naming_conventions.py \
  -r /path/to/project/Converted/Reports/SnowConvert \
  -d ./analysis-output

# Output:
# ✅ Parsed TopLevelCodeUnits.NA.csv: 733 objects
# Total Objects: 733
# Temp/Staging Objects: 156
# Deprecated/Legacy Objects: 4
# Testing Objects: 29
# Objects with Multiple Versions: 4
# ✅ Results written to: ./analysis-output/exclusion_analysis_20251205_103045/
```

### Example 2: Find Objects with Version Analysis

```bash
python scripts/analyze_naming_conventions.py \
  -r /path/to/project/Converted/Reports/SnowConvert \
  -d ./analysis-output

# Extract version analysis
python -c "
import json
import glob

# Find the latest analysis
json_files = glob.glob('./analysis-output/exclusion_analysis_*/naming_conventions.json')
latest = sorted(json_files)[-1]

with open(latest) as f:
    data = json.load(f)
    version_groups = data['version_analysis']['objects_with_versions']
    print(f\"Found {len(version_groups)} object groups with multiple versions\")
    for group in version_groups:
        prod = group['production_full_name']
        prod_file = group['production_file']
        deprecated_count = len(group['deprecated_versions'])
        print(f\"\\n✅ MIGRATE: {prod}\")
        print(f\"   File: {prod_file}\")
        print(f\"   {deprecated_count} deprecated version(s):\")
        for dep in group['deprecated_versions']:
            print(f\"   ❌ DO NOT MIGRATE: {dep['full_name']}\")
"
```

### Example 3: Find All Temporary/Staging Objects

```bash
python scripts/analyze_naming_conventions.py \
  -r /path/to/project/Converted/Reports/SnowConvert \
  -d ./analysis-output

# Filter results from latest analysis
python -c "
import json
import glob

json_files = glob.glob('./analysis-output/exclusion_analysis_*/naming_conventions.json')
latest = sorted(json_files)[-1]

with open(latest) as f:
    data = json.load(f)
    count = data['summary']['temp_staging_objects_count']
    print(f\"Found {count} temporary/staging objects\")
    
    # Group by schema
    by_schema = {}
    for obj in data['temporary_staging_objects']:
        schema = obj['schema']
        by_schema.setdefault(schema, []).append(obj)
    
    for schema, objects in sorted(by_schema.items()):
        print(f\"\\n{schema} schema: {len(objects)} objects\")
        for obj in objects[:5]:  # Show first 5
            print(f\"  - {obj['full_name']} ({obj['type']})\")
"
```

### Example 4: Find Deprecated Objects for Review

```bash
python scripts/analyze_naming_conventions.py \
  -r /path/to/project/Converted/Reports/SnowConvert \
  -d ./analysis-output

# Extract deprecated objects with production versions
python -c "
import json
import glob

json_files = glob.glob('./analysis-output/exclusion_analysis_*/naming_conventions.json')
latest = sorted(json_files)[-1]

with open(latest) as f:
    data = json.load(f)
    deprecated = data['deprecated_legacy_objects']
    
    with_production = [obj for obj in deprecated if 'production_version' in obj]
    without_production = [obj for obj in deprecated if 'production_version' not in obj]
    
    print(f\"Total deprecated objects: {len(deprecated)}\")
    print(f\"\\nWith production version: {len(with_production)}\")
    for obj in with_production:
        print(f\"  ❌ {obj['full_name']}\")
        print(f\"     ✅ Use instead: {obj['production_version']}\")
        print(f\"     File: {obj['production_file']}\")
    
    print(f\"\\nStandalone deprecated: {len(without_production)}\")
    for obj in without_production:
        print(f\"  - {obj['full_name']} (no replacement found)\")
"
```

## HTML Report Features

The HTML report (generated via the assessment multi-report tool) provides an interactive, enterprise-grade UI:

### 1. Modern Professional Design
- **Snowflake-Inspired Color Scheme** with consistent CSS variables
- **Responsive Layout** optimized for desktop, tablet, and mobile viewing
- **Smooth Animations** for hover and navigation feedback
- **Enterprise Aesthetics** suitable for stakeholder presentations

### 2. Statistics Overview Section
- **Color-Coded Summary Cards** for Total, Flagged, Temp, Deprecated, Testing
- **Dependency Analysis Banner** when dependency data is present
- **Schema Distribution Pie Chart** with per-schema counts
- **Inline Tooltips** explaining category definitions

### 3. Integrated Version Analysis
- **Inline Production Guidance** displayed directly with each object
- **Production Versions** marked with ✅ **PRODUCTION** and version count badges
- **Deprecated Versions** flagged with ⚠️ **REQUIRES REVIEW**
- **Complete File Paths** for production versions

### 4. Data Export
- **CSV/Excel Export** with version analysis data
  - Shows correct production version name
  - **Shows complete file path to production version**
  - Example: "File: DW.CC_Analytics_GetData.StoredProcedure.sql"
- **No Separate Section**: Version analysis integrated inline (no need to scroll/cross-reference)

### 5. Dependency Analysis Display
- **Per-Object Dependency Details**: Each object shows what it depends on and what depends on it
  - `depends_on`: Objects this item references/calls
  - `depended_by`: Objects that reference/call this item
  - Category classification for each dependency
- **Called-By Information**: Shows which objects reference each deprecated object
  - Expandable section showing all callers
  - Identifies problematic vs normal callers
  - Total caller count displayed
- **Dependency Validation Warnings**: Highlights deprecated objects that may actually be normal
  - Shows number of normal objects depending on it
  - Review recommendation message

### 6. Interactive Filtering
- **Category Tabs**: Professional styled filter tabs with hover effects
- **Dynamic Display**: Smooth transitions between categories
- **Visual Feedback**: Active tab highlighting with gradient backgrounds
- **Complete Object Details**: Each object card shows:
  - Full qualified name (schema.object)
  - Schema, type, and source file
  - Matched pattern badges (color-coded)
  - Version guidance (if applicable with production file path)
  - Testing reasons (if applicable)
  - Category-specific left border colors

### 7. Bulk Data Export
- **CSV Export**: Download filtered object lists (All, Temporary, Deprecated, Testing)
- **Excel Export**: Full-featured Excel files with proper formatting
- **Bulk Download**: Export all objects or filtered subsets
- **Column Headers**: Category, Object Name, Full Name, Schema, Type, File, Production Version, Patterns, Reason

### 8. Professional UI Elements
- **Modern Badges**: Rounded badges with proper spacing and colors
  - Production badge (green)
  - Deprecated version badge (red)
  - Version count badge (light blue)
  - Pattern badges (primary blue)
- **Enhanced Typography**: Professional fonts with proper weights and spacing
- **Better Spacing**: Consistent rem-based spacing throughout
- **Improved Readability**: Better contrast ratios and line heights
- **Code Display**: Monospace font for file paths and object names

## Version Analysis Deep Dive

The version analysis feature automatically groups related objects and identifies production versions:

### How It Works

1. **Groups Related Objects**: Finds objects with the same base name (e.g., `MyProc`, `MyProc_v1`, `MyProc_v2`)
2. **Prioritizes Production**: Uses heuristics to determine the production version:
   - Base name without suffixes (highest priority)
   - Latest version number (_v3 > _v2 > _v1)
   - Most recent date stamp
   - Excludes test/fake/demo/backup variants
3. **Provides Guidance**: Marks deprecated versions with production version information and file path

### HTML Report Display

**Production Version:**
```
DW.CC_Analytics_GetData
✅ MIGRATE THIS VERSION [PRODUCTION] [2 versions found]
```

**Deprecated Version:**
```
DW.CC_Analytics_GetData_bak_20231009
❌ DO NOT MIGRATE [DEPRECATED VERSION]
Correct version: DW.CC_Analytics_GetData
File: DW.CC_Analytics_GetData.StoredProcedure.sql
```

### Benefits

- **No Cross-Referencing**: All information inline with each object
- **Complete File Paths**: Know exactly which file to migrate
- **Clear Decision Making**: Immediate visual guidance (✅ migrate / ❌ don't migrate)
- **Time Savings**: Reduces decision-making time by ~90%
- **Reduces Errors**: Clear guidance prevents migrating wrong versions

## Related Skills

- **waves-generator**: Dependency analysis and wave planning for migration sequencing
- **analyzing-sql-dynamic-patterns**: SQL Dynamic code pattern detection and complexity assessment
- **migration-assessment-reporter**: Comprehensive migration assessment report generation

