# Run Tests

Guide for the `runTests` task. The machine invokes this after deployment succeeds for procedures and functions, and after baseline capture for BTEQ scripts (which are not deployed).

## Run validation

The `scai test validate` tool compares Snowflake output against captured baselines. Baselines were captured during the prep phase — this step only re-runs validation.

Read the results file:

```
<project_dir>/test-results/results.json
```

Each entry has `code_unit_name`, `status`, `match_type`, `error`, and `differences`. Focus on entries where `status` is not `PASS`. BTEQ result rows carry `metadata.kind: "bteq"` and compare file I/O + table deltas rather than a return value.

## Test statuses

| Status | Meaning |
|--------|---------|
| `PASS` | Output matches baseline |
| `FAIL` | Output differs from baseline |
| `ERROR` | Exception during execution |
| `NO_BASELINE` | No captured baseline exists for this test case. Run `scai test capture` first. |

## Check for dependency failures first

Before attempting a fix, check whether the failure is caused by a **missing dependency** (table, view, function, or procedure that hasn't been migrated yet). Fixing code won't help if the real problem is a missing object.

### Dependency failure patterns

Scan the `error` field from failing test entries for these patterns:

| Pattern | Likely Cause |
|---------|-------------|
| "does not exist" | Missing table, view, or schema |
| "object does not exist" | Missing dependency object |
| "unknown function" | Function not yet migrated |
| "unknown procedure" | Procedure not yet migrated |
| "invalid identifier" | Column from unmigrated table/view |
| "unresolved reference" | Unresolved cross-object reference |
| "cannot resolve" | Missing schema or object |

### If a dependency failure is detected

1. **Identify the missing object** from the error message (e.g., `Unknown function: dbo.HelperFunc`).
2. **Look it up in the registry** with `query_registry`:
   ```
   query_registry(
     where="source.canonicalName ILIKE '%<missing_name>%'",
     fields="id,source,codeStatus,cloudStatus,extensions"
   )
   ```
3. **Route based on the returned fields:**

| Registry result | Action |
|---|---|
| No row returned | **Skip this object.** Report: "Blocked on `<dependency>` — not in registry." |
| Row exists but `cloudStatus.deployment.status != "completed"` | **Skip this object.** Report: "Blocked on `<dependency>` — not yet deployed." |
| Deployed but `codeStatus.testing.status != "completed"` (procs/funcs) or `extensions.dataValidation.status` is `failed`/`error` (tables) | **Skip this object.** Report: "Blocked on `<dependency>` — deployed but failing tests/validation." |
| Otherwise | Not a dependency failure — proceed to fix the code. |

If blocked on a dependency, call `transition_status(status='advance', task='runTests', outcome='failed', error='dependency')`. Name the specific dependency in your user-facing reply so the user knows what to migrate. The state machine will land this in the errored bucket without entering the fix loop — the SQL isn't broken, the precondition is.

### If not a dependency failure

Proceed — the machine will route to the fix loop.

## After tests complete

- **All pass:** call `transition_status(status='advance', task='runTests', outcome='completed')`.
- **Any fail (not dependency):** call `transition_status(status='advance', task='runTests', outcome='failed', error='sql')` — the machine routes to rule application and the fix loop. Use `error='sql'` only when the test failure is caused by a SQL/DDL bug the fix loop can address; for transient infrastructure issues (timeouts, connection drops) use `error='infra'` instead.
