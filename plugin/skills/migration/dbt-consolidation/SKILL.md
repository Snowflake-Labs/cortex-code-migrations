---
name: dbt-consolidation
description: Collect opt-in dbt consolidation choices for SSIS and Informatica dbt conversions. Explains model-chain vs project consolidation, asks the user to confirm each independently, and supplies `--consolidate-dbt-model-chains` and `--consolidate-dbt-projects` for `scai code convert`. Load from `convert` or `code-conversion-only` only when ETL will emit dbt.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# dbt Consolidation

Load this skill from `convert` or `code-conversion-only` only when:

- `source/_etl/` contains **SSIS** (`.dtsx`), or
- `source/_etl/` contains **Informatica** PowerCenter XML **and** the user chose the **dbt** target (not Snowflake Scripting).

Do **not** load this skill for Informatica Snowflake Scripting, AI-First "Something else" ETL, or when `source/_etl/` is empty.

Both options default **off**. Never pass either flag unless the user explicitly confirms yes. The two options are independent: one may be yes and the other no.

## Workflow

Detect platform from `source/_etl/` (`.dtsx` = SSIS; Informatica XML = Informatica). If both are present, ask both applicable questions.

### 1. Model-chain consolidation (fewer models)

Applies to **SSIS** and **Informatica dbt**.

Say to the user (verbatim):

> *"Model-chain consolidation inlines sequential dbt models into fewer CTE-based models (`--consolidate-dbt-model-chains`). You get fewer model files to review and deploy. Skip this if you want one model per transformation so each stays easier to inspect."*

Then ask via `ask_user_question` (`multiSelect = false`):

> "Consolidate dbt model chains to reduce the number of generated model files?"
>
> 1. **Yes** — fewer models (inline sequential models as CTEs)
> 2. **No** — keep separate models (default)

- On **Yes**, set `CONSOLIDATE_DBT = true` for the calling skill.
- On **No**, or if the user does not confirm, leave `CONSOLIDATE_DBT` unset. Do **not** pass `--consolidate-dbt-model-chains`.

### 2. Project consolidation (fewer dbt projects)

Applies to **SSIS only**. Skip this step for Informatica-only workloads (the engine has no Informatica project-consolidation flag).

Say to the user (verbatim):

> *"Project consolidation writes one dbt project per SSIS package (`{PackageName}Dbt/`) instead of one project per Data Flow (`--consolidate-dbt-projects`). You deploy fewer dbt projects. Models inside the shared project stay tagged per Data Flow. Skip this if you want a separate dbt project for each Data Flow."*

Then ask via `ask_user_question` (`multiSelect = false`):

> "Consolidate SSIS dbt output into one dbt project per package?"
>
> 1. **Yes** — one dbt project per package
> 2. **No** — one dbt project per Data Flow (default)

- On **Yes**, set `CONSOLIDATE_DBT_PROJECTS = true` for the calling skill.
- On **No**, or if the user does not confirm, leave `CONSOLIDATE_DBT_PROJECTS` unset. Do **not** pass `--consolidate-dbt-projects`.

### 3. Return

Return to the calling skill. When it runs `scai code convert`, it appends flags only for variables set above.

## Option Reference

| Option | Description |
|--------|-------------|
| `--consolidate-dbt-model-chains` | Opt-in. Inline sequential dbt models into fewer CTE-based models (engine `EtlShrinker`). SSIS and Informatica dbt. Never pass unless the user confirmed yes. |
| `--consolidate-dbt-projects` | Opt-in. One dbt project per SSIS package at `{PackageName}Dbt/` instead of one project per Data Flow (engine `ConsolidateDbtProjects`). Never pass unless the user confirmed yes. Informatica does not support this flag. |

## CHECKPOINT Addendum

After the calling skill's conversion CHECKPOINT, if either flag was passed, also confirm:

- [ ] `--consolidate-dbt-model-chains` was used only after an explicit yes
- [ ] `--consolidate-dbt-projects` was used only after an explicit yes, and only for SSIS

Then return to the calling skill.
