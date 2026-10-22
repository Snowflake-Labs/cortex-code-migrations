---
name: convert-sas-to-snowflake
parent_skill: sas
description: "Preview. Convert SAS code to Snowflake SQL and stored procedures. Use for: DATA steps, PROC SQL, macros, PROC steps, EGP projects (extracted .sas files only). Triggers: convert SAS, migrate SAS, SAS to Snowflake, translate SAS code, SAS migration. Note: For .egp files, run the assess-sas-migration skill first; it extracts the embedded .sas code and the process-flow order into egp_extracted/."
license: Proprietary. See License-Skills for complete terms
---

# Convert SAS to Snowflake

> © Snowflake Inc. This skill and its contents are the proprietary intellectual property of Snowflake Inc.

Expert SAS to Snowflake migration. Output is `.sql` by default (Tier 1 SQL + Tier 2 stored
procedures); a PySpark/SCOS notebook is the last resort for true Tier 3 blocks.

**Consent model.** The user answers every question once, at Step 1 -- including how deep to
validate (T1 compile / T2 unit test / T3 end-to-end) and what data exists. Those answers govern
the whole run: no per-phase or per-operation prompts afterwards. Nothing is created, changed or
dropped outside the target and validation schemas.

---

## Intent Detection

```
Convert intent  (convert, migrate, translate, transform)           → Conversion Workflow below
Assess intent   (assess, analyze, size, estimate, complexity, LOE)  → ../assess-sas-migration/SKILL.md
Validate intent (validate, verify, test conversion, check migration) → validate-sas-conversion/SKILL.md
```

## Prerequisites

- Active Snowflake connection (for T1-T3 validation)
- Target schema and a writable validation schema (or the user confirms them at Step 1)

---

## SQL-First Tiers

Per-block tiers come from `../references/block-tiering-spec.md` (the same rules the assessment
CLI applies -- read its `assessment.json` instead of re-deriving them). In short:

| Tier | Output | When |
|---|---|---|
| 1 SQL | CTAS, CTEs, window functions, `QUALIFY` | default: PROC SQL, SORT, simple DATA steps, MERGE, ARRAY, RETAIN running totals, `%DO` loops, lookup-only hash (= JOIN) |
| 2 Stored procedure | Snowflake Scripting `EXECUTE AS CALLER` | CALL EXECUTE, RETAIN + conditional reset, FIRST./LAST. with multiple OUTPUT, multiple OUTPUT datasets, >5 IF/WHEN in a DATA step, 3+ dependent DML |
| 3 PySpark/SCOS | notebook (`references/pyspark-fallback.md`) | mutated/iterated HASH, DO UNTIL/WHILE with external state, statistical/modelling PROCs |

**These are SQL, not PySpark:** ARRAY iteration → CASE; RETAIN → window functions; FIRST./LAST. →
`ROW_NUMBER()`; `KEY=` / hash lookup → LEFT JOIN; `%DO` → GENERATOR/WHILE. Before choosing
PySpark ask: "can a window function, CTE or stored procedure do this?"

Stored procedure skeleton:
```sql
CREATE OR REPLACE PROCEDURE process_sas_logic(p_input STRING, p_output STRING)
RETURNS STRING LANGUAGE SQL EXECUTE AS CALLER
AS
$$
DECLARE
  v_row_count INTEGER;
BEGIN
  CREATE OR REPLACE TABLE IDENTIFIER(:p_output) AS
  SELECT *, SUM(amount) OVER (PARTITION BY group_col ORDER BY sort_col ROWS UNBOUNDED PRECEDING) AS running_total
  FROM IDENTIFIER(:p_input);
  SELECT COUNT(*) INTO :v_row_count FROM IDENTIFIER(:p_output);
  RETURN 'Processed ' || v_row_count || ' rows';
END;
$$;
```

---

## Critical Conversion Rules

Load `references/conversion-rules.md` at Step 5. Always in context:
- NEVER generate converter scripts -- the LLM reads each SAS file and writes the SQL
- NEVER truncate or use "similar pattern" shortcuts; every derivation and branch explicit
- SAS missing (`.`) = NULL with different comparison semantics; **missing keys join missing keys**
- MERGE != JOIN (many-to-many, IN= flags, last-listed dataset wins shared columns)
- WORK tables = TEMPORARY, bare name, no schema prefix
- Snowflake Scripting: `:var` only in SQL statements, SELECT INTO, named exceptions only
- Every table a SAS block reads is read by its SQL block; join type, `ON` placement, `DISTINCT` preserved
- Type traps (key casts, `TRY_TO_*`, `TO_DATE` on text dates) only on recorded type evidence, with `-- TYPE:`
- Every block starts with a `-- SAS: <file>:L<a>-L<b>` anchor
- Output tables and column counts match SAS; consolidation keeps every output
- `$VAR` works inside an `EXECUTE AS CALLER` body, but must be SET before the procedure is
  created; `GETVARIABLE()` is required only for names computed at run time

---

## Context Budget

Load only what the current step needs; never re-read converted files (use
`conversion_state.json`); write state before each step transition; batch mode converts 10-20
files per batch (`references/batch-mode.md`). Checkpoint at each file boundary, then continue,
so a compacted or new session can resume from the next file.

| Step | References |
|---|---|
| 1 | `state-tracker-schema.md` + `checkpoint-logging.md` (once) |
| 1-2 | `common-patterns.md` |
| 2.5 | `vendor-passthrough.md` (only for external LIBNAME / CONNECT TO) |
| 5 | `conversion-rules.md` + construct refs (table below); `multi-block-orchestration.md` for 3+ dependent blocks, `%DO` loops, `&&var&i`, `&SYSERR`, `FILEEXIST`, trigger files; `consolidation-patterns.md` in Optimize & Consolidate mode; `pyspark-fallback.md` for Tier 3 |
| 6+ | `workflows/validation-pipeline.md` (it names its own references) |
| 10 | `workflows/step-10-report.md` + `templates/conversion-report.md` + `mermaid-diagrams.md` |

| Construct (Step 5) | Reference |
|---|---|
| DATA steps | `references/data-steps.md` |
| PROC SQL | `references/proc-sql.md` |
| Macros | `references/macros.md` |
| PROC steps | `references/proc-steps.md` |
| Functions, formats, informats | `references/function-mappings.md` |
| Oracle/DB2/SQL Server passthrough | `references/vendor-passthrough.md` + `references/vendor-function-mappings.md` |
| Large files (>500 lines) | `references/large-file-rules.md` |

---

## Conversion State (`conversion_state.json`)

Written incrementally to `<output_dir>/conversion_state.json` (schema:
`references/state-tracker-schema.md`); every write is paired with one line appended to
`checkpoint_log.jsonl` (`references/checkpoint-logging.md`). State writes are blocking
prerequisites for step transitions -- context pressure does not exempt them. File status:
`classified → converted → self_checked → compiled → validated → complete`.

---

## Conversion Workflow

### Step 1: Gather Input (the only interactive stop besides Step 4 and Step 10)

**Pre-check:** if `<output_dir>/conversion_state.json` exists, offer **Resume** from
`current_step` or **Restart** (delete state, start fresh).

Ask in ONE prompt:
1. SAS code source (file, directory or paste) and output directory
2. Target schema (`DATABASE.SCHEMA`) and validation schema (writable scratch)
3. Migration mode: **1:1 Direct** (default, one `.sql` per SAS file) or **Optimize & Consolidate**
4. Validation depth: **T1** compile (no credits) / **T2** + unit test on test data / **T3** + end-to-end
   on full data / none
5. Data questions for the chosen depth (`workflows/validation-pipeline.md` §Step 1 inputs): where
   the source tables live, DDL files, test data, SAS outputs to compare against, full-data location
6. External sources found in Step 2.5 (asked in this same prompt when present)

Write `conversion_state.json` (`metadata`: output_dir, target_schema, validation_schema,
migration_mode, `validation_selections`, timestamps, `current_step: "1"`) and the first
`checkpoint_log.jsonl` line before Step 2.

### Step 2: Load References

Load `references/common-patterns.md` (variable binding, platform constraints). Everything else is
loaded at the step that needs it (Context Budget table).

### Step 2.5: External Sources and the Table Registry

Scan for external database references: `LIBNAME` with an engine (`sqlsvr`, `oracle`, `teradata`,
`odbc`, `oledb`, `postgres`, `mysql`, `mssql`), `CONNECT TO`, and `DSN=` / `qualifier=` /
`schema=`. For each: engine, DSN/qualifier, schema, tables read through it. Show them in the Step 1
prompt:

```
| LIBNAME | Engine | DSN/Qualifier | Schema | Tables Referenced |
| EXTDB   | sqlsvr | <SOURCE_DB>   | dbo    | Table1, Table2    |
Target Snowflake location: a) {TARGET_SCHEMA}  b) another DATABASE.SCHEMA  c) placeholders
```
Store the mapping under `source_mappings`; Step 5 resolves `EXTDB.dbo.MyTable` to the chosen
`DB.SCHEMA.MYTABLE`.

**Registry.** Copy the assessment's `tables.json` to `<output_dir>/tables.json` (the working copy).
It lists every input and output; Step 5 adds intermediates. Read it only through
`../assess-sas-migration/tool/tables.py` (`summary`, `get`, `gap`, `update --batch`) -- never load the
JSON. Locations and columns are resolved in the pipeline's Registry step.

### Step 3: Classify Each Block (with Dependency Tracking)

**Assessment discovery (no prompt).** Use the first readable `assessment.json` among
`<output_dir>/`, `<source_dir>/`, `<source_dir>/assessment_output/`,
`<output_dir>/../assessment_output/`, then a depth-≤2 glob; valid only with `metadata.generated_at`
and `files[]`. If found, take per-file blocks, tiers, `block_ranges` (line spans for `-- SAS:` anchors) and the dependency graph from it (`stale: true`
if older than the newest source file). If none, classify per `../references/block-tiering-spec.md`
and record `assessment.consumed: false`.

Build the dependency map: tables each block creates and reads, macro variables set (`CALL SYMPUT`,
`%LET`, `INTO :var`) and where consumed, inter-block edges, and repeated macro invocations by
parameter combination.

**Block counting** follows the tiering spec exactly (each DATA/PROC step inside a macro is its own
block; DI Studio scaffolding excluded), so counts and tiers match the assessment. When the
assessment was consumed, reconcile per file (`blocks`, `primary_tier`, `tier_distribution`);
mismatches are informational (`assessment.reconciliation`).

**Confidence:** LOW = nested macros, `%INCLUDE` with a dynamic path, external LIBNAME; MEDIUM =
INTCK/INTNX, NOTSORTED; HIGH = everything else.

Write `conversion_state.json` (all files `classified`, tier, block count, `dependencies.creates/reads`,
`assessment`) before Step 4.

### Step 4: Present Block Analysis

```markdown
## Block Analysis: script_name.sas
| Block | Type | Tier | Lines | Creates | Reads | Reason |
| 1 | PROC SQL | SQL | 10-25 | staging_data | source_table | Direct SQL mapping |
| 3 | DATA step | Stored Proc | 47-80 | flagged | summary | RETAIN + FIRST./LAST. |
**Dependencies:** Block 3 depends on Block 2 (summary).
```
Add the assessment reconciliation table when one was consumed (file, assessment blocks/tier,
conversion blocks/tier, match).

**⚠️ STOP** (interactive mode): review classification; if the user disagrees with a PySpark block,
attempt SQL/stored procedure. **Tier 2 present:** ask whether the role has CREATE PROCEDURE --
*No* → those blocks become an SCOS notebook (`metadata.sp_permission: false`); *Unsure* → proceed,
T1 reports permission errors. Record reclassifications in state before Step 5.

### Step 5: Generate Conversion

- **Tier 1:** clean SQL, `CREATE OR REPLACE TABLE`, explicit column lists where `ROW_NUMBER()`
  helpers exist; WORK datasets → `CREATE OR REPLACE TEMPORARY TABLE` (bare name).
- **Tier 2:** variable binding per `common-patterns.md`; CTEs and window functions inside; named
  exceptions only; `SELECT INTO :var`; cross-block variables via `EXECUTE IMMEDIATE 'SET ...'`.
- **Tier 3:** SCOS notebook for those blocks only (`references/pyspark-fallback.md`).
- **Every block:** a `-- SAS: <file>:L<a>-L<b>` anchor; every column derivation and branch; the SAS
  output table count; every `CALL SYMPUT/SYMPUTX`; PROC FORMAT as CASE (simple) or a lookup table
  (ranges); vendor passthrough stripped to Snowflake SQL; `%INCLUDE` without source → CALL to a
  `MANUAL_REVIEW_REQUIRED` stub; external macros without source → parameterised stub comment.
- Record each WORK intermediate the SQL creates in the registry (`tables.py update --batch`, role
  `intermediate`).
- Subagents used for context must read SAS and write SQL themselves -- never a converter program.
- Validation in scope: write `run_assumptions.md`, dispatch the data-prep subagent (registry + seed
  files), convert while it works, then dispatch blind tracers (`references/batch-mode.md` §Parallel subagents).

Mark each file `converted` in state as its `.sql` is written.

### Step 6: Self-Check (mechanical checks are a tool; judgement checks are yours)

```bash
python3 tool/sql_check.py all --dir <output_dir> --sas-dir <source_dir> --tables <output_dir>/tables.json
```
Fix every `error` and resolve every `warn` (Gate 0 of the pipeline). It covers: comment-delimiter
desync, `EXECUTE IMMEDIATE ... INTO`, non-literal EXCEPTION messages, `HEADER` inside
`FILE_FORMAT`, `f(*)` outside a SELECT list, unquoted procedure bodies, XLSX via COPY, bare temp
tables before `USE`, session variables a procedure needs at create time, casts without type
evidence, cross-file qualifier mismatches, CALL arity, stubs shadowing real procedures, sub-flows
nothing calls, and per-anchor join type / DISTINCT / anti-join drift.

Then check what no tool can:
1. No unresolved SAS macro variables (`&var`, `&&var`) and no `:var` in scripting control flow
2. Every output table and column of the SAS block is produced (count ≥ SAS)
3. No invented variables, parameters, columns or filters (conversion-rules.md Anti-Hallucination)
4. Validation lookups stay data-driven; no hardcoded value list replaces a table
5. Procedures that use session variables or shared temp tables are `EXECUTE AS CALLER`
6. Reserved-word column names are double-quoted
7. No vendor SQL left (DECODE, NVL, CONNECT TO); no "similar pattern" shortcuts
8. Re-runs: the new output has ≥ the file count of the previous version (or consolidation explains it)

Set `self_check_passed: true` per file and `current_step: "6"`.

### Step 6a: Artifact Presence (HARD GATE)

Every expected `.sql` exists in `<output_dir>/` and the count matches Step 4. If any is missing:
print `BLOCKED: Missing: [...]`, set `gates.step_6a_artifacts: "BLOCKED"`, regenerate it, and do not
continue until the gate passes (`"PASSED"`).

### Validation (T1 / T2 / T3)

At the Step 6 boundary, save all converted files and write `conversion_state.json`, so a
compacted or new session resumes from the earliest incomplete step.

Load `workflows/validation-pipeline.md` and run it to the depth chosen at Step 1 (none → every
gate `SKIPPED`). It owns the registry, compile, unit test, end-to-end run, the repair loop and the
result files.

### Step 10: Report (MANDATORY)

Load `workflows/step-10-report.md`. The conversion is not complete -- and no final output is
presented -- until the report and the post-Step-10 artifact gate pass.

---

## Output Formats

`templates/output-sql.md` (SQL and stored procedures) and `templates/output-mixed.md` (SQL +
PySpark). Every output file carries the standard header (Converted from, Target Schema, Tier).

## Stopping Points

- Interactive (<10 files): Step 1 (inputs), Step 4 (classification), Step 10 (report)
- Batch (10+ files): Step 1 once, Step 10 once

## Mandatory Output Artifacts (checked by the post-Step-10 gate)

| Artifact | Required |
|---|---|
| `*.sql`, `conversion_state.json` (`current_step: "complete"`), `checkpoint_log.jsonl` | always |
| `sql_check.json`, `tables.json`, `compilation_results.json` (status `SKIPPED` if not run) | always |
| `source_table_ddl.sql`, `tests/*/expected/*.csv`, `snowflake_execution_results.json`, `validation_results.json` | when T2 ran |
| `e2e_test_results.json`, `orchestration/` harness, `testing/` loaders | when T3 ran |
| `conversion_report.md` (all mandatory sections) | always |
| `conversion_report.docx` | only when `pandoc` is installed |

## Success Criteria

- Every block attempted as SQL first; stored procedures before PySpark; PySpark only for true Tier 3
- `sql_check` errors = 0, warnings resolved or justified; judgement checks done
- Validation ran to the chosen depth; every failure classified and either fixed or reported
- Every table not found and every inferred type named in the report
- Low-confidence blocks marked `MANUAL_REVIEW_REQUIRED`; remediation items catalogued with priority
- Cross-file DAG and orchestration recommendation when 2+ files
