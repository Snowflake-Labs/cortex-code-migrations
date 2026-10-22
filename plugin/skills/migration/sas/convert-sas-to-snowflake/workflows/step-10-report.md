# Step 10: Conversion Report and Artifact Verification

## When to Load

Load after `workflows/validation-pipeline.md` finishes (or every tier is `SKIPPED`). Validation
(compile, unit test, end-to-end) and its consent live in that pipeline; this file only reports.

---

### Step 10: Generate Conversion Report (MANDATORY)

**MANDATORY STATE WRITE:** At the START of Step 10, set `current_step: "10-in-progress"` in `conversion_state.json`. This distinguishes "report generation started but not finished" from "not yet started." On successful completion, set `current_step: "10"`.

**Batch mode (10+ files):** Generate consolidated report with ALL sections populated. This is the ONLY stopping point in batch mode (besides Step 1).

**ALWAYS generate a conversion report at the end of every conversion session.**

Load `templates/conversion-report.md` and generate the report with:

**PRE-CONDITION CHECK** (before generating):
- Read `<output_dir>/compilation_results.json` → populate Section 1 Compile Status. If file missing → "COMPILATION NOT PERFORMED"
- Read `tables.py summary tables.json` → name every table that was `not_found` or `inferred` (Section 3)
- Read `sql_check.json` (errors fixed, warnings justified) and `validation_results.json` (`repairs[]`, unresolved) → Section 3
- Read trace baselines under `tests/*/expected/` → Section 3a. If no baseline → "NO BASELINE (T2 not run)"
- Check if `source_table_ddl.sql` and `synthetic_data.sql` exist → populate Section 3. If missing → "Test artifacts not generated"
- Read `<output_dir>/snowflake_execution_results.json` if it exists → populate Section 3 with Snowflake validation results (per-file status counts, error categories). Override any "NOT TESTED" / "skipped" / "not generated" placeholders in Section 3, 3a, and 3b with actual results. This file may be generated in a later session (e.g., when user runs validation separately); always check for it.

**MANDATORY sections** (MUST be populated, never silently omitted):
- ✅ Section 1 (Conversion Summary) — always
- ✅ Section 2 (Difficult Blocks) — always (even if empty: "No difficult blocks identified")
- ✅ Section 3 (Testing) — batch: list test artifact files; interactive: full results or "NOT TESTED"
- ✅ Section 3a (Data Validation Summary) — when validation performed
- ✅ Section 3b (Data Quality Gate Readiness) — when validation performed
- ✅ Section 4 (Consolidation) — when 2+ files or Optimize & Consolidate mode
- ✅ Section 5 (DAG + Orchestration) — when 2+ files with dependencies; MUST include mermaid diagram, DAG properties, CREATE TASK SQL, Dynamic Table alternative
- ✅ Section 5c (Orchestration Deployment Checklist) — when orchestration recommended
- ✅ Section 5d (Runtime/Sizing) — when orchestration recommended
- ✅ Section 5e (Monitoring Recommendations) — when orchestration recommended
- ✅ Section 6 (Manual Remediation) — always (even if empty: "No remediation required")

Generate the report with:

1. **Conversion Summary** — files processed, blocks analyzed, tier distribution, compile/test status per file
2. **Difficult / Unremediated Blocks** — every block not classified as Tier 1 HIGH confidence: PySpark blocks, low/medium confidence, MANUAL_REVIEW_REQUIRED markers, missing %INCLUDE sources, external LIBNAME, HASH/CALL EXECUTE, statistical procs
3. **Testing Results** — per-file result per tier (T1 compile, T2 unit, T3 end-to-end) with the failure class of every non-pass, root cause analysis for failures. Mark "NOT TESTED" if user skipped validation. Include test artifact map linking to `tests/<script>/` subfolders (synthetic data, expected baselines, actual results, per-script validation reports)
4. **Multi-Script Consolidation** — flag when multiple SAS files produce the same output artifact; include traceability matrix
5. **Cross-File DAG** — if 2+ SAS files share data dependencies, generate a mermaid dependency diagram following `references/mermaid-diagrams.md` rules. Include DAG properties (critical path, parallelizable groups, independent pipelines)
6. **Orchestration Recommendation** — for each DAG, recommend a Snowflake-native orchestration approach:
   - **Snowflake Tasks DAG** (default): for pipelines with stored procedures, side effects, or mixed SQL/PySpark
   - **Dynamic Tables**: for pure SQL pipelines where incremental refresh is preferred
   - **Tasks + Streams**: when pipeline should react to new data arrivals
   - Generate the actual CREATE TASK / CREATE DYNAMIC TABLE SQL for the recommended approach
   - **Orchestration deployment is REPORT-ONLY** — the SQL is generated in the report for reference. DO NOT execute CREATE TASK / CREATE DYNAMIC TABLE unless the user explicitly requests deployment. If deployment is requested, confirm per the Snowflake Interaction Policy before executing:
     ```
     SNOWFLAKE OBJECT CREATION

     Action: Deploy orchestration objects
     Objects: [list of CREATE TASK / CREATE DYNAMIC TABLE statements]
     Credit impact: Moderate (ongoing scheduled execution)

     Proceed? [Yes] / [No - Keep as report only] / [Show SQL first]
     ```
7. **Manual Remediation** — consolidate ALL items needing human attention with priority (P1/P2/P3) and specific action required

**Output Formats**: Generate the report in TWO formats:
1. **Markdown** — write to `<output_dir>/conversion_report.md`
2. **DOCX** — only if `pandoc` is installed: `pandoc conversion_report.md -o conversion_report.docx`.
   Otherwise skip it and record `DOCX skipped: pandoc not installed` (no hand-built fallback).

**Post-report state update:** Update `conversion_state.json` with `current_step: "10"`. The final artifact gate (Post-Step-10) will set it to `"complete"`.

**⚠️ STOP**: Present the report to the user. Confirm which files were written.

---

### Post-Step-10: Artifact Verification (MANDATORY)

Before declaring conversion complete, verify all required artifacts exist on disk.

**Required artifacts (must exist):**
- [ ] `conversion_state.json` — must show `current_step: "complete"` (primary proof of workflow completion)
- [ ] `compilation_results.json` — even if compilation was skipped, file must exist with a status field
- [ ] `source_table_ddl.sql` — required in batch mode (10+ files)
- [ ] `synthetic_data.sql` — required in batch mode (10+ files)
- [ ] `conversion_report.md` — must contain all 6 mandatory section headings

**Best-effort artifacts:**
- [ ] `conversion_report.docx` — only when pandoc is installed; otherwise the skip note is in the summary

**Report section headings check** — verify `conversion_report.md` contains these headings:
1. "Conversion Summary" or "Summary"
2. "Difficult" or "Unremediated"
3. "Testing" or "Test"
4. "Consolidation" (if Optimize & Consolidate mode was used)
5. "DAG" or "Orchestration" (if 2+ files with dependencies)
6. "Manual Remediation" or "Remediation"

**If ANY required artifact is missing:**
```
INCOMPLETE: Missing required artifacts: [list]
Generate missing artifacts before declaring conversion done.
```

**If all required artifacts present:**
```
All required artifacts verified. Conversion complete.
```

**Post-verification state update:** If all artifacts present, update `conversion_state.json` — set `current_step: "complete"`, `gates.step_10_final_artifacts: "PASSED"`.
