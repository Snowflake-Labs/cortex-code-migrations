# Run Tests

Runs in this procedure's `AIMSBX_*` pair after `captureBaseline`; on pass the walk goes to `deployCommonSandbox`, then `deploy`. Sandbox ops, `restore_from_sandbox`, and sandbox-catalog rules: [create-isolated-sandbox.md](create-isolated-sandbox.md#deploy-modes).

## 1. Refresh the sandbox

The step has no `sandbox` → skip; tests bind the common catalogs. Otherwise tests bind that `AIMSBX_*` pair and disk edits are not live until pushed (setup never CREATEs this object on Snowflake). Op `test` pushes this object first when the sandbox lacks its body as on disk (reply `pushed: true`; a failed push replies as `sandbox_object` would, with no case run):

- **`invalidation` on the step** (or a `reason` from a `reopened` return) — a closure member changed. `walk(action="lookup")`: any row not `done` → return `partial`, blocked on that walk. Else `walk_run(op="sandbox_closure")`: the changed callee and this object onto the pair's Snowflake side, with no table reload, so seeded rows stay.
- **Otherwise:** `walk_run(op="sandbox_object")`.

## 2. Validate

Run the step's `run` as given (op `test`). It binds the step's `sandbox`, else `.scai/bindings/database-bindings.yaml`; in a procedure sandbox, mutated tables restore from common between cases. `failing[].status`: `FAIL` (differs from baseline), `ERROR` (exception), `NO_BASELINE`. A failed reply carries `results` (per failing `params_hash`: `status`, `diffs`, `delta`) and `results_table`, the full name of this project's RESULTS table; query that name (never a guessed catalog), and only in the fix loop or verifier.

On failure do what `fix` says; when cases fail the reply carries `next`, the fix loop's step. Only this fixture's rows to blame → the fixture-rows test in [general_task §3](../../../../agents/general_task.md#3-rules); `sandbox_specialist` with `task=runTests`. On `done`, re-push per §1 and re-run `run`.

Never patch this procedure around a dependency's defect.

## 3. After the fix loop

- **Still failing**, where a Snowflake-SQL or YAML change would be illogical (source wall-clock; source non-determinism such as `TOP` ties without a unique `ORDER BY`; identity / sequence / UUID values each side generates, and their copies in referencing columns; never edit source), or the remaining hashes are illogical YAML rows you added a covering row for, or leftover identities: one foreground `test_case_verifier`, fresh context, for **all** remaining hashes (`walk(action="next")` `reason` lists them, including RESULTS hashes no longer in the YAML). Never on the first FAIL. It treats a human `answered` row (`human: true`) as binding.
  - Only if the project set `require_independent_override_accept: false`, override-accept yourself:
    ```
    walk(action="note", params_hash="<RESULTS params_hash>",
         asks=["override-accept the named case", "<the other reading>"],
         choice="override-accept the named case", reason="<the known limitation, named>")
    ```
  - Per `cases[]`: `accepted` → continue; `rejected` → a Snowflake-SQL or YAML edit exists (a table CSV is not that edit): fix loop. Same hash still FAILs after that fix → a **new** verifier; a second override-accept is allowed.
  - Do not `walk done` `runTests`; RESULTS still shows FAIL and the `runTests` status source absorbs accepted hashes. Do not escalate leftover hashes as "purge RESULTS" while the YAML still covers the path.
- **Never remove a YAML case** (delete, comment out, omit on regenerate). `scai test validate` runs only rows in the file, but the `runTests` status source scores every `params_hash` ever seen in RESULTS: dropping a row prints 20/20 while `runTests` stays failed. For illogical inputs (harness-rounded MONEY past the type limit), add a row that covers the same path and keep the illogical one; if it fails, its hash is override-accepted.
