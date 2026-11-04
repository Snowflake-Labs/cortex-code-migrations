# Deploy to the shared source catalog

Views and functions run this after convert, tables after `enrichTestbed`, and
procedures after `runTests` passes, then `deploy`.

Run the step's `run` as given (op `source`). It is **source-only**: deploys the
object's source DDL (`scai code deploy -t source`) into the shared source
catalog (CREATE skipped when it already exists) and, for a table, compiles and
generates its testbed CSV, then loads it. Snowflake is the later `deploy` task — do **not** run op `deploy`
here. Schema/ETL/BTEQ units and units with no source return `skipped`, not failed.

On failure do what `fix` says; act on a helper's `result` per
[general_task §4](../../../../agents/general_task.md#4-helpers) — for
`sandbox_specialist` `needs_sql_fix`, after the fix spawn it again for
`load_only`. The DDL deployed here is `files.source_bindable`: a failure the
customer's `files.source` would not hit is drift
([general_task §3](../../../../agents/general_task.md#3-rules)). Do not DROP shared databases or write `source_ready` by hand.
