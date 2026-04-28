<!--
  ROADMAP: Execution plan for {PACKAGE_NAME}

  This is a PLAN — it defines what to do, in what order, with what agents.
  It does NOT contain element bodies, source excerpts, or EWI guide content.
  Agents read those on-demand from their source files.

  Phase types:
  - full-tdd: Test generation + fixing from scratch
  - lightweight: Apply known fix patterns from a prior phase + verify
  - dbt: dbt project test/fix cycle
  - final-validation: Artifact review and sanity check

  Design rationale and justification: write to a separate file if needed for auditing
-->
<!--
  EXECUTION STEPS: Each phase section includes an "Execution Steps" subsection.
  These steps are the literal task descriptions that become cortex tasks at execution time.
  They bake in: agent lifecycle, boundaries, validation criteria, tracking commands.
  Source material: reference/protocols/phase-execution.md (rationale document, not read at runtime).
-->

# Roadmap: {PACKAGE_NAME}

## Package Summary

| Field | Value |
|-------|-------|
| Package | {PACKAGE_NAME} |
| Platform | {PLATFORM_ID} |
| Orchestration file | {ORCH_SQL_PATH} |
| Source definition | {SOURCE_FILE_PATH} |
| Total elements | {TOTAL_ELEMENTS} |
| EWI density | {EWI_PERCENT}% ({EWI_COUNT} of {TOTAL_ELEMENTS}) |
| dbt projects | {DBT_COUNT} |
| Duplicate groups | {DUP_GROUP_COUNT} covering {DUP_ELEMENT_COUNT} elements |

## Phase Overview

<!-- One row per phase. This table is the orchestrator's execution checklist. -->

| Phase | Type | Procedure(s) | Elements | Depends On | Status |
|-------|------|--------------|----------|------------|--------|
<!-- Example rows:
| 1 | full-tdd | proc_onerror_handler | 8 | — | [ ] Planned |
| 2 | lightweight | proc_end_log_onerror_handler | 8 | Phase 1 | [ ] Planned |
| 3 | dbt | project_abs, project_mbs | 2 | Phase 2 | [ ] Planned |
| 4 | final-validation | — | all | Phase 3 | [ ] Planned |
-->

## Duplicate Groups

<!-- Archetype = gets full TDD. Clones = lightweight phases that apply archetype's patterns.
     Group all archetype/clone relationships here for cross-phase reference. -->

| Group | Archetype | Clones | Phase (archetype) | Phase (clones) |
|-------|-----------|--------|-------------------|----------------|

---

## Phase {N}: {PHASE_NAME}

### Metadata

| Field | Value |
|-------|-------|
| Type | {full-tdd / lightweight / dbt / final-validation} |
| Procedure(s) | {procedure_name(s)} |
| Scope | {orchestration / dbt} |
| Depends on | {Phase M / none} |
| Pattern source | {Phase M fix_log (lightweight only) / —} |
| dbt projects | {project_name_1, project_name_2 (dbt phases only)} |
| dbt health | {per-project summary from scan_results: config_valid, ewi_count, ewi_codes, macro_count (dbt phases only)} |

### Completion Criteria

<!-- Orchestrator checks these before marking phase complete -->
- [ ] All elements have terminal status (test-passed, fixed, no-fix-needed, skipped, needs-user, auto-fixed-needs-review, failed)
- [ ] Post-apply tag integrity check passes (for orchestration phases)
- [ ] Learnings merged into artifacts/tracking/fix_log.md
- [ ] session_status.json updated for all elements in this phase
<!-- For dbt phases, add these criteria: -->
- [ ] dbt-test-gen agents produced test artifacts for every project (seeds/, tests/, test_report.md)
- [ ] dbt-fix agents processed every project with failing tests
- [ ] Every dbt node has terminal status (test-passed, fixed, failed, skipped, needs-user)

### Batch Assignments

<!-- One row per element. Batch column groups elements into parallel agent batches.
     Phase cap (see SKILL.md § Phase design principles): pack up to 40-50 small-medium items
     per phase OR up to 20 large items per phase. Do not mix classes in the same phase.
       - Small-medium = dbt project with ≤20 models, OR any orchestration element (atomic)
       - Large = dbt project with >20 models (orchestration elements are never classified large)
     Batch cap: ~10 small-medium items per batch, ~5 large items per batch; max 5 parallel batches.
     Grouped elements (shared tables) stay in same batch.
     NAMING: Batch IDs use B{P}.{M} format (e.g., B1.1, B1.2, B2.1) where P=phase, M=batch number.
     Schemas: ETL_FIX_P{N}_B{M} (schema naming does not use the dot format). -->

| Batch | Schema | Element | Strategy | EWI Codes | Archetype? |
|-------|--------|---------|----------|-----------|------------|
<!-- Example rows:
| B1.1 | ETL_FIX_P1_B1 | SCR Calculate Duration | isolated | SSC-EWI-SSIS0004 | archetype |
| B1.1 | ETL_FIX_P1_B1 | SCR Write Log File | isolated | SSC-EWI-SSIS0004 | clone:G-SCR-DURATION |
| B1.2 | ETL_FIX_P1_B2 | SQL Log Error Message | isolated | SSC-FDM-0007, SSC-EWI-SSIS0046 | — |
-->

### Execution Steps

<!-- TEMPLATE INSTRUCTION (delete after filling):
     Replace all {placeholders} with concrete values. Select ONE phase-type template below, delete the others.
     Step {P}.0 is a gate — the Execution Workflow (SKILL.md § Step 2) creates the cortex task.
     All steps use - [ ] checkboxes. Mark [x] when completed.
     {B} = full batch ID (e.g., B1.1 for Phase 1, Batch 1). Includes phase number. -->

<!-- ═══════════════════════════════════════════════════════════
     TEMPLATE: full-tdd (7 steps: 0-6) — use for phases with type=full-tdd
     ═══════════════════════════════════════════════════════════ -->

- [ ] **Step {P}.0: Initialize Phase Tracking** *(gate — see Execution Workflow § Step 2)*
  Cortex task "Phase {P}: {PHASE_NAME}" must exist before proceeding.
  Steps to register: {P}.1 (Setup), {P}.2 (Test-Gen Wave), {P}.3 (Fix Wave), {P}.4 (Apply-Fixes), {P}.5 (Phase Completion), {P}.6 (Phase Transition).
  If no task exists, the Execution Workflow creates it automatically.

- [ ] **Step {P}.1: Setup**
Run: uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py \
  start-phase {SESSION_JSON} {P}
Create schemas in {DATABASE}: {schema_list}.
Deploy artifacts/phases/phase_{P}/_infrastructure.sql to each schema
(replace {{SCHEMA}} placeholder with actual schema name).

- [ ] **Step {P}.2: Test-Gen Wave**
Resume guard: if baseline_batch_{B}.md already exists for ALL batches
  (from a prior partial run), skip agent spawning and proceed to tracking update below.
Use `team_create` tool: team_name="etl-fix-{package_name}-p{P}".
Spawn agents (MANDATORY — do NOT skip, do NOT do the work yourself):
{for each batch:}
  - {agent_name}: elements {element_list}, schema {schema}
    Instruction: Read {SKILL_DIR}/orchestration-test-gen/SKILL.md
{end for}
Max 5 agents per wave. If more, spawn first 5, wait, then remaining.
Wait for all agents: end your turn and wait for automatic task notifications.
  Each notification confirms one agent completed — process its result immediately.
  NEVER use `bash sleep`, `bash_output`, or `cortex agent output` CLI.
Validate: baseline_batch_{B}.md MUST exist for EVERY batch.
  Re-read session_status.json — confirm all phase elements have status `orch-tested`.
  If missing: respawn as {agent_name}-r1 (max 2 retries).
  After 2 retries: mark remaining elements `failed` reason `context-exhaustion`.
  For partial-completion recovery (agent processed some elements then died):
    see reference/protocols/phase-execution.md § Partial-Artifact Recovery.
Update tracking (SEQUENTIAL — one call per invocation, never batched):
  For each element in baseline summary:
    uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py \
      update {SESSION_JSON} {ELEMENT} --status orch-tested

- [ ] **Step {P}.3: Fix Wave**
Resume guard: if batch_{B}.md already exists for ALL batches
  (from a prior partial run), skip agent spawning and proceed to tracking update below.
Spawn fix agents ONLY for batches where baseline has >=1 failing element:
{for each batch with failures:}
  - {agent_name}: same schema, add baseline_batch_{B}.md path to context
    Instruction: Read {SKILL_DIR}/orchestration-fixer/SKILL.md
{end for}
For batches where ALL elements passed or skipped: do NOT spawn agent.
  Write minimal batch_{B}.md and empty learnings_batch_{B}.md yourself.
Wait for all agents via task notifications. Validate: batch_{B}.md AND learnings_batch_{B}.md MUST exist for every batch.
  Re-read session_status.json — confirm all fixed elements have terminal status.
  Same retry logic as Step {P}.2 (max 2, then mark failed).
  For partial-completion recovery: see reference/protocols/phase-execution.md § Partial-Artifact Recovery.
Update tracking (SEQUENTIAL):
  For each element in task artifacts:
    uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py \
      update {SESSION_JSON} {ELEMENT} --status {status_from_artifact}

- [ ] **Step {P}.4: Apply-Fixes**
Wait until ALL fix agents from Step {P}.3 are complete.
Spawn SINGLE apply-fixes agent:
  - Name: apply-fixes
    Instruction: Read {SKILL_DIR}/reference/agent-prompts/apply-fixes.md
    Context: all batch_{B}.md files from artifacts/phases/phase_{P}/
Wait for completion.
Post-apply validation (orchestrator performs directly, no re-running tests):
  - Count !!!RESOLVE EWI!!! markers in orch SQL (should have decreased)
  - Verify tag integrity: all ---- Start block have matching ---- End block
  - Count all tags before/after — counts must match
If issues found: log warning, continue (TDD already verified fixes).

- [ ] **Step {P}.5: Phase Completion**
Merge learnings: read all learnings_batch_*.md from artifacts/phases/phase_{P}/.
  Append NEW patterns only to artifacts/tracking/fix_log.md (skip duplicates).
  Rebuild the EWI code index at the top of fix_log.md per reference/templates/fix-log-format.md.
Validation gate (MANDATORY — do NOT proceed to complete-phase until this passes):
  uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py \
    validate-phase {SESSION_JSON} {P} --list-test-files
  If validation fails (exit code 1): review failing elements before proceeding.
Run: uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py \
  complete-phase {SESSION_JSON} {P}
Run: uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py \
  update-state {SESSION_JSON} --current-phase {NEXT_P} --phase-status "Phase {P} completed" --next-action "Execute Phase {NEXT_P}"
Checkpoint: cp orchestration SQL + session_status.json to checkpoints/phase_{P}/
Mark Phase {P} as [x] Complete in this ROADMAP.
Shutdown team: use `send_message` with `type: "shutdown_request"` to each agent → wait for `shutdown_response` notifications → use `team_delete` tool.

- [ ] **Step {P}.6: Phase Transition**
Read this ROADMAP's § Phase {NEXT_P} — extract phase name and step count.
Create cortex task for Phase {NEXT_P}:
  `cortex ctx task add "Phase {NEXT_P}: {NEXT_PHASE_NAME}"`
  `cortex ctx task start <task_id>`
  Add one `cortex ctx step add` per ROADMAP step ({NEXT_P}.1 through {NEXT_P}.{LAST}).
Verify: `cortex ctx show tasks` — confirm "Phase {NEXT_P}:" task exists.
Mark Step {NEXT_P}.0 as [x] in ROADMAP.
Mark this step [x] and continue with Step {NEXT_P}.1.

<!-- ═══════════════════════════════════════════════════════════
     TEMPLATE: lightweight (6 steps: 0-5) — use for phases with type=lightweight
     ═══════════════════════════════════════════════════════════ -->

- [ ] **Step {P}.0: Initialize Phase Tracking** *(gate — see Execution Workflow § Step 2)*
  Cortex task "Phase {P}: {PHASE_NAME}" must exist before proceeding.
  Steps to register: {P}.1 (Setup), {P}.2 (Fix Wave), {P}.3 (Apply-Fixes), {P}.4 (Phase Completion), {P}.5 (Phase Transition).
  If no task exists, the Execution Workflow creates it automatically.

- [ ] **Step {P}.1: Setup**
Run: uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py \
  start-phase {SESSION_JSON} {P}
Create schemas in {DATABASE}: {schema_list}.
Deploy artifacts/phases/phase_{P}/_infrastructure.sql to each schema
(replace {{SCHEMA}} placeholder with actual schema name).

- [ ] **Step {P}.2: Fix Wave (Apply Known Patterns)**
Resume guard: if batch_{B}.md already exists for ALL batches
  (from a prior partial run), skip agent spawning and proceed to tracking update below.
Use `team_create` tool: team_name="etl-fix-{package_name}-p{P}".
Spawn fix agents — these apply PROVEN patterns from Phase {SOURCE_PHASE} fix_log:
{for each batch:}
  - {agent_name}: elements {element_list}, schema {schema}
    Instruction: Read {SKILL_DIR}/orchestration-fixer/SKILL.md
    Additional context: pattern_source = Phase {SOURCE_PHASE} fix_log
{end for}
NO test-gen agents — patterns are already proven from the archetype phase.
Wait + validate: batch_{B}.md AND learnings_batch_{B}.md for every batch.
  Retry logic: max 2 retries per batch, then mark failed.
  For partial-completion recovery: see reference/protocols/phase-execution.md § Partial-Artifact Recovery.
Update tracking (SEQUENTIAL):
  For each element in task artifacts:
    uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py \
      update {SESSION_JSON} {ELEMENT} --status {status_from_artifact}

- [ ] **Step {P}.3: Apply-Fixes**
Wait until ALL fix agents from Step {P}.2 are complete.
Spawn SINGLE apply-fixes agent:
  - Name: apply-fixes
    Instruction: Read {SKILL_DIR}/reference/agent-prompts/apply-fixes.md
    Context: all batch_{B}.md files from artifacts/phases/phase_{P}/
Wait for completion.
Post-apply validation (orchestrator performs directly, no re-running tests):
  - Count !!!RESOLVE EWI!!! markers in orch SQL (should have decreased)
  - Verify tag integrity: all ---- Start block have matching ---- End block
  - Count all tags before/after — counts must match
If issues found: log warning, continue (TDD already verified fixes).

- [ ] **Step {P}.4: Phase Completion**
Merge learnings: read all learnings_batch_*.md from artifacts/phases/phase_{P}/.
  Append NEW patterns only to artifacts/tracking/fix_log.md (skip duplicates).
  Rebuild the EWI code index at the top of fix_log.md per reference/templates/fix-log-format.md.
Validation gate (MANDATORY — do NOT proceed to complete-phase until this passes):
  uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py \
    validate-phase {SESSION_JSON} {P} --list-test-files
  If validation fails (exit code 1): review failing elements before proceeding.
Run: uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py \
  complete-phase {SESSION_JSON} {P}
Run: uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py \
  update-state {SESSION_JSON} --current-phase {NEXT_P} --phase-status "Phase {P} completed" --next-action "Execute Phase {NEXT_P}"
Checkpoint: cp orchestration SQL + session_status.json to checkpoints/phase_{P}/
Mark Phase {P} as [x] Complete in this ROADMAP.
Shutdown team: use `send_message` with `type: "shutdown_request"` to each agent → wait for `shutdown_response` notifications → use `team_delete` tool.

- [ ] **Step {P}.5: Phase Transition**
Read this ROADMAP's § Phase {NEXT_P} — extract phase name and step count.
Create cortex task for Phase {NEXT_P}:
  `cortex ctx task add "Phase {NEXT_P}: {NEXT_PHASE_NAME}"`
  `cortex ctx task start <task_id>`
  Add one `cortex ctx step add` per ROADMAP step ({NEXT_P}.1 through {NEXT_P}.{LAST}).
Verify: `cortex ctx show tasks` — confirm "Phase {NEXT_P}:" task exists.
Mark Step {NEXT_P}.0 as [x] in ROADMAP.
Mark this step [x] and continue with Step {NEXT_P}.1.

<!-- ═══════════════════════════════════════════════════════════
     TEMPLATE: dbt (6 steps: 0-5) — use for phases with type=dbt
     ═══════════════════════════════════════════════════════════ -->

- [ ] **Step {P}.0: Initialize Phase Tracking** *(gate — see Execution Workflow § Step 2)*
  Cortex task "Phase {P}: {PHASE_NAME}" must exist before proceeding.
  Steps to register: {P}.1 (Setup), {P}.2 (dbt-Test-Gen Wave), {P}.3 (dbt-Fix Wave), {P}.4 (Phase Completion), {P}.5 (Phase Transition).
  If no task exists, the Execution Workflow creates it automatically.

- [ ] **Step {P}.1: Setup**
Run: uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py \
  start-phase {SESSION_JSON} {P}
Use `team_create` tool: team_name="etl-fix-{package_name}-p{P}".
Register dbt nodes (SEQUENTIAL — one call per project):
{for each dbt_project:}
  uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py \
    init-dbt {SESSION_JSON} {PROJECT_NAME} {DBT_PROJECT_PATH}
{end for}

- [ ] **Step {P}.2: dbt-Test-Gen Wave**
Resume guard: if test_report.md already exists for ALL projects
  (from a prior partial run), skip agent spawning and proceed to tracking update below.
Spawn dbt-test-gen agents (MANDATORY — UNCONDITIONAL — do NOT skip):
{for each dbt_project:}
  - dbt-test-gen-{project_name}:
    Instruction: Read {SKILL_DIR}/dbt-test-gen/SKILL.md
    Context: project_path={DBT_PROJECT_PATH}, database={DATABASE},
      target_schema={SCHEMA}, source_file={SOURCE_FILE}, ROADMAP_path, SESSION_JSON
{end for}
Spawn even if: placeholder config, broken macros, missing sources, heavy EWI.
Test generation IS the assessment — agent documents blockers in test_report.md.
Early exit WITHOUT test artifacts is a protocol violation.
Do NOT do this work yourself. Do NOT edit dbt files directly.
Wait for all agents: end your turn and wait for automatic task notifications.
  NEVER use `bash sleep`, `bash_output`, or `cortex agent output` CLI.
Validate for EACH project — ALL must exist:
  - .migrate-etl-package/tests/dbt/{PROJECT}/seeds/ — at least 1 .csv
  - .migrate-etl-package/tests/dbt/{PROJECT}/tests/ — at least 1 .sql
  - .migrate-etl-package/tests/dbt/{PROJECT}/test_report.md
If ANY missing: respawn (max 2 retries), then mark nodes `failed` reason `test-gen-exhaustion`.
  For partial-completion recovery: see reference/protocols/phase-execution.md § Partial-Artifact Recovery.
Update tracking (SEQUENTIAL):
  uv run ... track_status.py update-dbt {SESSION_JSON} {PROJECT} --status dbt-tested
  uv run ... track_status.py update-dbt-node {SESSION_JSON} {PROJECT} {NODE} --status {result}

- [ ] **Step {P}.3: dbt-Fix Wave**
Resume guard: if dbt_learnings_{project}.md already exists for ALL projects
  (from a prior partial run), skip agent spawning and proceed to tracking update below.
Spawn fix agents for projects with: failing tests, compilation errors, or bootstrap blockers.
{for each project_needing_fix:}
  - dbt-fixer-{project_name}:
    Instruction: Read {SKILL_DIR}/dbt-fixer/SKILL.md
    Context: same as test-gen + baseline test results path
{end for}
Projects where ALL nodes passed and no compilation errors: no agent needed.
  Write minimal dbt_learnings_{project}.md with no-fix-needed.
Wait + validate: dbt_learnings_{project}.md MUST exist for every project.
Update tracking (SEQUENTIAL):
  uv run ... track_status.py update-dbt-node per node
  uv run ... track_status.py update-dbt per project

- [ ] **Step {P}.4: Phase Completion**
Merge learnings: read dbt_learnings_*.md, append to fix_log.md.
  Rebuild the EWI code index at the top of fix_log.md per reference/templates/fix-log-format.md.
Validation gate (MANDATORY — do NOT proceed to complete-phase until this passes):
  uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py \
    validate-phase {SESSION_JSON} {P} --list-test-files
  If validation fails (exit code 1): review failing elements before proceeding.
Run: uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py \
  complete-phase {SESSION_JSON} {P}
Run: uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py \
  update-state {SESSION_JSON} --current-phase {NEXT_P} --phase-status "Phase {P} completed" --next-action "Execute Phase {NEXT_P}"
Mark Phase {P} as [x] Complete in this ROADMAP.
Shutdown team: use `send_message` with `type: "shutdown_request"` to each agent → wait for `shutdown_response` notifications → use `team_delete` tool.

- [ ] **Step {P}.5: Phase Transition**
Read this ROADMAP's § Phase {NEXT_P} — extract phase name and step count.
Create cortex task for Phase {NEXT_P}:
  `cortex ctx task add "Phase {NEXT_P}: {NEXT_PHASE_NAME}"`
  `cortex ctx task start <task_id>`
  Add one `cortex ctx step add` per ROADMAP step ({NEXT_P}.1 through {NEXT_P}.{LAST}).
Verify: `cortex ctx show tasks` — confirm "Phase {NEXT_P}:" task exists.
Mark Step {NEXT_P}.0 as [x] in ROADMAP.
Mark this step [x] and continue with Step {NEXT_P}.1.

---

<!-- Repeat Phase section for each phase -->

<!-- FINAL PHASE: Final Validation -->

## Phase {LAST}: Final Validation

### Metadata

| Field | Value |
|-------|-------|
| Type | final-validation |
| Depends on | Phase {LAST-1} |

### Completion Criteria

- [ ] All elements across all phases have terminal status
- [ ] No remaining `!!!RESOLVE EWI!!!` markers (except expected skip/needs-user elements)
- [ ] fix_log.md consistent across phases
- [ ] session_status.json matches artifact state
- [ ] Summary report generated

### Execution Steps

<!-- TEMPLATE INSTRUCTION (delete after filling):
     Replace all {placeholders} with concrete values.
     Step {P}.0 is a gate — the Execution Workflow (SKILL.md § Step 2) creates the cortex task.
     All steps use - [ ] checkboxes. Mark [x] when completed. -->

- [ ] **Step {P}.0: Initialize Phase Tracking** *(gate — see Execution Workflow § Step 2)*
  Cortex task "Phase {P}: Final Validation" must exist before proceeding.
  Steps to register: {P}.1 (Validation Checks), {P}.2 (Generate Report), {P}.3 (Migration Complete).
  If no task exists, the Execution Workflow creates it automatically.

- [ ] **Step {P}.1: Validation Checks**
Run: uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py \
  start-phase {SESSION_JSON} {P}
Read session_status.json — verify ALL elements across ALL phases have terminal status.
  Terminal statuses: test-passed, fixed, no-fix-needed, skipped,
    needs-user, auto-fixed-needs-review, failed.
  ZERO elements may have status pending or orch-tested.
Count remaining !!!RESOLVE EWI!!! markers in orchestration SQL.
Read fix_log.md — verify no contradicting patterns across phases.
Verify each phase directory has: baseline + batch + learnings artifacts for all batches.

- [ ] **Step {P}.2: Generate Report**
Run: uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/generate_report.py {PACKAGE_FOLDER}
Output: artifacts/report.html
This step is MANDATORY — every migration must produce an HTML report.

- [ ] **Step {P}.3: Migration Complete**
Run: uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py \
  complete-phase {SESSION_JSON} {P}
Run: uv run --project {SKILL_DIR} python {SKILL_DIR}/scripts/track_status.py \
  update-state {SESSION_JSON} --current-phase {P} --phase-status complete --next-action "Migration complete — review report"
Mark Phase {P} as [x] Complete in this ROADMAP.
Present final summary to user: element counts by status, phases completed, report path.
