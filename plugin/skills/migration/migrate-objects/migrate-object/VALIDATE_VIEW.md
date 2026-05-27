# Validate View

Compare a deployed view between source and Snowflake to verify the migration produced equivalent results.

**IMPORTANT:** Run this validation as a foreground subagent to avoid polluting the parent context window.

## Inputs

- `<schema>.<view_name>` — the view to validate
- All connections and database are configured via MCP (`configure()`)

## Step 1: Row Count Comparison

```
query_source("SELECT COUNT(*) FROM <source_schema>.<view_name>")
```

Compare with:

```sql
SELECT COUNT(*) FROM <TARGET_DATABASE>.<SCHEMA>.<VIEW_NAME>
```

on Snowflake (via the configured connection).

## Step 2: Spot Check

```
query_source("SELECT TOP 10 * FROM <source_schema>.<view_name>")
```

Compare with:

```sql
SELECT * FROM <TARGET_DATABASE>.<SCHEMA>.<VIEW_NAME> LIMIT 10
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
| Snowflake side has 0 rows (or far fewer) because base tables haven't had data migrated yet | Source has rows; Snowflake-side count is 0 or anomalously low; the view's `dependencies` in the registry list tables whose `extensions.dataMigration.status` is not `completed` | `dependency` |
| Validation couldn't run (connection drop, query timeout, permissions) | Tool-level error, not a row-count divergence | `infra` |

When the parent calls `transition_status(... outcome="failed", error=<code>)`:
- `error="sql"` routes to the rule engine + fix loop (`applyRules` → `fixCode`). Use ONLY when the SQL needs editing.
- `error="dependency"` lands the task in the errored bucket without entering the fix loop. In your user-facing reply, name the specific tables that need data migration first so the user knows what to fix.
- `error="infra"` lands in the errored bucket; the user retries.

If validation passes, return success and the parent will call `transition_status(... outcome="completed")` with no `error`.
