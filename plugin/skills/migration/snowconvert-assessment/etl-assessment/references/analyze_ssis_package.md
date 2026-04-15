# Guide to Analyze SSIS Packages

## CRITICAL WORKFLOW RULES

**Following these sub workflow steps exactly is CRITICAL for success:**

1. **One Package at a Time**
   - The `pending` command returns ONLY ONE package on purpose
   - Complete ALL steps for current package before requesting next

2. **Context Window Management**
   - If context window is approaching its limit before checkpoint, STOP immediately
   - Ask user: "I've analyzed X packages. Context window is near limit. Would you like me to continue?"

3. **Follow Steps Strictly**
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

## Step 1: Get Pending Package

**NEVER** read the json file directly, **ALWAYS** use this command:
```bash
uv run python -m scai_assessment_analyzer etl <JSON_PATH> pending
```

Returns: `Name: package.dtsx | Relative Path: Folder/package.dtsx`

---

## Step 2: Scan Package

Run the scan command with the package path and DTSX file path:

```bash
uv run python -m scai_assessment_analyzer etl <JSON_PATH> scan-package '<PACKAGE_PATH>' '<DTSX_PATH>'
```

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
