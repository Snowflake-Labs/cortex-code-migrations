# SSC-FDM-SSIS0033 — Emptying Statement Removed for a Dynamic Table

The package emptied an OLE DB Destination (`TRUNCATE TABLE` or an unfiltered `DELETE`) before reloading it. That destination is now a Dynamic Table (`SSC-FDM-SSIS0032`), which dbt refreshes from its query and which cannot receive DML, so SnowConvert removed the statement from the converted orchestration and left this note where it was.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment in the orchestration, in place of the removed statement |
| Breaks compilation? | **No** |
| Frequency | Once per removed statement; only with `--materialize-as-dynamic-table` |
| Common action | None, unless the matching mart is reverted to `incremental` |

## Identification

When the task held only that statement, its body becomes `NULL;`:

```sql
---- Start block 'Package\Truncate Staging'
--** SSC-FDM-SSIS0033 - The TRUNCATE TABLE of 'dbo.SsisEmployeeStaging' was removed because 'dbo.SsisEmployeeStaging' is now a Dynamic Table, which Snowflake refreshes from its query and which cannot receive DML. Other database-side effects of the original statement are not reproduced. **
NULL;
---- End block 'Package\Truncate Staging'
```

When the task emptied several tables, only the promoted table's statement is removed. The statements that follow the note in the same block belong to other tables, were not promoted, and still run:

```sql
---- Start block 'Package\Truncate Staging'
--** SSC-FDM-SSIS0033 - The TRUNCATE TABLE of 'dbo.SsisEmployeeStaging' was removed because ... **
TRUNCATE TABLE dbo.SsisLoadAudit;
---- End block 'Package\Truncate Staging'
```

## Decision Tree

1. **Is the mart named in the note still a Dynamic Table?** Leave the statement removed. Do not add it back.
2. **Was that mart reverted to `incremental` (`SSC-FDM-SSIS0032`, Fix Pattern 1)?** Restore the statement where the note is, replacing the `NULL;` when there is one, e.g. `TRUNCATE TABLE dbo.SsisEmployeeStaging;`. The reverted mart appends, so without the statement every run duplicates the rows.
3. **Did the original statement have side effects beyond emptying the table** (for example `TRUNCATE` resetting an identity seed that other code reads)? Those are not reproduced; flag them to the user.

## Key Points

- Never restore a `TRUNCATE` or `DELETE` against a table that is still a Dynamic Table; it fails at run time.
- Do **NOT** remove the FDM comment.
