---
name: migrate-objects
description: Deploy and validate all object types (tables, views, functions, procedures) in dependency order. Triggers: deploy objects, migrate objects, deploy tables, deploy views, migrate functions, migrate procedures.
parent_skill: migration
---

# Migrate Objects

## Step 1: Configure Session

Call `configure()` to retrieve the current configuration.

Check the returned values for `snowflake_connection`, `source_connection`, and `snowflake_database`:

- **All three set** → confirm them with the user (e.g. "Using snowflake_connection=X, source_connection=Y, deploying to database Z — correct?"). If the user wants changes, call `configure` with the updated values.
- **Any missing** → ask the user for the missing values, then call `configure` with all of them.

Before calling `configure` with the final values, verify the target database exists:

```sql
SHOW DATABASES LIKE '<snowflake_database>';
```

If the database does not exist, create it:

```sql
CREATE DATABASE <snowflake_database>;
```

Then proceed with the `configure` call.

Verify the validation framework is set up (needed for functions/procedures):

```sql
SHOW SCHEMAS LIKE 'VALIDATION' IN DATABASE <TARGET_DATABASE>;
```

If VALIDATION schema doesn't exist, load [setup/SKILL.md](setup/SKILL.md).

## Step 2: Testing Preferences (Functions / Procedures)

Check the `configure()` response for `testing_data_source`.

If not yet configured → ask the user

> Does your source database have representative data for testing?
>
> - **A) Yes** — we'll capture baselines from your source DB
> - **B) No, generate synthetic data** — AI Migrator creates test data

Then call `configure(testing_data_source="source_database")` or `configure(testing_data_source="synthetic")` to persist the choice.

## Step 3: Batch Test Case Generation (Optional)

Ask the user:

> Would you like to **generate test cases in batch** for the next 5 functions and procedures in this wave before starting the migration loop?
>
> This spawns parallel agents to generate test cases and capture source baselines for those function/procedure at once, so they're ready when the object's turn comes.
>
> 1. **Yes — batch capture** (recommended for large waves)
> 2. **No — capture per-object** (baselines will be captured one at a time during migration)

If the user chooses **batch capture**, load [baseline-capture/BATCH.md](baseline-capture/BATCH.md) and wait for it to complete before proceeding.

## Step 4: Dispatch Loop

**IMPORTANT** Run `/compact` between objects to free up context. **IMPORTANT**

Call `next_object()`. It returns JSON with a `status` field and, when `ready`, a `name` and `type`.

| Status | Type | Action |
|--------|------|--------|
| `tables_pending` | — | Load [actions/migrate_table.md](actions/migrate_table.md) |
| `ready` | `view` | Load [actions/migrate_view.md](actions/migrate_view.md) |
| `ready` | `function` / `procedure` | Load [actions/migrate_function.md](actions/migrate_function.md) |
| `done` | — | Go to Step 4. |

After each object completes, call `next_object()` again and repeat.

## Step 5: Report

Call `migration_status()` and present the final summary. If the wave is complete, the next `configure()` call will auto-advance to the next wave.
