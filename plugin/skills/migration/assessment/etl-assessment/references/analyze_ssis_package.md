# Guide to Analyze SSIS Packages

## CRITICAL WORKFLOW RULES

**Following these sub workflow steps exactly is CRITICAL for success:**

1. **One Package at a Time**
   - The `pending` command returns ONLY ONE package on purpose
   - Complete ALL steps for current package before requesting next

2. **Read Every Package in Full**
   - Write each analysis from that package's whole `scan-package` output. Never shorten, grep, or skip scan output, and never reuse sentences from another package's analysis: `update` refuses an analysis that repeats another package's.
   - If you cannot finish every package, stop and return `error` with the number of packages still PENDING. Do not ask anyone to continue and do not mark a package DONE that you did not read. Every finished package is already saved, so a re-run resumes where you stopped; running out of context is never a reason to fan out.

3. **One writer, in this agent**
   - Work through the packages yourself, serially. Never hand slices of them to sub-agents,
     Task calls, background jobs or scripted loops, and never run `update` in parallel: every
     `update` rewrites the whole assessment JSON, and parallel reviewers exhaust the machine's memory.

4. **Follow Steps Strictly**
The instructions in the steps must be follow for each package strictly.

---

## Workflow Checklist

```
- [ ] Step 1: Get Pending Package
- [ ] Step 2: Scan Package
- [ ] Step 3: Classify and Write Analysis
- [ ] Step 4: Repeat
```

---

## Batch mode (`review_mode: review-batch`)

Work through `package_paths` in order instead of Step 1: for each path, run Step 2 and Step 3 with that path. Never run `pending`, which returns the first PENDING package of the whole assessment, including packages another batch is reviewing. When the last path is done, run `scai assessment etl summary` and confirm each of your paths shows DONE.

## Step 1: Get Pending Package

**NEVER** read the json file directly, **ALWAYS** use this command:
```bash
scai assessment etl pending
```

Returns: `Name: package.dtsx | Relative Path: Folder/package.dtsx`

---

## Step 2: Scan Package

Run the scan command with ONLY the package path (relative path from the SSIS source directory):

```bash
scai assessment etl scan-package '<PACKAGE_PATH>'
```
**Note:** The command takes a single argument (the relative package path). Do NOT pass an absolute DTSX path as a second argument.

This outputs everything needed for analysis:
- **Package Info**: Metrics, connection managers, component breakdown
- **Control Flow DAG**: Execution order and task hierarchy
- **Data Flow DAGs**: Pipeline for each data flow (if any)
- **Variables**: Package variables from DTSX
- **SQL Statements**: SQL logic from Execute SQL Tasks
- **Connection Managers**: Connection details from DTSX
- **Script Tasks**: Script code (if any)

---

## Step 3: Write Analysis

After reviewing the package data, write analysis following the **mandatory format** in [writing_analysis.md](writing_analysis.md).

**Note:** Analysis is validated. If format is wrong, the command will fail with guidance.

---

## Step 4: Repeat

Run Step 1 again. If no pending packages, all are analyzed.
