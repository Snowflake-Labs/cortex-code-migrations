# Batch Apply

Apply one or more rules to several files the user names.

## Step 1: Accept Targets

Take the target list from the user:
- "Apply rule X to dbo.ProcA, dbo.ProcB" → specific named targets

## Step 2: Batch Regex-Mode Rules

For rules where `replacement_mode = 'regex'`:

1. Apply to the **first** target file
2. Show the diff as a sample:
   > **Sample diff** (`dbo.GetOrderTotal`):
   > ```diff
   > - ISNULL(@val, 0)
   > + COALESCE(@val, 0)
   > ```
   > Apply to all N files? [All / One-by-one / Cancel]
3. If **All**: apply the same regex to every target file, report summary
4. If **One-by-one**: show diff for each file, ask approval per file
5. If **Cancel**: skip this rule entirely

## Step 3: Batch AI-Mode Rules

For rules where `replacement_mode = 'ai'`:

1. Process each target file individually:
   a. Read the file content
   b. Apply the rule using `ai_context` and `examples`
   c. Show the proposed diff
   d. Ask for approval
2. After reviewing a few, offer "approve remaining":
   > Approved 3/8. Apply the same pattern to the remaining 5 without review? [Yes / Continue reviewing]

## Step 4: Track

After each successful application, record it using the `record_rule_application` tool with `rule_id` set to the rule's ID, `outcome` set to `"applied"`, and the unit's `code_unit_name` and `file_path`. Do not update `RULE_ENGINE.RULES` with SQL: the tool writes to the rule store's database and logs the event.

## Step 5: Batch Summary

> **Batch application complete for rule "EXEC to CALL":**
> - Applied to **N** of **M** code units
> - Regex mode: K auto-applied
> - AI mode: J applied (user approved), L skipped
> - Recorded each application with `record_rule_application`
>
> Test the modified objects?
>
> - **Re-validate all modified objects at once** (fast sanity check):
>   ```bash
>   scai test validate -c <SNOWFLAKE_CONNECTION_NAME> \
>     --where "source.canonicalName IN (<comma-separated-canonical-names>)"
>   ```
>   Confirm in `<metadata_database>.VALIDATION.LATEST`; the state machine picks up testing status from that table via the `testValidationResults` status source. Do not stamp `codeStatus.testing`.
> - **For any failures, run the full diagnose/fix loop per object** → [../../migrate-object/SKILL.md](../../migrate-object/SKILL.md)
