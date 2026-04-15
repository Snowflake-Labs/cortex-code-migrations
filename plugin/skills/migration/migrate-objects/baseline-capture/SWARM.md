# Test Case Generation: AI-Assisted Swarm

Use when no query logs exist. Spawns a swarm of agents, each focusing on a different testing dimension to generate comprehensive, non-overlapping test cases for a single object.

> **SCOPE: Generate test cases for ONE object (`<object_name>`) only.**

## Step 1: Gather Context

First, read the source code and understand `<object_name>`:

```bash
# Find the source file
find <project_dir>/source -name "*.sql" | xargs grep -l "<object_name>"
```

Read the source SQL file to understand:
- Parameter names and types
- Tables/views referenced
- Business logic and code branches
- Any constraints or validation

## Step 2: Determine Complexity

| Complexity | Characteristics | Agents |
|------------|-----------------|--------|
| **Simple** | 1-3 params, straightforward logic | 3 (one of each type) |
| **Complex** | 4+ params, multiple branches, table lookups | 6 (two of each type) |

## Step 3: Spawn Agent Swarm

Launch agents **in parallel** using the Task tool. Each agent reads its own instruction file — do NOT paste agent instructions into your context.

**IMPORTANT** Propogate the current SQL connection to each agent.

| Agent Type | Instruction File | Needs Source DB | Key Focus |
|------------|-----------------|-----------------|-----------|
| **Data-Driven** (most important) | `agents/data_driven.md` | Yes | Real parameter values from actual data |
| **Edge Cases & Boundaries** | `agents/edge_cases.md` | No | NULLs, zeros, type limits, overflow |
| **Business Logic** | `agents/business_logic.md` | No | Code path coverage, branch testing |

### Spawning Each Agent

For each agent, use the Task tool with a prompt like:

```
Read the instructions at <baseline_capture_dir>/agents/<agent_type>.md
then generate test cases for <object_name>.

Object signature: <signature>
Source code: <source_code>
Referenced tables: <table_list>           # data-driven only
Source connection name: <source_connection_name>  # data-driven only
Project directory: <project_dir>
```

Where `<baseline_capture_dir>` is the directory containing this file.

For **complex objects**, spawn 2 agents per type (see each agent doc for A/B split guidance).

## Step 4: Merge and Deduplicate

After agents complete:

1. Read test cases from `<project_dir>/.scai/tmp/<object_name>_*.yml` files
2. If any tmp file is missing, fall back to parsing the agent's stdout output
3. Remove exact duplicates
4. Aim for **15-25 test cases** total

## Step 5: Create Test YAML File

Create the test YAML file for `<object_name>` at:

```
<project_dir>/artifacts/<database>/<schema>/procedure/<ProcedureName>/test/<procedure_name>.yml
```

### Stored Procedure Template

```yaml
validation:
  source:
    steps:
      run: |-
        EXECUTE <database>.<schema>.<ProcedureName> @Param1 = {0}, @Param2 = {1}
  target:
    steps:
      run: |-
        CALL <DATABASE>.<SCHEMA>.<PROCEDURENAME>({0}, {1})
  test_cases:
    # Data-driven (real values from DB)
    - [42, 19.99]            # valid customer, typical price
    - [999, 0.01]            # valid customer, minimum price
    # Edge cases & boundaries
    - [null, null]           # all nulls
    - [0, 0]                 # zeros
    # Business logic
    - [1, 100.00]            # happy path
    - [-1, 10.00]            # error path (negative ID)
```

**Placeholders:** Use `{0}`, `{1}`, `{2}`, etc. to reference test case values by position. The template engine substitutes them with properly formatted literals (strings quoted, nulls as `NULL`, etc.). Do NOT use `?` -- it will be sent literally and cause syntax errors.

### Scalar Function Template

**Important:** Always alias the SELECT expression with `AS RESULT`. Without an alias, SQL Server returns an unnamed column (empty string) while Snowflake uses the full expression as the column name — causing every comparison to fail on column name mismatch.

```yaml
validation:
  source:
    steps:
      run: |-
        SELECT <database>.<schema>.<FunctionName>({0}) AS RESULT
  target:
    steps:
      run: |-
        SELECT <DATABASE>.<SCHEMA>.<FUNCTIONNAME>({0}) AS RESULT
  test_cases:
    - [<value1>]
    - [<value2>]
```

### Procedures That Return via Temp Table or OUT Parameter

For procedures that populate a temp table or use an OUT parameter, add `capture` steps:

```yaml
validation:
  source:
    steps:
      run: |-
        EXECUTE <database>.<schema>.<ProcedureName> @Param1 = {0}
      capture:
        - "SELECT * FROM {UNQUOTED:0}"
  target:
    steps:
      run: |-
        CALL <DATABASE>.<SCHEMA>.<PROCEDURENAME>({0})
      capture:
        - "SELECT * FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))"
  test_cases:
    - ["#TempTable"]
```

### Redshift Procedures with INOUT/OUT Parameters (Temp Table Pattern)

When a Redshift procedure has an `INOUT` parameter used to return a temp table
name, and the converted Snowflake procedure has a corresponding `OUT` parameter:

- **Source (Redshift):** Can pass a literal for INOUT: `CALL proc({0}, {1}, '')`
- **Target (Snowflake):** OUT params require a variable — wrap in anonymous block
- **Capture:** Query the temp table directly (it persists in the session)

```yaml
validation:
  source:
    steps:
      run: |-
        CALL <schema>.<proc_name>({0}, {1}, '')
      capture:
        - "SELECT * FROM <temp_table_name> ORDER BY <key_column>"
  target:
    steps:
      run: |-
        BEGIN LET out_var VARCHAR := ''; CALL <DATABASE>.<SCHEMA>.<PROC_NAME>({0}::TIMESTAMP_NTZ, {1}::TIMESTAMP_NTZ, :out_var); END;
      capture:
        - "SELECT * FROM <temp_table_name> ORDER BY <key_column>"
  test_cases:
    - ["2025-01-01 00:00:00", "2025-01-31 23:59:59"]
```

Key points:
- The anonymous block `BEGIN LET ... CALL ... END;` is required because
  Snowflake OUT parameters cannot accept literal values
- Both source and target capture from the temp table directly (not RESULT_SCAN)
- Add `ORDER BY` to capture queries for deterministic row ordering
- Cast timestamp parameters with `::TIMESTAMP_NTZ` on the Snowflake side
  when the procedure expects `TIMESTAMP_NTZ` parameters

### Redshift Procedures with Scalar INOUT (Return Value Pattern)

When a Redshift procedure has an `INOUT` parameter that returns a **scalar value**
(not a temp table name), the Snowflake anonymous block returns a column named
`ANONYMOUS BLOCK` instead of the parameter name. The capture query must alias it
to match the Redshift baseline column name.

```yaml
validation:
  source:
    steps:
      run: |-
        CALL <schema>.<proc_name>({0}, {1}, 0)
  target:
    steps:
      run: |-
        BEGIN LET out_var NUMERIC := 0; CALL <DATABASE>.<SCHEMA>.<PROC_NAME>({0}, {1}, :out_var); RETURN :out_var; END;
      capture:
        - "SELECT \"ANONYMOUS BLOCK\" AS <INOUT_PARAM_NAME> FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))"
  test_cases:
    - [2024, 1]
```

Key points:
- Redshift `CALL` with a scalar INOUT returns a column named after the parameter
  (e.g., `P_RESULT`). The Snowflake anonymous block returns `ANONYMOUS BLOCK`.
- The capture query must alias `"ANONYMOUS BLOCK"` to the Redshift parameter name
  so column names match during comparison.
- Use `RETURN :out_var;` in the anonymous block to surface the scalar value.
- Match the INOUT parameter's default value type (`0` for numeric, `''` for varchar).
