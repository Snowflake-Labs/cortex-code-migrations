---
name: migrate-etl-package
parent_skill: migrate-objects
description: >
  Phase-based orchestrator for fixing SnowConvert ETL conversion gaps in
  ETL-to-Snowflake migrations (SSIS, Informatica, and other platforms).
  Analyzes packages holistically, creates a ROADMAP with test strategies,
  and executes fixes through phased TDD with cross-phase learning.
  Use when user says "fix ETL
  package", "fix SSIS conversion", "fix Informatica conversion", "resume ETL
  fixing", "run next phase", or when processing a converted ETL package folder
  containing orchestration SQL, optional dbt sub-projects, and the original
  source definition file (e.g., DTSX for SSIS, XML for Informatica). Do NOT
  use for non-ETL migrations or greenfield dbt projects.
license: Proprietary. See License-Skills for complete terms
---

# ETL Orchestrator

Fix SnowConvert ETL conversion gaps through phased execution with upfront package analysis, agent-determined test strategies, and cross-phase learning.

## Prerequisites

- Converted ETL package folder (orchestration `.sql` + optional dbt subfolders)
- Original source definition file (e.g., `.dtsx` for SSIS, `.xml` for Informatica)
- Active Snowflake connection with a warehouse
- DATABASE + SCHEMA with write privileges (`CREATE TABLE`, `CREATE FUNCTION`, `CREATE PROCEDURE`)

## Persistent Files

All files stored in `{PACKAGE}/.migrate-etl-package/`:

| File | Purpose |
|------|---------|
| `artifacts/planning/scan_results.json` | Package scan output (elements, EWIs, dbt projects) |
| `artifacts/planning/PACKAGE_ORCH_CONTEXT.md` | Orchestration structural understanding (statements, element relationships, containers) |
| `artifacts/planning/PACKAGE_DBT_CONTEXT.md` | dbt project analysis (model inventory, health, source mapping, bootstrap blockers). Only present when package has dbt projects. |
| `artifacts/planning/SOURCE_EXCERPTS.md` | Source-definition excerpts for traceability (conditional — only if source file is large) |
| `artifacts/planning/ROADMAP.md` | Phase plan (agent-authored from template; updated in-place during execution). Never delete content. |
| `artifacts/tracking/STATE.md` | Resumption bookmark (GENERATED — use `track_status.py` commands, do not edit directly) |
| `artifacts/tracking/session_status.json` | Element-level tracking (machine-readable) |
| `artifacts/tracking/fix_log.md` | Append-only record of every fix applied. Absent until Phase 1 completes. |
| `artifacts/phases/phase_{N}/` | Per-phase artifacts: baselines, batch reports, learnings, infrastructure SQL |
| `artifacts/report.html` | Self-contained HTML report aggregating all artifacts. Generated during Final Validation by `generate_report.py`. |
> **Progressive disclosure:** Reference files are loaded on-demand — only read a reference file when its content is needed for the current step.

## Agent Wait Protocol

**NEVER use `bash sleep`, `bash_output`, or `cortex agent output` to wait for agents.**

Background agents deliver results via **automatic task notifications** — a new conversation turn arrives when each agent finishes. The correct flow:

1. Spawn all background agents in a **single message** (parallel tool calls)
2. **End your turn** — do not issue further tool calls or narrate while waiting
3. When a notification arrives, process that agent's result
4. When all notifications have arrived, verify output files exist and continue

Do not attempt to call `agent_output` — it may not be available and failed attempts waste a turn. Automatic task notifications are the only reliable mechanism.

## Entry Point

On every invocation:

1. Check if `{PACKAGE}/.migrate-etl-package/artifacts/tracking/STATE.md` exists
2. **If no STATE.md** → new package → run **Planning Workflow**
3. **If STATE.md exists** → read it → run **Execution Workflow** for next pending phase

---

## Planning Workflow

### Step 0: Create Progress Task

```bash
cortex ctx task add "Planning: {package_name}"
cortex ctx task start <task_id>
cortex ctx step add "Step 1: Gather inputs" -t <task_id>
cortex ctx step add "Step 2: Scan package" -t <task_id>
cortex ctx step add "Step 3: Initialize tracking" -t <task_id>
cortex ctx step add "Step 4: Configure test environment" -t <task_id>
cortex ctx step add "Step 5: Backup and strip dead code" -t <task_id>
cortex ctx step add "Step 6: Context mapping — spawn parallel agents, wait for notifications" -t <task_id>
cortex ctx step add "Step 6b: Classify dbt project readiness" -t <task_id>
cortex ctx step add "Step 7: Create ROADMAP (7a-7c)" -t <task_id>
cortex ctx step add "Step 8: Create STATE.md" -t <task_id>
cortex ctx step add "Step 9: Present ROADMAP for approval" -t <task_id>
```

Mark each step done via `cortex ctx step done <id>` **immediately** upon completion — do not batch. Mark the task done after Step 9 approval.

### Step 1: Gather Inputs

Ask the user for:
- Package folder path (containing orchestration `.sql` and optional dbt subfolders)
- Original source definition file path (e.g., `.dtsx` for SSIS, `.xml` for Informatica)
- Source platform (if not obvious from file extension)

**STOPPING POINT**: Use `ask_user_question` to get the user's answer before proceeding.

### Step 1b: Detect Platform

1. **Auto-detect from file extension**: `.dtsx` → `ssis`, `.xml` → ask user to confirm platform
2. **If ambiguous**, ask the user which platform via `ask_user_question`
3. **Read the platform profile** from `{SKILL_DIR}/platforms/{PLATFORM_ID}/platform-profile.md`
4. **Store the platform** in session — subsequent steps use `{PLATFORM_ID}`, `{PLATFORM_DIR}` (`{SKILL_DIR}/platforms/{PLATFORM_ID}`), and `{SOURCE_FILE_PATH}`

The platform profile defines: source file label, traceability comment format, guide file paths, dead code stripping script, element classification rules, and platform-specific vocabulary.

### Step 2: Scan Package

```bash
uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/scan_package.py {PACKAGE_FOLDER} {SOURCE_FILE} --platform {PLATFORM_ID}
```

Output: `{PACKAGE}/.migrate-etl-package/artifacts/planning/scan_results.json`

If scan_package.py fails, check: (1) package folder contains a `.sql` orchestration file, (2) source file path is correct, (3) `uv` is installed. See Troubleshooting below.

### Step 3: Initialize Tracking

```bash
uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py init {SCAN_RESULTS_JSON}
```

Output: `{PACKAGE}/.migrate-etl-package/artifacts/tracking/session_status.json` — all elements start `pending`.

### Step 4: Configure Test Environment

Check `session_status.json` for existing `test_environment`. If not found, ask the user via `ask_user_question` with two options:
1. **"Use current connection's database"** — run `SELECT CURRENT_DATABASE()` to get it
2. The user can type a different database name via "Something else"

The question text:
```
Which database should be used for test schemas? You need CREATE SCHEMA, CREATE TABLE, CREATE FUNCTION, and CREATE PROCEDURE privileges. Each phase creates per-batch schemas automatically and drops them when done.
```

After getting the database name:
```bash
uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py set-test-env {SESSION_JSON} {DATABASE} PUBLIC
```

### Step 5: Backup and Strip Dead Code

Snapshot the package directory before stripping:

```bash
uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/backup_package.py {PACKAGE}
```

This creates `{PACKAGE}/.migrate-etl-package/original/` with a copy of the package excluding the `.migrate-etl-package/` sub-tree.

If the platform profile defines a `strip_script` (not null), run dead code stripping:
```bash
uv run --project {SKILL_DIR} python {PLATFORM_DIR}/{STRIP_SCRIPT} {ORCHESTRATION_SQL_FILE}
```

### Step 6: Context Mapping (parallel agents)

Use `team_create` tool: team_name="etl-plan-{package_name}".

**Orchestration context mapper** (always):
Spawn a teammate with `name="context-mapper"`, `run_in_background=false`, and the prompt template at `{SKILL_DIR}/reference/agent-prompts/context-mapper.md` (substitute `{ORCH_SQL_PATH}`, `{SOURCE_FILE_PATH}`, `{PACKAGE}`, `{SKILL_DIR}`, `{PLATFORM_DIR}` placeholders).

Output: `PACKAGE_ORCH_CONTEXT.md` — element inventory, duplicate groups, behavioral patterns, container hierarchy.

**dbt context mapper** (conditional — only if dbt_projects exist):
Spawn a teammate with `name="dbt-context-mapper"`, `run_in_background=false`, and the prompt template at `{SKILL_DIR}/reference/agent-prompts/dbt-context-mapper.md` (substitute `{PACKAGE}`, `{SOURCE_FILE_PATH}`, `{TRANSFORMATION_GUIDE}` placeholders).

Output: `PACKAGE_DBT_CONTEXT.md` — project health, model inventory, macro inventory, source mapping, bootstrap blockers.

**Spawn both agents in a single message** (parallel tool calls), then follow the **Agent Wait Protocol**: end your turn and wait for task notifications. When both notifications arrive, verify both output files exist and are non-empty before continuing.

Use `team_delete` tool after verifying outputs.

### Step 6b: Classify dbt Project Readiness (if dbt projects exist)

If `scan_results.json` contains dbt_projects:

1. **Read the health signals** from `scan_results.json` — for each dbt project, check `has_valid_config`, `has_placeholder_config`, `ewi_count`, `ewi_codes`, `health_issues`
2. **Read PACKAGE_DBT_CONTEXT.md** — the dbt-context-mapper has analyzed model structure, macros, source definitions, and bootstrap blockers
3. **Classify each project's readiness:**
   - **Ready**: `has_valid_config=true`, zero or low EWI count → standard dbt phase
   - **Needs bootstrap**: `has_valid_config=false` or `has_placeholder_config=true` → dbt phase with bootstrap sub-phase (config + macro fixes before model testing)
   - **Heavy EWI**: high EWI count relative to model count → dbt phase with expected baseline failures, longer fix cycle

These classifications inform the ROADMAP phase design in Step 7. Do NOT mark projects as `needs-user` at planning time — that decision is made by the dbt-test-gen agent after attempting test generation.

### Step 7: Create ROADMAP

Using PACKAGE_ORCH_CONTEXT.md, PACKAGE_DBT_CONTEXT.md (if dbt projects exist), and scan_results.json, design the phase plan. The ROADMAP is **agent-authored** — write it directly using the Write tool from the template at `{SKILL_DIR}/reference/templates/ROADMAP_TEMPLATE.md`.

**PACKAGE_ORCH_CONTEXT.md is CRUCIAL** for orchestration phases — it contains structural understanding (statement inventory, container hierarchy, element relationships, shared variables, event handler patterns). **PACKAGE_DBT_CONTEXT.md is CRUCIAL** for dbt phases — it contains model inventory, health signals, source mapping, and bootstrap blocker analysis. Use both as primary inputs.

**Phase design principles:**
- Phases align with CREATE TASK/PROCEDURE boundaries
- Phase types: `full-tdd`, `lightweight`, `dbt`, `final-validation`
- **Item sizing caps** (an "item" is one orchestration element or one dbt project — caps apply to both):
  - **Small-medium item**: a dbt project with ≤20 models (from `scan_results.json` `health.model_count`); OR any orchestration element (elements are atomic — 1 element = 1 item against the phase cap, regardless of internal complexity)
  - **Large item**: a dbt project with >20 models. **Only dbt projects can be classified as large** — orchestration elements are always small-medium
  - **Phase cap**: pack up to **40-50 small-medium items per phase** OR up to **20 large items per phase**
  - **Do NOT mix classes in the same phase** — route small-medium and large items into separate phases so sizing stays predictable
  - **Batch cap**: ~10 small-medium items per batch, ~5 large items per batch
  - **Concurrency cap**: max 5 parallel batches per phase regardless of item size
- Push each phase toward its cap rather than creating many small phases — a 48-project small-medium phase is preferable to two 24-project phases when the items share patterns
- Never split `grouped:{name}` element sets across batches
- Archetype elements get `full-tdd`; clones get `lightweight` phases applying the archetype's patterns
- Orchestration phases are sequential (edit the same SQL file); batches within a phase are parallel
- dbt phases on different projects may run in parallel
- dbt phases receive the SAME rigor as orchestration phases: health assessment, explicit batch assignments, completion criteria
- dbt projects with `has_placeholder_config=true` or `has_valid_config=false` need a bootstrap sub-step (the dbt-test-gen agent handles this internally — document the blocker in the ROADMAP phase metadata)
- Every dbt project MUST be assigned to a dbt phase — no project may be omitted or deferred to "manual" resolution
- The ROADMAP must include dbt project health summaries in the phase metadata (from scan_results.json health fields and PACKAGE_DBT_CONTEXT.md)

**Phase sizing factors** (refine assignment within the caps above — not a substitute for the caps):
1. Post-strip orchestration file size
2. EWI density and type complexity per statement
3. Statement topology (don't break loops, containers, event handler groups)
4. Element count per statement
5. dbt project boundaries
6. Cross-element dependencies (shared variables, shared tables)

**Always include a Final Validation phase** as the last phase.

**Step 7a: Write ROADMAP.md** — Read template at `{SKILL_DIR}/reference/templates/ROADMAP_TEMPLATE.md`, fill all sections, write to `{PACKAGE}/.migrate-etl-package/artifacts/planning/ROADMAP.md`.

**Step 7b: Register phases in session_status.json:**
```bash
uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py init-roadmap {SESSION_JSON} --phases-json '[{"phase":1,"name":"...","goal":"...","scope":"orchestration","parallel_safe":false,"depends_on":[]}, ...]'
```

**Step 7c: Assign elements to phases (single batch call):**

Write a JSON file with all phase→element→strategy mappings, then call `batch-assign-phases` once:
```bash
# Write assignments to a temp file, then:
uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py batch-assign-phases {SESSION_JSON} --assignments-file {ASSIGNMENTS_FILE}
```

The JSON file format:
```json
[
  {"phase": 1, "elements": ["Package\\El_A", "Package\\El_B"], "strategy": "isolated"},
  {"phase": 2, "elements": ["Package\\El_C"], "strategy": "grouped:core"}
]
```

> **Do NOT call `assign-phases` multiple times in parallel.** Use `batch-assign-phases` to assign all phases atomically in one invocation.

**Step 7d: Generate _infrastructure.sql per phase** — For each phase:
1. Determine the superset of infrastructure tags needed across all batches
2. Write `{PACKAGE}/.migrate-etl-package/artifacts/phases/phase_{N}/_infrastructure.sql`
   - Core: control_variables table, GetControlVariableUDF, UpdateControlVariable
   - Tagged conditionals: CLEAR_VARIABLES, INIT_FROM_CONFIG, BUILD_DBT_VARS (only if phase needs them)
   - Use `{SCHEMA}` placeholder (orchestrator does string replacement at execution time)
   - See `orchestration-test-gen/infrastructure-dedup.md` for full DDL

### Step 8: Create STATE.md

```bash
uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py update-state {SESSION_JSON} --current-phase 1 --phase-status "Ready to execute" --next-action "Execute Phase 1 ({phase_name})"
```

### Step 9: Present ROADMAP for Approval

Display the ROADMAP to the user. Highlight:
- Number of phases and batches per phase
- Phase types and procedure alignment
- Test strategies (grouped vs isolated, and why)

**STOPPING POINT**: Use `ask_user_question` to get the user's approval or revision requests.

### Step 10: Begin Execution

After user approval, proceed to execute Phase 1 using the Execution Workflow below.

---

## Cortex Task Invariant

A cortex task MUST exist for the current phase at all times during execution.
This is the auto-compact resilience mechanism — cortex ctx data is persisted
externally and re-injected via system-reminders every turn.

- **Created by:** Execution Workflow Step 2 (for the first phase or after restart)
  or the previous phase's Phase Transition step (for subsequent phases)
- **Verified by:** `cortex ctx show tasks` — must show a task matching "Phase {P}:"
- **Never skip:** If no task exists, create it before any phase work begins

---

## Execution Workflow

Phase execution is continuous and autonomous. Do NOT stop between phases
to ask the user. The only approved stopping points are in the Planning
Workflow (Steps 1, 4, 9) and when an error requires user input.

### Step 1: Read State
Read `{PACKAGE}/.migrate-etl-package/artifacts/tracking/STATE.md`
→ identify current phase number and status.

### Step 2: Ensure Cortex Task Exists (MANDATORY GATE)

Run `cortex ctx show tasks` via bash.

**Branch A — Task already exists:** A task matching "Phase {P}:" is found
with unchecked steps. Continue from its first unchecked step at Step 3.
Each step description says "(see ROADMAP.md § Phase {P})" — read those
instructions from disk before executing.

**Branch B — No task exists (MANDATORY creation before ANY phase work):**

1. Read `ROADMAP.md` § Phase {P} → extract phase name, type, and step list
2. Create the cortex task and steps — execute these bash commands directly
   (substitute actual values for all placeholders):
   ```bash
   cortex ctx task add "Phase {P}: {PHASE_NAME}"
   cortex ctx task start <task_id>
   # Add one cortex step per ROADMAP execution step (Steps {P}.1 through {P}.{LAST}):
   cortex ctx step add "Step {P}.1: {step_description} (see ROADMAP.md § Phase {P})" -t <task_id>
   cortex ctx step add "Step {P}.2: {step_description} (see ROADMAP.md § Phase {P})" -t <task_id>
   # ... continue for every remaining ROADMAP step
   ```
3. **Verify creation:** Run `cortex ctx show tasks` again — confirm a task
   matching "Phase {P}:" exists. If not, STOP and repeat this step.
4. Mark Step {P}.0 as `[x]` in the ROADMAP
5. If some later steps are already `[x]` in the ROADMAP (session restart),
   mark those cortex steps done immediately. Also check disk artifacts for
   the current phase: if step outputs exist (e.g., `baseline_batch_*.md`
   for test-gen, `batch_*.md` for fix wave) but the ROADMAP checkbox was
   not marked, mark those cortex steps done too.

**GATE CHECK:** Do NOT proceed to Step 3 until `cortex ctx show tasks`
confirms a task for "Phase {P}:" exists with at least one unchecked step.

### Step 3: Execute Steps
For each pending cortex step:
1. Read the step's instructions from ROADMAP.md
2. Execute them
3. Mark `[x]` next to the step in the ROADMAP
4. Mark the cortex step done

The last step of each phase (except Final Validation) is a **Phase Transition**
that creates the next phase's cortex task inline (see ROADMAP step instructions)
and continues execution. This creates a continuous chain — cortex tasks for
Phase {NEXT_P} are created before Phase {P}'s task completes, so the agent
always has a pending task.

### Error Recovery
- **Catastrophic file corruption**: Restore from `checkpoints/phase_{N}/` or `original/`.
- **Snowflake connection failure**: Verify connection. Re-run `track_status.py set-test-env` if credentials changed.
- **ROADMAP amendment needed**: Log via `track_status.py add-decision`, amend future phases only, document reasoning.

---

## Batch Output Format

See [reference/templates/batch-artifacts.md](reference/templates/batch-artifacts.md).

## Sub-Skills

- **[orchestration-test-gen](orchestration-test-gen/SKILL.md)** — Generate AAA tests for orchestration elements (isolated or grouped per ROADMAP)
- **[orchestration-fixer](orchestration-fixer/SKILL.md)** — Fix orchestration elements using test-file workbench
- **[dbt-test-gen](dbt-test-gen/SKILL.md)** — Generate dbt tests (seeds, schema tests, singular assertions)
- **[dbt-fixer](dbt-fixer/SKILL.md)** — Fix dbt models via iterative compile-fix loop

## Reference Files

See [reference/index.md](reference/index.md) for the full index of all reference files.

Sub-skill guides:
- **[orchestration-test-gen/assertion-patterns.md](orchestration-test-gen/assertion-patterns.md)** — SQL assertion templates
- **[orchestration-test-gen/stored-procedure-wrapping.md](orchestration-test-gen/stored-procedure-wrapping.md)** — SP template and Snowflake quirks
- **[orchestration-test-gen/test-categorization.md](orchestration-test-gen/test-categorization.md)** — Isolated vs grouped test strategy

Platform-specific guides (loaded from `{PLATFORM_DIR}/`, filenames defined in the platform profile):
- **`{PLATFORM_DIR}/{orchestration_guide}`** — Source file navigation for orchestration structure
- **`{PLATFORM_DIR}/{transformation_guide}`** — Source file navigation for transformation logic
- **`{PLATFORM_DIR}/element-types.md`** — Element type to Snowflake mapping
- **`{PLATFORM_DIR}/ewi/`** — Platform-specific EWI/FDM fix guides

## Examples

See [reference/examples.md](reference/examples.md).

## Troubleshooting

See [reference/troubleshooting.md](reference/troubleshooting.md).

## Output

- Fixed orchestration `.sql` file with EWI gaps resolved
- Fixed dbt model files (per sub-project)
- Test artifacts in `{PACKAGE}/.migrate-etl-package/tests/`
- `{PACKAGE}/.migrate-etl-package/artifacts/report.html` — self-contained HTML report aggregating all artifacts (generated during Final Validation)
- `artifacts/tracking/fix_log.md` — append-only record of every fix applied
- `artifacts/phases/phase_{N}/` — per-phase baselines, batch reports, learnings
