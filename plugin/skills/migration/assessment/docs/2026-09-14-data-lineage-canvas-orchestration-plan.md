# Data Lineage as an assessment sub-skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Data Lineage is a first-class assessment step, same as Waves: the parent lists it, gathers optional reporting-layer files, and dispatches one sub-agent that enriches the CUR from Power BI when present, then writes the lineage graph and returns a result.

**Architecture:** Keep the directory and JSON id `data-lineage`. Change what that id *means*. The child skill is no longer "Power BI Lineage Enrichment" that stops at the registry. It is the Data Lineage assessment: (1) optional Power BI extract+enrich when the parent staged `.pbit` files, (2) `scai assessment data-lineage` to fold the CUR into `artifacts/assessment/data-lineage.json`, (3) a one-line result the parent surfaces. The parent no longer treats Power BI as a sibling analysis. Step 4 asks whether the user has a reporting layer (Power BI `.pbit`) to add or add more — only as input to this sub-skill. Sub-agents stay non-interactive; that question stays on the parent.

**Tech Stack:** `assessment/SKILL.md`, `data-lineage/SKILL.md`, `USER_GUIDE.md`, pytest static contracts in `ai/tests/assessment/data_lineage/test_powerbi_skill_contract.py`. Existing CLIs only: `powerbi extract`, `powerbi enrich`, `assessment data-lineage`. No C# change.

## Global Constraints

- Implement on **`feat/SNOW-4104753`**.
- Do **not** rename `data-lineage/` or `sub_skill: "data-lineage"`.
- User-facing name of the Step 3 / Step 8 row is **Data Lineage**, not "Power BI Lineage Enrichment".
- Dispatch the child whenever Data Lineage is in scope, **even with zero `.pbit` files**. Empty reporting layer → skip extract/enrich, still run the graph CLI.
- Extract+enrich must run **inside** the child **before** `scai assessment data-lineage`. Do not run the graph from the parent in parallel with this sub-agent.
- Parent still gathers Power BI paths in Step 4; the child never asks the user a question.
- Commit prefix: `SNOW-4104753:`.

---

## Why the first screenshot happened

Step 3 lists "Power BI Lineage Enrichment" and never "Data Lineage". The runner only calls `powerbi extract` / `powerbi enrich`. `scai assessment data-lineage` is documented as deferred. Contract tests pin that.

The HTML tab already auto-discovers `artifacts/assessment/data-lineage.json`. This plan makes the sub-skill produce that file.

## Workflow (parent → child)

```
Parent Step 3  →  "8. Data Lineage (optional Power BI reporting layer — asked next)"
Parent Step 4  →  if Data Lineage in scope: "add / add more .pbit?" then stage
Parent Step 5  →  Task: data-lineage-runner (always when in scope)
Child          →  if staged_pbits: extract → author manifest → enrich
               →  scai assessment data-lineage
               →  JSON result (graph path + optional enrichment summary)
Parent Step 7  →  HTML report (--project-dir discovers the JSON)
Parent Step 8  →  row labeled Data Lineage
```

## File map

| File | Responsibility |
|---|---|
| `ai/plugin/skills/migration/assessment/SKILL.md` | Step 3 name, dispatch gate, runner prompt, Step 6/8 contract |
| `ai/plugin/skills/migration/assessment/data-lineage/SKILL.md` | Child: enrich then graph; new completion contract |
| `ai/plugin/skills/migration/assessment/USER_GUIDE.md` | One capability: Data Lineage, reporting layer optional |
| `ai/tests/assessment/data_lineage/test_powerbi_skill_contract.py` | Static guards |

---

### Task 1: Rewrite contract tests to the new workflow (RED)

**Files:**
- Modify: `ai/tests/assessment/data_lineage/test_powerbi_skill_contract.py`

**Interfaces:**
- Consumes: current SKILL.md text (will fail)
- Produces: the names later tasks must write: `USER_FACING_NAME = "Data Lineage"`, graph command in the child, dispatch even with no `.pbit`

- [ ] **Step 1: Change the user-facing name constant and Step 3 assertion**

Replace:

```python
USER_FACING_NAME = "Power BI Lineage Enrichment"
```

with:

```python
USER_FACING_NAME = "Data Lineage"
CANVAS_COMMAND = "scai assessment data-lineage"
```

Update `test_the_scope_list_and_status_row_use_the_explicit_name` so both Step 3 and Step 8 contain `Data Lineage`, and Step 3 does **not** list `Power BI Lineage Enrichment` as its own analysis:

```python
def test_the_scope_list_and_status_row_use_the_explicit_name(parent: str):
    scope = parent[
        index_of(parent, "## Step 3: Confirm Scope") : index_of(
            parent, "## Step 4: Gather Sub-Skill Inputs"
        )
    ]
    status = parent[index_of(parent, "## Step 8: Surface Results") :]

    assert USER_FACING_NAME in scope
    assert "Power BI Lineage Enrichment" not in scope
    assert USER_FACING_NAME in status
```

- [ ] **Step 2: Dispatch even without templates; Power BI is an input, not the gate**

Replace `test_no_staged_template_means_no_dispatch` with:

```python
def test_no_staged_template_still_dispatches_data_lineage(parent: str):
    """The graph reads the CUR. No .pbit only means skip extract/enrich."""
    section = _power_bi_inputs(parent)

    assert says(section, "dispatch `data-lineage`")
    assert says(section, "staged_pbits")
    assert "do **not** dispatch `data-lineage`" not in section


def test_a_step_3_exclusion_of_data_lineage_stops_dispatch(parent: str):
    section = _power_bi_inputs(parent)

    assert says(section, "excluded Data Lineage in Step 3")
    assert says(section, "set `data_lineage.dispatch: false`")
```

Rewrite `test_a_step_3_exclusion_stops_the_dispatch_but_not_the_question` so the question is asked when Data Lineage is in scope (add/add more `.pbit`), and skipped only when Data Lineage itself was excluded:

```python
def test_reporting_layer_question_follows_data_lineage_scope(parent: str):
    section = _power_bi_inputs(parent)

    assert says(section, "when Data Lineage is in scope")
    assert says(section, "add or add more")
    assert says(section, ".pbit")
```

Update `test_every_dispatch_condition_names_the_scope_entry_exactly` to require **Data Lineage** in the dispatch conditions (not Power BI Lineage Enrichment).

Replace banned strings in `test_no_dispatch_condition_still_says_data_lineage` — that test currently forbids "excluded Data Lineage in Step 3", which is now the correct wording. Change it to ban the old sibling name in the scope list only, or delete it and rely on the Step 3 test above.

- [ ] **Step 3: Child must run the graph CLI after enrich**

Replace `test_child_never_tells_the_agent_to_run_the_data_lineage_command` with:

```python
def test_child_runs_extract_enrich_then_the_canvas(child: str):
    text = child
    extract_at = index_of(text, "scai assessment powerbi extract")
    enrich_at = index_of(text, "scai assessment powerbi enrich")
    canvas_at = index_of(text, CANVAS_COMMAND)
    assert extract_at < enrich_at < canvas_at


def test_child_skips_power_bi_when_staged_pbits_empty(child: str):
    assert says(child, "If staged_pbits is empty")
    assert says(child, "do not run extract")
    assert says(child, CANVAS_COMMAND)
```

- [ ] **Step 4: Completion contract points at the graph artifact**

Update `test_child_completion_contract_is_exactly_the_six_keys` (or replace it) so `output_json` is the canvas file:

```python
def test_child_completion_contract_returns_the_graph_artifact(child: str):
    contract = child[index_of(child, "### Completion contract") :][:2500]
    assert says(contract, '"sub_skill": "data-lineage"')
    assert says(contract, "artifacts/assessment/data-lineage.json")
    assert says(contract, '"output_json"')
```

Parent Step 6 checks must follow: `test_step_6_only_demands_an_artifact_from_an_ok_return` should look for `data-lineage.json`, not only `powerbi/enrichment.json`.

- [ ] **Step 5: Runner prompt in the parent includes the graph command**

Add:

```python
def test_the_runner_requires_the_canvas_cli(parent: str):
    prompt = _runner_prompt(parent)
    assert CANVAS_COMMAND in prompt
    assert index_of(prompt, "powerbi enrich") < index_of(prompt, CANVAS_COMMAND)
```

- [ ] **Step 6: Run to confirm RED**

```bash
python3.11 -m pytest ai/tests/assessment/data_lineage/test_powerbi_skill_contract.py \
  -k "scope_list_and_status_row or no_staged_template_still_dispatches or child_runs_extract_enrich or child_completion_contract_returns_the_graph or the_runner_requires_the_canvas" -q
```

Expected: FAIL on missing `Data Lineage` in Step 3, missing canvas in child, parent still saying do not dispatch without `.pbit`.

- [ ] **Step 7: Commit**

```bash
git add ai/tests/assessment/data_lineage/test_powerbi_skill_contract.py
git commit -m "SNOW-4104753: Fail until Data Lineage is a full assessment step"
```

---

### Task 2: Parent skill — list, ask, dispatch like other steps

**Files:**
- Modify: `ai/plugin/skills/migration/assessment/SKILL.md`
- Modify: `ai/plugin/skills/migration/assessment/USER_GUIDE.md`

**Interfaces:**
- Consumes: Task 1 names
- Produces: Step 3 item `Data Lineage`; `data_lineage.dispatch` means "Data Lineage in scope"; `staged_pbits` may be empty

- [ ] **Step 1: Step 3 list**

Replace item 8. Exact fenced list:

```
I will run:
1. Waves (dependency analysis + deployment partitioning)
2. Anti-Patterns  (SQL Server only)
3. Effort Estimates  (SQL Server and Redshift only)
4. Dynamic SQL Patterns
5. Discovery  (SQL Server only — capture files are optional, asked next)
6. ETL/SSIS Assessment  (only if present)
7. Informatica Assessment  (only if present)
8. Data Lineage  (optional reporting layer such as Power BI — asked next)
9. HTML Report

Proceed with all, or pick a subset?
```

- [ ] **Step 2: Step 4 §5.0 — reporting layer as lineage input**

Keep staging mechanics (`stage_powerbi_inputs.py`, `.pbix` unsupported, error table). Change the gate and the question:

- Ask **only when Data Lineage is in scope** (including "proceed with all").
- Copy: already staged → "add more `.pbit`?"; nothing staged → "Do you have a reporting layer (Power BI `.pbit` files or folders) to include, or say no?"
- `data_lineage.dispatch` = Data Lineage was **not** excluded in Step 3 (templates optional).
- `data_lineage.staged_pbits` = whatever was staged (possibly `[]`).
- Delete "do **not** dispatch `data-lineage`" when there are no templates.
- If Data Lineage was excluded: skip the question, `data_lineage.dispatch: false`, synthesize skipped.

- [ ] **Step 3: Runner prompt §6.7**

Dispatch when `data_lineage.dispatch` is true (Data Lineage in scope). Pass `staged_pbits` even if empty. After the existing extract/enrich steps, add:

```
5. If staged_pbits is empty, skip steps 2–4 (extract, inspect, enrich).
6. From <project_dir> run:
     scai assessment data-lineage
   Success writes artifacts/assessment/data-lineage.json.
7. Return JSON: output_json is that graph file. If enrich ran, also set
   manifest and mention enrichment counts in summary. If enrich was skipped,
   manifest is null and summary says the graph was built without a reporting layer.
```

Renumber the existing extract/inspect/enrich bullets as 2–4. Keep catalog-helper matching rules unchanged.

- [ ] **Step 4: Step 6 collect + Step 8 row**

For `data-lineage` `"ok"`, require `artifacts/assessment/data-lineage.json` exists. If `manifest` is non-null, also require `enrichment.json` as today.

Step 8 example row:

```
Data Lineage                     ok      data-lineage.json   (<summary>)
```

Remove "this workflow does not run" / "does not generate the Data Lineage graph" from Step 8.

Routing: one **Data Lineage** entry. Triggers include "data lineage", "power bi", "pbit", "reporting layer". Load `data-lineage/SKILL.md`. State that Power BI extract/enrich is an inner step when `.pbit` were staged.

- [ ] **Step 5: USER_GUIDE.md**

Replace the Power BI-only bullet with:

```
- **Map data lineage** - See sources, pipelines, targets, and reports; include Power BI `.pbit` files if you have a reporting layer
```

- [ ] **Step 6: Run parent-focused tests**

```bash
python3.11 -m pytest ai/tests/assessment/data_lineage/test_powerbi_skill_contract.py \
  -k "parent or scope_list or runner or step_6 or step_8 or reporting_layer" -q
```

Expected: parent tests PASS; child tests still FAIL until Task 3.

- [ ] **Step 7: Commit**

```bash
git add ai/plugin/skills/migration/assessment/SKILL.md \
        ai/plugin/skills/migration/assessment/USER_GUIDE.md
git commit -m "SNOW-4104753: Treat Data Lineage as a first-class assessment step"
```

---

### Task 3: Child skill — Power BI then graph, then result

**Files:**
- Modify: `ai/plugin/skills/migration/assessment/data-lineage/SKILL.md`

**Interfaces:**
- Consumes: context `staged_pbits` (list, may be empty), `project_dir`, `manifest_path`, `catalog_helper_path`
- Produces: `output_json` = canvas JSON; optional `manifest`; `summary` covering both halves

- [ ] **Step 1: Frontmatter and title**

```yaml
name: data-lineage
description: Builds the Data Lineage graph from the Code Unit Registry (`scai assessment data-lineage`). When the parent staged Power BI `.pbit` files, extract and enrich those reports into the registry first so the Reports lane is populated. Use when running the assessment Data Lineage step.
parent_skill: assessment
```

Title the body `# Data Lineage`. Opening paragraph: this is the assessment step that produces the lineage graph. Power BI is an optional reporting-layer input, not the name of the skill.

- [ ] **Step 2: Completion contract**

```json
{
  "sub_skill": "data-lineage",
  "status": "ok",
  "output_json": "<abs path to artifacts/assessment/data-lineage.json>",
  "manifest": "<abs path or null if no Power BI enrich>",
  "summary": "<graph counts; plus Power BI extract/enrich counts when that ran>",
  "error": null
}
```

Keep `skipped` / `error` semantics. Skip the whole skill only when the parent did not dispatch. Missing `.pbit` is not a skip.

- [ ] **Step 3: Ordered steps in the child**

After configure():

1. If `staged_pbits` is non-empty: existing extract → inspect → catalog match → enrich (unchanged rules). If extract is ASM0039 skipped, still run the graph; say so in `summary`.
2. If `staged_pbits` is empty: do not run extract or enrich.
3. Run `scai assessment data-lineage` from `project_dir`.
4. Confirm `artifacts/assessment/data-lineage.json` exists. That path is `output_json`.
5. Return the JSON contract.

Replace "What this skill does not do" that says it does not run the canvas. It **does** run it. It still does not write HTML (parent Step 7) and still does not repoint `.pbit` files.

- [ ] **Step 4: Run the full contract suite**

```bash
python3.11 -m pytest ai/tests/assessment/data_lineage/test_powerbi_skill_contract.py -q
```

Expected: PASS.

Fix any remaining tests that still require `Power BI Lineage Enrichment` as the Step 3 label, `do not dispatch` without templates, or "child never runs data-lineage". Matching/catalog tests should stay green if extract/enrich prose is preserved.

- [ ] **Step 5: Commit**

```bash
git add ai/plugin/skills/migration/assessment/data-lineage/SKILL.md
git commit -m "SNOW-4104753: Fold Power BI enrich and the lineage graph into one sub-skill"
```

---

### Task 4: Golden-project smoke (no skill change unless a path drifted)

- [ ] **Step 1:** From `/Users/aespinoza/Documents/etl/workload4/migration`, run `scai assessment data-lineage` and confirm `artifacts/assessment/data-lineage.json`.
- [ ] **Step 2:** Confirm `generate_multi_report.py` still discovers that path via `--project-dir`.
- [ ] **Step 3:** Manual: an assessment "proceed with all" session must list **Data Lineage**, ask about Power BI add/add more, and after the sub-agent return the graph file exists even if the user said no `.pbit`.

---

## Self-review

1. Spec: first-class Step 3 item; sub-agent; Power BI inside the child; graph CLI after enrich; reporting-layer question on the parent; result JSON. Not in scope: HTML generation inside the child, renaming the directory, C# auto-project in `assessment report`.
2. Parallel fan-out: other sub-skills still run in parallel with Data Lineage. That is correct — only extract/enrich vs graph must be sequential, and both live in this one child.
3. Names: Step 3/8 = `Data Lineage`; inner CLI = `powerbi extract` / `powerbi enrich` then `scai assessment data-lineage`.
