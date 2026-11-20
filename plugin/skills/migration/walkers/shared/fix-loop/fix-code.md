# Diagnose & Fix

`fixCode` for one object: read the failure, name a root cause, apply a
faithful fix or stop. "Done" below means `walk(action="done")`; the machine then
retries the step's `failedTask`. Do not spawn `test_case_verifier` here.

## 1. Context

On a repeat pass, do not retry an unchanged approach.

From the first step's `files`, read the source SQL (`files.source`), the converted
SQL (`files.converted`) and the failure of `failedTask`:

| Failed task | Evidence |
|---|---|
| `deploy` / `deployCommonSandbox` / `createIsolatedSandbox` | Compile error text |
| `runTests` | The failed test reply's `results`; more rows: query its `results_table` |
| `validateView` / `migrateData` / `validateData` | That task's error or diff |
| `verify` | Unresolved EWIs; for an open `invalidation` (source-less helper), its named inputs: `query_source` of the source builtin vs this helper (re-probe after the push) |

`<files.artifacts>/speculative.sql`, when present, is a fix a `speculative_fixer` wrote
early against stub data: diff it against the converted file and try its changes that address
this failure first.

Fix each failure on this object whose converted-SQL edit would match source.
Do not change or deploy another object onto `common`.

## 2. Known shortcuts

Check these before inventing a theory. A match is a fix (or a stop), not a swarm.

- Error 002232 (invalid virtual column) — inline the UDF.
- Mixed-quote PIVOT identifiers — fix quoting.
- All-rows-different from column order, case, or formatting — reorder / alias /
  cast when that still means what the source means.
- SQL Server `DECIMAL` / `MONEY` division **truncates**; Snowflake `NUMBER`
  **rounds**. A cent-level miss after `ROUND(..., 2)` is
  `TRUNCATE(expr, source_scale)` on each division. Extra CSV digits are not a diagnosis.
- Other decimal / timestamp precision — match source in converted SQL.
- Wall-clock expression that can never match between capture and validate — §4.
- Snowflake 001187 (`COPY INTO` refused on CHECK constraints) — delete the
  `CONSTRAINT … CHECK` clauses from the converted file, then deploy. Do not
  `ALTER TABLE … DROP CONSTRAINT` on the live table.
- **Dynamic SQL** (`EXECUTE IMMEDIATE`, `IDENTIFIER(`, `sp_executesql`,
  `EXEC(` / `EXEC @`) — [dynamic-sql.md](dynamic-sql.md).
- **Rules** — `find_similar_rules(query=<primary error or first diff>)`. It returns
  only name / mode / `ai_context`; `ai_context` is a diagnosis, not an accept.
  A name starting `[AVOID]` is an approach not to repeat.
- **YAML `steps:` do not match the proc** (not a SQL bug) — apply the recipe from
  [../testing/edit-test-yaml.md](../testing/edit-test-yaml.md) to
  `<project_dir>/<files.artifacts>/test/*.yml` (`files.artifacts` verbatim),
  recapture per [../testing/capture-baseline.md](../testing/capture-baseline.md),
  then done. Nothing to redeploy.

  | Smell | Recipe |
  |---|---|
  | Multiple result sets / "got N, expected M" | Multi-result-set validation |
  | OUT / INOUT param column null or missing | OUT / INOUT parameter comparison |
  | DML proc, "no rows captured" | Side-effect-only DML |
  | Proc writes a table the YAML never reads | Table-read assertion |
  | Redshift refcursor / `RESULT_SCAN` empty | Cursor-read step |
  | `"ANONYMOUS BLOCK"` vs Redshift param name | Redshift scalar INOUT aliasing |
  | Teradata 5315 on the source side | Teradata cross-database GRANTs |

## 3. Root cause

| Finding | Action |
|---|---|
| Converted logic ≠ source (incl. source-less helper ≠ source builtin on the named inputs) | Edit converted SQL |
| Missing schema prefix that is not a catalog-binding problem | Add the prefix |
| Source function left in source dialect | Snowflake equivalent |
| Precision / collation / padding, and a CAST or `RTRIM` still means what the source means | Edit converted SQL, then `note` |
| Unknown function / procedure / object, or a two-part `PUBLIC.X` / tokenless catalog, for any project object | One foreground `cur_reconciler`. Not a `-- NEEDS-USER:` comment, stub (`NULL` / `WHERE FALSE`), inlined copy, borrowed object, or SNAP name in this file. Escalate only if the child returns `escalate`. |
| Missing object whose `walk(action="lookup", name=…)` `state` is not `done` | Do not `walk done`; `walk(action="next")` and return `partial`. |
| Clock drift and the source (or a view it reads) computes from now | §4 — do not edit |
| Only identity / sequence / UUID values each side generates differ, and their copies in referencing columns | §4 — do not edit |
| `error_mismatch` (both sides error, different code / SQLSTATE) | Do not delete the YAML case. Done; a second verifier is allowed after a later code change. |
| Source-side error the customer's `files.source` would not raise — the sandbox ran a bindable copy that lost a clause | Drift: [general_task §3](../../../../../agents/general_task.md#3-rules) |
| Source cannot run as written (INSERT…EXEC column count, missing source columns, source `EXEC` error) | Escalate. Do not invent columns in converted SQL; do not `ALTER` source. |
| No nameable cause after reading the files and any matching rule | Escalate with the diffs and the readings you cannot choose between |

Exhaust converted-SQL fixes before blaming the fixture or escalating.
Override-accept is last: "the baseline moved by a day" is not enough if a CAST,
prefix, YAML shape, or collation/`RTRIM` would make the case pass.

## 4. Wall-clock or generated values — stop

When the only remaining failures are drift from an expression that must stay
(`GETDATE`, `CURRENT_TIMESTAMP`, `CURRENT_DATE`, `DATEDIFF` against now,
age-from-today), or values each side generates (identity, sequence, `NEWID()` /
`UUID_STRING()`) and their copies in referencing columns: do not edit, do not
reseed or recapture, do not override-accept, do not spawn a
verifier. Done; `runTests` hands the remaining hashes to `test_case_verifier`.

## 5. Apply and push

Edit `files.converted` only, minimally. Keep source comments; keep
`EXECUTE AS` and the SnowConvert `COMMENT` provenance block unless the error named
them. Do not rewrite the database qualifier to the SNAP / configure name —
`deploy` substitutes `<%token%>` from the active bindings; leave a leading
`USE DATABASE` (the tool comments it out). `note` any edit that chose among
meanings (CHECK drop so COPY can run, `RTRIM` for trailing-space collation).

Push before `walk done` — a live sandbox pair does not make disk live. A push returns `{ok: true}`; on failure do what `fix` says.

| Need | Call |
|---|---|
| This object only, into the live sandbox | `walk_run(op="sandbox_object")` |
| Closure into the live sandbox (a helper / view / function also changed) | `walk_run(op="sandbox_closure")` (peer functions/views/procs, then this body, on Snowflake; no table reload) |
| This object only, onto the common catalogs (failed task is `deploy`, or a source-less helper) | `walk_run(op="deploy")` |

A source-side `already exists` on the sandbox twin is a skip (Snowflake is
CREATE OR REPLACE); do not spawn `sandbox_specialist` for it. Then done.
