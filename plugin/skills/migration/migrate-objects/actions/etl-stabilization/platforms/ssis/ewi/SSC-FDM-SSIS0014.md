# SSC-FDM-SSIS0014 — Bulk Insert TableLock Not Needed

A Bulk Insert task's `TableLock` took a table lock for the load. Snowflake needs no lock hint: readers see the table as of their query's start while the `COPY` runs. The FDM is informational.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Low (once per Bulk Insert task with TableLock) |
| Common action | No code change |

## Identification

Look for the marker:
```
--** SSC-FDM-SSIS0014 - SSIS BULKINSERTTASK TABLELOCK IS NOT NEEDED IN SNOWFLAKE. MVCC ARCHITECTURE ALLOWS CONCURRENT READS DURING WRITES WITHOUT EXPLICIT LOCKING. **
```

It sits above the task's `COPY INTO`.

## Fix Patterns

### Pattern 1: No change

Leave the comment and the `COPY` as they are.


## Key Points

- Do **NOT** remove the FDM comment.
- Do not add a `LOCK` statement or an explicit transaction to imitate `TableLock`; Snowflake serializes concurrent writes to the same table itself.
