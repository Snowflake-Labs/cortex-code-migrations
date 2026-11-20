# SSC-FDM-SSIS0013 — Bulk Insert KeepIdentity Disabled

A Bulk Insert task without `KeepIdentity` let SQL Server generate identity values and ignore the file's values for that column. A `COPY INTO` with no column list loads the file's values into the table's columns in order, identity column included. SnowConvert adds this FDM to almost every Bulk Insert, whether or not the target has an identity column.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | High (nearly every Bulk Insert task) |
| Common action | Check the target table: no identity column means no change |

## Identification

Look for the marker:
```
--** SSC-FDM-SSIS0013 - SSIS BULKINSERTTASK KEEPIDENTITY DISABLED. SNOWFLAKE COPY INTO WOULD TRY TO LOAD FILE VALUES INTO AUTOINCREMENT COLUMNS, WHICH MAY CAUSE ERRORS. EXCLUDE IDENTITY COLUMNS FROM THE FILE OR MODIFY THE TARGET TABLE. **
```

It sits above the task's `COPY INTO`.

## Fix Patterns

### Pattern 1: The target has no `IDENTITY` / `AUTOINCREMENT` column

No change. Leave the comment.

### Pattern 2: The target has an identity column

List the other columns, so Snowflake generates the identity:

```sql
-- Target: dbo.Employees (EmployeeID NUMBER AUTOINCREMENT, Name VARCHAR, Dept VARCHAR)
-- File: Name, Dept
COPY INTO dbo.Employees (Name, Dept)
FROM (SELECT $1, $2 FROM @public.landing_stage/hr/)
FILES = ('employees.csv')
FILE_FORMAT = (...);
```

When the file *does* contain an id column that SSIS ignored, leave its `$n` out of the `SELECT`.


## Key Points

- Do **NOT** remove the FDM comment.
- Read the target table's converted DDL, not the source's: SnowConvert turns `IDENTITY(1,1)` into `IDENTITY` / `AUTOINCREMENT`.
- A format file that skips table columns needs the same column list: see [SSC-EWI-SSIS0023](SSC-EWI-SSIS0023.md).
