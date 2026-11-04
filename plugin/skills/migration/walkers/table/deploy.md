# Deploy (table)

Runs after `deployCommonSandbox`, before `migrateData`. Run the step's `run` as
given (op `deploy`): `scai code deploy` onto the Snowflake common catalogs with
the active bindings.

## Converted-file rules

- Leave a leading `USE DATABASE`; the tool comments it out.
- Keep the converted qualifier (`<%token%>.dbo.X`, `TaskTracker.dbo.X`,
  `schema.X`); tokens resolve at deploy. Never write the SNAP / configure
  database name into the file.
- Keep the source comments (synopsis, author, change log, …) when editing.
- Edit the file in `snowflake/`, then redeploy with the tool; a change made only
  in Snowflake is overwritten by the next deploy.

## If deploy fails

Do what `fix` says. One exception: an error caused by breaking a rule above
(read it with the `--** SSC-` EWI comments near it) → make that minimal edit and
re-run `run`. Otherwise do not rewrite the table here or loop redeploys; never
`CREATE SCHEMA`, deploy another object, or fall back to `sql_execute`.
