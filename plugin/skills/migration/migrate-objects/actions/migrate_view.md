# Action: Migrate View

## On Entry

Tell the user which view is being worked on:
> **Migrating view: `<name>`.** I'll apply any known fix rules, deploy it to Snowflake, and validate it returns matching data.

> **Entry:** Called from the parent dispatch loop with a specific view (`name` from `next_object()`). If you don't have one, call `next_object()`.

## Step 1: Read the Converted SQL

```bash
find <project_dir>/snowflake -ipath "*view*" -iname "*<view_name>*" -type f
```

Read the file content.

## Step 2: Apply Rules and Resolve EWIs

If the file contains `!!!RESOLVE EWI!!!` markers:
- Comment out the `!!!RESOLVE EWI!!!` wrapper but keep the actual SQL
- Replace `!!!RESOLVE EWI!!! /*** SSC-EWI-XXXX ... ***/!!!` with `--** SSC-EWI-XXXX - REVIEWED **`

Search for matching rules:

```
search_rules(file_path=<sql_file_path>)
```

For each matched rule where `replacement_mode = 'regex'`:
- Apply the find/replace mechanically
- Write the updated file

For rules where `replacement_mode = 'ai'`:
- **Present to the user for approval.** Read the rule's `ai_context`, show the proposed fix, apply only if approved.

## Step 3: Deploy

```
deploy(object_name="<schema>.<view_name>")
```

If it fails, go back to **Step 1** (read, fix, redeploy). Continue until it deploys successfully.

## Step 4: Validate

Spawn a **foreground subagent** (Task tool) to compare source and Snowflake data:

**IMPORTANT** DO NOT run the validation yourself to avoid polluting your context window. **IMPORTANT**

```
Compare the view <schema>.<view_name> between source and Snowflake.

Context:
- View: <schema>.<view_name>
- All connections and database are configured via MCP (`configure()`)

Validation steps:
1. Row count: run `query_source("SELECT COUNT(*) FROM <source_schema>.<view_name>")` and compare with `SELECT COUNT(*) FROM <TARGET_DATABASE>.<SCHEMA>.<VIEW_NAME>` on Snowflake.
2. Spot check: run `query_source("SELECT TOP 10 * FROM <source_schema>.<view_name>")` and compare with `SELECT * FROM <TARGET_DATABASE>.<SCHEMA>.<VIEW_NAME> LIMIT 10` on Snowflake.
3. Report: row count match (yes/no), any column or data differences found.
```

If validation fails, report the differences to the user.

## Step 5: Return

Tell the user:
> **View `<name>` deployed** in `<duration>`. Validation `<passed/failed>`: `<row_count>` rows.
> *If differences:* `<differences>`.
> AI-mode rules applied: `<list or "none">`.

Return control to the parent dispatch loop.
