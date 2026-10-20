# SSIS conversion target

Load this from `convert` or `code-conversion-only` when `source/_etl/` contains SSIS (`.dtsx`). Ask before any dbt question.

## The question

Ask via `ask_user_question` (`multiSelect = false`):

> "How should SSIS packages be converted?
> 1. **dbt**: each data flow becomes a dbt model orchestrated by Snowflake Tasks.
> 2. **Snowflake Scripting** (Preview): each data flow becomes a standalone Snowflake stored procedure the Task graph calls. Stabilization and deploy are not part of this preview."

Do not label either option recommended.

## Record the answer

Persist the choice with the MCP `configure` tool: `etl_ssis_target = "dbt"` or `"scripting"`.

- **Snowflake Scripting:** set `SSIS_SCRIPTING_MODE = true`. The calling skill appends `--ssis-to-snowflake-scripting` to the convert command, which records the project-level `etl_target` and `etl_scripting_platforms` in `project.yml`. Do not load `dbt-consolidation`.
- **dbt:** when Informatica is not present, load [../../dbt-consolidation/SKILL.md](../../dbt-consolidation/SKILL.md) immediately. When Informatica is also present, ask its target question first, then load `dbt-consolidation` once if either platform chose dbt.

A convert that includes SSIS without the flag converts it to dbt and removes SSIS from `etl_scripting_platforms`. Pass the flag on every convert that should keep SSIS on Snowflake Scripting, re-runs included.

## After a Snowflake Scripting conversion

The conversion is a preview and ends after convert. Do not stabilize or deploy the SSIS units: no `migrate-etl`, no `etl-stabilization`, no `deploy`. The `deploy` tool refuses them regardless.

Tell the user:

> SSIS data flows were converted to Snowflake Scripting stored procedures (preview). Stabilization and deploy are not part of this preview. The generated procedures and Task graph are under `snowflake/_etl/` for review.
