---
name: anti-patterns
description: Identify SQL Server migration anti-patterns — performance blockers, architecture/security considerations, and behavioral differences — by running `scai assessment anti-patterns`, which buckets SnowConvert's already-recorded issue codes by priority and writes JSON for the parent assessment multi-report. Use for anti-patterns, performance/architecture concerns in SQL Server → Snowflake migrations;
parent_skill: assessment
license: Proprietary. See License-Skills for complete terms
---

# Anti-Patterns

This skill is a thin wrapper over the SCAI CLI command `scai assessment anti-patterns`. SCAI filters the SnowConvert issue codes already recorded on the project's code units against a curated catalog of migration-relevant anti-patterns, groups them into customer-facing categories with a priority breakdown, and writes a JSON file the parent assessment skill's multi-tab HTML report consumes.

**Scope (v1): SQL Server only.** The command auto-detects the project's source dialect and aborts with a clear message on non-SQL-Server projects. Redshift, Teradata, and Oracle are planned for later phases.

## Sub-Agent Mode

When invoked from a parent skill (e.g., `assessment/SKILL.md`) as a sub-agent, the parent provides a context block with the fields below. This sub-skill takes no user prompts in either mode, so the only behavioral change in sub-agent mode is the JSON return contract.

| Field | Required | Notes |
|---|---|---|
| `project_dir` | yes | absolute path to the SCAI project root (must contain `.scai/` and an initialized registry) |

**On entry:** call the `configure` MCP tool with `project_dir` from the context block. Snowflake credentials are not required — `scai assessment anti-patterns` reads only the local Code Unit Registry.

Run the SCAI command exactly as documented in [Workflow Step 1](#step-1-run-scai).

**On completion**, return **JSON only**:

```json
{
  "sub_skill": "anti-patterns",
  "status": "ok",
  "output_json": "<abs path to anti-patterns-*.json>",
  "summary": "<one-line: buckets, distinct flags, code units affected>",
  "error": null
}
```

- On a **non-SQL-Server** project (the CLI aborts with `ASM0024`): return `"status": "skipped"`, `"output_json": null`, `"error": null`, and a `summary` explaining the dialect is unsupported in v1. Do **not** treat this as an error.
- On any other failure: `"status": "error"`, `"output_json": null`, `"error": "<message>"`.

## Critical Rules

- **Use ONLY the SCAI CLI.** No inline parsing, no custom analyzers, no new issue detection. `scai assessment anti-patterns` is the single source of truth. The catalog of codes and their bucket/priority classifications live inside SCAI, not in this skill.
- **Registry-only.** Detection reads the Code Unit Registry (`/registry/`).
- **Inputs come from the parent.** The parent `assessment` skill resolves `project_dir`; this skill just runs SCAI.
- **One artifact per run.** SCAI writes a single timestamped JSON: `anti-patterns-YYYYMMDD_HHMMSS.json` under `<project_dir>/artifacts/assessment/`.

## Inputs (auto-detected by parent)

| Input | Resolution under `project_dir` |
|-------|--------------------------------|
| Project directory | `<project_dir>` — SCAI reads the registry and gates on the SQL Server dialect |
| Output location (fixed) | `<project_dir>/artifacts/assessment/` — created by the command; not configurable |

## Workflow

### Step 1: Run SCAI

Run from inside the SCAI project directory so the command can read the registry:

```bash
scai assessment anti-patterns
```

There are no options in v1. The command:
- aborts immediately with `ASM0024` if the project's source dialect is not SQL Server (→ report `skipped`);
- otherwise scans every code unit's recorded issues, keeps the catalog-matched codes, and writes one file:

```
<project_dir>/artifacts/assessment/anti-patterns-YYYYMMDD_HHMMSS.json
```

### Step 2: Locate the latest output

After the command completes, capture the path of the newest `anti-patterns-*.json` in `<project_dir>/artifacts/assessment/` and pass it back to the parent skill. Do not parse or re-write the file.

### Step 3: Hand off to the parent

Return the artifact path to the parent `assessment` skill. The multi-tab report **auto-discovers** the latest `artifacts/assessment/anti-patterns-*.json` from `--project-dir`, so no explicit flag is required; an optional `--anti-patterns-json <path>` override exists for non-standard locations. This skill never generates HTML directly.

## SCAI Command Reference

| Option | Description |
|--------|-------------|
| _(none in v1)_ | The command takes no options. It must be run from within a SCAI project directory (`RequiresProject`), needs no Snowflake connection, and gates on the SQL Server source dialect. |

## Output Schema

SCAI writes a single JSON file (`snake_case`) with the following top-level structure: `schema_version`, `generated_at`, `project_name`, `source_dialect`, `summary` (with roll-ups by bucket and priority), `flags` (each with code/title/bucket/priority/recommendations), and `code_units` (each with its detected flags). The parent skill's multi-tab report reads these keys directly. Do not transform or rewrite the file.

## What SCAI Detects

(Documented for skill operators — SCAI handles all of this; no configuration is exposed to this skill.) The curated v1 catalog groups migration-relevant SQL Server issue codes into three customer-facing categories, each entry carrying a priority and a plain-language what/why/recommendation:

- **Performance Concerns** — cursor-heavy and row-by-row patterns that run poorly on Snowflake's set-based engine (e.g. cursor FOR loops, nested cursors, FETCH-in-loop, `WHILE`/`LOOP` row-by-row, case-insensitive-collation performance, recursive-CTE keyword, clustering review).
- **Architecture & Security Blockers** — source features with no direct Snowflake equivalent that need a native redesign or migration decision (e.g. `CREATE TYPE AS TABLE`, `OPENQUERY`/remote access, `BULK INSERT`→PUT, external-table conversion, nested transactions, CTE-in-view, GOTO into nested block, full-join DELETE, `SET ROWCOUNT`).
- **Behavior & Semantic Differences** — code that runs but can behave subtly differently (e.g. collation, `NUMBER` scale lowered for arithmetic, numeric/date format differences, `SELECT *` over remapped system objects, `SET QUOTED_IDENTIFIER`, output-parameter ordering, masking-policy role, `ANSI_PADDING OFF`, redundant single-table views as a modernization candidate).

Findings are also rolled up by migration-impact **priority** (Critical / High / Medium / Low).

## Failure Modes

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| `Error: … supports SQL Server projects only` (ASM0024) | Project's source dialect is not SQL Server | Expected in v1 — report `status: "skipped"`; not an error |
| `Error: Unable to resolve inputs …` (ASM0022) | Registry not initialized / not a SCAI project | Verify the parent ran `scai code convert` successfully and a `.scai/registry/` exists |
| `Error: Anti-patterns analysis generation failed …` (ASM0023) | Unexpected I/O or registry read failure | Check the message; verify the registry is intact |
| Empty `flags`/`code_units` with zeroed summary | No catalog-matched codes in this workload | Normal — a valid document is still written; proceed to report generation |

## Related

- Parent: `../SKILL.md` (consumes the artifact; auto-discovers it via `--project-dir`)
- Report tab renderer: `../scripts/anti_patterns_report/generate_anti_patterns_report_content.py`
- SCAI built-in help: `scai assessment anti-patterns --help`
