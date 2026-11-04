---
name: assessment
description: Use when assessing a SnowConvert migration workload, finding its business use cases and planning one migration wave per use case, identifying exclusions or risks, estimating effort, analyzing Dynamic SQL or ETL, reviewing SQL Server, Teradata, or Redshift discovery data, or mapping Data Lineage.
version: 0.1.0
license: Proprietary. See License-Skills for complete terms
---

# Assessment

## On Entry

Tell the user:

> **Migration Assessment** — I'll analyze your converted code to generate a
> migration plan: the business use cases in your workload with one migration
> wave per use case, object categorization, dynamic SQL patterns, and a
> summary report.

This is an end-to-end entry point. Given source code, drive setup, registration,
and conversion as needed before assessment. Never ask for CSV, registry, or
output paths; resolve them from the project.

Discovery is the exception: it reads query-log files conversion does not
produce—SQL Server Extended Events (`.xel`) or a Teradata DBQL metrics export
(`.csv`), or a Redshift `SYS_QUERY_HISTORY` metrics export (`.csv`). Step 4
offers skip, existing files, or dialect-specific collection SQL. Never copy
those inputs into the project.

## Non-negotiable rules

1. Call `configure(project_dir=...)` first. Assessment needs no Snowflake
   connection.
2. If invoked directly, call `progress_setup()` and follow its `next_task`
   until `runAssessment` is ready.
3. Use existing `scai` commands/scripts only. Never author assessment JSON,
   registry state, or `multi_report.html`. Every assessment command is
   `scai assessment <subcommand>` (`waves`, `report`, `object-exclusion`,
   `anti-patterns`, `effort-estimate`, `sql-dynamic`, `conversion-issues`,
   `data-lineage`, see [Command reference](#command-reference));
   there is no `scai assess` or `scai code assess`. Projects with AI-First ETL
   (Hop, Alteryx, ...) take the same path; their units appear in the waves.
4. Generate the final HTML export only with `scai assessment report`.
5. Gather remaining user input before dispatch. When `assessment_options` is
   already set (AIM collected Q1 and `assessment_name` on one
   `progress_setup` card), skip the Step 3 confirmation — do not ask it again.
   `progress_setup` returns those answers under `answered`; when that block is
   present, the scope is settled and no scope question goes to the user.
   Never ask for a wave size, prioritization patterns or a wave ordering: one
   business use case is one wave, ordered by dependency inside it. Still
   collect only the remaining Step 4 inputs selected by those tokens. Then
   follow the Step 5 dispatch reference: when Power BI templates are staged,
   Data Lineage runs alone first; then send the other in-scope Task calls in
   one message; business use cases run alone last. Do not prompt again until
   results are collected.
6. A child failure does not block siblings. Validate each return and offer one
   retry of failed children using the same captured inputs.
7. Present the Step 8 status table as soon as it is ready. Then ensure/open the
   live dashboard as defined in [On Completion](#on-completion). Opening the
   dashboard must not delay or hide those results.

## Command reference

`progress_setup` sends this block with `runAssessment` as `next_skill_commands`.
<!-- next-skill-commands:begin -->
Assessment commands, each run from `<project_dir>` (`waves` takes no `--project-dir`).
They are the only ones: no `scai assess`, `scai assessment run`, or `scai code assess`.
Each analysis runs in its own sub-agent per Step 5; the report runs last (Step 7).
- Waves: `scai assessment waves`
- Object exclusion: `scai assessment object-exclusion`
- Effort estimate: `scai assessment effort-estimate`
- Anti-patterns (SQL Server): `scai assessment anti-patterns`
- Dynamic SQL: `scai assessment sql-dynamic generate --project-dir <project_dir> --output <project_dir>/assessment/json/sql_dynamic_analysis.json`
- Conversion issues: `scai assessment conversion-issues`
- Data Lineage: `scai assessment data-lineage`
- Report (the step's done signal): `scai assessment report --project-dir <project_dir> --output <project_dir>/assessment/multi_report.html`
<!-- next-skill-commands:end -->

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
| SnowConvert reports | First directory that contains the needed conversion files: `<project_dir>/.scai/reports/SnowConvert/`, then `<project_dir>/reports/SnowConvert/`, then `<project_dir>/Reports/SnowConvert/`. Stop at the first hit. A leftover older folder can be stale if `.scai` already has the files. |
| Dynamic SQL issues | newest `Issues.*.csv` |
| SSIS inputs | newest `ETL.Elements.*.csv` and `ETL.Issues.*.csv`, when present |
| Power BI templates | `<project_dir>/source/BI/PowerBI/**/*.pbit` |
| Assessment output | `<project_dir>/assessment/` |

Scan `.pbix` only to explain that it is unsupported; never process or stage it.
Business use cases and their waves always come from the `scai assessment
waves` tools over the registry, into `<project_dir>/artifacts/assessment/waves/`.
Conversion CSVs under `.scai/` or the legacy `reports/` folders are for tooling. Point users at AIM Assessment (HTML report or the conversion-reports zip), not at those folders.

## Step 3: Confirm Scope

Call `configure()` and read `assessment_options` and
`assessment_conversion_issues`. If `assessment_options` is a non-empty
comma-separated token list **and** `assessment_conversion_issues` is `yes` or
`no`, **do not wait**: those are the scope and Conversion Issues answers.
Continue to Step 4. If only `assessment_options` is set, ask just the
Conversion Issues yes/no below with one `ask_user_question` call and persist it
to `assessment_conversion_issues` before Step 4. Data Lineage always runs;
Power BI enrichment uses the templates registration already staged without
another yes/no.

Otherwise use one `ask_user_question` call for three questions, in this order:
the multi-select scope question, the Conversion Issues yes/no, and the report
name (default from `metadata_tools.py --show-assessment-name`):

```text
Business use cases with one migration wave each, standard analyses, Data
Lineage, and the HTML report always run.
What else do you want? Select all that apply:
- Deep Dynamic SQL review
- Discovery (SQL Server, Teradata, or Redshift only)
- AI analysis of SSIS packages (when present)
- None of these
```

```text
Include a Conversion Issues report? It ranks the SSC-EWI issues from this conversion, writes a local ZIP for Jira, and adds the section to the assessment report. Nothing is uploaded unless you share it later.
- Yes
- No
```

Persist the comma-separated tokens to `assessment_options`, the yes/no to
`assessment_conversion_issues` (`yes` or `no`), and the third answer to
`assessment_name`. This is the only scope/name confirmation.

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
step is **three steps**:

1. **Enrichment first.** Dispatch only `data-lineage` and wait for it.
2. **Then the parallel fan-out.** In a later message, fire one Task call per
   remaining in-scope sub-skill except `business-use-cases`. Do not include
   `data-lineage` again.
3. **Then business use cases.** Once every fan-out agent has returned,
   dispatch `business-use-cases` alone and wait for it. It reads the
   exclusion findings and Power BI dependencies the earlier steps wrote, and
   its plan writes the registry, so it never runs beside another child.

When `data_lineage.dispatch` is false, or `staged_pbits` is empty, skip the
first step and send the fan-out in one message. Include `data-lineage` in that
fan-out when it is in scope. Business use cases still run alone after it.

**Wait in the same turn; do not end it.** After each dispatch message, call
`agent_output(agent_id=<id>, wait=true)` for every agent that message launched,
all in one message, and repeat the call for any agent that has not completed
when it returns. Then go on to Step 6 in the same turn. Ending the turn to wait
for the automatic completion notice hides everything after it in the AIM app:
the turn cortex starts on its own is not streamed, so the verification, report
and next questions never appear.

**Tell the user what is running before you wait.** Put this message's text in
the dispatch message itself, ahead of the Task calls, so the user sees it while
the analyses run. In two or three plain sentences, with no table or checklist:

- name every analysis you launched, e.g. "object exclusion, effort
  estimate, anti-patterns, dynamic SQL and SSIS"; say which are slow and why,
  such as per-item review, and that business use cases and their waves come
  last because they build on these results;
- say that each one runs as its own tab above the conversation, where the user
  can watch it, and that any command it asks to run shows a permission card
  that needs approval before that analysis can go on;
- say that on a large project the slow ones can run for many minutes, and that
  you post a short line every few minutes until they finish;
- say how the user will know the step is done: you report each analysis as it
  finishes, then you build the combined report (`multi_report.html`), which
  ends the step.

**Update as they finish, and while they run.** Each time an `agent_output` wait
returns, write one sentence, then wait again. When analyses finished, name them
with their one-line summary and say which are still running. When none finished,
say which are still running and what each is on now, from its latest output
(such as the package or object it reached), so the conversation is never silent
for minutes. A wait that returns before its agent finishes is not a failure, and
the user sees no card for it, so never describe it as "timed out". Never close a
message with a promise to collect the results later: keep waiting in the same
turn.

A permission card the user sees marked **Timed out** belongs to one analysis's
command, which did not run. Do not explain it as your own wait. Name the
analysis it belongs to, say its command was not approved in time so it did not
run, and that you will offer to re-run it with the results (Step 8's retry).

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
enrichment artifact. Data Lineage is the exception: it always runs, and a
`"skipped"` return is a failure. No Power BI input or ASM0039 skips only
enrichment; the child must
still run the Data Lineage graph and return `ok` with the stable
`artifacts/assessment/data-lineage.json`. Unresolved references safely omitted
by Data Lineage are also `ok` and must remain in its summary.

When Data Lineage returns a manifest, verify the manifest and
`artifacts/assessment/powerbi/enrichment.json` exist. Do not inspect the
registry to re-audit enrichment.

Business use cases add `wave_plan` and `top_use_cases`. When `wave_plan` is not
null, verify it exists; otherwise fail with `error: "wave plan missing"`. A
`null` plan with an `ok` status means no use case was deployable, which its
summary says.

Conversion issues does not skip a missing registry: `ASM0045` is `error`. Zero pairs is `ok`. When `assessment_conversion_issues` is not `yes`, synthesize `skipped` and do not dispatch it. An `ok` return with one or more summary rows is complete only when every summary row has a non-empty `problem_description` and `recommended_fix`. Empty fields mean the child stopped after the first command: fail it with `error: "conversion-issues enrichment missing"` and offer the retry. The parent does not upload the ZIP; the HTML tab shows the ZIP path and the Share issues link.

When Informatica returns `"ok"`, also verify
`<project_dir>/assessment/informatica/ai_informatica_summary.html` exists and
is non-empty. Otherwise fail with `error: "AI summary missing or empty"`.

Create a `results` table in this order:

1. business-use-cases
2. object-exclusion-detection
3. effort-estimate
4. anti-patterns
5. analyzing-sql-dynamic-patterns
6. conversion-issues
7. workload-insights
8. etl-assessment
9. informatica-assessment
10. data-lineage

Synthesize skipped rows for excluded/inapplicable analyses.

## Step 7: Generate Unified HTML Report

Resolve the report name. Do not ask for a report name here; AIM collected it
on the assessment scope card:

```bash
uv run --project plugin/skills/migration/assessment \
  python plugin/skills/migration/assessment/scripts/metadata_tools.py \
  --project-dir "<project_dir>" --show-assessment-name
```

Read `assessment_name` from `configure()`. When it is unset (legacy/direct
entry), use `resolved` from the command above. Store that value with:

```bash
uv run --project plugin/skills/migration/assessment \
  python plugin/skills/migration/assessment/scripts/metadata_tools.py \
  --project-dir "<project_dir>" \
  --set-assessment-name "<assessment_name, or resolved for a legacy session>"
```

A failed write is a warning; continue with the project name.

Read `plugin_version`: the trimmed text of `VERSION` at the plugin root,
three directories above this SKILL.md. Run:

```bash
scai assessment report \
  --plugin-version "<plugin_version>" \
  --project-dir "<project_dir>" \
  --output "<project_dir>/assessment/multi_report.html" \
  [--ssis-json "<path>" when etl-assessment is ok] \
  [--informatica-json "<path>" when informatica-assessment is ok]
```

The command also writes a sibling PDF of every tab beside the HTML. It needs Chrome, Edge, or Chromium. If the PDF cannot be rendered, the HTML is still written and the command fails.

Always pass `--project-dir` and successful SSIS/Informatica outputs explicitly.
Pass `--plugin-version` so the report names the plugin build; leave it out only
when `VERSION` cannot be read.
Other standard artifacts are auto-discovered. Do not write custom HTML. Record
a report failure and continue so the user still receives analysis results.

For partial assessment routing, script invocation rules, or nonstandard report
paths, read
[references/report-and-routing.md](references/report-and-routing.md).

## Step 8: Surface Results + Retry

Present one status line per result in the order above, then the report path.
Print the label as plain text and fence only the path, so copying the block
yields a usable path:

Multi-tab report:

```text
<absolute multi_report.html path>
```

If generation failed, print `Multi-tab report: FAILED — see error above`
unfenced.

Label the final row **Data Lineage**. Its summary includes graph counts,
optional Power BI enrichment counts, and any unresolved references.
An `ok` row cites the child-generated stable
`artifacts/assessment/data-lineage.json`.

Label the first row **Business use cases**. Then, when it returned
`top_use_cases`, show them as a numbered list, at most three, in rank order.
Each entry gives the name and its purpose in one line, then
`<objects> objects (SQL <sql>, ETL <etl>, BI <bi>)`. Say that the first is
recommended to migrate first, that each use case deploys its objects in
dependency order, and that the dashboard's Planning section lists every use
case. Do not show wave numbers or confidence: each use case is migrated on its
own, and confidence is internal. This is information, not a question: do not
ask the user to choose here.

When the user later asks to start with another use case, re-plan with that id
first and every other rated id from `use-cases.json` after it, in rank order:

```bash
scai assessment waves plan --use-case <chosen-id> --use-case <next-id> ...
```

A request for a wave or use case around an app, a process, a report or an
object goes to `business-use-cases/SKILL.md` in on-demand mode.

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
| Business use cases; a wave for an app, process, report or object | `business-use-cases/SKILL.md` |
| Size-based waves, only when explicitly asked (a wave size, prioritization patterns, category order) | `waves-generator/SKILL.md` |
| Exclusions | `object_exclusion_detection/SKILL.md` |
| Effort | `effort-estimate/SKILL.md` |
| Anti-patterns | `anti-patterns/SKILL.md` |
| Dynamic SQL | `analyzing-sql-dynamic-patterns/SKILL.md` |
| Conversion issues | `conversion-issues/SKILL.md` |
| Discovery | `workload-insights/SKILL.md` after input collection |
| SSIS | `etl-assessment/SKILL.md` |
| Informatica | `informatica-assessment/SKILL.md` |
| Data Lineage / Power BI | `data-lineage/SKILL.md` after input collection |

Data Migration & Validation and Testing readiness are registry-derived report
sections, not sub-skills.

## On Completion

The Step 8 status table is already on screen. Run these actions **before**
presenting the closing message. Do not reprint or withhold that table.

**Desktop app (`app_info` tool is available):** skip steps 1–5 entirely — the
app has its own dashboard panel and does not use the local dashboard or platform
opener. Go straight to the closing message below.

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
- summary table: Register, Convert, ETL conversion, Business use cases,
  Object exclusion, Dynamic SQL, SSIS/Informatica, Missing objects;
- 2–4 triggered findings only (staging ≥30%, unresolved external references,
  conversion friction, ETL risk, circular dependencies);
- the Step 7 HTML export path;
- this menu, describing what actually opened (skip option 1 when in the desktop
  app, since the app has its own dashboard):

> What would you like to do?
> 1. **Review the dashboard** — if a dashboard page opened, say `Assessment opened at <url>/assessment` and invite questions; if the HTML export opened instead, say `HTML report opened at <path>`; if neither opened, say `Review the results above; the dashboard could not be opened`
> 2. **Modify the assessment** — re-run with changed parameters, or start
>    with a different business use case
> 3. **Move on to migration setup** — configure the Snowflake target, testing,
>    and data infrastructure

Recommend option 1 when `missing > 0`; otherwise recommend option 3. Wait.
In the desktop app, show only options 2 and 3 (renumber accordingly) and
recommend option 2 (move on to migration setup).

If `configure` reported a dashboard URL at session start (not applicable in the
desktop app), add one line before the menu:
> The dashboard at `<url>` shows the same picture live as you migrate.

Skip it if no URL came back (the user opted out, or the port was busy) — never guess one.

On **Move on to migration setup** (option 3, or option 2 in the desktop app), the
user has just answered the setup machine's `continueToMigration` gate, so
**submit it rather than letting the gate ask again**:

```
progress_setup(answers={"continue_to_migration": "true"})
```

Act on that response as `setup/SKILL.md` describes — it walks git, the Snowflake
target and the testing choice. Calling a bare `progress_setup()` here instead
makes the machine put the same question to the user a second time. The same
applies later: if the user reviews the report and *then* says to move on, submit
the answer with that call. Do not load `../migrate-objects/SKILL.md` directly
from here; it has no Snowflake target configured yet.
