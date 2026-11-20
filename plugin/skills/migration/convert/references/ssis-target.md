# SSIS conversion target

Load this from `convert` or `code-conversion-only` when `source/_etl/` contains SSIS (`.dtsx`). Ask before any dbt question.

## The question

Ask via `ask_user_question` (`multiSelect = false`):

> "How should SSIS packages be converted?
> 1. **dbt**: each data flow becomes a dbt model orchestrated by Snowflake Tasks.
> 2. **Snowflake Scripting**: each data flow becomes a standalone Snowflake stored procedure the Task graph calls. Supports ETL stabilization and deploy."

Do not label either option recommended.

## Record the answer

Persist the choice with the MCP `configure` tool: `etl_ssis_target = "dbt"` or `"scripting"`.

- **Snowflake Scripting:** set `SSIS_SCRIPTING_MODE = true`. The calling skill appends `--ssis-to-snowflake-scripting` to the convert command, which records the project-level `etl_target` and `etl_scripting_platforms` in `project.yml`. Do not load `dbt-consolidation`.
- **dbt:** when Informatica is not present, load [../../dbt-consolidation/SKILL.md](../../dbt-consolidation/SKILL.md) immediately. When Informatica is also present, ask its target question first, then load `dbt-consolidation` once if either platform chose dbt. After `dbt-consolidation` returns, load [ssis-dynamic-tables.md](ssis-dynamic-tables.md), which asks whether SSIS full-reload tables become Dynamic Tables and may set `MATERIALIZE_AS_DYNAMIC_TABLE`.

A convert that includes SSIS without the flag converts it to dbt and removes SSIS from `etl_scripting_platforms`. Pass the flag on every convert that should keep SSIS on Snowflake Scripting, re-runs included.

## After a Snowflake Scripting conversion

The SSIS units follow the same path as Informatica Snowflake Scripting: each one is stabilized through `migrate-etl` (which runs `etl-stabilization`) and deploys once stabilization completes. The `deploy` tool refuses an SSIS Snowflake Scripting unit that has not completed stabilization, outside the validate flow.

Tell the user:

> SSIS data flows were converted to Snowflake Scripting stored procedures. The generated procedures and Task graph are under `snowflake/_etl/`. Each package is stabilized before it deploys.
