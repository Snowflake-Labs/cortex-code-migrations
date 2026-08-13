# Migrate data (per-object)

Guide for the `migrateData` task — migrate the batch of tables the machine handed you (`where = id IN (...)`). The shared orchestrator + worker are already up (brought up once via `data_infrastructure(mode="up")`; see `../../../data-infrastructure/SKILL.md`). This step is **pure dispatch**, not infrastructure setup.

## 1. Choose the approach (once per batch, if not already set)

If the migration approach hasn't been chosen for this run, call `progress_setup(mode="data_migration")` and answer the prompts (full vs incremental, sync strategy, extraction mechanism, target table type). The choice is persisted as session defaults — skip this if it's already set.

## 2. Generate the workflow

Call `migrate_data(mode="setup", where=<the batch's object filter>)`. It writes a workflow YAML and returns `edit_hints` plus any `partition_key_findings`. Review the file and apply row filters (`whereClauseCriteria`) or a partition column when the hints call for it. Pass `force_regenerate=true` only to discard prior edits and regenerate.

## 3. Dispatch

Call `migrate_data(mode="run", workflow_path=<path from setup>)`. This is **pure dispatch** against the already-running infrastructure — there are no infra flags to pass. If the response is a `remediation` saying infrastructure is not up, call `data_infrastructure(mode="up")` first, then retry.

The response carries a `monitor` block (a `job_id` and a ready-made `watch_command`).

## 4. Track it

Arm the `monitor.watch_command` with the Monitor tool, or call `job_status(job_id)` to read state on demand. `job_status(job_id, details=true)` attaches the error-first report once something needs attention. For the full monitoring / reporting / teardown walkthrough, load `SKILL.md` (Steps 5–7) in this folder.

## When it finishes

Completion stamps the registry field `extensions.dataMigration`, which advances the machine. Present the migration summary (`SKILL.md` Step 6) and offer to tear the shared infrastructure down when the wave is done.
