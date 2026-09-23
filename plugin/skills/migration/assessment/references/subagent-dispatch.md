# Assessment Sub-Agent Dispatch

Read this file in full after `assessment_inputs` is complete. Substitute every
placeholder and use absolute paths, except `staged_pbits` (see §6.8).

When `data_lineage.dispatch` is true and `staged_pbits` is non-empty, dispatch
is **two turns**, not one: enrichment first, then the remaining fan-out. When
dispatch is false or `staged_pbits` is empty, skip the first turn and send the
remaining in-scope runners in one message. After each dispatch message, end
the turn.

## Contents

- Common contract
- Core assessment runners
- ETL and Discovery runners
- Data Lineage runner

## Common contract

- Never dispatch an excluded analysis or a `review_mode: skip` analysis.
- Every child calls `configure(project_dir=...)`; MCP state is not inherited.
- Tell every child it is non-interactive and must not ask questions.
- Each child writes only its own artifacts; never registry/source/other-child
  output.
- Every child returns JSON only:

```json
{
  "sub_skill": "<name>",
  "status": "ok | skipped | error",
  "output_json": "<absolute path> | null",
  "summary": "<one-line counts or skip reason>",
  "error": "<message> | null"
}
```

Data Lineage adds `manifest`. End the parent turn after the dispatch message.

## Core assessment runners

### 6.1 waves-runner prompt

```text
Read and follow plugin/skills/migration/assessment/waves-generator/SKILL.md.
You are a non-interactive sub-agent. Do not ask questions.
Context: project_dir, partition_min_size, partition_max_size,
prioritization_globs, wave_ordering, output_dir=<project_dir>/assessment.
Call configure(project_dir). From project_dir run scai assessment waves with
--min-size/--max-size, one --prioritize per glob, and
--no-category-waves only for dependency ordering. Fail rather than wait for
TTY input. Return the common JSON contract for waves-generator with the newest
waves_analysis_*.json and partition/SCC/object counts.
```

### Object exclusion

```text
Read and follow plugin/skills/migration/assessment/object_exclusion_detection/SKILL.md.
You are a non-interactive sub-agent. Do not ask questions.
Context: project_dir.
Call configure(project_dir), run scai assessment object-exclusion from the
project, and return the common JSON contract for object-exclusion-detection
with the newest artifacts/assessment/object_exclusion_analysis_*.json and
temp/staging/deprecated/testing/duplicate counts.
```

### Effort estimates

```text
Read and follow plugin/skills/migration/assessment/effort-estimate/SKILL.md.
You are a non-interactive sub-agent. Do not ask questions.
Context: project_dir.
Call configure(project_dir), run scai assessment effort-estimate, and return
the common JSON contract for effort-estimate with the newest
artifacts/assessment/effort-estimates-*.json and DDL/hour totals.
ASM0031 is skipped, not error.
```

### Anti-patterns

Dispatch only for SQL Server.

```text
Read and follow plugin/skills/migration/assessment/anti-patterns/SKILL.md.
You are a non-interactive sub-agent. Do not ask questions.
Context: project_dir.
Call configure(project_dir), run scai assessment anti-patterns, and return the
common JSON contract for anti-patterns with the newest
artifacts/assessment/anti-patterns-*.json and bucket/flag/unit counts.
ASM0024 is skipped, not error.
```

### Dynamic SQL

```text
Read and follow plugin/skills/migration/assessment/analyzing-sql-dynamic-patterns/SKILL.md.
You are a non-interactive sub-agent. Do not ask questions.
Context: project_dir, output_dir=<project_dir>/assessment/json,
review_mode=generate-only|auto-review-all.
Call configure(project_dir). Run:
scai assessment sql-dynamic generate --project-dir <project_dir>
  --output <output_dir>/sql_dynamic_analysis.json
For auto-review-all, follow the child skill's per-occurrence loop until stats
shows zero PENDING; each update is one specifically analyzed record.
Return the common JSON contract for analyzing-sql-dynamic-patterns with
total/REVIEWED/PENDING counts.
```

## ETL and Discovery runners

### SSIS

```text
Read and follow plugin/skills/migration/assessment/etl-assessment/SKILL.md.
You are a non-interactive sub-agent. Do not ask questions.
Context: project_dir, output_dir=<project_dir>/assessment/ssis,
etl_replatform_sources_path, review_mode=generate-only|auto-review-all.
Call configure(project_dir). Locate newest ETL.Elements.*.csv and
ETL.Issues.*.csv; auto-detect replatform sources when context is empty. From
the project root run scai assessment etl generate, render DAG HTML from the
newest dag_model_*.json, and for auto-review-all classify every package and
produce ai_ssis_summary.html. Return the common JSON contract for
etl-assessment with the newest etl_assessment_analysis_*.json and package
counts.
```

### Informatica

```text
Read and follow plugin/skills/migration/assessment/informatica-assessment/SKILL.md.
You are a non-interactive sub-agent. Do not ask questions.
Context: project_dir, output_dir=<project_dir>/assessment/informatica,
informatica_target=dbt|scripting, review_mode=auto-review-all (required).
Call configure(project_dir, etl_informatica_target=<informatica_target>).
Locate ETL CSVs and follow the child skill to generate JSON and analyze every
workflow in the selected target mode. Run its summary command, read the AI
summary guide, write <output_dir>/ai_informatica_summary.html, and register it
with the `ai-summary` command. These actions are required. Verify the summary
HTML and newest informatica_assessment_analysis_*.json both exist and are
non-empty; return error rather than ok if either is missing. Return the common
JSON contract with workflow/classified/pending/target counts.
```

### Discovery

Dispatch only for SQL Server or Teradata when mode is `have_extract` and paths
are non-empty. For `skip`, synthesize `skipped by user`. For `later`,
synthesize `capture SQL provided; re-run assessment with the .xel files` on
SQL Server or `probe and export SQL provided; re-run assessment with the
metrics file` on Teradata.

```text
Read and follow plugin/skills/migration/assessment/workload-insights/SKILL.md.
You are a non-interactive sub-agent. Do not ask questions.
Context: project_dir, input_paths=<absolute .xel paths (SQL Server) or metrics
CSV paths (Teradata)>.
Call configure(project_dir). From project_dir run scai assessment
workload-insights with exactly one --input per path. Return the common JSON
contract for workload-insights with the newest
artifacts/assessment/workload-insights-*.json. ASM0034 is skipped. Exit 0 plus
a written artifact is ok even when stdout reports a large/long parse or
skipped-row warnings from a Teradata extract. Never copy input files into the
project.
```

### 6.7 data-lineage-runner prompt

Dispatch Data Lineage whenever `data_lineage.dispatch` is true, even with zero
staged templates. **Resolve `catalog_helper_path` and `assessment_skill_dir`
before you dispatch.** `catalog_helper_path` is
`data-lineage/scripts/query_cur_catalog.py` under the directory the parent
`SKILL.md` lives in, made absolute. `assessment_skill_dir` is that same
directory, also absolute — the `--project` root `stage_powerbi_inputs.py`
already uses. The child runs from `project_dir`, so a relative helper path is
invalid.

```text
Read and follow plugin/skills/migration/assessment/data-lineage/SKILL.md.
You are running in sub-agent mode — do NOT ask the user any questions.

Context:
- project_dir: <abs_path>
- staged_pbits: <project-relative .pbit paths>
- manifest_path: <project_dir>/artifacts/assessment/powerbi/manifest.json
- catalog_helper_path: <abs_path to data-lineage/scripts/query_cur_catalog.py>
- assessment_skill_dir: <abs_path to the directory this SKILL.md lives in>

staged_pbits are project-relative because that is the spelling the CLI and the
manifest match on. Resolve each against project_dir before opening it. Do not
rewrite them as absolute paths to satisfy §6.8 rule 2; they are identities, not
paths to open. Every path you pass to a shell command is absolute; every path
you write into the manifest is project-relative.

1. Call configure() with project_dir.
2. With no staged_pbits skip extraction/enrichment and go to step 7.
3. Otherwise run scai assessment powerbi extract from project_dir.
   ASM0039 means templates were found but none extracted into a usable model:
   skip Power BI enrichment, not Data Lineage, and continue to step 7.
   ASM0037 writes no artifact at all; ASM0038 and ASM0040 are errors.
4. Inspect every extracted report separately and infer direct database-object
   dependencies with evidence.
5. First qualify each identity with every schema and database justified by the
   evidence. Match references from project_dir; make one call per object type:
     uv run --project "<assessment_skill_dir>" \
       python "<catalog_helper_path>" --project-dir "<project_dir>" \
       --object-type <TYPE> --name "<object>" [--name "<object>" ...]
   --object-type is REQUIRED and applies to every --name in the call, so make
   one call per object type and pass every name of that type in it. Do NOT
   group by report. `--project` is `assessment_skill_dir`, never `project_dir`.
   Do NOT read the artifact's curCatalog yourself.
   Apply the FIRST rule that matches, in this order. The conditions overlap on
   purpose; the order settles it, so stop at the first hit:
   a. exactCount == 1: use that candidate id. Wins outright.
   b. exactCount > 1: omit and report.
   c. truncated → omit and report.
   d. reconcilableCount == 0: author a missingObject.
   e. reconcilableCount == 1 and "fullyComparable": true: that IS your object;
      use its id. Do NOT author a stub — enrich rejects it as a collision — and
      do not re-query hoping for an exact match.
   f. reconcilableCount > 1, or "fullyComparable": false: omit and report.
   Never guess. Include report, object, candidate ids, and evidence for every
   omission in the summary. Carry on with the remaining dependencies.
6. Author schema-v1 manifest_path, run
   scai assessment powerbi enrich --manifest <manifest_path>, and verify
   artifacts/assessment/powerbi/enrichment.json says succeeded.
7. Run scai assessment data-lineage and verify the stable non-empty
   artifacts/assessment/data-lineage.json.

Never write registry state, never invent a code unit id, author requiredBy, or
author a topological rank. CLI-owned writes from `scai assessment powerbi enrich`
are allowed.

Return JSON only:
{
  "sub_skill": "data-lineage",
  "status": "ok | skipped | error",
  "output_json": "<project_dir>/artifacts/assessment/data-lineage.json | null",
  "manifest": "<absolute authored manifest path> | null",
  "summary": "<graph counts, enrichment counts, and omitted references>",
  "error": "<message> | null"
}
```

No reporting layer is still `ok`. When extraction cannot produce a usable
model, omit enrichment but still build the graph. Unresolved references that
were safely omitted are successful output and must remain in the summary.

### 6.8 Common rules for every dispatch

1. **Enrichment before the fan-out.** When `data_lineage.dispatch` is true and
   `staged_pbits` is non-empty, send `data-lineage` alone first and wait. Then
   send all remaining in-scope dispatches in a single tool-use turn. With no
   templates, `data-lineage` may join that fan-out because it does not enrich
   the registry.
2. **Absolute paths only** in every context block, **except `staged_pbits`**.
   Those stay project-relative because that is the identity `extract` /
   `enrich` and the manifest match on.
3. **Sub-agent calls `configure()` itself** — do not assume MCP state is
   inherited.
4. **Each sub-agent writes only its own output JSON** and does not hand-edit
   the registry, source SQL, or other sub-agents' artifacts. CLI commands the
   skill tells it to run may write the registry (`scai assessment powerbi
   enrich` is the one that does). Those CLI-owned writes are allowed, and they
   are ordered: enrichment completes before waves and object-exclusion run.
5. **JSON return only** — free-form text in the report is harder to consume
   reliably.

End your turn after the dispatch message.
