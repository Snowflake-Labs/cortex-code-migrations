# Deploy (view)

Pushes the converted view to the common Snowflake catalogs. Runs after
`deployCommonSandbox`, before `validateView`. Run the step's `run` as given
(op `deploy`); the active bindings substitute `<%token%>`.

## Converted-file rules

Before (re)deploying an edited file in `snowflake/`:

1. Leave a leading `USE DATABASE`; the tool comments it out.
2. Keep the converted qualifier (`<%token%>.dbo.X`, `TaskTracker.dbo.X`, `schema.X`).
   Never write the SNAP / configure database name into the file.
3. Keep the original source comments (synopsis, author, change log, …).

## If deploy fails

Do what `fix` says. One exception: an error caused only by breaking rule 1–3
(read it with the nearby `--** SSC-` EWI comments) → make that minimal edit and
re-run `run`. Otherwise do not rewrite the view here or loop redeploys; never
deploy, create, or edit a dependency.
