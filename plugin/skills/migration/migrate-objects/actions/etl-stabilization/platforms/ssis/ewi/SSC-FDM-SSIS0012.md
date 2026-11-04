# SSC-FDM-SSIS0012 — Bulk Insert BatchSize Not Available

A Bulk Insert task's `BatchSize` (commit every *n* rows) has no `COPY INTO` equivalent: a `COPY` statement is one transaction, and Snowflake sizes its own work. The FDM is informational.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Low (once per Bulk Insert task with a BatchSize) |
| Common action | No code change |

## Identification

Look for the marker:
```
--** SSC-FDM-SSIS0012 - SSIS BULKINSERTTASK BATCHSIZE IS NOT AVAILABLE IN SNOWFLAKE. SNOWFLAKE MANAGES BATCHING AUTOMATICALLY FOR OPTIMAL PERFORMANCE. **
```

It sits above a `COPY INTO`, usually with other Bulk Insert markers ([SSC-EWI-SSIS0024](SSC-EWI-SSIS0024.md), [SSC-FDM-SSIS0013](SSC-FDM-SSIS0013.md), [SSC-FDM-SSIS0014](SSC-FDM-SSIS0014.md)).

## Fix Patterns

### Pattern 1: No change (most common)

Leave the comment and the `COPY` as they are.

### Pattern 2: The package relied on partial commits

With `BatchSize`, a failure part-way through kept the batches already committed. A failed `COPY` keeps nothing from that file. If a later task assumed partial loads (for example it resumes from the last loaded row), say so in a `-- NEEDS-USER:` comment and mark as needs-user; `ON_ERROR = CONTINUE` loads the good rows but is not the same thing.


## Key Points

- Do **NOT** remove the FDM comment.
- Error tolerance is `ON_ERROR`, not `BatchSize`: see [SSC-EWI-SSIS0024](SSC-EWI-SSIS0024.md).
