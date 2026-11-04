# SSC-FDM-SSIS0011 — Bulk Insert MaximumErrors Semantics Differ

A Bulk Insert task set `MaximumErrors` to something other than its default of 10. SnowConvert turned it into `ON_ERROR = SKIP_FILE_<n>`, or `ON_ERROR = ABORT_STATEMENT` for 0. SSIS **failed the task** once the error count went over the limit; `SKIP_FILE_<n>` skips the file **and succeeds**. The FDM is informational, but the `ON_ERROR` often needs a change.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Low (once per Bulk Insert task with a non-default MaximumErrors) |
| Common action | Fix `ON_ERROR` for 0; add a failure check when later tasks need a complete load |

## Identification

Look for the marker:
```
--** SSC-FDM-SSIS0011 - SSIS BULKINSERTTASK MAXIMUMERRORS SPECIFIES ERROR COUNT THRESHOLD. SNOWFLAKE ON_ERROR CONTROLS BEHAVIOR WHEN ERRORS OCCUR. REVIEW ERROR HANDLING STRATEGY. **
```

It sits above the task's `COPY INTO`; the value is in its `ON_ERROR = SKIP_FILE_50` and in `BulkInsertTask:MaximumErrors="50"` in the `.dtsx`.

| SSIS `MaximumErrors` | SSIS behaviour | Generated | Same behaviour in Snowflake |
|---|---|---|---|
| *n* > 0 | up to *n* bad rows skipped; one more fails the task | `SKIP_FILE_n` (skips at *n*, then succeeds) | `SKIP_FILE_<n+1>` plus the check in Pattern 2 |
| 0 | unlimited errors allowed | `ABORT_STATEMENT` (**wrong**: fails on the first) | `CONTINUE` |

## Fix Patterns

### Pattern 1: `MaximumErrors` is 0

Replace `ON_ERROR = ABORT_STATEMENT` with `ON_ERROR = CONTINUE`: bad rows are skipped and the rest load.

### Pattern 2: Later tasks need the task to fail

When an `OnFailure` path, an event handler or the package outcome depends on the load failing, raise when a file was skipped. `COPY` returns one row per file, with lower-case column names:

```sql
COPY INTO dbo.LargeDataset FROM @public.landing_stage/large/ FILES = ('large_dataset.csv')
FILE_FORMAT = (...) ON_ERROR = SKIP_FILE_51;
DECLARE
   skipped INTEGER;
   load_failed EXCEPTION (-20001, 'Bulk load of dbo.LargeDataset exceeded MaximumErrors');
BEGIN
   SELECT COUNT(*) INTO :skipped FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())) WHERE "status" = 'LOAD_FAILED';
   IF (skipped > 0) THEN
      RAISE load_failed;
   END IF;
END;
```

Run nothing between the `COPY` and the check, or `LAST_QUERY_ID()` points elsewhere.

### Pattern 3: Nothing depends on the outcome

Leave the generated `SKIP_FILE_<n>`.

## Key Points

- Do **NOT** remove the FDM comment.
- Without a `BatchSize`, a failed SSIS load rolled back all its rows; a skipped file loads none of its rows either. Rows of other files in the same `COPY` still load.
- With the default 10 there is no FDM, but the generated `SKIP_FILE_10` has the same gap: apply Pattern 2 there too when the outcome matters.
- `ON_ERROR` is a `COPY` option only; an `INSERT ... SELECT` (the casts in [SSC-EWI-SSIS0021](SSC-EWI-SSIS0021.md)) has none.
- Batching is a separate FDM: [SSC-FDM-SSIS0012](SSC-FDM-SSIS0012.md). The stage: [SSC-EWI-SSIS0024](SSC-EWI-SSIS0024.md).
