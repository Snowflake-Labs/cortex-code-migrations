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
4. **Sandbox** — under `subagent_mode`, tables/views/functions populate the shared source catalog (`setupSandbox`); procedures get a private binding (`deploySandbox`) before tests. See [../sandbox/SKILL.md](../sandbox/SKILL.md). Interactive sessions skip these tasks.
5. **Test prep** — procedures/functions **with a source side**: `createTests` + `captureBaseline` generate test YAML and capture source-side baselines. Procedures/functions **with no source** (UDF helpers) skip this and go straight to deploy. BTEQ scripts: `seedScript` (binding values + import fixtures resolved from the shell script that runs it via `scai test seed --bindings-from`, hand-filled otherwise — see [../baseline-capture/seed-script/SKILL.md](../baseline-capture/seed-script/SKILL.md)) then `captureBaseline`.
6. **Deploy** — `deploy` pushes the SQL to the common Snowflake catalogs. See [DEPLOY.md](DEPLOY.md).
7. **Validate** — depending on object type:
   - Tables: `migrateData` → `validateData`
   - Views: `validateView`
   - Procedures/functions with a source side: `runTests`. See [RUN_TESTS.md](RUN_TESTS.md).
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
| `setupSandbox` | [../sandbox/setup/SKILL.md](../sandbox/setup/SKILL.md) | Shared source catalog for tables, views, functions |
| `deploySandbox` | [../sandbox/deploy/SKILL.md](../sandbox/deploy/SKILL.md) | Private `AIMSBX_*` binding for a procedure |
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

On escalation, present iteration history and offer: provide guidance, decompose and retry, skip, mark as needs human repair, or mark done.
