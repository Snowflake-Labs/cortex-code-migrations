---
name: assessment
description: Use when assessing a SnowConvert migration workload, planning waves, identifying exclusions or risks, estimating effort, analyzing Dynamic SQL or ETL, reviewing SQL Server or Teradata discovery data, or mapping Data Lineage.
version: 0.1.0
license: Proprietary. See License-Skills for complete terms
---

# Assessment

## On Entry

Tell the user:

> **Migration Assessment** — I'll analyze your converted code to generate a
> migration plan: dependency waves, object categorization, dynamic SQL
> patterns, and a summary report.

This is an end-to-end entry point. Given source code, drive setup, registration,
and conversion as needed before assessment. Never ask for CSV, registry, or
output paths; resolve them from the project.

Discovery is the exception: it reads query-log files conversion does not
produce—SQL Server Extended Events (`.xel`) or a Teradata DBQL metrics export
(`.csv`). Step 4 offers skip, existing files, or dialect-specific collection
SQL. Never copy those inputs into the project.

## Non-negotiable rules

1. Call `configure(project_dir=...)` first. Assessment needs no Snowflake
   connection.
2. If invoked directly, call `progress_setup()` and follow its `next_task`
   until `runAssessment` is ready.
3. Use existing `scai` commands/scripts only. Never author assessment JSON,
   registry state, or `multi_report.html`.
4. Generate the final HTML export only with `scai assessment report`.
5. Gather every user input before dispatch. Then follow the Step 5 dispatch
   reference: when Power BI templates are staged, Data Lineage runs alone first;
   otherwise send in-scope Task calls in one message. Do not prompt again until
   results are collected.
6. A child failure does not block siblings. Validate each return and offer one
   retry of failed children using the same captured inputs.
7. Present the Step 8 status table as soon as it is ready. Then ensure/open the
   live dashboard as defined in [On Completion](#on-completion). Opening the
   dashboard must not delay or hide those results.

## Step 0: Configure session

Call `configure` with the absolute `project_dir`. Use the current directory when
unambiguous; otherwise ask once. Do not request Snowflake credentials.

## Step 1: Verify prerequisites

If setup is incomplete, follow `progress_setup()` through init, register, and
convert. Re-enter this skill when it routes to `runAssessment`. If registry or
SnowConvert reports are still absent after a successful-looking conversion,
run `../convert/SKILL.md` once more and stop if they remain absent.

## Step 2: Auto-Detect SnowConvert Outputs

Resolve without prompting:

| Input | Location |
|---|---|
| Project | `project_dir` containing `.scai/` and `registry/` |
| SnowConvert reports | `<project_dir>/reports/SnowConvert/` |
| Dynamic SQL issues | newest `Issues.*.csv` |
| SSIS inputs | newest `ETL.Elements.*.csv` and `ETL.Issues.*.csv`, when present |
| Power BI templates | `<project_dir>/source/BI/PowerBI/**/*.pbit` |
| Assessment output | `<project_dir>/assessment/` |

Scan `.pbix` only to explain that it is unsupported; never process or stage it.
Waves always come from `scai assessment waves` over the registry.

## Step 3: Confirm Scope

Show one compact confirmation:

```text
I will run:
1. Waves (dependency analysis + deployment partitioning)
2. Optimization Opportunities (SQL Server only)
3. Effort Estimates (SQL Server and Redshift only)
4. Dynamic SQL Patterns
5. Discovery (SQL Server and Teradata only — query-log files are optional, asked next)
6. ETL/SSIS Assessment (only if present)
7. Informatica Assessment (only if present)
8. Data Lineage (optional reporting layer such as Power BI — asked next)
9. HTML Report (shareable export; the live dashboard opens when finished)

Proceed with all, or pick a subset?
```

Wait for yes or a subset. This is the only scope confirmation.

## Step 4: Gather Sub-Skill Inputs

**Before asking any analysis-specific question, read
[references/input-collection.md](references/input-collection.md) in full.**
Follow it to stage optional Power BI templates, collect every applicable answer,
and create the in-context `assessment_inputs` snapshot. Do not dispatch until
that snapshot is complete.

## Step 5: Sub-Agent Dispatch

**Before creating Task calls, read
[references/subagent-dispatch.md](references/subagent-dispatch.md) in full.**
Use its exact gates, context fields, command requirements, and JSON return
contracts.

When `data_lineage.dispatch` is true and `staged_pbits` is non-empty, this
step is **two turns**, not one:

1. **Enrichment first.** Dispatch only `data-lineage`. End your turn and wait.
2. **Then the parallel fan-out.** In a later message, fire one Task call per
   remaining in-scope sub-skill. Do not include `data-lineage` again.

When `data_lineage.dispatch` is false, or `staged_pbits` is empty, skip the
first turn and send remaining in-scope sub-skills in one message. Include
`data-lineage` in that fan-out when it is in scope. After each dispatch
message, end the turn.

## Step 6: Wait + Verify Outputs

Collect a JSON object from every child. Data Lineage adds `manifest`; all other
children return:

```json
{
  "sub_skill": "<name>",
  "status": "ok | skipped | error",
  "output_json": "<absolute path> | null",
  "summary": "<one-line counts or reason>",
  "error": "<message> | null"
}
```

Validate each:

| Check | Failure result |
|---|---|
| Return is a JSON object | `error: "no response"` |
| Status is `ok` or `skipped` | returned error |
| `ok` output path exists | `error: "claimed JSON not found"` |
| `ok` output is non-empty | `error: "JSON empty"` |

`"skipped"` is a valid return from any dispatched child, not only from a
dispatch the parent already intended to skip. Because a skip had nothing to
write, its `output_json: null` is the correct answer; it has no manifest and no
enrichment artifact. Data Lineage is the exception: synthesize its skip only
when Step 3 excluded it. A dispatched Data Lineage `"skipped"` return is a
failure. No Power BI input or ASM0039 skips only enrichment; the child must
still run the Data Lineage graph and return `ok` with the stable
`artifacts/assessment/data-lineage.json`. Unresolved references safely omitted
by Data Lineage are also `ok` and must remain in its summary.

When Data Lineage returns a manifest, verify the manifest and
`artifacts/assessment/powerbi/enrichment.json` exist. Do not inspect the
registry to re-audit enrichment.

When Informatica returns `"ok"`, also verify
`<project_dir>/assessment/informatica/ai_informatica_summary.html` exists and
is non-empty. Otherwise fail with `error: "AI summary missing or empty"`.

Create a `results` table in this order:

1. waves-generator
2. object-exclusion-detection
3. effort-estimate
4. anti-patterns
5. analyzing-sql-dynamic-patterns
6. workload-insights
7. etl-assessment
8. informatica-assessment
9. data-lineage

Synthesize skipped rows for excluded/inapplicable analyses.

## Step 7: Generate Unified HTML Report

Resolve the report name:

```bash
uv run --project plugin/skills/migration/assessment \
  python plugin/skills/migration/assessment/scripts/metadata_tools.py \
  --project-dir "<project_dir>" --show-assessment-name
```

When `assessmentName` is unset, ask once using `projectName` as default and
store the answer with:

```bash
uv run --project plugin/skills/migration/assessment \
  python plugin/skills/migration/assessment/scripts/metadata_tools.py \
  --project-dir "<project_dir>" --set-assessment-name "<answer>"
```

A failed write is a warning; continue with the project name.

Run:

```bash
scai assessment report \
  --project-dir "<project_dir>" \
  --output "<project_dir>/assessment/multi_report.html" \
  [--ssis-json "<path>" when etl-assessment is ok] \
  [--informatica-json "<path>" when informatica-assessment is ok]
```

Always pass `--project-dir` and successful SSIS/Informatica outputs explicitly.
Other standard artifacts are auto-discovered. Do not write custom HTML. Record
a report failure and continue so the user still receives analysis results.

For partial assessment routing, script invocation rules, or nonstandard report
paths, read
[references/report-and-routing.md](references/report-and-routing.md).

## Step 8: Surface Results + Retry

Present one status line per result in the order above, then this report line:

```text
Multi-tab report: <absolute multi_report.html path>
```

If generation failed, print `FAILED — see error above`.

Label the final row **Data Lineage**. Its summary includes graph counts,
optional Power BI enrichment counts, and any unresolved references.
An `ok` row cites the child-generated stable
`artifacts/assessment/data-lineage.json`.

If any child failed, ask after the table:

> Retry failed sub-skills? Successful JSONs will be reused — only failed runs
> re-fire. (yes / no)

Surface the failed rows with this prompt so the user knows what is being
retried. Do not withhold the rest of the table.

On yes, re-dispatch only failures using the original `assessment_inputs`, repeat
validation, regenerate the report, and reprint the table. On no, retain the
failed rows. Do not delete old timestamped artifacts.

### Pre-completion check

Verify:

- Every requested analysis is `ok` or explicitly `skipped`.
- Reviewed Dynamic SQL has no PENDING records.
- `scai assessment report` received every successful explicit output.
- No custom HTML was written.

Then perform On Completion. Do not stop after generating artifacts.

## Analysis routing

| Request | Skill |
|---|---|
| Waves | `waves-generator/SKILL.md` |
| Exclusions | `object_exclusion_detection/SKILL.md` |
| Effort | `effort-estimate/SKILL.md` |
| Anti-patterns | `anti-patterns/SKILL.md` |
| Dynamic SQL | `analyzing-sql-dynamic-patterns/SKILL.md` |
| Discovery | `workload-insights/SKILL.md` after input collection |
| SSIS | `etl-assessment/SKILL.md` |
| Informatica | `informatica-assessment/SKILL.md` |
| Data Lineage / Power BI | `data-lineage/SKILL.md` after input collection |

Data Migration & Validation and Testing readiness are registry-derived report
sections, not sub-skills.

## On Completion

The Step 8 status table is already on screen. Run these actions **before**
presenting the closing message. Do not reprint or withhold that table.

1. Actually call
   `configure(project_dir="<project_dir>", dashboard_port=-2)`. Do not rely on
   or try to remember the first configure response.
2. For `Dashboard started at <url>` or
   `Dashboard already running at <url>`, `<url>` is the dashboard's base URL,
   not a report page. Build the Assessment page as `<url>/assessment` by
   appending the suffix exactly once — if `<url>` already ends in
   `/assessment`, use it as-is rather than producing `/assessment/assessment`.
   Then actually run the platform opener on that page URL:
   - `open` on macOS: `open "<url>/assessment"`
   - `xdg-open` on Linux: `xdg-open "<url>/assessment"`
   - `start` on Windows: `start "" "<url>/assessment"`
   Do not merely print or suggest the command. Do not also open HTML after a
   successful dashboard open.
3. For `Dashboard disabled (port 0)`, respect the opt-out and actually open
   `<project_dir>/assessment/multi_report.html` with the platform opener.
4. If dashboard startup fails and configure reports
   `Dashboard not started: <error>`, report its error and open the HTML export.
5. If the platform-specific open command fails, print the attempted URL/path,
   try the HTML export when the dashboard target failed, and continue to the
   next-steps menu. Opening failure must not erase assessment results already
   shown.

Present the closing message with:

- opening line: `migration_status.in_scope` objects in `wave_count` waves;
- summary table: Register, Convert, ETL conversion, Waves, Object exclusion,
  Dynamic SQL, SSIS/Informatica, Missing objects;
- 2–4 triggered findings only (staging ≥30%, unresolved external references,
  conversion friction, ETL risk, circular dependencies);
- the Step 7 HTML export path;
- this menu, describing what actually opened:

> What would you like to do?
> 1. **Review the dashboard** — if a dashboard page opened, say `Assessment opened at <url>/assessment` and invite questions; if the HTML export opened instead, say `HTML report opened at <path>`; if neither opened, say `Review the results above; the dashboard could not be opened`
> 2. **Modify the assessment** — re-run with changed parameters
> 3. **Move on to migration setup** — configure the Snowflake target, testing,
>    and data infrastructure

Recommend option 1 when `missing > 0`; otherwise recommend option 3. Wait.

For option 3, submit the answer instead of asking twice:

```text
progress_setup(answers={"run_mode": "manual"})
```

This satisfies the setup machine's `chooseRunMode` gate. Follow the returned
setup task. Do not load `../migrate-objects/SKILL.md` directly because no
Snowflake target exists yet.
