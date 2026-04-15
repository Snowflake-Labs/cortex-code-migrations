# SnowConvert Assessment Skill - User Guide

> **Internal Review Document** - Draft for public documentation

This guide helps users understand how to effectively use the SnowConvert Assessment Skill to analyze their migration workload and create deployment plans.

## Overview

The SnowConvert Assessment Skill analyzes your database migration workload using SnowConvert output files. It helps you:

- **Plan deployment waves** - Organize objects into deployment sequences that respect dependencies
- **Identify exclusions** - Find temporary, staging, and deprecated objects that may not need migration
- **Analyze complexity** - Assess Dynamic SQL patterns and SSIS packages for migration effort
- **Generate reports** - Create interactive HTML reports for stakeholders

## What You Can Do

This skill is designed for interactive use:

| Capability | Description |
|------------|-------------|
| 📊 **View Reports** | After analysis, an interactive HTML report is generated that you can explore |
| 🔄 **Iterate & Refine** | Ask to adjust results - change wave sizes, prioritize objects, or relocate items |
| 🎯 **Set Goals Upfront** | Specify your preferences before analysis (e.g., number of waves, priority objects) |

## Getting Started

### Prerequisites

Before using this skill, ensure you have:

1. **SnowConvert output files** from a completed assessment:
   - `ObjectReferences.csv` - Object dependencies
   - `TopLevelCodeUnits.csv` - Object metadata
   - `Issues.csv` - For Dynamic SQL analysis (optional)
   - `ETL.Elements.csv` and `ETL.Issues.csv` - For SSIS analysis (optional)

2. **Python 3.11+** installed

3. **uv package manager** installed

### What to Expect

When you invoke the skill, it will:

1. **Show a welcome message** explaining what you can do
2. **Confirm your request** before running any analysis
3. **Ask for details** if needed (paths, goals, preferences)

### Quick Start

Start by invoking the skill:

```
use skill snowconvert-assessment
```

The skill will greet you and ask for:
- Path to your SnowConvert reports directory
- Output directory for results
- Any specific goals or preferences

## Example Prompts

### Starting an Assessment

```
Run a comprehensive assessment with all analyses
```

```
Analyze my SnowConvert reports at /path/to/Reports
```

```
Start fresh analysis (don't reuse previous results)
```

### Setting Goals Upfront

**Limit Number of Waves:**
```
I want a maximum of 5 deployment waves
```

```
Create 3-4 deployment waves for easier rollout
```

**Control Wave Size:**
```
Waves should have 20-30 objects each
```

```
I need smaller batches - maximum 15 objects per wave
```

**Prioritize Objects:**
```
Prioritize all Payroll-related objects in Wave 1
```

```
Put all Customer* objects in the earliest waves
```

```
I need PKG_PAYROLL, PKG_HR, and PKG_FINANCE deployed first
```

### Refining Results After Analysis

Once you have initial results, you can refine them:

**Relocate Objects:**
```
Move dbo.CriticalTable to Wave 1
```

```
Relocate all reporting procedures to Wave 5
```

**Investigate Dependencies:**
```
Show me which objects have circular dependencies
```

```
What objects are blocking the migration?
```

```
Which objects depend on dbo.LegacyTable?
```

**Regenerate with Changes:**
```
Regenerate waves with smaller batch sizes
```

```
Redo the analysis excluding the Staging schema
```

### Working with Reports

**Generate Report:**
```
Generate the HTML report
```

**Query Results:**
```
How many objects are flagged for exclusion?
```

```
What's the breakdown by schema?
```

```
Show me a summary of the assessment
```

### Specific Analyses

**Object Exclusion:**
```
Identify temporary and staging objects
```

```
Find deprecated objects that can be excluded
```

**Dynamic SQL:**
```
Analyze Dynamic SQL patterns in my codebase
```

**SSIS/ETL:**
```
Assess my SSIS packages for migration complexity
```

## Tips for Best Results

### 1. Specify Goals Upfront

Instead of using defaults and refining later, tell the skill what you want:

❌ Less efficient:
```
Generate waves
```
Then: `Make the waves smaller`
Then: `Prioritize Payroll objects`

✅ More efficient:
```
Generate waves with 20-30 objects each, prioritizing all Payroll-related objects
```

### 2. Use Patterns for Prioritization

The skill supports wildcards for object selection:

| Pattern | Matches |
|---------|---------|
| `*Payroll*` | Any object containing "Payroll" |
| `PKG_*` | Objects starting with "PKG_" |
| `dbo.Customer*` | Objects in dbo schema starting with "Customer" |
| `*_Archive` | Objects ending with "_Archive" |

### 3. Understand Wave Ordering

By default, waves are organized by object category:
1. **TABLEs** - Deployed first (schema foundation)
2. **VIEWs** - Second (depend on tables)
3. **FUNCTIONs** - Third
4. **PROCEDUREs** - Fourth
5. **ETL/SSIS Packages** - Last (consume everything else)

If you prefer pure dependency-based ordering (mixing all types), ask:
```
Use dependency-based ordering instead of category-based
```

### 4. Iterate on Results

After the initial analysis, you can:

- **View the report** to understand the results
- **Ask questions** about specific findings
- **Request changes** like relocating objects or adjusting wave sizes
- **Regenerate** with different parameters

The skill maintains context, so you don't need to start over.

## Understanding the Output

### HTML Report

The generated HTML report includes:

| Tab | Contents |
|-----|----------|
| **Waves** | Deployment sequence with objects per wave, dependencies |
| **Object Exclusion** | Temporary, staging, deprecated objects identified |
| **Dynamic SQL** | Patterns found with complexity scores |
| **SSIS** | Package classifications and migration effort |

### Key Metrics

- **Total Objects** - Number of objects in the migration
- **Waves/Partitions** - Number of deployment batches
- **Exclusion Candidates** - Objects that may not need migration
- **Circular Dependencies** - Objects with mutual dependencies (require attention)

## Troubleshooting

### "I want different wave sizes"

Specify min and max sizes:
```
Regenerate waves with minimum 15 and maximum 30 objects per wave
```

### "Important objects are in late waves"

Use prioritization:
```
Prioritize *CriticalProcess* objects to appear in Wave 1
```

Or relocate after generation:
```
Move dbo.CriticalTable to Wave 1
```

### "I have too many waves"

Increase wave size:
```
Regenerate with larger waves - 60-100 objects each
```

### "Objects with circular dependencies"

Review the `cycles.txt` output and consider:
- Schema refactoring
- Deploying circular dependency groups together
- Manual intervention for complex cases

## FAQ

**Q: Can I run just one analysis (e.g., only waves)?**
A: Yes! Ask for the specific analysis: "Just generate deployment waves"

**Q: How do I update the analysis after code changes?**
A: Re-run the analysis with updated SnowConvert reports, or say "Start fresh analysis"

**Q: Can I export the data?**
A: Yes, the HTML report includes CSV/Excel export options

**Q: What if I disagree with object exclusion recommendations?**
A: The exclusions are recommendations - you decide what to actually exclude

**Q: How do I handle objects the skill can't categorize?**
A: Review them manually - the skill flags uncertain items for your review
