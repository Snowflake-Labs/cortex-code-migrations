---
name: dbt-setup
description: Bootstraps a detected dbt project in the Setup phase. Resolves the source SQL dialect from profiles.yml, initializes the migration project, and points registration at local dbt files — without showing the generic source-dialect menu.
parent_skill: dbt
license: Proprietary. See License-Skills for complete terms
---

# dbt Setup

## On Entry

Tell the user:

> **dbt project detected.** I found `dbt_project.yml` in your source directory, so I'll set
> up this migration as a dbt workload — repointing your Jinja models to Snowflake rather than
> treating it as a generic code migration.
>
> To do that I need the path to the dbt source project, then I'll resolve your source dialect
> from `profiles.yml` and initialize.

## Step 1: Confirm the dbt Source Path

Ask the user for the path to the dbt project (the folder containing `dbt_project.yml`). It was
auto-detected via the enclosing directory, but confirm it explicitly so the source is unambiguous:

> "Where is your dbt project located? (the folder containing `dbt_project.yml`)"

Accept the detected path if the user confirms it, or record the path they give.

## Step 2: Resolve Source Dialect from profiles.yml

Resolve `profiles.yml` in this order and **stop at the first hit** — do not search a later
location once an earlier one matches:

1. **`<dbt project path>/profiles.yml`** — the directory where you found `dbt_project.yml`.
   Read it directly; do not glob for it. dbt projects that ship their own profile keep it here,
   and this file is authoritative for the source dialect.
2. `$DBT_PROFILES_DIR/profiles.yml`, if that variable is set.
3. `~/.dbt/profiles.yml` — **fallback only.** Never look here while a profile exists at the
   project path. A stale `~/.dbt/profiles.yml` from an unrelated project will resolve the wrong
   source platform, and probing it costs the user a permission prompt outside the project tree.

Then read the `type:` field under the profile's `outputs.<target>`:

| `profiles.yml type:` | `source_language` to configure |
|---|---|
| `redshift` | `Redshift` |
| `bigquery` | `BigQuery` |
| `databricks` | `Databricks` |
| `spark` | `Spark` |
| `postgres` | `Postgresql` |
| `snowflake` | *(already Snowflake — nothing to repoint)* |

- If `type` is `snowflake`: tell the user this dbt project already targets Snowflake, so there
  is nothing to repoint, and stop — do not initialize or continue.
- If the dialect resolves: confirm briefly, *"Detected source platform: Redshift."*
- If `profiles.yml` is absent or the type is unrecognized: ask
  > "What source platform does this dbt project run on? (e.g. Redshift, BigQuery, Databricks)"
  and use the matching `source_language` from the table.

## Step 3: Configure Source Language (triggers init)

Call `configure(source_language="<resolved>", code_source="local")` with the value from the
table. This initializes the migration project with the correct CLI dialect — the generic
source-dialect menu is never shown for a dbt workload. In a dbt project no source connection
is needed (code is local files), so do not set a source connection.

Set `code_source="local"` in the same call: a dbt project is by definition local files, and
this path skips the machine's `chooseCodeSource` prompt, so recording it here is what keeps
the generic "extract or local?" question from being asked later.

## Step 4: Next

The Setup machine proceeds to register the source. Return so the machine advances.
