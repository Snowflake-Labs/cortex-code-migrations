# SQL Query Reference

Queries against the `VALIDATION` schema created by `scai test validate --create-schema`.

## Validation Results

```sql
-- Summary by code unit
SELECT * FROM VALIDATION.SUMMARY ORDER BY pass_rate DESC;

-- Latest result per test case
SELECT * FROM VALIDATION.LATEST ORDER BY code_unit_name;

-- Failures with details
SELECT * FROM VALIDATION.FAILURES;
```

## Investigation

```sql
-- Failures for a specific code unit
SELECT code_unit_name, params_hash, status, baseline_rows, actual_rows, error_message
FROM VALIDATION.LATEST
WHERE code_unit_name = '<object_name>'
  AND status IN ('FAIL', 'ERROR');

-- All results history for a code unit
SELECT code_unit_name, params_hash, status, match_type, error_message, executed_at
FROM VALIDATION.RESULTS
WHERE code_unit_name = '<object_name>'
ORDER BY executed_at DESC;
```

## Local Results (Preferred)

The agent should prefer reading local results from `test-results/results.json` for detailed cell-level diffs that are not stored in Snowflake:

```bash
cat <project_dir>/test-results/results.json
```

Each entry contains:
- `code_unit_name`, `params_hash`, `status`, `match_type`, `error`
- `differences` — human-readable diff descriptions
- `in_memory_diff` — structured cell-level diffs with `row_counts`, `summary_stats`, `cell_diffs`

## Available Views

| View | Purpose |
|------|---------|
| `VALIDATION.SUMMARY` | Pass/fail counts per code unit |
| `VALIDATION.LATEST` | Latest result per test case |
| `VALIDATION.FAILURES` | Failed/errored tests with details |
