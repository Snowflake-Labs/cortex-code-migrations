# Validate data (table)

Run the step's `run` as given (op `validate_data`). On SQL Server it is
synchronous `scai data validate start --direct`: it generates the one-table
workflow if needed (matching keys, `sync=none`) and returns when validation
finishes. Add `workflow_path` only to reuse an edited YAML. Do not arm Monitor
or poll; revalidation needs the orchestrator — not for walkers.

On failure do what `fix` says. A repeatable row mismatch, schema drift, or an
invalid identifier / compile error in the generated validation SQL is
deterministic: when no converted-SQL edit can repair it, escalate with the exact
evidence and the required repair. "Supports SQL Server only" → escalate with the
message.
