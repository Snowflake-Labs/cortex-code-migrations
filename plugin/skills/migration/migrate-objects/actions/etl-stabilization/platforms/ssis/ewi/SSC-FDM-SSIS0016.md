# SSC-FDM-SSIS0016 — Bulk Insert CheckConstraints

A Bulk Insert task had `CheckConstraints` set, so SQL Server checked the target's `CHECK` and `FOREIGN KEY` constraints during the load (without it, `BULK INSERT` ignores them). The marker says Snowflake always validates constraints during loading. **That is wrong** on two counts: a Snowflake standard table enforces only `NOT NULL` and `CHECK` (not `PRIMARY KEY`, `UNIQUE` or `FOREIGN KEY`), and a `COPY INTO` a table that has a `CHECK` constraint **fails**. SnowConvert generated the plain `COPY INTO` regardless.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** (but the `COPY` fails at run time if the target has a `CHECK`) |
| Frequency | Low (once per Bulk Insert task with CheckConstraints) |
| Common action | Read the target's converted DDL: a `CHECK` means replacing the `COPY` with an `INSERT ... SELECT` |

## Identification

Look for the marker:
```
--** SSC-FDM-SSIS0016 - SSIS BULKINSERTTASK CHECKCONSTRAINTS OPTION IS IMPLICIT IN SNOWFLAKE. CONSTRAINTS ARE ALWAYS VALIDATED DURING DATA LOADING. **
```

It sits above the task's `COPY INTO`. Then open the target table's converted `CREATE TABLE`: SnowConvert keeps T-SQL `CHECK` constraints there, column-level or table-level.

## Fix Patterns

### Pattern 1: No `CHECK` and no foreign key that matters

No change. Leave the comment.

### Pattern 2: The target has a `CHECK` constraint

`INSERT` enforces `CHECK`; `COPY` refuses the table. Copy the file into a temporary table with the target's columns and no constraints, then insert from it:

```sql
-- dbo.Orders has CHECK (Quantity > 0)
CREATE OR REPLACE TEMPORARY TABLE orders_load (OrderId NUMBER(38, 0), Quantity NUMBER(38, 0), OrderDate DATE);
COPY INTO orders_load
FROM @public.landing_stage/orders/
FILES = ('orders.csv')
FILE_FORMAT = (...)   -- the generated COPY's FILE_FORMAT and ON_ERROR
ON_ERROR = SKIP_FILE_10;
INSERT INTO dbo.Orders (OrderId, Quantity, OrderDate)
SELECT OrderId, Quantity, OrderDate FROM orders_load;
```

One row that fails the `CHECK` fails the whole `INSERT`, as the constraint failed the SQL Server load. `FILES` names the one file exactly; a `PATTERN` such as `'.*orders[.]csv'` also loads `old_orders.csv`. A temporary table has no load history, so the file loads on every run.

### Pattern 3: The package relied on a foreign key

A standard table does not enforce `FOREIGN KEY`, `PRIMARY KEY` or `UNIQUE`. If later tasks rely on the load having rejected orphans, check after the load and raise:

```sql
DECLARE
   orphans INTEGER;
   orphan_rows EXCEPTION (-20002, 'dbo.Orders loaded rows with no matching dbo.Customers row');
BEGIN
   SELECT COUNT(*) INTO :orphans FROM dbo.Orders o
   WHERE NOT EXISTS (SELECT 1 FROM dbo.Customers c WHERE c.CustomerId = o.CustomerId);
   IF (orphans > 0) THEN RAISE orphan_rows; END IF;
END;
```

When the table feeds dbt models, a `relationships` or `unique` test is the lighter option.

## Key Points

- Do **NOT** remove the FDM comment; do not trust its text.
- The `COPY`-into-`CHECK` failure hits every Bulk Insert into such a table, with or without this FDM. Without `CheckConstraints`, SQL Server loaded rows that break the `CHECK`, and Snowflake's `INSERT` will reject them: if the data can break it, add `-- NEEDS-USER: filter the rows or drop the CHECK on <table>` and mark as needs-user.
- `NOT NULL` is enforced by `COPY` too: a NULL in a `NOT NULL` column is a row error, counted under `ON_ERROR` ([SSC-FDM-SSIS0011](SSC-FDM-SSIS0011.md)).
- Hybrid tables enforce all constraint types; check the DDL for `CREATE HYBRID TABLE` before adding Pattern 3.
