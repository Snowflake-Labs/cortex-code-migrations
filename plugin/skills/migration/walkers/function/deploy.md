# Deploy (function)

Pushes this function onto the Snowflake common catalogs. With a source it runs
after `captureBaseline` and before `runTests`; a source-less helper deploys
right after convert, then goes to `verify`. Run the step's `run` as given
(op `deploy`); the active bindings substitute `<%token%>`.

## Converted-file rules

Leave the file's leading `USE DATABASE` and its converted qualifiers
(`<%token%>.dbo.X`, `TaskTracker.dbo.X`, `schema.X`) as they are; the tool
comments the `USE` out after substitution. Never write the SNAP / configure
database name into the file. Keep original source comments when editing.

## If deploy fails

Do what `fix` says. One exception: an error caused by breaking a rule above →
make that minimal edit and re-run `run`. Otherwise do not rewrite or
redeploy-loop here. A live sandbox yaml does not count as deployed.
