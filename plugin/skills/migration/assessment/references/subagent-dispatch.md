# Assessment Sub-Agent Dispatch

Read this file in full after `assessment_inputs` is complete. Substitute every
placeholder and use absolute paths, except `staged_pbits` (see §6.8).

When `data_lineage.dispatch` is true and `staged_pbits` is non-empty, dispatch
is **three steps**: enrichment first, then the remaining fan-out, then
business use cases last. When dispatch is false or `staged_pbits` is empty,
skip the first step: send the fan-out in one message, then business use cases
once it has returned. Business use cases are three agents and a merge the
parent runs (§ Business use cases, after the fan-out). After each dispatch message, call
`hub(mode="wait", confirm=true, cursor=<last>)`. Do not call
`agent_output(wait=true)`, and do not end the turn. Ending the turn exits a
headless session and kills every child. Before waiting, tell the user what is
running, where to watch it and how completion is signalled. Write one line each
time a wait returns: the analyses that finished, or what is still running (see
SKILL.md Step 5).

## Contents

- Common contract
- Core assessment runners
- ETL and Discovery runners
- Data Lineage runner
- Business use cases runner, after the fan-out

## Common contract

- Never dispatch an excluded analysis, a `review_mode: skip` analysis, or conversion issues when `conversion_issues.run` is false.
- Every child calls `configure(project_dir=...)`; MCP state is not inherited.
  A child that cannot load the tool, or whose call fails, stops and returns
  `error` saying so; it never continues without it.
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

Data Lineage adds `manifest`; the lineage search adds `wave_plan` (null),
`catalog`, `context` and `top_use_cases`; the context pass adds `context_md`.
After the dispatch message, call
`hub(mode="wait", confirm=true, cursor=<last>)`. Do not end the parent turn.
The parent reports each analysis as it finishes (see SKILL.md Step 5).

## Core assessment runners

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

Dispatch only for SQL Server, Redshift, Oracle, and Teradata.

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

### Conversion issues

```text
Read and follow plugin/skills/migration/assessment/conversion-issues/SKILL.md.
You are a non-interactive sub-agent. Do not ask questions.
Context: project_dir.
Call configure(project_dir). The first command only collects issues and leaves
problem_description and recommended_fix empty. That is not done.
Run scai assessment conversion-issues. For each summary-panel pair, research
the problem and the fix, write
artifacts/assessment/conversion-issues/updates.json, and rerun:
scai assessment conversion-issues --updates artifacts/assessment/conversion-issues/updates.json
Read conversion-issues.json again. Return ok only when every summary row has
both fields non-empty, or when there are zero pairs. Do not return ok after
the first command. ASM0045 is error, not skipped. Do not upload the ZIP.
```

## ETL and Discovery runners

### One ETL generate per project

A project has one ETL platform, and `scai assessment etl generate` writes only
that platform's artifact. Dispatch exactly one ETL generate child per
assessment: the SSIS one when SSIS is in scope, the Informatica one when
Informatica PowerCenter is. Never both, and never a second generate for the
same project.

### SSIS

SSIS runs in up to three dispatches, so that no agent holds more packages
than it can read in full:

1. **Generate**, in the fan-out, always `review_mode=generate-only`.
2. **Review batches**, only when the snapshot's `etl.review_mode` is
   `auto-review-all`. As soon as the generate child returns `ok`, run
   `scai assessment etl summary` from the project root and take every
   package listed `PENDING` under "AI Analysis per Package". Split those paths,
   in listed order, into batches of at most **10 packages**, and send one
   review child per batch, one at a time: send the next batch only after the
   previous review child has returned. With no PENDING packages, go straight
   to the summary.
3. **Summary**, alone, once every review child has returned.

The fan-out is not complete until the last SSIS dispatch has returned.
Never run two review children at once: each `etl update` rewrites the whole
assessment JSON, and parallel reviewers each hold their own context, which
exhausts a laptop's memory on a large estate. Each child saves its packages
with `etl update`, so never merge their outputs yourself.

Generate:

```text
Read and follow plugin/skills/migration/assessment/etl-assessment/SKILL.md.
You are a non-interactive sub-agent. Do not ask questions.
Resolve etl_assessment_skill_dir before dispatch: the absolute directory of
etl-assessment/SKILL.md under this plugin (plugin root +
skills/migration/assessment/etl-assessment). The install root differs between
a checkout and a packaged plugin, and the sub-agent runs from project_dir,
where no relative ai project exists.
Context: project_dir, output_dir=<project_dir>/artifacts/assessment/etl,
etl_replatform_sources_path, ssis_target=dbt|scripting,
review_mode=generate-only,
etl_assessment_skill_dir=<absolute directory containing etl-assessment/SKILL.md>.
Call configure(project_dir, etl_ssis_target=<ssis_target>). Locate newest ETL.Elements.*.csv and
ETL.Issues.*.csv; auto-detect replatform sources when context is empty. From
the project root run scai assessment etl generate. Render DAG HTML from the
newest dag_model_*.json with:
uv run --project "<etl_assessment_skill_dir>" python "<etl_assessment_skill_dir>/scripts/dag_renderer/render_dags.py" "$dag_model"
Never pass project_dir as --project. Return the common JSON contract for
etl-assessment with the newest etl_assessment_analysis_*.json and package
counts.
```

Review batch (one per batch of at most 10 package paths):

```text
Read and follow plugin/skills/migration/assessment/etl-assessment/SKILL.md.
You are a non-interactive sub-agent. Do not ask questions.
Context: project_dir, ssis_target=dbt|scripting, review_mode=review-batch,
package_paths=[<relative package path>, ...],
etl_assessment_skill_dir=<absolute directory containing etl-assessment/SKILL.md>.
Call configure(project_dir, etl_ssis_target=<ssis_target>). For each path in
package_paths, in order: run scai assessment etl scan-package '<path>', read
its whole output, write that package's analysis from it, and run
scai assessment etl update for that path only. Never run pending, never touch
a package outside package_paths, never reuse text from another package, and
never shorten, grep or skip scan output. If update refuses an analysis,
rescan that package and rewrite it. If you cannot finish every path, return
error naming the paths still PENDING. Return the common JSON contract for
etl-assessment with the newest etl_assessment_analysis_*.json and
done/pending counts for package_paths.
```

Summary:

```text
Read and follow plugin/skills/migration/assessment/etl-assessment/SKILL.md.
You are a non-interactive sub-agent. Do not ask questions.
Context: project_dir, output_dir=<project_dir>/artifacts/assessment/etl,
ssis_target=dbt|scripting, review_mode=summary-only,
etl_assessment_skill_dir=<absolute directory containing etl-assessment/SKILL.md>.
Call configure(project_dir, etl_ssis_target=<ssis_target>). Run Step 4 of the
child skill: scai assessment etl summary, write
<output_dir>/ai_ssis_summary.html, and register it with
scai assessment etl ai-summary. Then run scai assessment etl stats. Return
the common JSON contract for etl-assessment with the newest
etl_assessment_analysis_*.json and total/done/pending counts from stats.
```

### Informatica

Informatica runs in three dispatches, like SSIS, so that no agent holds more
workflows than it can read in full. It always reviews every workflow:

1. **Generate**, in the fan-out, `review_mode=generate-only`. Keep the JSON
   path it returns: it is `assessment_json` for the next dispatches and
   `--informatica-json` for the report.
2. **Review batches**, as soon as the generate child returns `ok`. Run
   `scai assessment etl stats --platform informatica` from the project root.
   While it reports pending workflows, send one review child with
   `batch_size=10`, and send the next only after it has returned. Run `stats`
   again after each one. Stop when no workflow is pending, or when a batch
   returned `error` or left the pending count unchanged.
3. **Summary**, alone, once the last review child has returned.

The fan-out is not complete until the last Informatica dispatch has returned.
Never run two review children at once: each `etl update` rewrites the whole
assessment JSON under its lock. Each child saves its workflows with
`etl update`, so never merge their outputs yourself.

Generate:

```text
Read and follow plugin/skills/migration/assessment/informatica-assessment/SKILL.md.
You are a non-interactive sub-agent. Do not ask questions.
Context: project_dir, output_dir=<project_dir>/artifacts/assessment/etl,
informatica_target=dbt|scripting, review_mode=generate-only.
Call configure(project_dir, etl_informatica_target=<informatica_target>).
Then read etl_informatica_target from <project_dir>/.scai/config/plugin.yml.
If it is missing or differs from informatica_target, return error naming both
values and run nothing else.
From the project root run scai assessment etl generate. If it exits non-zero,
return error with its message and write no HTML. Then run
scai assessment etl stats --platform informatica. Return the common JSON
contract for informatica-assessment with output_json set to the path generate
printed, and the workflow and pending counts from stats.
```

Review batch (one at a time, each up to 10 workflows):

```text
Read and follow plugin/skills/migration/assessment/informatica-assessment/SKILL.md.
You are a non-interactive sub-agent. Do not ask questions.
Context: project_dir, informatica_target=dbt|scripting,
review_mode=review-batch, batch_size=10,
assessment_json=<path the generate child returned>.
Call configure(project_dir, etl_informatica_target=<informatica_target>).
Then read etl_informatica_target from <project_dir>/.scai/config/plugin.yml.
If it is missing or differs from informatica_target, return error naming both
values and run nothing else.
Up to batch_size times: run scai assessment etl pending --platform informatica
(exit 1 means none is pending: stop), run
scai assessment etl scan-package --platform informatica '<path>', read the
source XML it names in full, write that workflow's analysis, and run
scai assessment etl update --platform informatica for that path only. Never
reuse text from another workflow and never skip scan output. If update
refuses an analysis, rewrite it and run update again. If you cannot finish a
workflow you took, return error naming it. Return the common JSON contract
for informatica-assessment with output_json=assessment_json and the
done/pending counts from scai assessment etl stats --platform informatica.
```

Summary:

```text
Read and follow plugin/skills/migration/assessment/informatica-assessment/SKILL.md.
You are a non-interactive sub-agent. Do not ask questions.
Context: project_dir, output_dir=<project_dir>/artifacts/assessment/etl,
informatica_target=dbt|scripting, review_mode=summary-only,
assessment_json=<path the generate child returned>.
Call configure(project_dir, etl_informatica_target=<informatica_target>).
Then read etl_informatica_target from <project_dir>/.scai/config/plugin.yml.
If it is missing or differs from informatica_target, return error naming both
values and run nothing else.
Run
Step 4 of the child skill: scai assessment etl summary --platform informatica,
read the AI summary guide, write <output_dir>/ai_informatica_summary.html, and
register its absolute path with
scai assessment etl ai-summary --platform informatica. These actions are
required. If summary exits non-zero, return error and
write no HTML. If ai-summary exits non-zero, return error. Then run scai assessment etl stats --platform informatica. Return error
rather than ok when the summary HTML is missing or empty. Return the common
JSON contract for informatica-assessment with output_json=assessment_json and
total/done/pending counts from stats.
```

### Discovery

Dispatch only for SQL Server, Teradata, or Redshift when mode is `have_extract`
and paths are non-empty. For `skip`, synthesize `skipped by user`. For `later`,
synthesize `capture SQL provided; re-run assessment with the .xel files` on
SQL Server, `probe and export SQL provided; re-run assessment with the
metrics file` on Teradata, or `extract SQL provided; re-run assessment with
the Redshift metrics file` on Redshift.

```text
Read and follow plugin/skills/migration/assessment/workload-insights/SKILL.md.
You are a non-interactive sub-agent. Do not ask questions.
Context: project_dir, input_paths=<absolute .xel paths (SQL Server) or metrics
CSV paths (Teradata or Redshift)>.
Call configure(project_dir). From project_dir run scai assessment
workload-insights with exactly one --input per path. Return the common JSON
contract for workload-insights with the newest
artifacts/assessment/workload-insights-*.json. ASM0034 is skipped. Exit 0 plus
a written artifact is ok even when stdout reports a large/long parse or
skipped-row warnings from a Teradata or Redshift extract. Never copy input
files into the project.
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

### Business use cases, after the fan-out

The last part of the assessment, after every fan-out agent has returned. It
reads the exclusion findings and Power BI dependencies the earlier steps wrote.
`waves plan` writes `wave-plan.json` for the dashboard and does not write
`planning.wave` or `planning.waveRank`; size-based waves do. It is one
command, three agents and a merge:

1. **Size-based waves**: the parent runs `scai assessment waves` from
   `project_dir`, with no options. It writes `planning.wave` and
   `planning.waveRank` on every deployable object, in category packs of about
   100–200 objects. When it fails, add its error to the Business use cases
   row and continue.
2. **Context pass**, alone. Wait for it.
3. **Lineage search** and **other-objects search**, together in one message.
   Wait for both.
4. **Merge, build and plan**: the parent runs it, below, and turns the result
   into the Business use cases row.

Both searches read the `anchors.json` and `assessment-context-ai.md` the
context pass wrote. Only the lineage search runs `waves catalog` and
`waves use-cases`; the other-objects search writes its own draft and runs no
waves command that writes a file.

Context pass:

```text
Read and follow plugin/skills/migration/assessment/business-use-cases/references/context-pass.md.
You are a non-interactive sub-agent. Do not ask questions.
Context:
- project_dir: <abs_path>
- assessment_skill_dir: <abs_path to the directory the assessment SKILL.md lives in>
Call configure(project_dir); if it cannot be called, return error and stop.
From project_dir run scai assessment waves anchors --json once, summarize where
the data goes with business-use-cases/scripts/catalog_draft.py lineage (uv run
--project <assessment_skill_dir>), read the code freely under source/, and
write artifacts/assessment/assessment-context-ai.md with the sections the
reference lists. Never copy a command, password, connection string or host
name into it. Return the reference's JSON.
```

Lineage search:

```text
Read and follow plugin/skills/migration/assessment/business-use-cases/SKILL.md
in assessment mode, as the lineage search.
You are a non-interactive sub-agent. Do not ask questions.
Context:
- project_dir: <abs_path>
- assessment_skill_dir: <abs_path to the directory the assessment SKILL.md lives in>
- context_md: <project_dir>/artifacts/assessment/assessment-context-ai.md
- context (optional; absolute paths, read in place, never copied; send only the
  kinds the user was asked, taken from business_use_cases.context):
    scheduler: {mode: have_files | skip | later, paths: [...]}   # Informatica in scope
    agent_jobs: {mode: have_files | skip | later, paths: [...]}  # SSIS in scope
    usage: {mode: have_files | skip | later, paths: [...]}
Call configure(project_dir); if it cannot be called, return error and stop.
Do not run scai assessment waves anchors: the context pass did, and the
other-objects search is reading anchors.json. Read context_md in full, follow
business-use-cases/references/context-review.md for every provided context
path, see where the data goes with business-use-cases/scripts/catalog_draft.py
lineage, read the landing objects with catalog_draft.py landing and groups and
their flows with scai assessment waves query flow, and read their sources. Then
write artifacts/assessment/waves/catalog-draft.json grouping landing objects by
outcome, never by folder (anchor ids or groups, never members), and work down
catalog_draft.py unplaced. Run
scai assessment waves catalog and fix every ASM0055 problem, then check
business-use-cases.json with business-use-cases/scripts/compose_use_cases.py
check, both scripts run through uv run --project <assessment_skill_dir>. Run
scai assessment waves use-cases and fix every ASM0050 problem it lists, at most
three rounds. Do not run scai assessment waves plan: the parent plans after the
merge. Never invent a code unit id. Never ask for a wave size, prioritization
patterns or an ordering.
After scai assessment waves catalog, write
artifacts/assessment/waves/use-case-context.json per the contract, listing every
input that applies as reviewed, unusable or notProvided, even when no context was
sent. Context never changes a grade, and no command, password, connection string
or host name is copied from it. Return the skill's JSON: use-cases.json as
output_json, wave_plan null, catalog copied from use-case-catalog.json, context
listing the kinds by status, and at most three top_use_cases copied from
use-cases.json. Return error, not ok, when the catalog holds no use case or a
step was skipped.
```

Other-objects search:

```text
Read and follow plugin/skills/migration/assessment/business-use-cases/references/other-objects.md.
You are a non-interactive sub-agent. Do not ask questions.
Context:
- project_dir: <abs_path>
- assessment_skill_dir: <abs_path to the directory the assessment SKILL.md lives in>
- context_md: <project_dir>/artifacts/assessment/assessment-context-ai.md
Call configure(project_dir); if it cannot be called, return error and stop.
Read context_md in full. Page the groups no exit or report backs with
business-use-cases/scripts/catalog_draft.py unevidenced (uv run --project
<assessment_skill_dir>), read their code with catalog_draft.py landing,
scai assessment waves query flow and their sources, and deduce what they do.
Write artifacts/assessment/waves/other-objects-draft.json: every use case with
origin aiAnalysis and missingEvidence, ids and group keys copied from
anchors.json. Run catalog_draft.py check-ai and fix every problem, at most
three rounds. Never write catalog-draft.json or any CLI artifact, and never run
waves catalog, waves use-cases or waves plan. Return the reference's JSON.
```

Merge, build and plan, run by the parent from `project_dir` once both searches
have returned:

1. When the context pass returned `error`, still dispatch both searches; they
   work without `context_md`. When the lineage search returned `error`, skip
   the merge and fail the Business use cases row with its error. When the
   other-objects search returned `error` or wrote no draft, skip steps 2 and 3
   and plan the lineage catalog as it is; say so in the row.
2. Merge:

   ```bash
   uv run --project "<assessment_skill_dir>" python \
     "<assessment_skill_dir>/business-use-cases/scripts/catalog_draft.py" merge
   ```

   It keeps every lineage use case, takes from each AI analysis use case only
   the landing objects no other use case holds, and drops one left empty or
   repeating an id or a name. Keep its JSON (`aiAnalysis`, `trimmed`,
   `dropped`) for the row.
3. Build and check: `scai assessment waves catalog --json`, then
   `compose_use_cases.py check` (uv run as above). When either lists problems
   on `aiAnalysis` use cases only, send the other-objects search once more with
   those problems and the instruction to fix `other-objects-draft.json` and
   run `check-ai`, then repeat steps 2 and 3. Problems that remain on
   `aiAnalysis` use cases after that: remove those entries from
   `other-objects-draft.json` and repeat steps 2 and 3 once. Never rewrite a
   narrative yourself, and never touch a lineage use case.
4. Rate and plan: `scai assessment waves use-cases --json`, then, when a use
   case is deployable, `scai assessment waves plan --json`.
5. Build the Business use cases row from the files, never from the children's
   text: `output_json` is `use-cases.json`, `wave_plan` is `wave-plan.json`,
   `catalog` is copied from `use-case-catalog.json` (with `ai_analysis` from
   `summary.aiAnalysis`), `context` from the lineage search's return, and at
   most three `top_use_cases` from `use-cases.json` and `wave-plan.json`. Add
   `merge` with the merge JSON from step 2.

### 6.8 Common rules for every dispatch

1. **Enrichment before the fan-out.** When `data_lineage.dispatch` is true and
   `staged_pbits` is non-empty, send `data-lineage` alone first and wait. Then
   send all remaining in-scope dispatches in a single tool-use message. With no
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
   enrich`, `scai assessment object-exclusion` and `scai assessment waves`
   do). Those CLI-owned writes are allowed, and they are ordered:
   enrichment completes before object exclusion runs, and both complete
   before the parent runs `scai assessment waves`.
5. **JSON return only** — free-form text in the report is harder to consume
   reliably.
6. **Business use cases last.** After every other agent has returned, run
   `scai assessment waves`, then dispatch the context pass in a message of
   its own; then both searches
   together; then merge and plan yourself. Nothing else runs beside them.

After the dispatch message, call `hub(mode="wait", confirm=true, cursor=<last>)`.
Do not call `agent_output(wait=true)`, and do not end the turn.
