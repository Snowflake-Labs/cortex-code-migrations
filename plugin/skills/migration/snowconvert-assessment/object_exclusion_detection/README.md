# Object Exclusion Detection

A tool for analyzing SnowConvert reports to identify temporary/staging, deprecated/legacy, testing, and duplicate database objects with integrated version analysis and modern enterprise UI.

## 🚀 Quick Start

### Basic Analysis
```bash
python scripts/analyze_naming_conventions.py /path/to/SnowConvert/Reports --output results.json
```

### Skip HTML Generation
```bash
python scripts/analyze_naming_conventions.py /path/to/SnowConvert/Reports --output results.json --no-html
```

### Generate an HTML Report (via multi-report)
```bash
python ../scripts/generate_multi_report.py --exclusion-json results.json --output exclusion_report.html
```

## 📊 Output

The analyzer generates:
- **JSON Report** (`results.json`): Detailed classification with version analysis and file paths

To view results in HTML, generate a report using the assessment multi-report tool:
```bash
python ../scripts/generate_multi_report.py --exclusion-json results.json --output exclusion_report.html
```

## ✨ Key Features

### Version Analysis
✅ **Automatic Production Detection** - Identifies the correct version to migrate  
✅ **Inline Guidance** - Shows production version directly with deprecated objects  
✅ **Complete File Paths** - Displays exact file location for production versions  
✅ **No Cross-Referencing** - All information in one place  
✅ **Visual Badges** - Clear ✅ MIGRATE / ❌ DON'T MIGRATE indicators

### Modern Enterprise UI
✅ **Professional Design** - Snowflake-inspired color scheme  
✅ **Interactive Filtering** - Filter by category (All, Temp, Deprecated, Testing, Duplicates)  
✅ **Visual Charts** - Bar, doughnut, and schema distribution charts  
✅ **Data Export** - Download filtered lists as CSV or Excel  
✅ **Responsive Layout** - Works on desktop, tablet, and mobile

## 📁 What Gets Classified

### Temporary/Staging Objects
Objects used for intermediate data processing:
- Staging schema objects (STAGING, STG, TEMP, TMP)
- Naming patterns: `tmp_`, `temp_`, `staging_`, `work_`, `_tmp`, etc.
- ETL intermediate objects and landing tables

### Deprecated/Legacy Objects  
Objects that appear outdated or obsolete with version detection:
- **Version Analysis**: Groups related objects (e.g., MyProc, MyProc_v1, MyProc_v2)
- **Production Identification**: Automatically determines which version to migrate
- Backup objects: `_bak`, `_backup_20231009`, `_old_2023`
- Versioned objects: `_v1`, `_v2`, `_copy`, `_copy2`
- **File Path Guidance**: Shows exact file location for production versions

### Testing Objects
Objects that appear to be test/development artifacts:
- Test patterns: `_test`, `test_`, `_fake`, `fake_`
- Demo/sample patterns: `_demo`, `_sample`, `demo_`, `sample_`
- Mock/dummy patterns: `_mock`, `_dummy`, `mock_`, `dummy_`
- Objects that may not belong in production

### Duplicate Objects
Objects with the same full name defined in multiple source files:
- **Primary Selection**: Automatically picks the recommended version to migrate
- **File Comparison**: Identifies which file is likely the production version
- **Dependency Warnings**: Flags duplicates that have dependents
- Helps decide which source file to use during migration

## 🔄 Version Analysis Example

### JSON Output
```json
{
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
    ]
  }
}
```

### HTML Display

**Production Version:**
```
DW.CC_Analytics_GetData
Schema: DW | Type: PROCEDURE | File: DW.CC_Analytics_GetData.StoredProcedure.sql
✅ MIGRATE THIS VERSION [PRODUCTION] [2 versions found]
```

**Deprecated Version:**
```
DW.CC_Analytics_GetData_bak_20231009
Schema: DW | Type: PROCEDURE | File: DW.CC_Analytics_GetData_bak_20231009.StoredProcedure.sql
❌ DO NOT MIGRATE [DEPRECATED VERSION]
Correct version: DW.CC_Analytics_GetData
File: DW.CC_Analytics_GetData.StoredProcedure.sql
```

## 📊 Modern HTML Report Features

### Visual Elements
- **Color-Coded Statistics Cards**: Category-specific borders (Primary, Warning, Danger, Info)
- **Schema Distribution Chart**: Pie chart with per-schema totals
- **Dependency Analysis Banner** (when available)
- **Integrated Version Analysis**: Production guidance inline with deprecated objects
- **Professional Badges**: Production (green), Requires Review (orange), Version count (blue)

### User Experience
- **Filter Tabs**: Switch between All, Temporary, Deprecated, Testing, Duplicates
- **Schema Filter**: Narrow temp/staging objects by schema
- **Hover Effects**: Smooth animations and visual feedback
- **Responsive Design**: Optimized for all screen sizes
- **Export Functionality**: Download CSV/Excel filtered by category

## 🎯 Use Cases

### Migration Assessment
Identify objects that shouldn't be migrated:
- Temporary/staging tables (ETL intermediate objects)
- Legacy backup objects with clear production alternatives
- Test/demo/fake procedures
- **Version Analysis**: Automatically identify production versions to migrate

### Migration Decision Support
Get immediate guidance:
- ✅ **Production Versions**: Clear "MIGRATE THIS" indicators
- ❌ **Deprecated Versions**: Clear "DO NOT MIGRATE" warnings with alternatives
- 📁 **File Paths**: Complete path to production version files
- 🔢 **Version Counts**: See how many versions exist for each object

### Code Cleanup Planning
Find technical debt before or after migration:
- Objects with multiple versioned variants
- Backup objects that can be removed
- Test/fake objects in production
- Testing-related naming patterns

### Scope Reduction
Reduce migration scope systematically:
- Exclude temporary/staging schemas
- Identify deprecated objects for removal
- Filter out test objects
- Calculate potential scope reduction percentage

## 📚 Documentation

- **[SKILL.md](./SKILL.md)** - Complete skill documentation and API reference
- **[LICENSE.txt](./LICENSE.txt)** - License information

## 📦 Requirements

```bash
# Python 3.7+
# No external dependencies required (uses only standard library)
```

## 🛠️ Command-Line Options

```bash
# Show help
python scripts/analyze_naming_conventions.py --help

# Basic analysis
python scripts/analyze_naming_conventions.py REPORT_DIR --output results.json

# Skip HTML generation
python scripts/analyze_naming_conventions.py REPORT_DIR --output results.json --no-html

# Generate HTML report with the multi-report tool
python ../scripts/generate_multi_report.py --exclusion-json results.json --output exclusion_report.html
```

## 📊 Example Output

```
🔍 Analyzing SnowConvert reports in: /path/to/SnowConvert/Reports
  ✅ Parsed TopLevelCodeUnits.NA.csv: 733 objects (utf-8-sig)

============================================================
📊 Naming Convention Analysis Summary:
  Report Directory: SnowConvert
  Total Objects: 733
  Temp/Staging Objects: 156
  Deprecated/Legacy Objects: 4
  Testing Objects: 29
  Duplicate Objects: 12
  Objects with Multiple Versions: 4
============================================================

✅ Results written to: naming_conventions.json
ℹ️ HTML report generation is handled by the assessment multi-report tool.
```

## 🎨 UI Design

### Color Scheme
- **Primary**: #29b5e8 (Snowflake Blue)
- **Secondary**: #11567f (Dark Blue)
- **Success**: #10b981 (Green) - Production versions
- **Warning**: #ff9f36 (Orange) - Temporary/Staging
- **Danger**: #ef4444 (Red) - Deprecated
- **Info**: #71d3dc (Light Blue) - Testing
- **Purple**: #8b5cf6 (Purple) - Duplicates

### Design Philosophy
- Professional enterprise-grade aesthetics
- Consistent with Snowflake and migration assessment tools
- Optimized for stakeholder presentations
- Clear visual hierarchy and intuitive navigation

## 📄 License

See [LICENSE.txt](./LICENSE.txt)

