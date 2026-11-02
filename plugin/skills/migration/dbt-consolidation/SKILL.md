---
name: dbt-consolidation
description: Collect one dbt consolidation choice before SSIS and Informatica dbt conversions. Consolidate SSIS projects and models by package, consolidate every SSIS package into one dbt project, consolidate Informatica projects and models by folder, or retain the per-Data-Flow/per-mapping layout. Supplies `--consolidate-dbt-projects` or, for SSIS only, `--consolidate-as-single-dbt-project` for `scai code convert`. Load from `convert` or `code-conversion-only` only when ETL will emit dbt.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# dbt Consolidation

Load this skill from `convert` or `code-conversion-only` only when:

- `source/_etl/` contains **SSIS** (`.dtsx`) **and** the user chose the **dbt** target (not Snowflake Scripting), or
- `source/_etl/` contains **Informatica** PowerCenter XML **and** the user chose the **dbt** target (not Snowflake Scripting).

Do **not** load this skill for Informatica Snowflake Scripting, SSIS Snowflake Scripting, AI-First "Something else" ETL, or when `source/_etl/` is empty. When a project has both platforms and only SSIS chose Snowflake Scripting (`SSIS_SCRIPTING_MODE`), ask the Informatica questions only.

Consolidation defaults **on** after the question unless the user chooses the per-object layout (SSIS: one dbt project per Data Flow; Informatica: one dbt project per mapping). Still ask before convert. Accepting the recommended default sets `CONSOLIDATE_DBT_PROJECTS`.

Every workload asks **one** consolidation question. `--consolidate-dbt-projects` consolidates SSIS by package and Informatica by folder. `--consolidate-as-single-dbt-project` is an SSIS-only choice that writes one dbt project for the whole workload. The two flags are mutually exclusive. When both platforms are present, ask once and apply that answer to both; do not offer or pass the single-project flag on that question.

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

Do **not** offer a single-dbt-project choice. Do **not** set `CONSOLIDATE_AS_SINGLE_DBT_PROJECT` or pass `--consolidate-as-single-dbt-project`.

### SSIS only

Say to the user (verbatim):

> *"Consolidation is the recommended default for SSIS. It writes one dbt project per SSIS package (`{PackageName}Dbt/`) instead of one project per Data Flow (`--consolidate-dbt-projects`) and consolidates sequential models within that project. You review and deploy fewer dbt projects and models. Choose another layout only if you want a separate project and models for each Data Flow, or one project for the whole workload. Consolidating into a single dbt project writes one dbt project for the entire workload (`--consolidate-as-single-dbt-project`). Models stay grouped by package and Data Flow inside that project. It is not the default."*

Then ask via `ask_user_question` (`multiSelect = false`):

> "How should SSIS dbt projects and models be organized? (1 is recommended)"
>
> 1. **Consolidate dbt projects and models by package** (default)
> 2. **Generate 1 project per Data Flow**
> 3. **Consolidate into a single dbt project**

### Both SSIS and Informatica

Say to the user (verbatim):

> *"Consolidation is the recommended default. For SSIS it consolidates dbt projects and models by package (`{PackageName}Dbt/`) instead of one project per Data Flow. For Informatica it consolidates projects and models by PowerCenter folder instead of one project per mapping (`--consolidate-dbt-projects`). Choose the other layout only if you want separate projects and models for each Data Flow and mapping."*

Then ask via `ask_user_question` (`multiSelect = false`):

> "How should dbt projects and models be organized? (1 is recommended)"
>
> 1. **Consolidate by SSIS package and Informatica folder** (default)
> 2. **Generate 1 project per Data Flow and per mapping**

Do **not** offer a single-dbt-project choice. Do **not** set `CONSOLIDATE_AS_SINGLE_DBT_PROJECT` or pass `--consolidate-as-single-dbt-project`. That flag consolidates all generated dbt output, including Informatica.

For Informatica dbt only and for both platforms:

- On **1**, including when the user accepts the recommended default, set `CONSOLIDATE_DBT_PROJECTS = true` for the calling skill.
- On **2** only, leave `CONSOLIDATE_DBT_PROJECTS` unset. Do **not** pass `--consolidate-dbt-projects`.

For SSIS only:

- On **1**, including when the user accepts the recommended default, set `CONSOLIDATE_DBT_PROJECTS = true`. Leave `CONSOLIDATE_AS_SINGLE_DBT_PROJECT` unset.
- On **2**, leave both unset. Do **not** pass `--consolidate-dbt-projects` or `--consolidate-as-single-dbt-project`.
- On **3**, set `CONSOLIDATE_AS_SINGLE_DBT_PROJECT = true` and leave `CONSOLIDATE_DBT_PROJECTS` unset. Pass `--consolidate-as-single-dbt-project` only.

Never pass both consolidation flags.

Then return to the calling skill. Do not ask another consolidation question.

## Option Reference

| Option | Description |
|--------|-------------|
| `--consolidate-dbt-projects` | Recommended default. SSIS: consolidate projects and sequential models by package at `{PackageName}Dbt/` instead of one project per Data Flow. Informatica: one dbt project per folder instead of one per mapping, with models under `models/<mapping>/`. Pass when the user chooses that consolidation, including the recommended default. Leave unset for the per-Data-Flow/per-mapping layout and for the SSIS single-project choice. Ignored for Informatica Snowflake Scripting. Mutually exclusive with `--consolidate-as-single-dbt-project`. |
| `--consolidate-as-single-dbt-project` | SSIS dbt only, when the user chooses **Consolidate into a single dbt project**. One dbt project for every SSIS package in the workload; models stay grouped by package and Data Flow. Do not pass it with `--consolidate-dbt-projects`, for Informatica dbt, for the shared both-platforms answer, or for SSIS Snowflake Scripting. |

## CHECKPOINT Addendum

After the calling skill's conversion CHECKPOINT, also confirm:

- [ ] exactly one consolidation question was asked
- [ ] the convert flag matches the answer: `--consolidate-dbt-projects` only for package or folder consolidation; neither flag for the per-Data-Flow/per-mapping layout; `--consolidate-as-single-dbt-project` only when SSIS-only chose the single dbt project

Then return to the calling skill.
