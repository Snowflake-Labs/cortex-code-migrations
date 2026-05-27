# Action: Validate Tables

Validate migrated table data between source and Snowflake using cloud validation.

> **Scope is set per call.** `validate_data(mode="run")` validates **every** table listed in the workflow file produced by setup. Pass a `where` filter to setup that matches exactly the tables you intend to validate.

## Step 1: Generate the validation workflow

Translate the user's choices into a `validate_data(mode="setup", ...)` call.

For the `where` filter, in order of preference:

1. **You already have the claimed object IDs** (e.g. from a `transition_status(status="begin", ...)` response). Use them verbatim — `where="id IN ('<id1>', '<id2>', ...)"`.
2. **Specific table names.** `where="source.canonicalName IN ('dbo.Customers', 'dbo.Orders')"`.
3. **A whole schema or wave.** `where="source.schema = 'dbo'"` or `where="planning.wave = 'wave_1'"`.
4. **All deployed tables.** Omit `where`. Only do this if the user explicitly asked to validate everything.

If you're unsure of the registry filter columns, run `scai code where` for the syntax reference.

```
validate_data(
  mode="setup",
  where="<registry filter>",
  schema_validation=true | false,    # optional; persisted as a session default
  metrics_validation=true | false,   # optional; persisted as a session default
  row_validation=true | false,       # optional; persisted as a session default
  continue_on_failure=true | false,  # optional; persisted as a session default
)
```

If setup returns `status: "error"` with a message about validation not being configured, load `../../setup/data-validation/SKILL.md` to complete the one-time infrastructure setup, then retry.

## Step 2: Review and edit the workflow

The setup response contains:

- `workflow_path` — `artifacts/data_validation/workflows/<hash>.yaml`. Same `where` always maps to the same file; distinct filters produce distinct files.
- `regenerated` — `false` means scai re-used an existing file.
- `defaults` — the merged session defaults applied to this call.
- `applied_overrides` — toggle values that were patched into `validation_configuration`.
- `edit_hints` — the agent should walk through these.

If you need per-table overrides (column_mappings, index_column_list, where_clause for row filters, target_database/target_schema/target_name for renamed tables), edit the file directly — see `../../setup/data-validation/references/workflow-config-reference.md` for the field reference.

Show the user the final `tables:` list and validation toggles before running.

## Step 3: Run validation

```
validate_data(mode="run", workflow_path="<path from setup>")
```

On success, returns a `job_id` immediately — validation runs in the background via the SPCS validation service and a local Data Exchange Worker.

## Step 4: Poll for completion

Poll with `validate_data_status()` until `status` is `"completed"` or `"failed"`. The response includes per-table progress in `progress.output` (parsed JSON from scai). Report any errors to the user.

When the job completes, inspect:
- `status` — `"completed"` or `"failed"`
- `result.output` — final per-table validation results (parsed JSON)
- `error` — present only when `status == "failed"`

## Step 5: Report

Summarize from the final `validate_data_status()` response:

- Total tables validated (passed / failed)
- Per-table results: schema match, metrics match, row-level match (if enabled)
- Any mismatches or errors found

If any tables failed validation, report the errors to the user with details on which checks failed and for which tables.

## Step 6: Offer to Suspend Infrastructure (Cost Saving)

The wave's data work is now complete. Ask the user (default Yes):

> Suspend the orchestrator and compute pool now to stop accruing SPCS / warehouse cost?
>
> 1. **Yes (default)** — load `../../data-infrastructure/teardown/SKILL.md` to suspend the service, suspend the compute pool, and stop the local worker. The next `migrate_data()` / `validate_data()` call will auto-resume the service.
> 2. **No, keep running** — useful if you're starting the next wave immediately and want to avoid the ~60s warm-up.

If the user picks **Yes** (or doesn't respond), load the teardown sub-skill, then return here.

Return control to the parent skill (../SKILL.md).
