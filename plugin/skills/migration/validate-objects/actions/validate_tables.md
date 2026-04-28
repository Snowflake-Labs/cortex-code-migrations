# Action: Validate Tables

Validate migrated table data between source and Snowflake using cloud validation.

> **Scope:** All tables included in `.scai/settings/data-validation-config.json`.

## Step 1: Run Validation

```
validate_data()
```

This call **blocks until validation is complete** — `scai data cloud-validate --start-worker` runs in watch mode and exits only when all tables have been processed. The response already contains the final result; no polling is needed.

Check the returned `status`:

- `"completed"` — validation finished; inspect `output` for per-table results.
- `"failed"` — validation encountered an error; inspect `error` and `output` for details.

## Step 2: Report

Summarize from the `validate_data()` response:

- Total tables validated (passed / failed)
- Per-table results: schema match, metrics match, row-level match (if enabled)
- Any mismatches or errors found

If any tables failed validation, report the errors to the user with details on which checks failed and for which tables.

Return control to the parent skill (../SKILL.md).
