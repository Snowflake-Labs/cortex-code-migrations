# Deploy

Guide for the `deploy` task — common catalogs. The machine invokes this to
push converted SQL to the project's Snowflake database.

## Call the tool

Use the `deploy` MCP tool with `object_name` = `<object_name>` (or the
`invocation` from `next_task`).

The tool uses the connection and database from `configure` and deploys via `scai code deploy`.
Do **not** pass `--profile` or `--database-bindings` yourself — the tool injects them.

**`deploy` is Snowflake-only**, onto the common catalogs. Common-catalog deploy
injects `--database-bindings` from this walker's active yaml so `<%token%>`
substitutes; `-d` only when convert wrote no bindings file.

**Do NOT deploy by executing the CREATE PROCEDURE/FUNCTION SQL directly.** Always use the `deploy` tool to ensure proper tracking and consistency.

## Pre-deploy file checks

Converted files may contain issues that need manual fixes before deployment:

1. Leave a leading `USE DATABASE` in the file. The tool comments it out after substituting bindings (or after `-d` when convert wrote no yaml).
2. Keep the converted qualifier (`<%token%>.dbo.X`, `TaskTracker.dbo.X`, or `schema.X`). `deploy` injects `--database-bindings` from the session's active yaml so tokens resolve at deploy time. Do **not** write the SNAP / configure database name into the file. `-d` is only used when convert wrote no bindings file.
3. **Variable binding in LANGUAGE SQL procedures:** Parameters and variables inside SQL statements (SELECT, INSERT, WHERE, etc.) must use `:param_name` syntax. SnowConvert often omits the colon prefix — always verify.
4. **Preserve original comments:** When editing or rewriting converted SQL, always retain the original source code comments (synopsis, metadata, author, archive, change log, etc.). These comments document provenance and authorship — do not strip them during conversion or fixes.
5. **A `DEFAULT` on an output argument:** Snowflake supports optional arguments (`HISTORICALPERIODS INT DEFAULT 12`) and, in `LANGUAGE SQL` procedures, output arguments (`TARGETID OUT INT`) — but not both on one argument. `TARGETID OUT INT DEFAULT NULL` fails to compile; delete the `DEFAULT` from that argument and leave the signature otherwise alone. The other arguments keep their defaults, `OUT` stays, and callers keep their calling convention — do not bundle the outputs into a `RETURNS OBJECT`, return a result set, or drop the output arguments, all of which change every call site to work around a one-token defect.

## If deployment fails

| Error | Cause | Fix |
|-------|-------|-----|
| Syntax error | Invalid SQL | A pre-deploy check above, if one matches — otherwise `transition_status(outcome='failed', error='sql')` and let the fix loop take it |
| `unexpected 'DEFAULT'` | An output argument carries a default | Pre-deploy check 5 — delete that argument's `DEFAULT`, nothing else |
| Unknown function `<name>` | Missing dependency | Deploy that function first |
| Object does not exist | Missing table/view | Deploy or check schema |
| Schema does not exist | Missing schema | `CREATE SCHEMA IF NOT EXISTS <schema>` |
| `Error [XXXXXXX]: ...` | Planner error | Try to fix the SQL and redeploy; if the error persists, do **not** use `sql_execute` — leave the task unstamped if a known dependency is not ready (the walk will show `blockedOn`), or `error='sql'` / escalate if a person must register or stub a missing object |

1. **Read the error message** — identify the line/issue.
2. **Look for EWI comments** — SnowConvert comments (`--** SSC-`) near the error indicate unconverted constructs.
3. **Fix it only when it is one of the pre-deploy checks above** — those are known, bounded edits. Make the minimal change and redeploy.
4. **Otherwise stamp `outcome='failed', error='sql'`** — `applyRules` → `fixCode` owns converted-SQL defects, carries the diagnosis guidance, and turns the fix into a rule other objects reuse. Rewriting the object here skips all three, and a redeploy loop on a real conversion defect churns the file instead of fixing it.

## File-update rule

When you make code changes, you **MUST** edit the SQL file in `snowflake/` — do NOT just deploy directly to Snowflake. If you only deploy without updating the file, your changes will be **overwritten** the next time someone deploys from the repository.

Workflow:
1. Edit the file in `snowflake/`
2. Deploy using `deploy` with `where`: `object_id IN (<your_object_ids>)`

## After deployment

Re-pull `migration_status(mode="my_objects_summary")` (or `next_task` with the object's
`object_id`). If deployment **failed** with anything the pre-deploy checks do not cover, call
`transition_status(status='advance', task='deploy', outcome='failed')` with the appropriate
`error` code. See [Advancing and reporting](../SKILL.md#advancing-and-reporting).
