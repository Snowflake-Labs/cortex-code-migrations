# SSC-FDM-SSIS0015 — Bulk Insert SortedData Hint Not Available

A Bulk Insert task's `SortedData` (for example `ID ASC`) became `BULK INSERT ... ORDER (ID ASC)`: a promise that the file is sorted like the table's clustered index, so SQL Server could skip a sort. It is a speed hint only, with no effect on which rows load. `COPY INTO` has no such hint and SnowConvert drops it. The FDM is informational.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Rare (once per Bulk Insert task with SortedData) |
| Common action | No code change |

## Identification

Look for the marker:
```
--** SSC-FDM-SSIS0015 - SSIS BULKINSERTTASK SORTEDDATA HINT IS NOT AVAILABLE IN SNOWFLAKE. USE CLUSTER BY ON TABLE DEFINITION FOR SIMILAR OPTIMIZATION. **
```

It sits above the task's `COPY INTO`. The columns are in `BulkInsertTask:SortedData` in the `.dtsx`; the marker does not show them.

## Fix Patterns

### Pattern 1: No change (most common)

Leave the comment and the `COPY` as they are. Do **not** add `CLUSTER BY` because of this marker.

### Pattern 2: The project already tunes this table

A clustering key pays off only on very large tables (multi-terabyte) whose queries filter on those columns, and automatic clustering costs credits. If the user asked for performance tuning and the table qualifies, the key goes in the table DDL, not in the load:

```sql
ALTER TABLE dbo.LargeDataset CLUSTER BY (ID);
```

## Key Points

- Do **NOT** remove the FDM comment.
- Row order in a table is never kept: a consumer that needs the file order sorts in its own query (`ORDER BY`), or uses `METADATA$FILE_ROW_NUMBER` captured at load time.
- Other Bulk Insert performance options are informational too: [SSC-FDM-SSIS0012](SSC-FDM-SSIS0012.md) (BatchSize), [SSC-FDM-SSIS0014](SSC-FDM-SSIS0014.md) (TableLock).
