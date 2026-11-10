# SnowConvert Assessment Skill - User Guide

> **Internal Review Document** - Draft for public documentation

This guide helps users understand how to effectively use the SnowConvert Assessment Skill to analyze their migration workload and create deployment plans.

## Overview

The SnowConvert Assessment Skill analyzes your database migration workload using SnowConvert output files. It helps you:

- **Find business use cases** - Identify the outcomes your workload delivers (reports, marts, feeds) and plan one migration wave per use case, its objects in dependency order
- **Identify exclusions** - Find temporary, staging, and deprecated objects that may not need migration
- **Surface migration optimization opportunities** - Group SnowConvert findings into performance, architecture/security, and behavior/semantic risk buckets (SQL Server)
- **Analyze complexity** - Assess Dynamic SQL patterns and SSIS packages for migration effort
- **Map data lineage** - See sources, pipelines, targets, and reports; include Power BI `.pbit` files when you have a reporting layer to enrich the graph
- **Generate reports** - Create interactive HTML reports for stakeholders

## What You Can Do

This skill is designed for interactive use:

| Capability | Description |
|------------|-------------|
| 📊 **View Reports** | After analysis, an interactive HTML report is generated that you can explore |
| 🔄 **Iterate & Refine** | Ask to start with a different use case, or for a wave around an app or process |
| 🎯 **Set Goals Upfront** | Name the application or process that matters most, and it gets its own use case |

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
use skill assessment
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

### Business Use Cases and Waves

Every assessment finds the workload's business use cases without asking for a
wave size or priorities. Each use case becomes one wave, and its objects deploy
in dependency order. The top three are shown in chat; the dashboard's
**Wave Planning** section (Preview) lists every use case with its narrative, counts and
deployment stages.

**Start with a different use case:**
```
Make Loan Decision Audit wave 1
```

**A wave around an application, process or object:**
```
Create a wave for the payroll app
```

```
Find the use case behind the Store Stock report
```

**Size-based waves, on request:** the earlier bin-packed waves remain
available when you ask for them by size or pattern. They replace the business
plan until you ask for business waves again.
```
Generate waves of 20-30 objects each, prioritizing *Payroll*
```

### Refining Results After Analysis

Once you have initial results, you can refine them:

**Change the Wave Plan:**
```
Put the stock report use case first
```

```
Add dbo.CriticalTable to its own use case
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
Find the business use cases again
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

**Optimization Opportunities (SQL Server):**
```
Show me the migration optimization opportunities in my workload
```

**Dynamic SQL:**
```
Analyze Dynamic SQL patterns in my codebase
```

**SSIS/ETL:**
```
Assess my SSIS packages for migration complexity
```

**Data Lineage with Power BI:**
```
Include my Power BI reports — here's the folder with the .pbit templates
```

When Data Lineage is included, the assessment asks whether you have reporting
files to add. Supply Power BI `.pbit` files or a folder to search; the skill
copies them into `source/BI/PowerBI`, records which database objects each report
reads, then builds the Data Lineage graph. Without reporting files, it still
builds the source, pipeline, and target lanes.

**`.pbix` is not supported.** It is a binary format the assessment cannot read.
Open the report in Power BI Desktop and use *File → Export → Power BI template*
to produce a `.pbit`.

An object a report reads that the migration does not convert shows up as a
missing object rather than being silently dropped — that gap is one of the more
useful things this analysis surfaces.

**What you get is registry data, not a diagram.** This step records your reports
and their dependencies alongside every other object in the migration, so they
show up in planning wherever dependencies matter. It does **not** draw the Data
Lineage graph — that is a separate report with its own tab. A successful "Power
BI Lineage Enrichment" line in the summary means the dependencies were recorded,
not that a lineage diagram was produced.

## Tips for Best Results

### 1. Name What Matters

Use cases are found from the registry, so an outcome that matters to you but
leaves little trace in the code (a report fed through dynamic SQL, a process
spread across scripts) may rank low. Name it and it gets its own use case:
```
Create a use case for month-end close and make it wave 1
```

### 2. Understand Wave Ordering

Waves follow the use cases' rank: confirmed before proposed, then confidence,
then the fewest missing objects, the smallest size and the fewest conversion
issues. Inside a wave, objects deploy in dependency order (stage 1 first).
Objects no use case needs go into a closing wave, "Objects not in a business
use case".

### 3. Iterate on Results

After the initial analysis, you can:

- **View the report** to understand the results
- **Ask questions** about specific findings
- **Request changes** like starting with another use case or adding one
- **Regenerate** with different parameters

The skill maintains context, so you don't need to start over.

## Understanding the Output

### HTML Report

Before presenting final results, the skill starts or reuses the **live
dashboard** and opens `/assessment`. A saved dashboard opt-out is respected.
The skill still writes `assessment/{customer}_migration_plan_{timestamp}.html` as a shareable export and
opens it as the fallback when the dashboard is disabled or unavailable.

The generated HTML report opens on the **Migration Journey** page. For SQL Server,
Teradata, and Redshift, **Discovery** appears next, followed by the conversion tabs grouped
under **Code/ETL Conversion** and the later migration phases. Most tabs appear only
when the report has data to fill them. Discovery uses SQL Server Extended Events,
a Teradata DBQL metrics export, or a Redshift `SYS_QUERY_HISTORY` metrics export. Without input, the tab stays and explains how
to collect the appropriate files and re-run the assessment. Other dialects omit
the tab.

| Tab | Contents |
|-----|----------|
| **Migration Journey** | Landing page — what each phase of your migration involves, one card per phase |
| **Discovery** | SQL Server Extended Events, Teradata DBQL, or Redshift SYS_QUERY_HISTORY volume, duration mix, statement types, applications, users, long-running executions, and errors. No input yet: dialect-specific collection steps and re-run guidance. Hidden on unsupported dialects. |
| **Waves** | Deployment sequence with objects per wave, dependencies |
| **Object Exclusion** | Temporary, staging, deprecated objects identified |
| **Optimization Opportunities** | Performance, architecture/security, and behavior/semantic findings grouped by priority (SQL Server) |
| **Dynamic SQL** | Patterns found with complexity scores |
| **SSIS** | Package classifications and migration effort |
| **Effort Estimates** | Hours for code conversion and testing, priced per object by complexity, plus workload tier and phase budgets. Editable — change an hours-per-object rate and every total updates (SQL Server, Redshift, Teradata, and Oracle; Informatica mappings are a row on those projects, the same as SSIS packages) |
| **Data Migration & Validation** | Data type coverage for your source platform, per-table readiness, topology and validation guidance, plus reviewed inventory SQL (SQL Server and Redshift) |
| **Testing** | Procedure/function and ETL readiness ladders — what is testable now, and what each object still needs first |

### Key Metrics

- **Total Objects** - Number of objects in the migration
- **Business Use Cases / Waves** - One wave per use case, plus a closing wave for objects no use case needs
- **Exclusion Candidates** - Objects that may not need migration
- **Circular Dependencies** - Objects with mutual dependencies (require attention)

## Troubleshooting

### "Important objects are in a late wave"

Ask for their process by name, so it becomes its own use case and goes first:
```
Create a wave for the CriticalProcess app and make it wave 1
```

### "A use case is too large"

Waves can still be worked in parallel by stage. To split one, name the
outcomes it mixes:
```
Split the Finance use case into the ledger load and the close reports
```

### "Objects with circular dependencies"

Objects that depend on each other share a deployment stage inside their wave.
For size-based waves, review the `sccs` section of
`waves_analysis_<timestamp>.json` and consider:
- Schema refactoring
- Deploying circular dependency groups together
- Manual intervention for complex cases

## FAQ

**Q: Can I run just one analysis (e.g., only waves)?**
A: Yes! Ask for the specific analysis: "Just find the business use cases and their waves"

**Q: How do I update the analysis after code changes?**
A: Re-run the analysis with updated SnowConvert reports, or say "Start fresh analysis"

**Q: Can I export the data?**
A: Yes, the HTML report includes CSV/Excel export options

**Q: What if I disagree with object exclusion recommendations?**
A: The exclusions are recommendations - you decide what to actually exclude

**Q: How do I handle objects the skill can't categorize?**
A: Review them manually - the skill flags uncertain items for your review
