---
name: migrate-object
description: Core migration loop for a single stored procedure, function, or BTEQ script. Iterates deploy -> test -> diagnose -> fix until Snowflake output matches source.
parent_skill: migrate-objects
license: Proprietary. See License-Skills for complete terms
---

# Migrate Object — Reference

This document describes the conceptual flow for migrating a single object. The state machine drives execution — you do not follow these steps manually. Each task in the machine points to a specific guide via its `skill` field.

## Overview

Each object goes through a pipeline managed by the state machine:

1. **Claim** — `claimObject` reserves the object for this user.
2. **Checkout** — `checkoutBranch` creates or switches to a git branch.
3. **Convert** — `convert` runs SnowConvert to produce initial Snowflake SQL.
4. **Sandbox** — under `subagent_mode`, tables/views/functions populate the shared source catalog (`deployCommonSandbox`); procedures get a private binding (`createIsolatedSandbox`) before tests. See [../sandbox/SKILL.md](../sandbox/SKILL.md). Interactive sessions skip these tasks.
5. **Test prep** — procedures/functions **with a source side**: `createTests` + `captureBaseline` generate test YAML and capture source-side baselines. Procedures/functions **with no source** (UDF helpers) skip this and go straight to deploy. BTEQ scripts: `seedScript` (binding values + import fixtures resolved from the shell script that runs it via `scai test seed --bindings-from`, hand-filled otherwise — see [../baseline-capture/seed-script/SKILL.md](../baseline-capture/seed-script/SKILL.md)) then `captureBaseline`.

   When synthetic data for the object already exists and the user asks to test it on the source, do not stop after the YAML. A table seed writes no YAML. Call `setup_sandbox` for the table (it runs `scai testbed load` itself — do not shell that command). Seed and capture the view whose SQL selects that table. Do not pass the table name to `scai test seed` or `scai test capture`. Do not call `run_tests`. Do not shell `scai code deploy`, `scai code extract`, or `scai code convert` — objects are already deployed. A missing view or unresolved binding token is not permission to redeploy.

   For `OverlayClean` (table → view path only — **never** a procedure):

   ```
   setup_sandbox(where="source.canonicalName ILIKE '%.OverlayClean'")
   ```

   ```bash
   scai test seed --where "source.canonicalName ILIKE '%.OverlayDoubled'"
   scai test capture --keep-baselines --where "source.canonicalName ILIKE '%.OverlayDoubled'"
   ```

   Seed/capture **only** `OverlayDoubled` when the user named **`OverlayClean`**.
   Do **not** seed or capture `GetOverlayDouble` / `OverlayEasyEwi` on that
   path. Do not retarget to a procedure. Do not add `--profile` unless
   seed/capture otherwise cannot resolve bindings. After seed, `artifacts/**/test/*.yml` for OverlayDoubled **must**
   exist and its body **must** contain the literal string `OverlayClean`.
   If the stub lacks that string, set `source_query` to the view `SELECT` that
   names `OverlayClean`, then capture `--keep-baselines` again. Never stop with
   zero YAML or a YAML that omits `OverlayClean`.

   For **`GetOverlayDouble`** (user named the procedure — do **not** substitute
   OverlayDoubled):

   ```
   setup_sandbox(where="source.canonicalName ILIKE '%.OverlayClean'")
   ```

   ```bash
   scai test seed --where "source.canonicalName ILIKE '%.GetOverlayDouble'"
   scai test capture --keep-baselines --where "source.canonicalName ILIKE '%.GetOverlayDouble'"
   ```

   The YAML under `artifacts/**/test/` **must** name `GetOverlayDouble`. Capturing
   only OverlayDoubled when the user asked for GetOverlayDouble fails the hop.

   For any other procedure or view the user named, call `setup_sandbox` then
   shell seed and capture `--keep-baselines`, all scoped to **that same name**,
   anchored after a dot so a shorter stem cannot select a sibling (`Overlay`
   matches `OverlayEasyEwi`). When the procedure's closure includes a table
   (GetOverlayDouble → OverlayClean), call `setup_sandbox` on that **table**
   first so synthetic rows load before seed/capture of the procedure. Always call `setup_sandbox` even when the object reads no tables — a no-op load
   still satisfies the hop; skipping it fails hard rules — but
   `extracted live source preserved` / self-mapped preserve is **not** a load:
   rebind to `AIMSBX_TB_*`, re-configure, retry until rows load. Never stop after seed alone: missing `baselines/*.json` is a failed hop. After seed for
   a table-backed view, the written `artifacts/**/test/*.yml` body must contain
   the table name. Leave literal `TEST_SQL_CUJ_*` / `EVAL_*` / `SNAP_*` names
   in `target_query` — checkpoint restore rewrites them to this hop's clone.
   Do not invent a `${...}` binding token (wrong token → validate reports
   Passed with `Snowflake queries executed: 0` and writes nothing to
   `VALIDATION.LATEST`). Only add `test_cases: [ [] ]` when the stub lacks
   cases. Do not shell `scai testbed load` — `setup_sandbox` replaces that
   command. `scai test capture` without `--keep-baselines` does not leave
   `baselines/*.json`. **Stop after capture.** Do not run `scai test validate`.
   Do not enter `assessment`. Do not shell `scai code deploy`. Do not retarget
   `testing_results_database` to a private `SNOWCONVERT_AI_EVAL_*` database.
6. **Deploy** — `deploy` pushes the SQL to the common Snowflake catalogs. See [DEPLOY.md](DEPLOY.md).
7. **Validate** — depending on object type:
   - Tables: `migrateData` → `validateData`
   - Views: `validateView`
   - Procedures/functions with a source side: `runTests`. See [RUN_TESTS.md](RUN_TESTS.md). When the source baseline already exists and the user asks to test the Snowflake side, shell **bash** `scai test validate --create-schema --where "source.canonicalName ILIKE '%.<object_name>'"` — not `run_tests`. The literal `--create-schema` flag is required. When the named object was a **table** whose source-test captured a selecting view (`OverlayClean` → `OverlayDoubled`), validate **OverlayDoubled**. When the user named **GetOverlayDouble**, validate **GetOverlayDouble**. PASS must appear in `SNOWCONVERT_AI.VALIDATION.LATEST` (not a private `SNOWCONVERT_AI_EVAL_*` DB). If Snowflake tables are empty (`row_count_mismatch`), shell `scai testbed load` (omit `--source-only`) for OverlayClean then re-validate once — still no `migrate_data`. Do not enter `data-migration`. Do not edit `.scai` profiles, bindings, or `testing_results_database`. Do not redeploy. Do not shell `scai code deploy`.
   - Procedures/functions with no source: `verify`. See [VERIFY.md](VERIFY.md).
   - BTEQ scripts: `runTests` (deploy is skipped — the converted script is run by the test). See [RUN_TESTS.md](RUN_TESTS.md).
8. **Fix loop** — if deployment or validation fails, the machine enters a cycle:
   - `applyRules` — apply known migration rules from the rule engine.
   - `fixCode` — diagnose the failure and make targeted fixes. See [DIAGNOSE_FIX.md](DIAGNOSE_FIX.md).
   - Loop back to deploy.
9. **Extract rules** — `extractRules` captures reusable rules from successful fixes. See [DEDUCE_RULE.md](DEDUCE_RULE.md).
10. **Finalize** — `finalizeBranch` commits and pushes, `markDone` closes the claim.

## Task guides

| Task | Guide | Purpose |
|------|-------|---------|
| `deployCommonSandbox` | [../sandbox/DEPLOY_COMMON.md](../sandbox/DEPLOY_COMMON.md) | Shared source catalog for tables, views, functions |
| `createIsolatedSandbox` | [../sandbox/CREATE_ISOLATED.md](../sandbox/CREATE_ISOLATED.md) | Private `AIMSBX_*` binding for a procedure |
| `deploy` | [DEPLOY.md](DEPLOY.md) | Common-catalog deploy: pre-deploy checks, error table, file-update rules |
| `runTests` | [RUN_TESTS.md](RUN_TESTS.md) | Interpreting results, dependency failure detection |
| `fixCode` | [DIAGNOSE_FIX.md](DIAGNOSE_FIX.md) | Root cause analysis, minimal fix strategy |
| `extractRules` | [DEDUCE_RULE.md](DEDUCE_RULE.md) | Capturing reusable rules from fixes |

## Complexity check

If the source SQL file has **200+ non-empty lines**, consider the decompose-convert-assemble approach described in [references/LONG_PROCEDURE.md](references/LONG_PROCEDURE.md) instead of the standard fix loop.

## Escalation criteria

Do NOT iterate blindly. Escalate to the user when:

| Condition | Trigger |
|-----------|---------|
| Same error persists | Same primary error for 3 consecutive iterations |
| Errors churning | Errors keep changing but never resolve after 5 total iterations |

On escalation, present iteration history and offer: provide guidance, decompose and retry, skip (remove the object from the migration), mark as needs human repair, or mark done. For a table parked on `migrateData`, also offer skip data (`skip_data`): keep the table and deploy its structure, but do not copy its rows.
