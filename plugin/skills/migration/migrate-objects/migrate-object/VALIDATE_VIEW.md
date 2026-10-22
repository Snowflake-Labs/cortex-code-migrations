# Validate View

Compare a deployed view between source and Snowflake to verify the migration produced equivalent results.

Run this validation as a foreground subagent so its output stays out of the parent context window.

## Step 0: Record skill start

Before any queries, record a `started` TASK_EVENT:

```
transition_status(status="started", task="validateView", where="id = '<object_id>'")
```

Finish with `transition_status` in Step 4 — do not call `begin` / `status='start'` here.

## Inputs

- `<schema>.<view_name>` — the view to validate
- `<snowflake_connection>` — attach `snowflake_connection:` / first-prompt
  `snowflakeConnection`. Pass it as `sql_execute` `connection` (`-c`).
- `<source_database>` — the source **catalog** from the attach
  `active_bindings:` `source:` map (inlined under the path). Not the
  connection's default database and not `source.database`.
- `<snowflake_database>` — the Snowflake **target** from the attach
  `active_bindings:` `snow:` map (inlined under the path). Not `source.database`
  and not the workload catalog name.

If leftover sandbox yaml exists for this view
(`.scai/bindings/sandbox/{hash}.yaml` after a make_testable mint), use
that file's `source:` / `snow:` maps instead of the attach common yaml.

## Step 1: Row Count Comparison

```
query_source("SELECT COUNT(*) FROM <source_database>.<source_schema>.<view_name>")
```

Compare with:

```
sql_execute(
  connection="<snowflake_connection>",
  sql="SELECT COUNT(*) FROM <snowflake_database>.<SCHEMA>.<VIEW_NAME>",
  description="Count rows in the deployed target view"
)
```

`query_source` is the source database — it does not apply bindings, so qualify
with the `source:` catalog from `active_bindings`. `sql_execute` is Cortex
Snowflake and does not inherit `configure` — pass `connection` from attach
`snowflake_connection:` / the first-prompt `snowflakeConnection`, and qualify
with the `snow:` catalog from `active_bindings`. Never substitute
`source.database`, a `SNAP_USE_*` clone, or `SNOWCONVERT_AI*`. Never
`SHOW DATABASES` or roam other catalogs. If `sql_execute` is unavailable,
denied, times out, or the catalog is missing, park; do not fall back to
shell, `snow sql`, Python, or an unqualified query.

## Step 2: Spot Check

```
query_source("SELECT TOP 10 * FROM <source_database>.<source_schema>.<view_name>")
```

Compare with:

```
sql_execute(
  connection="<snowflake_connection>",
  sql="SELECT * FROM <snowflake_database>.<SCHEMA>.<VIEW_NAME> LIMIT 10",
  description="Sample rows from the deployed target view"
)
```

Check for:
- Column name mismatches
- Data type differences (e.g. datetime precision, numeric scale)
- NULL handling differences
- Character encoding or collation issues

## Step 3: Report

Return a structured result:
- **Row count match:** yes/no (source count vs Snowflake count)
- **Column differences:** any mismatched column names or types
- **Data differences:** any value mismatches from the spot check
- **Verdict:** pass/fail
- **If fail, classify the cause** — see Step 4.

## Step 4: Classify the Failure

Before reporting fail, identify *why*. The classification drives how the parent advances the task and how the user is told about it.

| Cause | Signal | `error` code |
|---|---|---|
| The view's DDL is wrong (compile error, column missing, type mismatch, bad expression) | Snowflake-side query errors, or values diverge despite full data | `sql` |
| Fixture rows or a missing AIMSBX table | Source and Snowflake agree on empty/wrong; a different legal dataset would exercise the view — **or** 42S02 / `missing_object` | *(do not stamp — Step 4a)* |
| Snowflake side has 0 rows (or far fewer) because base tables haven't had data migrated yet | Source has rows; Snowflake-side count is 0 or anomalously low; the view's `dependencies` in the registry list tables whose live `migrateData` job is not completed | *(do not stamp)* |
| Validation couldn't run (connection drop, query timeout, permissions) | Tool-level error, not a row-count divergence; do not substitute a shell query | `infra` |

### Step 4a: Fixture / missing AIMSBX table

Do not stamp `error=sql` or `infra`. Do not edit WAVE_SRC or a table CSV.
Qualify retries from leftover yaml `source:` / `snow:` maps.

| Evidence | Do |
|---|---|
| Named id not on `dependsOn`, `id` is null, **or** SQL/CUR of the named object is not bindable | Spawn **one** foreground `cur_reconciler`, then `next_task` |
| Every named id already on `dependsOn` **and** SQL/CUR bindable, or empty join / VARCHAR concat / a filter the fixture never produced | **Under `subagent_mode`:** one foreground `sandbox_specialist` (`task=validateView`). After `done`, `note` (inverse = drop this AIMSBX pair / reload CSVs) and retry. `needs_cur` → spawn `cur_reconciler`. `repaired` / `clean` → `deploy(sandbox=true)` omit `mode`, then retry. **Interactive:** tell the user and wait. |

### Step 4b: Stamp the outcome

Advance from this skill (or the parent walker) so `TASK_EVENTS` get an `advanced` row — do not leave completion to `next_task` alone:

- **Pass** → `transition_status(status="advance", task="validateView", outcome="completed", where="id = '<object_id>'")`
- **Fail, DDL wrong** → `transition_status(status="advance", task="validateView", outcome="failed", error="sql", where="id = '<object_id>'")` — routes to `applyRules` → `fixCode`. Use ONLY when the SQL needs editing.
- **Fail, infra** → `transition_status(status="advance", task="validateView", outcome="failed", error="infra", where="id = '<object_id>'")` — lands in the errored bucket; the user retries.
- **Fixture / missing AIMSBX table** → do not stamp; follow Step 4a.
- **Missing `migrateData`** → do not stamp a dependency wait. The walk already surfaces those tables on `blockedOn`; name them in your reply and leave the task unstamped.
