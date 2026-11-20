# Run Tests (function)

`runTests` runs after `deploy` onto the common catalogs.

## Sandbox pair

A function has no sandbox unless a `sandbox_specialist` minted one on demand
(the step has `sandbox`). None → skip; tests bind the common catalogs.
Otherwise tests bind that `AIMSBX_*` pair, and sandbox setup
never Snowflake-CREATEs this function, so push it before validating:

- `invalidation` on the step (a dependency in the closure changed):
  `walk(action="lookup")`; any row not `done` → return `partial`, blocked on
  that walk. Else `walk_run(op="sandbox_closure")` (the closure and this
  function onto the pair's Snowflake side, no table reload).
- Otherwise `walk_run(op="sandbox_object")`.

## Run

Run the step's `run` as given (op `test`); it binds the step's `sandbox`, else
the common yaml. After AIMSBX DML the tools did not see (`sql_execute`), run
`walk_run(op="sandbox_object", restore_from_sandbox=true)` first — on op `test`
it only clones when none is latched yet; a helper's `reload_tables` and mutating
`query_source` into AIMSBX latch it automatically. `failing[].status`: `FAIL`
(differs from baseline), `ERROR` (exception), `NO_BASELINE`. A failed reply
carries `results` (per failing `params_hash`: `status`, `diffs`, `delta`) and
`results_table`, the full name of this project's RESULTS table; query that
name (never a guessed catalog), in the fix loop / verifier only.

On failure do what `fix` says; when cases fail the reply carries `next`, the
fix loop's step. Only this fixture's rows to blame → the
fixture-rows test in [general_task §3](../../../../agents/general_task.md#3-rules);
`sandbox_specialist` with `task=runTests`. On `done`, re-push per "Sandbox
pair" and re-run `run`.

Never patch this function around a dependency's defect.

## After the fix loop

- **Still failing**, and a Snowflake-SQL or YAML change would be illogical
  (source wall-clock expression; source non-determinism such as `TOP` ties
  without a unique `ORDER BY`; identity / sequence / UUID values each side
  generates, and their copies in referencing columns), or the only
  remaining hashes are illogical YAML rows you added a covering row for, or
  leftover RESULTS identities: spawn **one** foreground
  `test_case_verifier` for **all** remaining hashes (`walk(action="next")`
  `reason` lists them). Never on the first FAIL. It honours a human
  `answered` row (`human: true`) as binding.
  - Only if the project set `require_independent_override_accept: false`,
    override-accept yourself:

    ```
    walk(action="note", params_hash="<RESULTS params_hash>",
         asks=["override-accept the named case", "<the other reading>"],
         choice="override-accept the named case", reason="<the known limitation, named>")
    ```
  - Per `cases[]` row: `accepted` → continue. `rejected` → a Snowflake-SQL or
    YAML fix exists (a table CSV is not that fix): fix loop. If the hash still
    FAILs after that fix, spawn a **new** verifier — a second override-accept
    is allowed.
  - Do not `walk done` `runTests`; RESULTS still shows FAIL and the `runTests`
    status source absorbs accepted hashes. Do not escalate leftover hashes as "purge
    RESULTS" while the YAML still covers the path.

## YAML cases

Never remove a case (delete, comment out, or omit on regenerate). `scai test
validate` runs only the rows in the file, but the `runTests` status source scores every
`params_hash` ever seen in `VALIDATION.RESULTS` — dropping a failing row prints
20/20 while `runTests` stays failed. For illogical inputs (e.g. MONEY rounded
past the type limit), add a row that covers the same path and keep the illogical
one; if it fails, its hash is override-accepted.
