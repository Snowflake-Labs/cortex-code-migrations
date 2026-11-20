# SSC-FDM-SSIS0029 — Disabled Task Commented Out

The task was disabled in the source package (`DTS:Disabled="True"`), so SnowConvert kept its converted body as `--` comments. A disabled task inside a container is just commented lines. A disabled **top-level** task still gets its own `CREATE OR REPLACE TASK ... AFTER ... AS` whose body is only comments, which does not compile.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Low (once per disabled task) |
| Common action | Keep it disabled; give a top-level task a no-op body |

## Identification

Look for the marker:
```
--** SSC-FDM-SSIS0029 - THE SSIS TASK '<Package\Task name>' WAS DISABLED IN THE SOURCE PACKAGE AND HAS BEEN COMMENTED OUT. **
```

```sql
CREATE OR REPLACE TASK public.disabled_expression_task_disabled_expression
WAREHOUSE=DUMMY_WAREHOUSE
AFTER public.disabled_expression_task
AS
--** SSC-FDM-SSIS0029 - THE SSIS TASK 'Package\disabled_expression' WAS DISABLED IN THE SOURCE PACKAGE AND HAS BEEN COMMENTED OUT. **
--User_message := UPPER(:User_message || 'message');
```

## Fix Patterns

### Pattern 1: Inside a container (commented lines in a parent body)

No change. Leave the comments.

### Pattern 2: A top-level task with an empty body

Give it a statement that does nothing, keep the comments, and keep the task in the graph so its successors keep their `AFTER`:

```sql
CREATE OR REPLACE TASK public.ops_housekeeping_sql_rebuild_fragmented_indexes
WAREHOUSE=DUMMY_WAREHOUSE
AFTER public.ops_housekeeping_seqc_share_cleanup
AS
--** SSC-FDM-SSIS0029 - THE SSIS TASK 'Package\SQL Rebuild Fragmented Indexes' WAS DISABLED IN THE SOURCE PACKAGE AND HAS BEEN COMMENTED OUT. **
--EXECUTE IMMEDIATE 'CALL dba.usp_IndexMaintenance()';
SELECT 'disabled in the source package';
```


## Key Points

- Do **NOT** remove the FDM comment, and do **not** uncomment the body: the task was off in production, often for a reason in its description ("moved to the weekend DBA job").
- When no task runs `AFTER` it, dropping the `CREATE TASK` is also fine; say so in the fix log.
- A task disabled by an *expression* is [SSC-EWI-SSIS0026](SSC-EWI-SSIS0026.md), not this.
