# Step-Based Test YAML — Cheat Sheet

Schema `scai test capture` / `validate` consume. For editing recipes see [edit-test-yaml.md](edit-test-yaml.md).

```yaml
validation:
  steps: [...]              # required, non-empty
  test_cases: [...]         # optional, default []
  modifies_data: true       # optional override, inferred from CUR
  affected_tables:          # optional override, inferred from CUR
    - Database.Schema.Table
```

Files are discovered under `artifacts/**/test/*.yml`; a file is step-based when `validation.steps` is a list.

## Step types

Each step uses keys from exactly one type; mixing is a parse error.

| Type | Keys | `validate` | Notes |
|---|---|---|---|
| SQL query | `source_query` / `target_query`, or `both` | `true` (default) / `false` / `[list]` | Omit one side to no-op it. Block scalars `\|-` for multiline. |
| Declaration | `source_declare` / `target_declare` | must be `false` | One variable per row; cannot share a row with a query. Oracle: naked decl (`p NUMBER := 0`) hoisted into `DECLARE`. SQL Server / Snowflake: full statement (`DECLARE @x INT = 0` / `LET X INT := 0`). |
| OUT param compare | `source_params` / `target_params` | always (setting `false` is a parse error) | Snowflake reads `:NAME` in the scripting block. |
| Table read | `table`, or `source_table` / `target_table` | always | Snowflake: `SELECT * FROM IDENTIFIER('{name}')`. |
| Cursor read | `cursor`, or `source_cursor` / `target_cursor` | always | Source side **Redshift only** (`FETCH ALL FROM`). |

```yaml
- source_query: "EXECUTE MyDB.dbo.GetOrders @region = {0}"
  target_query: "CALL MyDB.dbo.GetOrders({0})"
- source_params: ["@totalOrders"]
  target_params: ["TOTALORDERS"]
```

`validate: false` executes without capture (setup, declarations, side-effect calls).

## Multi-result-set validation

`validate: [list]` — **SQL Server source → Snowflake target only** (Redshift: use cursor reads). One entry per
source result set, in order:

| Entry | Compare against |
|---|---|
| `false` | skip this RS |
| `result` | the CALL's direct return |
| `array_index: N` | `GET(call_return, N)` — Nth temp table of a `RETURNS ARRAY` proc (0-based) |
| `table: "name"` | `SELECT * FROM name` |
| `cursor: "name"` | the named cursor |
| `target_query: "SQL"` | arbitrary target SQL |

## Placeholders and `test_cases`

`{0}`, `{1}`, … in step SQL are replaced from the current test-case array as dialect SQL literals. In `table:` /
`cursor:` names they are substituted raw (unquoted). An index past the array end is left as literal `{N}`.

```yaml
test_cases:
  - ["West", "active"]    # {0} = 'West', {1} = 'active'
  - ["East", null]        # {1} = NULL
  - []                    # zero-arg
```

| YAML | SQL Server | Snowflake / Redshift |
|---|---|---|
| `null` | `NULL` | `NULL` |
| `true` / `false` | `1` / `0` | `TRUE` / `FALSE` |
| `42`, `3.14` | as-is | as-is |
| `"it's"` | `'it''s'` | `'it''s'` |

All steps run once per test case, each case in a fresh session.

## `modifies_data` / `affected_tables`

Omit by default — CUR inference is right for most procedures. Override only when CUR misses DML
(`modifies_data: true`), to skip delta capture (`false`), or when CUR misses a touched table. With delta capture
the runner snapshots `SELECT *` of each affected table on both sides before and after, and compares the deltas.

## Things that bite

- **CALL detection:** only a `target_query` that *starts* with `CALL ` (case-insensitive, trimmed) is captured via
  `RESULT_SCAN(LAST_QUERY_ID())`. Any other `validate: true` SQL is wrapped in
  `CREATE OR REPLACE TEMPORARY TABLE _step_N AS <query>`. No statements before the CALL — put follow-up work in
  a later step.
- **Target scope:** all target steps run in one `BEGIN … END;` block; `LET` variables carry across steps,
  referenced as `:VARNAME` (uppercase).
- **Source scope:** SQL Server — one T-SQL batch; `DECLARE`d variables and OUTPUT params persist across steps.
  Redshift — statements run individually in one transaction; INOUT values come from the CALL result row (no
  `DECLARE`); one open cursor at a time.
- **Reserved names:** `_step_N`, `_step_N_vK` (Kth `validate` list entry), `_rs_N` (raw CALL result for a
  `result` entry). Do not use them in your SQL.
