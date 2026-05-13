# Action: Migrate Tables

## On Entry

Tell the user:
> **Deploying tables.**
>
> Here's what I'll do:
> 1. Deploy every table in wave `<WAVE>` to Snowflake in one batch.
> 2. For any failures, apply known migration rules and retry up to 3 times before asking for help.
> 3. Migrate data from source into the deployed tables (runs in the background).
> 4. Validate row counts against the source baseline.
>
> Deploy itself is usually fast. Data migration scales with row count and can take longer. The terminal will be quiet between phases.

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
2. Resolve any `!!!RESOLVE EWI!!!` markers (comment out the wrapper, keep the SQL).
3. Call `search_rules(file_path=<sql_file_path>)`; apply regex-mode rules mechanically. Present AI-mode rules to the user for approval.
4. Re-deploy: `deploy(object_name="<schema>.<table_name>")`.
5. If it still fails, repeat from step 1. After 3 failed attempts, ask the user for help (show the current error and what was tried). Apply the user's suggestion and retry.

Report back: success/failure, what was fixed, final deploy status.
```

## Step 3: Migrate Data

```
migrate_data()
```

If `migrate_data()` returns `status: "error"` with a message about data migration not being configured, load `../../setup/data-migration/SKILL.md` to complete the one-time setup, then retry `migrate_data()`.

On success, it returns a `job_id` immediately; the migration runs in the background via the SPCS orchestrator and local worker.

Poll with `migrate_data_status()` until `status` is `"completed"` or `"failed"`. The response includes per-table progress in `progress.output` (parsed JSON from scai). Report any errors to the user.

## Step 4: Validate Data

Load `../../validate-objects/SKILL.md` to validate migrated data against the source.

## Step 5: Report

Tell the user. Fill placeholders from the JSON envelope returned by `deploy(...)` and the data-migration / validate phases.
> **Tables complete** in `<duration>`. `<deployed>/<total>` deployed, `<data_migrated>` with data migrated (`<row_counts>`), `<validated>/<total>` validated.
> *If `failed > 0`:* `<failed_count>` still failing. First 5: `<list>`. Most common error: `<top_error>`.
> AI-mode rules applied: `<list or "none">`.

Return control to the parent skill (`../SKILL.md`).
