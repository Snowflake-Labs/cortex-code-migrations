# Action: Migrate Tables

Deploy tables to Snowflake, migrate data from source, and validate row counts.

> **Scope:** Tables only within the current wave.

## Step 1: Deploy All Tables

Deploy all tables in the current wave in one batch. Use the current `wave` if present (use `configure()` if needed):

```
deploy(where="source.objectType = 'table' AND planning.wave = '<WAVE>'")
```

## Step 2: Fix Failed Tables

For each table that failed to deploy, follow these steps:

```
Fix and redeploy the failed table <schema>.<table_name>.

Context:
- Table: <schema>.<table_name>
- Deploy error: <error_message>
- All connections and database are configured via MCP (`configure()`)

Steps:
1. Find and read the converted SQL file under the project's snowflake/ directory.
2. Resolve any `!!!RESOLVE EWI!!!` markers — comment out the wrapper, keep the SQL.
3. Call `search_rules(file_path=<sql_file_path>)` — apply regex-mode rules mechanically. Present AI-mode rules to the user for approval.
4. Re-deploy: `deploy(object_name="<schema>.<table_name>")`.
5. If it still fails, repeat from step 1. After 3 failed attempts, ask the user for help — show the current error and what was tried. Apply the user's suggestion and retry.

Report back: success/failure, what was fixed, final deploy status.
```

## Step 3: Migrate Data

Start data migration for all deployed tables:

```
migrate_data()
```

This returns a `job_id` immediately — the migration runs in the background. Poll for completion:

```
migrate_data_status()
```

Keep polling until `status` is `"completed"` or `"failed"`. While `"running"`, `elapsed_seconds` shows how long it has been going.

This defaults to tables where `cloudStatus.deployment.status = 'completed'` and `extensions.dataMigration.status` is NULL or failed. Each table is automatically marked `in_progress` → `completed` / `failed`.

After each successful migration, `migrate_data` automatically validates row counts by comparing the source and Snowflake tables. The completed result includes a validation summary with per-table source vs Snowflake row counts and any mismatches.

If any tables fail data migration or have row count mismatches, report the errors to the user.

## Step 4: Report

Summarize:
- Total tables deployed (succeeded / failed)
- Total tables with data migrated (with row counts)
- Any tables still failing (with error details)
- Any AI-mode rules that were applied or skipped

Return control to the parent skill (../SKILL.md).
