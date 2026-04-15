---
name: migrate-code-unit
description: Core migration loop for a single stored procedure or function. Iterates deploy -> test -> diagnose -> fix until Snowflake output matches source.
parent_skill: migrate-objects
---

# Migrate Object

Migrate a single **stored procedure** or **function** by iterating: pre-apply rules → deploy → test → diagnose → fix → repeat.

## Step 1: Verify Object Identity

You must already know the object you are migrating (e.g., `dbo.CalculateLineTotal`).

**If not:** Load [../SKILL.md](../SKILL.md) to pick the next object.

## Step 1.5: Assess Procedure Complexity

Count the non-empty lines in the source SQL file for this object (under `source/`).

**If the source has 200+ non-empty lines**, this is a large procedure. Inform the user and offer two paths:

1. **Standard loop** — proceed with the normal deploy-test-fix cycle. Suitable if the SnowConvert output is close to correct and only needs targeted fixes.
2. **Decompose-convert-assemble** — load [references/LONG_PROCEDURE.md](references/LONG_PROCEDURE.md) for a segment-by-segment approach. Suitable if the SnowConvert output is substantially broken or the procedure is too large for the agent to reason about holistically.

**If under 200 lines**, skip this step — proceed normally.

## Step 2: Pre-Apply Known Rules

Before deploying, check the converted SQL file against known migration rules stored in Snowflake. This catches common source-to-Snowflake issues (ISNULL, GETDATE, variable binding, etc.) before they cause deployment or test failures.

### Find the SQL File

```bash
find <project_dir>/snowflake -iname "*<object_name>*" -type f
```

### Search for Applicable Rules

Read the SQL file first, then use the `search_rules` MCP tool to sync it to Snowflake and find matching rules (regex + Cortex semantic search):

Use the `search_rules` tool with:
- `file_path` = `<sql_file_path>`
- `description` = `"<your summary of the code's migration-relevant patterns>"`

**Always pass `description`** — you've already read the file, so summarize the key patterns you see (e.g., `"function using CONVERT with style codes, ISNULL, and string concatenation with +"`). This improves Cortex semantic search accuracy.

The tool outputs a JSON object with two arrays:
- `rules` — matched migration rules, sorted by priority
- `ewi_references` — SnowConvert EWI markers found in the file, with paths to reference docs

### Apply Rules

If `rules` is non-empty, spawn a **foreground subagent** (Task tool) to apply them:

```
Read and follow ../rule-engine/apply/SKILL.md

Context:
- rules: <rules JSON from search_rules>
- file_path: <sql_file_path>
- object_name: <object_name>

Apply matched rules to this file.
Report back: regex rules applied (count + replacements), AI rules applied/skipped, whether file was modified.
```

### Resolve EWI References

If `ewi_references` is non-empty, resolve them **after** rule application but **before** deployment:

1. For each entry where `reference_file` is not null, **read the reference file** and follow its fix guidance
2. For each entry where `reference_file` is null, resolve using your knowledge, then create a reference file per [../rule-engine/resolving-ewis/SKILL.md](../rule-engine/resolving-ewis/SKILL.md)
3. Remove `!!!RESOLVE EWI!!!` markers from the code as you fix each issue

If both arrays are empty, skip to Step 3.

## Step 3: Deploy

### Deploy to Snowflake

Use the `deploy` MCP tool:

- `object_name` = `<object_name>`

The tool uses the connection and database from `configure` and deploys via `scai code deploy`.

⚠️ **Do NOT deploy by executing the CREATE PROCEDURE/FUNCTION SQL directly.** Always use `deploy` to ensure proper tracking and consistency.

⚠️ **IMPORTANT:** Converted files may contain issues that need manual fixes before deployment:
1. `USE DATABASE <source_db>` at the top referencing the **source** database — remove it
2. Fully qualify the object name with the **target** database: `<TARGET_DATABASE>.<SCHEMA>.<object_name>`
3. **Variable binding in LANGUAGE SQL procedures:** Parameters and variables inside SQL statements (SELECT, INSERT, WHERE, etc.) must use `:param_name` syntax. SnowConvert often omits the colon prefix — always verify.

### If Deployment Fails

| Error | Cause | Fix |
|-------|-------|-----|
| Syntax error | Invalid SQL | Fix the code, redeploy |
| Unknown function `<name>` | Missing dependency | Deploy that function first |
| Object does not exist | Missing table/view | Deploy or check schema |
| Schema does not exist | Missing schema | `CREATE SCHEMA IF NOT EXISTS <schema>` |

1. **Read the error message** — identify the line/issue
2. **Look for EWI comments** — SnowConvert comments (`--** SSC-`) near the error indicate unconverted constructs
3. **Fix the code** — make the minimal change to resolve the error
4. **Redeploy** — repeat until deployment succeeds

> **⚠️ IMPORTANT: Always update the file in the repository**
> 
> When you make code changes, you **MUST** edit the SQL file in `snowflake/` — do NOT just deploy directly to Snowflake. If you only deploy without updating the file, your changes will be **overwritten** the next time someone deploys from the repository.
> 
> Workflow:
> 1. Edit the file in `snowflake/<type>/<schema>/<object>.sql`
> 2. Deploy using `deploy` with `object_name` = `<object_name>`

## Step 4: Run Tests

Run the test type determined by `<testing_data_source>` (passed from the parent skill). Both paths compare source output against Snowflake output — they differ only in where the test data comes from.

### If `testing_data_source == "source_database"`

```bash
scai test validate -c <CONNECTION_NAME> \
  --where "source.schema = '<schema>' AND source.name = '<name>'"
```

Read results:

```bash
cat <project_dir>/test-results/results.json
```

Each entry has `code_unit_name`, `status`, `match_type`, `error`, and `differences`. Focus on entries where `status` is not `PASS`.

### If `testing_data_source == "synthetic"`

```bash
SKILL_DIR="<absolute path to plugin/skills/migration/tools/ai-migrator>"
TARGET_DIR="<project_dir>/.scai/jobs/unit-testing/$(date +%Y%m%d_%H%M%S)_$(openssl rand -hex 2)"

uv run --project ${SKILL_DIR} run_migration_tests \
    --source <project_dir>/source \
    --converted <project_dir>/snowflake \
    --converted-with-code <project_dir>/snowflake \
    --target ${TARGET_DIR} \
    --reuse-tests <project_dir>/artifacts/unit_tests \
    --source-dialect MS_SQL_SERVER \
    --objects '["<object_name>"]'
```

Check exit code: 0 = all pass, 1 = any fail. Detailed results in `${TARGET_DIR}/progress.json`.

### Test Statuses

| Status | Meaning |
|--------|---------|
| `PASS` | Output matches |
| `FAIL` | Output differs |
| `ERROR` | Exception during execution |

If any test fails, proceed to Step 5.

## Step 5: Check for Dependency Failures

Before attempting a fix, check whether the failure is caused by a **missing dependency** (table, view, function, or procedure that hasn't been migrated yet). Fixing code won't help if the real problem is a missing object.

### Dependency Failure Patterns

Scan the `error` field from failing test entries for these patterns:

| Pattern | Likely Cause |
|---------|-------------|
| "does not exist" | Missing table, view, or schema |
| "object does not exist" | Missing dependency object |
| "unknown function" | Function not yet migrated |
| "unknown procedure" | Procedure not yet migrated |
| "invalid identifier" | Column from unmigrated table/view |
| "unresolved reference" | Unresolved cross-object reference |
| "cannot resolve" | Missing schema or object |

### If a Dependency Failure Is Detected

1. **Identify the missing object** from the error message (e.g., `Unknown function: dbo.HelperFunc`)
2. **Check if it exists in the registry:**

   Use the `testing_progress` tool with `project_dir` set to `<project_dir>` — look for the missing object in the output.

3. **Route based on status:**

| Missing object status | Action |
|-----------------------|--------|
| Not in registry / not deployed | **Skip this object.** Report: "Blocked on `<dependency>` — not yet deployed. Moving to next object." Return to [../SKILL.md](../SKILL.md) Step 2 to pick a different object. |
| Deployed but tests not passing | **Skip this object.** Report: "Blocked on `<dependency>` — deployed but not yet passing tests. Fix that object first." Return to [../SKILL.md](../SKILL.md) Step 2. |
| Deployed and tests passing | The dependency exists and works. This is **not** a dependency failure — proceed to Step 6. |

### If Not a Dependency Failure

Proceed to Step 6.

## Step 6: Decision

### All Tests Pass?

1. **Record rule successes** — if rules were applied in Step 2, record their success:

   For each rule applied in Step 2, use the `record_rule_application` tool with `rule_id` set to the rule's ID and `outcome` set to `"success"`.

2. **Extract Rule** — if code changes were made (i.e., pre-applied rules from Step 2 alone were NOT sufficient — there was at least one fix iteration), spawn a **foreground subagent** (Task tool) to extract a reusable rule:

   ```
   Read and follow DEDUCE_RULE.md

   Context:
   - mode: success
   - object_name: <object_name>
   - file_path: <sql_file_path>
   - fix_summary: <1-sentence description of what was changed and why>
   - code_diff: <before/after of the key code change>

   Summarize the fix, check for duplicate rules, and ask the user whether to save.
   Report back: whether a new rule was created (name + ID), and how many other code units it matches.
   ```

   If no code changes were made (pre-applied rules from Step 2 were sufficient with no fix iterations), skip this step.

3. **Update registry status:**

   Use the `update_testing` tool with `results_path` set to:
   - `<project_dir>/test-results/results.json` if `testing_data_source == "source_database"`
   - `${TARGET_DIR}/progress.json` if `testing_data_source == "synthetic"`

   This is required to move on to the next step.

4. **Commit (if code changed):**
   ```bash
   git add <file> && git commit -m "Fix <object_name>: <summary>"
   ```

5. **Return to caller** for next object — go back to [../SKILL.md](../SKILL.md) Step 2 (Dispatch Loop).

### Tests Fail?

**Track the iteration count** — each pass through Steps 3-6 is one iteration.

1. **Diagnose & Fix** → Load [DIAGNOSE_FIX.md](DIAGNOSE_FIX.md) (pass the current iteration number and accumulated context)
2. **Go back to Step 3** (deploy) after fixing

### Escalation Criteria

Do NOT iterate blindly. Escalate to the user when any of these conditions is met:

| Condition | Trigger | Action |
|-----------|---------|--------|
| **Same error persists** | The same primary error appears for 3 consecutive iterations | Escalate — the fix approach is not working |
| **Errors churning** | Errors keep changing but never resolve after 5 total iterations | Escalate — the problem may be structural |
| **Review loop** | The fix review agent returns NEEDS_CHANGES twice for the same root cause | Escalate — the agent cannot produce an acceptable fix |
| **Low confidence repeated** | The review agent returns LOW_CONFIDENCE on 2 consecutive iterations | Escalate — uncertain fixes are not converging |

### On Escalation

Present a structured summary to the user:

> **Escalation: `<object_name>`**
>
> **Iterations attempted:** N
>
> **Error history:**
> - Iteration 1: `<error_summary>` → Fix: `<what_was_tried>` → Result: `<outcome>`
> - Iteration 2: ...
>
> **Diagnosis findings:** `<combined_root_cause_analysis>`
>
> **Recommendation:** `<your best assessment of what's needed>`
>
> Options:
> 1. Provide guidance — I'll try a specific approach you suggest
> 2. Decompose and retry — switch to segment-by-segment conversion (see [references/LONG_PROCEDURE.md](references/LONG_PROCEDURE.md)) *(only if the object is 200+ lines and has not already been decomposed)*
> 3. Skip this object — move to the next one
> 4. Mark as needs human repair — record the context for later

After escalation, also **record the anti-pattern** by spawning a **foreground subagent** (Task tool):

```
Read and follow DEDUCE_RULE.md

Context:
- mode: anti-pattern
- object_name: <object_name>
- file_path: <sql_file_path>
- escalation_summary: <iteration history, errors encountered, what was tried, why each approach failed>

Record the anti-pattern so future objects avoid these failed approaches.
Report back: whether an anti-pattern rule was created (name + ID).
```

## Loop Until Done

Repeat Steps 3-6 per the escalation criteria above.
