---
name: sql-dynamic-pattern-analyzer
description: Analyzes Dynamic SQL occurrences from SnowConvert issues and records migration considerations. Use for SQL Server, Redshift, Oracle, or Teradata to Snowflake migrations. Driven entirely by `scai assessment sql-dynamic`; no custom scripts.
parent_skill: assessment
license: Proprietary. See License-Skills for complete terms
---

# Analyzing SQL Dynamic Patterns

Analyzes Dynamic SQL occurrences flagged by SnowConvert (issue codes `SSC-EWI-0030`, `SSC-EWI-0125`, `SSC-EWI-0126` and `SSC-EWI-0129`) and records migration considerations. Do not tag pattern categories or SQL classification. Complexity shown in the report comes from the SnowConvert EWI catalog, not from this analysis. All operations go through the `scai assessment sql-dynamic` command — there are no Python helpers, no CSV/JSON scripts, no bash loops.

## Sub-Agent Mode

When invoked from a parent skill (e.g., `assessment/SKILL.md`) as a sub-agent, the parent provides a context block with the fields below. The `review_mode` field controls whether the per-occurrence review loop runs.

| Field | Required | Notes |
|---|---|---|
| `project_dir` | yes | absolute path to the SCAI project root |
| `output_dir` | yes | typically `<project_dir>/assessment/json` |
| `review_mode` | yes | `generate-only`, `auto-review-all`, `review-batch`, or `skip` |
| `occurrence_ids` | with `review-batch` | integer IDs to review; skip any that are already REVIEWED |

**On entry:** the parent assessment skill runs `generate-only` itself (no
Task). For `auto-review-all` or `review-batch`, call `configure` with
`project_dir` only if this session has not already configured that project.
Snowflake credentials are not required — `scai assessment sql-dynamic` reads only local CSVs and source files.

**Branching by `review_mode`:**

- `generate-only` — run only `scai assessment sql-dynamic generate` (Workflow Step 1) and return. The output JSON will contain `PENDING` occurrences; that is expected. Do not start AI review.
- `auto-review-all` — generate if the analysis JSON is missing. Then follow [Review loop](#review-loop) for every PENDING occurrence. Run `stats` once at the end and confirm zero PENDING.
- `review-batch` — do not generate. Follow [Review loop](#review-loop) only for the IDs in `occurrence_ids` (skip already REVIEWED). Return remaining PENDING in `summary`.
- `skip` — return immediately with `"status": "skipped"`. The parent should not have dispatched in this case; this branch is defensive.

**Standalone report prompts** (pasted from the Dynamic SQL report Copy button): treat these as in-session review, not generate-only. Do not spawn a subagent. Do not re-run `generate`.

- `Run deep dynamic SQL analysis for all pending occurrences in this project.` → `auto-review-all`.
- `Run deep dynamic SQL analysis for all pending occurrences in code unit <code_unit_id> of this project.` → `review-batch` for every PENDING occurrence in that code unit (`show-code-unit --code-unit-id <code_unit_id>` then review those IDs). Do not match by procedure name; names can collide across databases/schemas.
- `Run deep dynamic SQL analysis for occurrence <id> in procedure <name> of this project. Analyze only that occurrence.` → `review-batch` with that one `occurrence_ids` value. Occurrence IDs are unique in the analysis JSON.

**On completion**, return **JSON only**:

```json
{
  "sub_skill": "analyzing-sql-dynamic-patterns",
  "status": "ok",
  "output_json": "<abs path to sql_dynamic_analysis.json>",
  "summary": "<one-line: total occurrences, REVIEWED count, PENDING count>",
  "error": null
}
```

On `skip`: `"status": "skipped"`, `"output_json": null`. On failure: `"status": "error"`, `"error": "<message>"`.

## Critical Rules

**ONLY USE `scai assessment sql-dynamic`:** All generate / show / update / stats operations are subcommands of `scai assessment sql-dynamic`. Do not write custom scripts, parsers, or batch wrappers.

**NO BATCH UPDATES:** Each `update` invocation processes **ONE** record with **ONE** unique analysis.
- Do **not** "walk IDs" sequentially as a batch just because they are adjacent.
- Do **not** use shell loops (e.g. `for id in ...; do scai assessment sql-dynamic update ...; done`) to apply the same update across many records.
- Do **not** copy/paste identical notes across multiple IDs.

**ONE REVIEW PATH:** The [Review loop](#review-loop) is the only way to AI-review. Do not add `show-file`, per-occurrence `show`, extra `stats`, or a CSV dialect hunt on top of it.

## Dialect

Pick the catalog from the project, in this order. Do not ask the user.

1. `source_language` from `configure()` or `<project_dir>/.scai/config/project.yml`.
2. Syntax in the procedure text from `show-code-unit` (see indicators below).
3. `SourceLanguage` in `TopLevelCodeUnits.*.csv` only if 1 and 2 are missing. Search `<project_dir>/.scai/reports/SnowConvert/`, then `<project_dir>/reports/SnowConvert/`, then `<project_dir>/Reports/SnowConvert/`. Stop at the first hit.

| `source_language` / CSV / syntax | Catalog |
|---|---|
| SqlServer, Transact, TSQL, `sp_executesql` / `EXEC(@sql)` / `QUOTENAME()` / `sys.*` | `reference/PATTERNS_TRANSACT.md` |
| Redshift, RedShift, `QUOTE_IDENT()` / `pg_catalog.*` / plpgsql | `reference/PATTERNS_REDSHIFT.md` |
| Oracle, `EXECUTE IMMEDIATE` / `DBMS_SQL.*` / `DBMS_ASSERT.*` / `:varname` / `@dblink` | `reference/PATTERNS_ORACLE.md` |
| Teradata, `DBC.TablesV` / `REPLACE MACRO` / `VOLATILE TABLE` / BTEQ `&variable` | `reference/PATTERNS_TERADATA.md` |

Read that **one** catalog once per session for Snowflake mappings in the notes: the table of contents, then only the pattern sections that could apply. Skip sections that clearly do not (e.g. Cross-System I/O when there is no linked-server or file access). Do not write pattern names or SQL classification onto the occurrence.

## Inputs (auto-detected by parent)

The parent `assessment` skill resolves all inputs from `project_dir`. Do **not** prompt the user for paths.

| Input | Where it lives under `project_dir` |
|-------|------------------------------------|
| Project directory (preferred) | The project root itself — pass via `--project-dir` |
| `Issues.*.csv` (CSV mode) | `<conversion_reports_dir>/Issues.*.csv` |
| `TopLevelCodeUnits.*.csv` (CSV mode) | `<conversion_reports_dir>/TopLevelCodeUnits.*.csv` |
| Source code directory | `source/` |

**Mode selection:**
1. **Project mode (preferred)** — `scai assessment sql-dynamic generate --project-dir <project_dir> --output <path>`. SCAI auto-detects the registry / CSV reports and the source directory.
2. **CSV mode (fallback)** — `scai assessment sql-dynamic generate --csv-dir <conversion_reports_dir> --source-dir <source_dir> --output <path>` when the project layout is not standard. Pass `<conversion_reports_dir>` as `--csv-dir`.

## Workflow

1. **Generate** the analysis JSON from the project (or CSVs) when `review_mode` is `generate-only` or `auto-review-all` and the file is missing.
2. **Review** PENDING targets with the [Review loop](#review-loop) when `review_mode` is `auto-review-all` or `review-batch`.
3. **Stats** once after the last `update`.

### 1. Generate

```bash
# Project mode (preferred)
scai assessment sql-dynamic generate \
  --project-dir <project_dir> \
  --output <project_dir>/assessment/json/sql_dynamic_analysis.json

# CSV mode (fallback)
scai assessment sql-dynamic generate \
  --csv-dir <conversion_reports_dir> \
  --source-dir <project_dir>/source \
  --output <project_dir>/assessment/json/sql_dynamic_analysis.json
```

**What this creates:**
- A JSON file with `metadata` (totals, generation timestamp, input files) and a `codeUnits` map.
- Each code unit holds `codeUnitId`, `procedureName`, `fileName`, `codeUnitStartLine`, `linesOfCode`, the full `procedure` text, and an `occurrences` list.
- Each occurrence starts with `status: PENDING` and empty analysis fields, ready for review. Its `issueCode` names the code that reported it.

The JSON is the source bundle: the full procedure text lives on the code unit. Do not open source files separately.

## Review loop

This is the only AI-review path.

1. Resolve the analysis JSON path (`<output_dir>/sql_dynamic_analysis.json` or the existing project file).
2. Resolve the dialect ([Dialect](#dialect)).
3. Group target PENDING occurrences by `code_unit_id`.
4. For each code unit, call `show-code-unit` **once**:

```bash
scai assessment sql-dynamic show-code-unit <analysis.json> --code-unit-id "<code_unit_id>"
```

That output is the procedure source and every occurrence. Do not call `show-file` or `show --id` for these records.

5. Read the catalog as in [Dialect](#dialect).
6. Analyze every target occurrence in that unit **from that one result**. Use the procedure once as shared context (how SQL is built and executed). Each occurrence still gets its own `update` with notes that are about **that line** (see [Notes](#notes)).
7. Issue the `update` calls back to back with no commentary in between. Do not set complexity.

```bash
scai assessment sql-dynamic update <analysis.json> \
  --id <N> \
  --line <line_number> \
  --status REVIEWED \
  --generated-sql "CREATE TABLE dbo.TempTable (ID INT, Name VARCHAR(100))" \
  --notes '{
    "justification": "Line X assigns @sql from concatenated @schema and @table and EXEC(@sql) runs it.",
    "complexity": "Unquoted identifiers; NULL @schema yields a NULL statement.",
    "migration_considerations": "Validate the two-part name, then IDENTIFIER(:schema || \".\" || :table). Estimated effort: 4–6 hours."
  }'
```

- `--id` is required.
- `--line` should be set after reading the procedure source — generated records start with `line = 0`. Keep `0` only when the source line cannot be reliably determined.
- Do not pass `--category` or `--sql-classification`. The report groups and filters by EWI (`issueCode`), not AI tags.
- `generated_sql`: the SQL that would run, with representative values, complete (no ellipses).

8. After the last `update` of the run:

```bash
scai assessment sql-dynamic stats <analysis.json>
```

Do not run `stats` between occurrences.

## Notes

Each `--notes` value is a JSON object with three keys. No minimum word count. Do not pad. Full sentences. Name real code.

```json
{
  "justification": "Why this line is dynamic SQL.",
  "complexity": "What makes this line hard to migrate.",
  "migration_considerations": "Snowflake mapping and effort."
}
```

**Required facts (not length):**
- `justification`: the line number, the construct (`EXEC`, `sp_executesql`, concat into `@sql`, …), and what that line does.
- `complexity`: the technical drivers for **this line** (unquoted identifiers, metadata cursor, NULL default, …).
- `migration_considerations`: a concrete Snowflake mapping and a concrete hour estimate. End with `Estimated effort: …`.

**Shared procedure vs per-occurrence:**
When several occurrences share a code unit, state how the procedure builds and executes SQL **once** (in the first occurrence's notes, or only in your reasoning). Later occurrences in the same unit must **not** retell that procedure story. Each occurrence's notes must still stand alone for **that line**: do not write "similar to occurrence N"; do not reuse another ID's notes. Name that line's variable, parse, or EXEC.

## Reference Files

- `reference/PATTERNS_TRANSACT.md` — SQL Server → Snowflake
- `reference/PATTERNS_REDSHIFT.md` — Redshift → Snowflake
- `reference/PATTERNS_ORACLE.md` — Oracle → Snowflake
- `reference/PATTERNS_TERADATA.md` — Teradata → Snowflake
