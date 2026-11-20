# Deploy (common catalogs)

A procedure with a source deploys here last, after sandbox `runTests` and `deployCommonSandbox`; a source-less one right after `createIsolatedSandbox`, then `verify`.

Run the step's `run` as given (op `deploy`) — common catalogs, not the sandbox; the active bindings substitute `<%token%>`. Sandbox ops: [create-isolated-sandbox.md](create-isolated-sandbox.md#deploy-modes).

## Pre-deploy file checks

The only edits allowed outside the fix loop (also apply before `sandbox_object`). Edit the file in `snowflake/`, then deploy — a Snowflake-only change is overwritten on the next deploy.

1. Leave a leading `USE DATABASE`; the tool comments it out after substituting bindings.
2. Keep the converted qualifier (`<%token%>.dbo.X`, `TaskTracker.dbo.X`, `schema.X`). Never write the SNAP / configure database name into the file.
3. LANGUAGE SQL procedures: parameters/variables inside SQL statements need `:param_name`; SnowConvert often omits the colon.
4. Preserve original source comments (synopsis, author, change log, …).
5. `OUT` argument with a `DEFAULT` (`TARGETID OUT INT DEFAULT NULL`, error `unexpected 'DEFAULT'`): Snowflake allows defaults or `OUT`, not both. Delete that argument's `DEFAULT` only — keep `OUT` and the other defaults; do not switch to `RETURNS OBJECT`, a result set, or drop the outputs.

## If deployment fails

Do what `fix` says. One exception: an error matching a pre-deploy check → minimal edit, re-run `run`. Otherwise do not rewrite the object here, loop redeploys, `sql_execute` it, or deploy / `CREATE SCHEMA` for another object. EWI comments (`--** SSC-`) near the error mark unconverted constructs — include them in the evidence.
