---
name: dbt-consolidation
description: Collect one dbt consolidation choice before SSIS and Informatica dbt conversions. Consolidate SSIS projects and models by package, consolidate Informatica projects and models by folder, or retain the per-Data-Flow/per-mapping layout. Supplies `--consolidate-dbt-projects` for `scai code convert`. Load from `convert` or `code-conversion-only` only when ETL will emit dbt.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# dbt Consolidation

Load this skill from `convert` or `code-conversion-only` only when:

- `source/_etl/` contains **SSIS** (`.dtsx`) **and** the user chose the **dbt** target (not Snowflake Scripting), or
- `source/_etl/` contains **Informatica** PowerCenter XML **and** the user chose the **dbt** target (not Snowflake Scripting).

Do **not** load this skill for Informatica Snowflake Scripting, SSIS Snowflake Scripting, AI-First "Something else" ETL, or when `source/_etl/` is empty. When a project has both platforms and only SSIS chose Snowflake Scripting (`SSIS_SCRIPTING_MODE`), ask the Informatica questions only.

Consolidation defaults **on** after the question unless the user chooses the per-object layout (SSIS: one dbt project per Data Flow; Informatica: one dbt project per mapping). Still ask before convert. Accepting the recommended default sets `CONSOLIDATE_DBT_PROJECTS`.

Every workload asks **one** consolidation question. `--consolidate-dbt-projects` is the single conversion option for consolidating generated dbt projects and models. When both platforms are present, ask once and apply the answer to both.

## Workflow

Detect platform from `source/_etl/` (`.dtsx` = SSIS; Informatica XML = Informatica). When `SSIS_SCRIPTING_MODE` is set, treat SSIS as absent: those packages are not becoming dbt.

- **Informatica dbt only** (no `.dtsx`, or SSIS is Snowflake Scripting): ask the question in "Informatica dbt only".
- **SSIS dbt only**: ask the question in "SSIS only".
- **Both on dbt**: ask the question in "Both SSIS and Informatica".

### Informatica dbt only

Say to the user (verbatim):

> *"Consolidating by folder writes one dbt project per PowerCenter folder (`--consolidate-dbt-projects`). Mappings in that folder share the project, and each mapping's models stay under `models/<mapping>/`, tagged with the mapping name. The other choice writes one dbt project per mapping."*

Then ask via `ask_user_question` (`multiSelect = false`):

> "How should Informatica dbt projects and models be organized? (1 is recommended)"
>
> 1. **Consolidate dbt projects and models by folder** (default)
> 2. **Generate 1 project per mapping**

### SSIS only

Say to the user (verbatim):

> *"Consolidation is the recommended default for SSIS. It writes one dbt project per SSIS package (`{PackageName}Dbt/`) instead of one project per Data Flow (`--consolidate-dbt-projects`) and consolidates sequential models within that project. You review and deploy fewer dbt projects and models. Choose the other layout only if you want a separate project and models for each Data Flow."*

Then ask via `ask_user_question` (`multiSelect = false`):

> "How should SSIS dbt projects and models be organized? (1 is recommended)"
>
> 1. **Consolidate dbt projects and models by package** (default)
> 2. **Generate 1 project per Data Flow**

### Both SSIS and Informatica

Say to the user (verbatim):

> *"Consolidation is the recommended default. For SSIS it consolidates dbt projects and models by package (`{PackageName}Dbt/`) instead of one project per Data Flow. For Informatica it consolidates projects and models by PowerCenter folder instead of one project per mapping (`--consolidate-dbt-projects`). Choose the other layout only if you want separate projects and models for each Data Flow and mapping."*

Then ask via `ask_user_question` (`multiSelect = false`):

> "How should dbt projects and models be organized? (1 is recommended)"
>
> 1. **Consolidate by SSIS package and Informatica folder** (default)
> 2. **Generate 1 project per Data Flow and per mapping**

For any of the three questions:

- On **1**, including when the user accepts the recommended default, set `CONSOLIDATE_DBT_PROJECTS = true` for the calling skill.
- On **2** only, leave `CONSOLIDATE_DBT_PROJECTS` unset. Do **not** pass `--consolidate-dbt-projects`.

Then return to the calling skill. Do not ask another consolidation question.

## Option Reference

| Option | Description |
|--------|-------------|
| `--consolidate-dbt-projects` | Recommended default and the only consolidation option. SSIS: consolidate projects and sequential models by package at `{PackageName}Dbt/` instead of one project per Data Flow. Informatica: one dbt project per folder instead of one per mapping, with models under `models/<mapping>/`. Pass when the user chooses consolidation, including the recommended default. Leave unset only for the per-Data-Flow/per-mapping layout. Ignored for Informatica Snowflake Scripting. |

## CHECKPOINT Addendum

After the calling skill's conversion CHECKPOINT, also confirm:

- [ ] exactly one consolidation question was asked
- [ ] `--consolidate-dbt-projects` is present unless the user chose the per-Data-Flow/per-mapping layout

Then return to the calling skill.
