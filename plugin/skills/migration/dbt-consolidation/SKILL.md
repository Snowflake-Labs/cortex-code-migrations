---
name: dbt-consolidation
description: Collect dbt consolidation choices before SSIS and Informatica dbt conversions. Informatica dbt with no SSIS asks one question — consolidate projects and models by folder, or generate one project per mapping — and passes `--consolidate-dbt-projects` only for the folder choice. SSIS still confirms model-chain consolidation (off unless yes) and project consolidation (recommended default, one dbt project per package). Supplies `--consolidate-dbt-model-chains` and `--consolidate-dbt-projects` for `scai code convert`. Load from `convert` or `code-conversion-only` only when ETL will emit dbt.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# dbt Consolidation

Load this skill from `convert` or `code-conversion-only` only when:

- `source/_etl/` contains **SSIS** (`.dtsx`), or
- `source/_etl/` contains **Informatica** PowerCenter XML **and** the user chose the **dbt** target (not Snowflake Scripting).

Do **not** load this skill for Informatica Snowflake Scripting, AI-First "Something else" ETL, or when `source/_etl/` is empty.

Model-chain consolidation defaults **off**. Never pass `--consolidate-dbt-model-chains` unless the user explicitly confirms yes on the SSIS question below. An Informatica-only workload does not ask it.

Project consolidation defaults **on** after the question unless the user chooses the per-object layout (SSIS: one dbt project per Data Flow; Informatica: one dbt project per mapping). Still ask before convert. Accepting the recommended default sets `CONSOLIDATE_DBT_PROJECTS`. One flag covers the whole convert: when both SSIS and Informatica are present, ask the project question once and apply that answer to both.

Informatica dbt with no SSIS asks **one** question. Do not also ask model-chain consolidation.

## Workflow

Detect platform from `source/_etl/` (`.dtsx` = SSIS; Informatica XML = Informatica).

- **Informatica dbt only** (no `.dtsx`): ask the question in "Informatica dbt only", then return. Do not ask section 1 or section 2.
- **SSIS only**: ask section 1, then the SSIS project question in section 2.
- **Both**: ask section 1 once, then the combined project question in section 2 once. Do not also ask the Informatica-only question.

### Informatica dbt only

Say to the user (verbatim):

> *"Consolidating by folder writes one dbt project per PowerCenter folder (`--consolidate-dbt-projects`). Mappings in that folder share the project, and each mapping's models stay under `models/<mapping>/`, tagged with the mapping name. The other choice writes one dbt project per mapping."*

Then ask via `ask_user_question` (`multiSelect = false`). This is the only consolidation question:

> "How should Informatica dbt projects and models be organized? (1 is recommended)"
>
> 1. **Consolidate dbt projects and models by folder** (default)
> 2. **Generate 1 project per mapping**

- On **1**, including when the user accepts the recommended default, set `CONSOLIDATE_DBT_PROJECTS = true`. Leave `CONSOLIDATE_DBT` unset. Do **not** pass `--consolidate-dbt-model-chains`.
- On **2** only, leave both unset. Do **not** pass `--consolidate-dbt-projects` or `--consolidate-dbt-model-chains`.

Then go to "Return". Do not ask another consolidation question.

### 1. Model-chain consolidation (fewer models)

Applies to **SSIS**, including a convert that also has Informatica. Skip this section for Informatica dbt only.

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

Applies to **SSIS**, including a convert that also has Informatica. Skip this section for Informatica dbt only (that workload already asked its one question) and for Informatica Snowflake Scripting. When both platforms are present, use the combined wording and ask once.

#### SSIS only

Say to the user (verbatim):

> *"Project consolidation is the recommended default for SSIS. It writes one dbt project per SSIS package (`{PackageName}Dbt/`) instead of one project per Data Flow (`--consolidate-dbt-projects`). You deploy fewer dbt projects. Models inside the shared project stay tagged per Data Flow. Choose the previous layout only if you want a separate dbt project for each Data Flow."*

Then ask via `ask_user_question` (`multiSelect = false`):

> "How should SSIS dbt projects be organized? (1 is recommended)"
>
> 1. **Consolidated** (default) — one dbt project per package at `{PackageName}Dbt/`
> 2. **Previous** — one dbt project per Data Flow

#### Both SSIS and Informatica

Say to the user (verbatim):

> *"Project consolidation is the recommended default. For SSIS it writes one dbt project per package (`{PackageName}Dbt/`) instead of one per Data Flow. For Informatica it writes one dbt project per PowerCenter folder instead of one per mapping (`--consolidate-dbt-projects`). Models stay tagged per Data Flow or per mapping. Choose the previous layout only if you want a separate dbt project for each Data Flow and each mapping."*

Then ask via `ask_user_question` (`multiSelect = false`):

> "How should dbt projects be organized? (1 is recommended)"
>
> 1. **Consolidated** (default) — one dbt project per SSIS package and per Informatica folder
> 2. **Previous** — one dbt project per Data Flow and per mapping

- On **1. Consolidated**, including when the user accepts the recommended default, set `CONSOLIDATE_DBT_PROJECTS = true` for the calling skill.
- On **2. Previous** only, leave `CONSOLIDATE_DBT_PROJECTS` unset. Do **not** pass `--consolidate-dbt-projects`.

### 3. Return

Return to the calling skill. When it runs `scai code convert`, it appends flags only for variables set above.

## Option Reference

| Option | Description |
|--------|-------------|
| `--consolidate-dbt-model-chains` | Opt-in. Inline sequential dbt models into fewer CTE-based models (engine `EtlShrinker`). SSIS question only. Never pass for an Informatica-only workload, and never pass unless the user confirmed yes. |
| `--consolidate-dbt-projects` | Recommended default (engine `ConsolidateDbtProjects`). SSIS: one dbt project per package at `{PackageName}Dbt/` instead of one per Data Flow; models tagged per Data Flow. Informatica: one dbt project per folder (directory is the folder name) instead of one per mapping; models under `models/<mapping>/`, tagged with the mapping name. Pass when the user chooses the folder option (Informatica) or Consolidated (SSIS), including the recommended default. Leave unset only for **Generate 1 project per mapping** or **Previous**. Ignored for Informatica Snowflake Scripting. |

## CHECKPOINT Addendum

After the calling skill's conversion CHECKPOINT, also confirm:

- [ ] `--consolidate-dbt-model-chains` was used only after an explicit yes on the SSIS question, and was not used for an Informatica-only workload
- [ ] `--consolidate-dbt-projects` is present unless the user chose **Generate 1 project per mapping** (Informatica) or **Previous** (SSIS)

Then return to the calling skill.
