# SSIS full-replace tables as Dynamic Tables

Load this from `convert` or `code-conversion-only` only when SSIS (`.dtsx`) is converted to **dbt**, after `../../dbt-consolidation/SKILL.md` has returned. Ask it once per conversion.

Do **not** load it when SSIS chose Snowflake Scripting (`SSIS_SCRIPTING_MODE`), when `source/_etl/` has no SSIS, or on the dbt repointing path (`source/dbt_project.yml`). The engine ignores the flag in all three.

## The question

Say to the user (verbatim):

> *"Each SSIS OLE DB Destination (`Microsoft.OLEDBDestination`) becomes a dbt model. By default that model is materialized as `incremental`: each `dbt run` inserts the data flow's rows, and any `TRUNCATE TABLE` or `DELETE` the package runs before the load stays in the converted orchestration."*
>
> *"SnowConvert can instead materialize a destination as a Snowflake Dynamic Table when the package fully replaces it on every run: an Execute SQL task empties the same table on the same connection (`TRUNCATE TABLE`, or `DELETE` with no `WHERE`) before one data flow reloads it, and nothing else in the package writes to it. The Dynamic Table is defined by the converted data-flow query, so SnowConvert removes that table's emptying statement and keeps any other statements in the same task. dbt refreshes it each time the project runs, and Snowflake refreshes only the changed rows when the query allows it. Every other destination, such as appends, upserts, and partial deletes, stays `incremental`. In real workloads this is usually a small share of the destinations."*
>
> *"Before you choose Dynamic Table: check that no other package, stored procedure, or script writes to these tables, because a Dynamic Table can't be inserted into, updated, or truncated. Identity columns, defaults, constraints, and triggers of the original table are not carried over. Running the project needs dbt-snowflake 1.11.5 or later and a warehouse set in `profiles.yml`."*

Then ask via `ask_user_question` (`multiSelect = false`):

> "Materialization of `Microsoft.OLEDBDestination`"
>
> 1. **Incremental** (default): every OLE DB Destination model is `incremental`, and the package's emptying statements stay, as in SSIS.
> 2. **Dynamic Table**: destinations the package fully replaces become Dynamic Tables and lose their emptying statement; all others stay `incremental`.

Do not label either option recommended. Accepting the default is option 1.

## Record the answer

- On **2**, set `MATERIALIZE_AS_DYNAMIC_TABLE = true` for the calling skill, which appends `--materialize-as-dynamic-table` to the convert command.
- On **1**, leave `MATERIALIZE_AS_DYNAMIC_TABLE` unset. Do **not** pass the flag.

The answer holds for this session only. A re-run convert in the same session, including one from "Changing Conversion Settings Later", passes the flag again when `MATERIALIZE_AS_DYNAMIC_TABLE` is set. In a new session, ask again before converting.

If the user later asks to change the OLE DB Destination materialization, load this file and ask again; `recommend-settings` cannot propose this flag because the settings catalog does not list it.

The flag combines with whichever consolidation flag `dbt-consolidation` chose. Never pass it with `--ssis-to-snowflake-scripting`.

## After the conversion

Each promoted model carries an `SSC-FDM-SSIS0032` note, and each removed `TRUNCATE` or `DELETE` an `SSC-FDM-SSIS0033` note. ETL stabilization handles both; see `../../migrate-objects/actions/etl-stabilization/platforms/ssis/ewi/`.

When you summarize the conversion, say how many OLE DB Destination models became Dynamic Tables (the marts under `snowflake/_etl/` with `materialized='dynamic_table'`). If none did, say that no destination was fully replaced in a way SnowConvert could prove, so every model stays `incremental`. Otherwise remind the user that running the project needs dbt-snowflake 1.11.5 or later and a warehouse in `profiles.yml`. Incremental refresh needs change tracking on the source tables, which their owner may have to enable.

## CHECKPOINT Addendum

- [ ] the question was asked at most once, and only for SSIS on dbt
- [ ] `--materialize-as-dynamic-table` is present only when the user chose **Dynamic Table**
