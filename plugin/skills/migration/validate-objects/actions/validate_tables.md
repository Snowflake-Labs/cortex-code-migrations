# Action: Validate Tables

Validate migrated table data between source and Snowflake using cloud validation.

> **Scope:** All tables included in `.scai/settings/data-validation-config.json`.

## Step 1: Start Validation

```
validate_data()
```

If `validate_data()` returns `status: "error"` with a message about data validation not being configured, load `../../setup/data-validation/SKILL.md` to complete the one-time setup, then retry `validate_data()`.

On success, it returns a `job_id` immediately — validation runs in the background via the SPCS validation service and local worker.

## Step 2: Poll for Completion

Poll with `validate_data_status()` until `status` is `"completed"` or `"failed"`. The response includes per-table progress in `progress.output` (parsed JSON from scai). Report any errors to the user.

When the job completes, inspect:
- `status` — `"completed"` or `"failed"`
- `result.output` — final per-table validation results (parsed JSON)
- `error` — present only when `status == "failed"`

## Step 3: Report

Summarize from the final `validate_data_status()` response:

- Total tables validated (passed / failed)
- Per-table results: schema match, metrics match, row-level match (if enabled)
- Any mismatches or errors found

If any tables failed validation, report the errors to the user with details on which checks failed and for which tables.

Return control to the parent skill (../SKILL.md).
