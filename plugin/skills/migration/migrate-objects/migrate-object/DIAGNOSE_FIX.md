# Diagnose & Fix

Analyze test failures and fix them. Uses error history from previous iterations, searches for relevant rules by error text, spawns investigation agents in parallel, then applies fixes with confidence-gated review.

## Step 1: Accumulate Iteration Context

Before investigating, gather context from all previous iterations of this fix loop. This prevents retrying approaches that already failed.

**Build the iteration log** by recalling from the current session:

- **Iteration number** — which pass through the deploy-test-fix loop is this?
- **Previous errors** — what errors/failures were seen in earlier iterations?
- **Previous fix attempts** — what code changes were made, and what was the outcome?
- **Approaches to avoid** — any fix strategies that were tried and failed?

Structure this as:

```
Iteration: <N>

Previous attempts:
- Iteration 1: <what was tried> → <outcome (error text or test diff summary)>
- Iteration 2: <what was tried> → <outcome>
...

Approaches to avoid:
- <description of failed approach and why it didn't work>
```

**If this is iteration 1**, skip this step — there is no prior context.

## Step 2: Get Current Failure Context

Read local test results for the failing object:

```bash
cat <project_dir>/test-results/results.json
```

Filter entries where `code_unit_name` matches `<object_name>` and `status` is `FAIL` or `ERROR`.

Gather from each failing entry:
- `params_hash` and `params` — input parameters
- `error` — error message (if ERROR status)
- `differences` — human-readable diff descriptions
- `in_memory_diff.cell_diffs` — exact cell-level differences (row, column, baseline value, actual value)
- `in_memory_diff.row_counts` — baseline vs actual row counts
- `in_memory_diff.summary_stats` — per-column aggregate mismatches

## Step 2.5: Detect Special Cases

Before the general rule search and investigation swarm, check whether this failure matches a **known error pattern**, involves **dynamic SQL**, or falls under a **documented troubleshooting scenario**. These checks can short-circuit or enrich the diagnosis.

### Check for Known Errors

Scan the error messages and diff descriptions from Step 2 against the patterns in [references/KNOWN_ERRORS.md](references/KNOWN_ERRORS.md).

**If a match is found:** Apply the documented fix directly — skip the investigation swarm and go straight to Step 6 (Apply Fix).

Known patterns include:
- Error 002232 (invalid virtual column expression) — inline UDF logic
- Mixed-quote PIVOT column identifiers — fix quoting
- All-rows-different due to column ordering, case, or formatting — reorder/alias/cast
- Decimal/rounding and timestamp precision differences — normalize or flag

### Check for Dynamic SQL Issues

If the error message or the converted SQL file contains any of these patterns:
- `EXECUTE IMMEDIATE`
- `IDENTIFIER(`
- `sp_executesql`
- `EXEC(`
- `EXEC @`

Then the failure likely involves dynamic SQL conversion. Read the canonical dynamic SQL conversion reference at [../../rule-engine/setup/resolving-ewis/reference/SSC-EWI-0030.md](../../rule-engine/setup/resolving-ewis/reference/SSC-EWI-0030.md) and pass the relevant conversion patterns into the investigation agents (Step 4) as additional context. This reference covers:
- Variable transformation and identifier quoting
- `sp_executesql` to `EXECUTE IMMEDIATE ... USING` conversion
- System catalog mappings (e.g., `sys.tables` to `INFORMATION_SCHEMA`)
- Temp table transformation in dynamic context
- Handling of commented-out dynamic SQL (SnowConvert `!!!RESOLVE EWI!!!` markers)

### Check Troubleshooting Reference

If neither of the above matched, also consult [../references/troubleshooting.md](../references/troubleshooting.md) for common test failure scenarios (wrong schema prefix, missing base data, connection issues, etc.) that may explain the failure without needing the full swarm.

---

## Step 3: Search Rules by Error Text

Before spawning the investigation swarm, check if a known rule already addresses this error. This can short-circuit the diagnosis entirely.

Collect the primary error messages from Step 2 (the `error` field from ERROR entries, or the first `differences` entry from FAIL entries). Use `find_similar_rules` with the error text as the query:

Use the `find_similar_rules` tool with `query` set to `"<primary_error_message_or_diff_description>"`.

**If a matching rule is found:**

| Rule's `replacement_mode` | Action |
|---------------------------|--------|
| `regex` | Apply `replacement_find` / `replacement_replace` mechanically to the SQL file. Skip to Step 6 (Apply Fix). |
| `ai` | Read the rule's `ai_context` and `examples`. Pass them into the investigation agents (Step 4) as additional context to guide diagnosis. |

After applying a matched rule (regex mode), record the application: use the `record_rule_application` tool with `rule_id` set to the matched rule's ID, `outcome` set to `"applied"`, and `code_unit_name` set to `<object_name>`.

**If the rule's name starts with `[AVOID]`:** This is a negative rule (anti-pattern). Note the `ai_context` — it describes an approach that was tried before and failed. Add it to the "Approaches to avoid" list from Step 1.

**If no matching rule is found**, proceed to Step 4.

## Step 4: Spawn Investigation Swarm

Launch 3 agents **in parallel** to investigate different causes. Each agent receives the iteration context from Step 1 so it can avoid repeating failed approaches.

### Agent 1: Code Comparison

```
Investigate test failures for <object_name> by comparing SOURCE vs TARGET code.

Source (truth): <source_file_path>
Snowflake target: <target_file_path>

Compare:
1. Parameter handling - same names, types, defaults?
2. Business logic - IF/CASE branches match?
3. Table/view references - correct schema prefixes?
4. Function calls - source functions converted correctly?
5. Return values - same columns, same order?

Look for SnowConvert EWI comments (--** SSC-) indicating conversion issues.

Failing tests context:
<failure_details>

Iteration context (if iteration > 1):
<iteration_log_from_step_1>

Matching rules context (if any from Step 3):
<rule_ai_context_and_examples>

IMPORTANT: Do NOT suggest approaches listed under "Approaches to avoid".

Output: List specific code differences that could cause the failures.
```

### Agent 2: Data Investigation

```
Investigate test failures for <object_name> by checking UNDERLYING DATA.

Referenced tables/views in the code:
<list_of_tables>

For each table, check:
1. Does it exist in Snowflake with correct schema prefix?
2. Row counts match between source baseline and Snowflake?
3. Any data type differences that could affect results?

Failing tests context:
<failure_details>

Iteration context (if iteration > 1):
<iteration_log_from_step_1>

IMPORTANT: Do NOT suggest approaches listed under "Approaches to avoid".

Run queries to verify data exists:
- SELECT COUNT(*) FROM <prefix><schema>.<table>
- Sample rows if needed

Output: List any data issues that could cause the failures.
```

### Agent 3: Output Analysis

```
Investigate test failures for <object_name> by analyzing TEST OUTPUT DIFFERENCES.

Failing test details:
<for each failure: params_hash, input_params, expected_output, actual_output>

Analyze:
1. Row count differences - missing rows? extra rows?
2. Column value differences - which columns differ? by how much?
3. Data type/format differences - precision, date formats, case?
4. Pattern across failures - same issue in all, or different issues?

Iteration context (if iteration > 1):
<iteration_log_from_step_1>

IMPORTANT: Do NOT suggest approaches listed under "Approaches to avoid".

Output: 
- What specifically differs (columns, values, row counts)
- Pattern analysis (is it the same root cause across all failures?)
- Likely root cause category (logic bug, precision issue, data issue, etc.)
```

## Step 5: Synthesize & Identify Root Cause

After agents complete, combine findings:

| Finding | Root Cause | Action |
|---------|------------|--------|
| Code logic differs | Conversion bug | Fix the code |
| Missing schema prefix | Wrong table reference | Add prefix |
| Function not converted | T-SQL function used | Replace with Snowflake equivalent |
| Data missing | Table not synced | Sync data or check schema |
| Precision differs | Type mismatch | Add explicit CAST |

For common issues and their solutions, also consult [../references/troubleshooting.md](../references/troubleshooting.md).

## Step 6: Apply Fix

1. **Open the Snowflake SQL file:**
   ```bash
   find <project_dir>/snowflake -iname "*<object_name>*" -type f
   ```

2. **Make the minimal change** to fix the root cause

   If the fix was informed by a rule from Step 3, record the application: use the `record_rule_application` tool with `rule_id` set to the rule's ID and `outcome` set to `"applied"`.

3. **Redeploy** → Return to [SKILL.md](SKILL.md) Step 3

4. **Retest** → Return to [SKILL.md](SKILL.md) Step 4

### Common Fixes

Query the rule engine for known fix patterns: `search_rules(description="<description of the root cause and fix needed>")`

## Step 7: Fix Review Agent

After making the fix, spawn a review agent to verify the change:

```
Review the code fix for <object_name>.

Original issue:
<root_cause_from_diagnosis>

File changed: <file_path>

Changes made:
<diff or description of changes>

Source (truth): <source_file_path>
Snowflake target (fixed): <target_file_path>

Iteration: <N> of fix loop

Checklist:
1. Does the fix address the specific root cause identified?
2. Are there any unrelated changes that should be reverted?
3. Is the SQL syntactically valid (no unclosed parens, missing semicolons)?
4. Are all schema references correct for the target environment?
5. Does the fixed code match the source logic for this specific area?
6. Are there any other instances of the same issue in the file that should also be fixed?
7. Could this fix introduce any new issues?
8. Are there any tests hardcoded?
9. Has this same approach been tried before and failed? (Check iteration context)

Output ONE of:
- HIGH_CONFIDENCE: Fix directly addresses root cause, syntactically correct, no regressions expected. Ready to deploy.
- LOW_CONFIDENCE: Fix is plausible but uncertain (e.g., edge cases unclear, partial fix, or similar approach partially failed before). List specific concerns. Deploy but flag for user review.
- NEEDS_CHANGES: List what needs to be fixed before deploying.
```

If review agent returns **NEEDS_CHANGES**, address the feedback and re-run the review. **Max 5 review iterations** — if the review agent still returns NEEDS_CHANGES after 5 rounds, present the current state to the user and ask for guidance.

**HIGH_CONFIDENCE** → Proceed to deploy (return to [SKILL.md](SKILL.md) Step 3).

**LOW_CONFIDENCE** → Present the fix and the reviewer's concerns to the user:

> The review agent flagged this fix as **low confidence**:
> - Concerns: `<reviewer_concerns>`
> - Changes: `<diff summary>`
>
> Deploy anyway, or adjust the fix first?

If user approves → deploy. If user wants changes → revise and re-run review.

**NEEDS_CHANGES** → Address the feedback and re-run the review.

## After Review

1. Redeploy → Return to [SKILL.md](SKILL.md) Step 3
2. Retest → Return to [SKILL.md](SKILL.md) Step 4
3. If still failing → repeat from Step 1
4. If all pass → done
