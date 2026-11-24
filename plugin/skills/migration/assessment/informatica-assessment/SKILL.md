---
name: informatica-assessment
description: Analyze Informatica Power Center workflows/mappings with the `scai assessment etl` commands, from the Code Unit Registry, SnowConvert ETL.* outputs and source XML files. Classifies workflows, scores migration complexity, and produces JSON for the parent assessment multi-report.
parent_skill: assessment
license: Proprietary. See License-Skills for complete terms
---

# Informatica Power Center Assessment

**Snowflake AIM for Data Warehouses** migrates Informatica Power Center workflows to Snowflake. This skill analyzes workflows and mappings from their source XML and SnowConvert assessment CSV reports to generate detailed migration analysis including workflow classification and complexity assessment. Every step runs a `scai assessment etl` command with `--platform informatica`.

---

## Sub-Agent Mode

When invoked from the parent `assessment` skill as a sub-agent, the parent provides a context block with the fields below. The `review_mode` field controls which steps run.

| Field | Required | Notes |
|---|---|---|
| `project_dir` | yes | absolute path to the SCAI project root |
| `output_dir` | except with `review-batch` | `<project_dir>/artifacts/assessment/etl`; the CLI writes the assessment JSON there, and `ai_informatica_summary.html` goes beside it |
| `informatica_target` | yes | `dbt` or `scripting`. Use it for Step 3 and Step 4; **On entry** checks that the project stores it. |
| `review_mode` | yes | `generate-only`, `review-batch`, `summary-only`, or `auto-review-all` |
| `parent_review_mode` | with `generate-only` from the parent | always `generate-only` during assessment. On-demand review may send `auto-review-all` later. |
| `batch_size` | with `review-batch` | how many pending workflows this agent reviews, at most 10 |
| `assessment_json` | with `review-batch` and `summary-only` | the absolute JSON path the generate child returned. Return it as `output_json`; the commands find the artifact themselves, so never pass it to them |

**On entry:** call the `configure` MCP tool with `project_dir` and `etl_informatica_target=<informatica_target>`. `scai assessment etl generate` reads that setting into the JSON's `summary.conversion_mode`, and uses `dbt` when it is unset. In a session whose `subagent_mode` latch makes `configure` attach-only, `configure` reports `etl_informatica_target` as not applied and leaves the stored value as it was. So after `configure`, read `etl_informatica_target` from `<project_dir>/.scai/config/plugin.yml`. If it is missing or differs from `informatica_target`, return `status: error` with `error: "Informatica target not recorded: plugin.yml has <stored or none>, expected <informatica_target>"`, and run no `scai assessment etl` command and write no HTML. Snowflake credentials are not required.

**Branching by `review_mode`:**

- `generate-only` — run Steps 1–2. Return the JSON path `generate` printed and the `stats` counts; do not review workflows or write the AI summary.
- `review-batch` — run Step 3 for at most `batch_size` workflows, each taken from `pending`. Do not generate and do not write the AI summary. Return `ok` when every workflow you took is DONE, or when `pending` reports none left.
- `summary-only` — run Step 4 only, then `scai assessment etl stats --platform informatica`, and report its total, done and pending counts.
- `auto-review-all` — direct entry only; the parent assessment never sends it. Run all four steps. Stop only when `stats` reports no pending workflows.

**On completion**, return **JSON only**:

```json
{
  "sub_skill": "informatica-assessment",
  "status": "ok",
  "output_json": "<abs path generate printed, or assessment_json>",
  "summary": "<one-line: total workflows, classified count, pending count, target>",
  "error": null
}
```

On failure: `"status": "error"`, `"error": "<message>"`.

## On-demand AI analysis

Assessment never reviews workflows. When the user later asks AIM to run AI
analysis on Informatica (analyze workflows, analyze ETL, and the like):

1. **Ask first.** Do not start review in that reply. This is a question AIM
   must wait on, not a default to all.
2. If that message already names one or more workflows, confirm those names
   and skip the menu.
3. Otherwise ask this, with the pending count from
   `scai assessment etl stats --platform informatica` when you have it (about
   **60s per workflow**, because each one is scanned and written back on its
   own):

   > N workflows have no AI analysis yet. Each takes about 60 seconds.
   >
   > Do you want AI analysis for:
   > 1. All of them
   > 2. Some of them
   > 3. One workflow

   Do not start review until they answer. If they pick some or one and have
   not named workflows, ask which names next.
4. Then stay in this turn. Run review batches of at most **10 workflows**, one
   after another, never side by side, as subagent-dispatch.md § Informatica
   says. Then the summary child.
5. Do not start this from the assessment scope card.

## Important Notes

- **No help command**: the `scai assessment etl` commands are hidden (AI-agent only). `--help` returns "No help available". They are documented in this skill only.
- **Always pass `--platform informatica`** to `pending`, `scan-package`, `update`, `stats`, `summary` and `ai-summary`. `generate` takes no platform: it reads the project's one ETL platform from the Code Unit Registry.
- **Auto-detection**: run every command from the project root. Each one finds the newest `artifacts/assessment/etl/informatica_assessment_analysis_<timestamp>.json` itself; do not pass a JSON path.
- **Single argument for scan-package**: pass only the workflow's relative path, as `pending` printed it.

## Rules

1. **Use ONLY the `scai assessment etl` commands**
   - Generation and tracking go through `generate`, `pending`, `scan-package`, `update`, `stats`, `summary` and `ai-summary`
   - DO NOT create custom scripts to read or manipulate the JSON file
   - DO NOT use grep, jq, or other tools to parse the JSON directly

2. **One workflow, one analysis**
   - Analyze each workflow from its own `scan-package` output and source XML, whatever the volume; never batch or reuse
     analysis text across workflows, because the report presents each workflow's analysis on its own.

3. **One writer, one workflow at a time**
   - Run the per-workflow loop yourself, in this agent, one workflow after another. Never split the workflows across
     sub-agents, Task calls, background jobs or shell loops, and never run two `scai assessment etl` commands at once.
   - Each `update` loads the whole assessment JSON, changes one workflow and writes it back under a lock. Progress is
     saved after every `update`, so a later run resumes from `pending`.
   - In `review-batch` mode the parent sends the batches one after another, never side by side.

4. **Follow ONLY Provided Analysis Methods**
   - Use ONLY the workflow defined in this skill

5. **Complete ALL Steps of the selected mode**
   - When the user selected AI analysis (`auto-review-all`), Step 4 (AI Summary) is MANDATORY before the assessment finishes
   - Every checkpoint of the selected mode must be completed

6. **Report Generation via Parent Skill ONLY**
   - The multi-report generator in the parent skill (`../SKILL.md`) is the ONLY approved method
   - The parent passes the JSON path `generate` printed as `--informatica-json`

7. **Stop when a command fails**
   - If a `scai assessment etl` command exits non-zero, show that error and stop. Two exits are not failures: `pending` exiting 1 means no workflow is pending, and `update` refusing an analysis (`ASM0019`) means rewrite that analysis and run `update` again
   - Do not write `ai_informatica_summary.html` or any other HTML after a failed `generate` or `summary`

---

## Workflow

### Conversion Target Context

The parent assessment skill collects `informatica.target` ("dbt" or "scripting"), or reuses the `etl_informatica_target` the project already recorded, and passes it as `informatica_target`. It determines how this skill frames its analysis:

- **dbt**: Mappings convert to dbt models. References to dbt project structure, `ref()`, and Snowflake Tasks calling dbt are appropriate.
- **scripting**: Mappings convert to Snowflake stored procedures (Snowflake Scripting). Zero dbt references allowed — use stored procedure calls, inline SQL, and `CALL` statements instead.

Use `informatica_target` to select the analysis framing in Step 3 and the AI summary guide in Step 4.

Copy this checklist and track your progress:

```
Analysis Progress:
- [ ] Step 1: Locate and Validate Input Files
- [ ] Step 2: Generate JSON Analysis
- [ ] Step 3: Analyze Informatica workflows (sub workflow)
- [ ] Step 4: Draft AI summary (HTML AI summary)
```

## Step 1: Locate Input Files (auto-detected)

**Do NOT prompt the user for paths.** `scai assessment etl generate` resolves its inputs from `project_dir`:

| Input | Auto-resolution |
|-------|-----------------|
| Informatica units | The Code Unit Registry at `<project_dir>/registry/`: units with kind `etl` and platform Informatica |
| `ETL.Elements.csv`, `ETL.Issues.csv` | Newest pair in `<project_dir>/.scai/reports/SnowConvert/`, then `reports/SnowConvert/`, then `Reports/SnowConvert/` |
| Informatica source dir | `<project_dir>/source/_etl/` (PowerCenter XML exports) |
| Output dir | `<project_dir>/artifacts/assessment/etl/` (created by `generate`) |

**Validation (silent — only surface a problem if it fails):** when `generate` fails with `ASM0014`, the registry has no in-scope Informatica units: return to the parent and ask it to re-run register (`code add`) then `convert`.

---

## Step 2: Generate JSON Analysis

From the project root:

```bash
scai assessment etl generate --review-mode <parent_review_mode>
```

It prints the absolute path of the assessment JSON it wrote; that path is `output_json`. It writes two files with one timestamp to `<project_dir>/artifacts/assessment/etl/`:
- `informatica_assessment_analysis_<timestamp>.json` — the assessment data the report reads
- `informatica_dag_model_<timestamp>.json` — the workflow and mapping graphs

`--review-mode` records what the user selected as `summary.review_mode`: `parent_review_mode` when the parent sent it, else your own `review_mode` when it is `generate-only` or `auto-review-all`. Never pass the generate phase's own `generate-only` when the parent sent `parent_review_mode=auto-review-all`: the report would then treat the run as generate-only (analyzer complexity, no pending count) instead of listing the workflows still pending. Under `generate-only` the banner says "AI analysis pending" and shows each workflow's complexity.

If it exits non-zero, stop and show its error. Do not write an HTML file.

## Step 3: Analyze Informatica Workflows

This step is a sub workflow to analyze workflows individually. After this, continue with step 4.

**Important:** To analyze workflows, follow the detailed instructions in [references/writing_analysis.md](references/writing_analysis.md). This reference explains:
- What to read from the XML files (MAPPING, TRANSFORMATION, SOURCE, TARGET elements)
- How to classify workflows (with concrete criteria for each category)
- Required analysis format and minimum lengths

### Sub-Workflow: Analyze Each Workflow

For each pending workflow (in `review-batch` mode, at most `batch_size` of them):

1. Get the next pending workflow. It prints `Name: <name> | Relative Path: <WORKFLOW_PATH>`, or exits 1 when none is pending:

```bash
scai assessment etl pending --platform informatica
```

2. Scan it. The output names the workflow's source XML and the mapping files it runs:

```bash
scai assessment etl scan-package --platform informatica '<WORKFLOW_PATH>'
```

3. Analyze the workflow:
   - Read the source XML files the scan named
   - Examine the mappings, transformations, source/target definitions
   - Identify custom transformations, SQL overrides, complex expressions
   - Classify the workflow based on the criteria in [references/writing_analysis.md](references/writing_analysis.md)

4. Write analysis following the **mandatory format** in [references/writing_analysis.md](references/writing_analysis.md).

   **Note:** Analysis is validated. If the format is wrong, `update` fails with `ASM0019` and guidance; nothing is saved.

5. Save it:

```bash
scai assessment etl update --platform informatica '<WORKFLOW_PATH>' \
  --ai-status DONE \
  --classification "Data Transformation" \
  --ai-analysis "<ANALYSIS_TEXT>"
```

`--classification` is one of: Ingestion, Data Transformation, Configuration & Control, Mixed: Ingestion + Transformation.

6. Repeat until no pending workflows remain (or the batch is done), then check:

```bash
scai assessment etl stats --platform informatica
```

---

## Step 4: Draft AI Summary

**DO NOT SKIP THIS STEP.** The AI Summary is required before finishing the assessment.

**Required Actions:**

1. Run the summary command to get all signals:

```bash
scai assessment etl summary --platform informatica
```

2. Read the guide: [references/ai_summary_guide.md](references/ai_summary_guide.md)

3. Generate summary file: `<project_dir>/artifacts/assessment/etl/ai_informatica_summary.html`
   - Follow the structured HTML template in the guide
   - Include all 6 sections: Workload Overview, Classification Breakdown, Sources & Destinations, Complexity Drivers, Recommended Migration Approach, Key Risks
   - Use real data from the summary command output
   - Use inline styles (not CSS classes) since this is an embedded HTML snippet
   - **IMPORTANT: The file must be a fragment only** — do NOT include `<!DOCTYPE>`, `<html>`, `<head>`, `<body>`, or `<h1>` tags. The report generator provides the section heading (`<h2>AI Summary</h2>`) automatically.

4. Register the summary in the JSON, with the absolute path:

```bash
scai assessment etl ai-summary --platform informatica "<project_dir>/artifacts/assessment/etl/ai_informatica_summary.html"
```

**Verification Checklist:**
- [ ] `<project_dir>/artifacts/assessment/etl/ai_informatica_summary.html` exists and is non-empty
- [ ] Summary includes all 6 sections from the guide template
- [ ] Summary uses specific numbers (not vague terms like "many")
- [ ] Summary registered with `ai-summary` command

**Completion:**
Do not report success until every verification item passes. If the HTML file is
missing or empty, finish Step 4 before returning to the parent. If registration
fails, report an error instead of `"ok"`.

Report to user:
- Total workflows analyzed
- JSON file location: the path `generate` printed, under `<project_dir>/artifacts/assessment/etl/`
- Go to main workflow in parent skill
