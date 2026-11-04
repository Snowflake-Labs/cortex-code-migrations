# SSC-FDM-SSIS0030 — Sort EliminateDuplicates Survivor Not Determined

An SSIS Sort with `EliminateDuplicates` keeps one row per sort-key combination: the **last** one to arrive. SnowConvert emits `QUALIFY ROW_NUMBER() OVER (PARTITION BY <sort keys> ORDER BY <sort keys>) = 1`, which also keeps one row per group, but the `ORDER BY` repeats the partition keys, so which row survives is arbitrary. The FDM is emitted only when some output column is outside the sort key, i.e. when the choice shows in the data.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Low (once per deduplicating Sort with passthrough columns) |
| Common action | Add the column that decides the survivor to the `ROW_NUMBER` `ORDER BY` |

## Identification

Emitted in the Snowflake Scripting output (`SsisToSnowflakeScripting`), above the Sort's CTE in the data-flow procedure:

```sql
INSERT INTO dbo.TgtDedupInsertOrder (Id, Name, Value)
WITH cte_ole_db_source AS
( SELECT Id, Name, Value FROM dbo.SrcDedupInsertOrder ),
--** SSC-FDM-SSIS0030 - THE SSIS SORT WITH ELIMINATEDUPLICATES KEEPS THE LAST ROW OF EACH DUPLICATE GROUP IN INPUT ARRIVAL ORDER. THE CONVERTED SQL KEEPS EXACTLY ONE ROW PER GROUP, BUT ARRIVAL ORDER IS NOT RECORDED IN THE PACKAGE AND IS NOT REPRESENTED IN A SNOWFLAKE TABLE, SO A GROUP WHOSE NON-KEY COLUMNS DIFFER MAY KEEP A DIFFERENT ROW. ADD THE COLUMN THAT DECIDES THE SURVIVOR TO THE ROW_NUMBER ORDER BY IF ONE MUST BE CHOSEN. **
cte_sort AS
(
   SELECT Id, Name, Value
   FROM cte_ole_db_source
   QUALIFY ROW_NUMBER() OVER (PARTITION BY (Name) ORDER BY Name ASC) = 1
   ORDER BY Name ASC
)
SELECT Id, Name, Value FROM cte_sort;
```

Sort keys are the Sort's input columns with a non-zero `NewSortKeyPosition` in the `.dtsx`. A dbt Sort model has the same `QUALIFY` but no marker; the same review applies there.

## Fix Patterns

### Pattern 1: The source query fixes the arrival order

If the upstream source's SQL command has an `ORDER BY` (and nothing between it and the Sort reorders or merges rows), arrival order is that order, and the last row is the last by it. Add the column, reversed, after the keys:

```sql
-- Source: SELECT Id, Name, Value FROM dbo.Src ORDER BY Id
QUALIFY ROW_NUMBER() OVER (PARTITION BY (Name) ORDER BY Name ASC, Id DESC) = 1
```

### Pattern 2: A business rule decides the survivor

Latest load date, highest version, a non-NULL value: put it in the `ORDER BY` (`LoadDate DESC NULLS LAST`), and say why in a comment.

### Pattern 3: Nothing decides it

The source has no order and the package owner gives no rule: SSIS's choice depended on how the database returned rows. Leave the SQL, add `-- NEEDS-USER: which row of each duplicate <keys> group should be kept?`, and mark as needs-user if a test compares the non-key columns.

## Key Points

- Do **NOT** remove the FDM comment.
- Keep `PARTITION BY` as generated: it reproduces SSIS's duplicate test, NULL keys included (NULLs form one group).
- The trailing `ORDER BY` of the CTE does not order rows in the target table; do not rely on it.
- A Sort whose `NewComparisonFlags` fold strings (ignore case, ...) also carries `SSC-EWI-0073 - PENDING FUNCTIONAL EQUIVALENCE REVIEW FOR 'Microsoft.Sort NewComparisonFlags' NODE`: the generated `PARTITION BY` compares exactly, so groups SSIS merged stay apart. Partition by `UPPER(<key>)` (or a `COLLATE` expression) to match.
