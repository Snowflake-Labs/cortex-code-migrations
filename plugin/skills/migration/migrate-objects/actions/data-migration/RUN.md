# Migrate data (per-object)

Guide for the `migrateData` task — migrate the batch of tables the machine handed you (`where = id IN (...)`). The shared orchestrator + worker are already up (brought up once via `data_infrastructure(mode="up")`; see `../../../data-infrastructure/SKILL.md`). This step is **pure dispatch**, not infrastructure setup.

## 1. Choose the approach (once per batch, if not already set)

If the migration approach hasn't been chosen for this run, call `progress_setup(mode="data_migration")` and answer the prompts (full vs incremental, sync strategy, extraction mechanism, target table type). The choice is persisted as session defaults — skip this if it's already set.

## 2. Generate the workflow

Call `migrate_data(mode="setup", where=<the batch's object filter>)`. It writes a workflow YAML and returns `edit_hints` plus any `partition_key_findings`. Review the file and apply row filters (`whereClauseCriteria`) or a partition column when the hints call for it. Pass `force_regenerate=true` only to discard prior edits and regenerate.

## 3. Dispatch

Call `migrate_data(mode="run", workflow_path=<path from setup>)`. This is **pure dispatch** against the already-running infrastructure — there are no infra flags to pass. If the response is a `remediation` saying infrastructure is not up: when you are the session driving the wave, call `data_infrastructure(mode="up")` and retry. When you were dispatched for a single object, it is not yours to fix — the infrastructure is shared by every slot, so return `partial` and let the orchestrator bring it up.

The response carries a `monitor` block (a `job_id` and a ready-made `watch_command`).

## 4. Track it

Arm the `monitor.watch_command` with the Monitor tool, or call `job_status(job_id)` to read state on demand. `job_status(job_id, details=true)` attaches the error-first report once something needs attention. For the full monitoring / reporting / teardown walkthrough, load `SKILL.md` (Steps 5–7) in this folder.

## When it finishes

The machine reads live `DATA_MIGRATION.TABLE_PROGRESS` — do not stamp the registry. Present the migration summary (`SKILL.md` Step 6), and offer to tear the shared infrastructure down when the wave is done — unless you were dispatched for a single object, in which case leave it alone: `data_infrastructure(mode="down")` stops the worker every other slot is using, so that offer belongs to whoever owns the wave.

If the job **failed**, do not re-run it and do not change Snowflake with `sql_execute`. Call `migration_status(mode="next_task")`. A failed load is `error=sql` and the machine owns the next step. A judgment you made in the converted file (meanings vs compile) is a `note` after the fix, not a live `ALTER` and not a re-dispatch of the same workflow.
