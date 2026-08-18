# Validate data (per-object)

Guide for the `validateData` task — validate the batch of tables the machine handed you (`where = id IN (...)`). The shared orchestrator + worker are already up (brought up once via `data_infrastructure(mode="up")`). This step is **pure dispatch**, not infrastructure setup.

## 1. Choose validation scope (once per batch, if not already set)

If validation type / sync strategy haven't been chosen for this run, call `progress_setup(mode="data_validation")` (full vs incremental, sync strategy). The choice is persisted as session defaults — skip if already set.

## 2. Generate the workflow

Call `validate_data(mode="setup", where=<the batch's object filter>)`. It writes a validation workflow YAML and returns `edit_hints`. Review and edit the toggles (schema / metrics / row validation, continue-on-failure) if needed before running.

## 3. Dispatch

Call `validate_data(mode="run", workflow_path=<path from setup>)` — **pure dispatch** against the already-running infrastructure. If the response is a `remediation` saying infrastructure is not up, **stop here — dispatch does not bring infrastructure up.** Hand back to [`../../data-infrastructure/SKILL.md`](../../data-infrastructure/SKILL.md): it is the single place the shared orchestrator + worker come up, and the only place the **local vs SPCS** placement is confirmed. Once it reports ready, retry this dispatch. Use `validate_data(mode="revalidate", workflow_name=<finished parent>)` to retry only the failed partitions of a finished run.

The response carries a `monitor` block (a `job_id` and a ready-made `watch_command`).

## 4. Track it

Arm the `monitor.watch_command` with the Monitor tool, or call `job_status(job_id)` on demand. `job_status(job_id, details=true)` attaches the error-first validation report. For the full monitoring / reporting / teardown walkthrough, load `validate_tables.md` (Steps 4–6) in this folder.

## When it finishes

Completion stamps the registry field `extensions.dataValidation`, which advances the machine. Present the error-first validation report (`validate_tables.md` Step 5) and offer re-validation when eligible.
