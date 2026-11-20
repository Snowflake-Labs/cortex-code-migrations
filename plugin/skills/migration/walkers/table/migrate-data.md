# Migrate data (table)

Run the step's `run` as given (op `migrate_data`). On SQL Server it is
synchronous `scai data migrate start --direct`: it generates the one-table
workflow if needed (`extraction=regular`, `sync=none`, native) and returns when
the load finishes. Add `workflow_path` only to reuse an edited YAML. Do not arm
Monitor or poll.

On failure do what `fix` says. Never change Snowflake with `sql_execute`: a
CHECK-constraint refusal is fixed in the converted file, never by a live `ALTER`.
"Supports SQL Server only" → other dialects have no walker path: escalate with
the message.
