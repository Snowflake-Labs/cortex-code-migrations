# Baseline Capture: From Query Logs

Use when you have SQL Server query logs (e.g., from Extended Events capture). See [references/query-logging.md](../references/query-logging.md) for how to set up query capture.

> **⚠️ SCOPE: Create test cases for ONE object (`<object_name>`) at a time.**

## Step 1: Export Query Logs

Export the unique procedure calls from your Extended Events capture as CSV. See [references/query-logging.md](../references/query-logging.md) for the export query.

## Step 2: Generate Test YAML from Execution Log

Use `scai test seed` to parse the execution log and generate YAML test files automatically:

```bash
scai test seed \
  --execution-log <path_to_execution_log.csv> \
  -s <SOURCE_CONNECTION_NAME> \
  -c <SNOWFLAKE_CONNECTION_NAME> \
  --max-cases 10
```

**Flags:**
- `-e, --execution-log` — Path to the CSV execution log file (required)
- `-s, --source-connection` — Source connection name. Uses default if not specified.
- `-c, --connection` — Snowflake connection name. Uses project/default if not specified.
- `-m, --max-cases` — Maximum test cases per procedure (default: 10)
- `-a, --append` — Append to existing test files instead of replacing them

**Output:** One YAML file per procedure at `artifacts/<target_db>/<target_schema>/<object_type>/.../<procedure_name>.yml`

To add more test cases from a different log without losing existing ones:

```bash
scai test seed --execution-log <new_log.csv> --append
```

## Step 3: Capture Baselines

```bash
scai test capture \
  -s <SOURCE_CONNECTION_NAME> \
  -c <SNOWFLAKE_CONNECTION_NAME> \
  --where "source.canonicalName ILIKE '%<schema>.<object_name>%'"
```

Baselines upload to `@<DATABASE>.VALIDATION.BASELINES` (no local copy).

## Next Step

Load [CAPTURE.md](CAPTURE.md) Step 2 onwards to verify baselines for `<object_name>`.
