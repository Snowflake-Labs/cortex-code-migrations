# SSC-EWI-SSIS0005 — Execute Package Task Runs Asynchronously

An Execute Package task calls a package that SnowConvert did not convert to a stored procedure, so it became `EXECUTE TASK public.<child>`, which starts a run of the child's task graph and returns at once. SSIS waited for the child and failed the task when the child failed. Here the parent's next tasks start right away, and a child failure does not reach the parent. The marker **breaks compilation**. Children that SnowConvert finds called by Execute Package tasks are converted to procedures and called with `CALL` ([SSC-FDM-SSIS0005](SSC-FDM-SSIS0005.md)), so this marker usually comes with [SSC-EWI-SSIS0008](SSC-EWI-SSIS0008.md).

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Once per Execute Package task whose child is not a converted procedure |
| Common action | Keep `EXECUTE TASK` when nothing waits on the child; otherwise `CALL` a procedure or wait for the run |

## Identification

Always the last marker in the chain, right before the `EXECUTE TASK`:

```sql
---- Start block 'Package\ExecuteExternalFileTask'
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0008 - EXECUTE PACKAGE TASK REFERENCES AN EXTERNAL PACKAGE ***/!!!!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0005 - SSIS EXECUTE PACKAGE TASK WAS CONVERTED TO A SNOWFLAKE EXECUTE TASK STATEMENT THAT RUNS ASYNCHRONOUSLY. ***/!!!
EXECUTE TASK public.concurrent_package;
---- End block 'Package\ExecuteExternalFileTask'
```

`public.<child>` is the root task of the child package's task graph. Search the converted output for `CREATE OR REPLACE TASK public.<child>` and `CREATE OR REPLACE PROCEDURE public.<child>`.

## Fix Patterns

### Pattern 1: Nothing after it depends on the child

The task is the last one in the graph, or the next tasks don't read anything the child writes. Keep `EXECUTE TASK` and remove the markers.

### Pattern 2: The child exists as a procedure

When the output has `CREATE OR REPLACE PROCEDURE public.<child>` (with the [SSC-FDM-SSIS0005](SSC-FDM-SSIS0005.md) comment), call it the way SnowConvert does for reusable packages: `CALL public.concurrent_package();`. The call blocks and passes on failures, like SSIS.

### Pattern 3: Later tasks need the child's results, and the child is a task graph

Wait for the run to finish and fail when it fails:

```sql
-- After
DECLARE
   child_failed EXCEPTION (-20001, 'Child package public.concurrent_package did not succeed');
   started TIMESTAMP_LTZ;
   child_state VARCHAR;
   polls INTEGER := 0;
BEGIN
   started := CURRENT_TIMESTAMP();
   EXECUTE TASK public.concurrent_package;
   -- Reads the newest EXECUTE TASK run since :started, which may not be this run
   -- if anything else also starts public.concurrent_package (see below).
   WHILE (child_state IS NULL AND polls < 120) DO
      SELECT SYSTEM$WAIT(30);
      polls := polls + 1;
      SELECT MAX_BY(STATE, COMPLETED_TIME) INTO :child_state
      FROM TABLE(INFORMATION_SCHEMA.COMPLETE_TASK_GRAPHS(ROOT_TASK_NAME => 'CONCURRENT_PACKAGE'))
      WHERE SCHEDULED_FROM = 'EXECUTE_TASK' AND SCHEDULED_TIME >= :started;
   END WHILE;
   IF (child_state IS NULL OR child_state <> 'SUCCEEDED') THEN
      RAISE child_failed;
   END IF;
END;
```

`COMPLETE_TASK_GRAPHS` lists only runs that completed in the last 60 minutes. A skipped root run returns no row, which is why the loop has a limit. Keep the limit under the parent task's `USER_TASK_TIMEOUT_MS` (60 minutes by default).

**This poll cannot tell runs of the child apart.** `EXECUTE TASK` returns no run ID, so the loop reads the newest run of the child's graph that was started by `EXECUTE TASK` after `started`. If another parent, session or person also runs `EXECUTE TASK public.concurrent_package` in that window, the loop can read that run's state instead of its own run's state, and pass or fail on the wrong run. Use this pattern only when this parent is the only thing that starts the child. Otherwise, use Pattern 2 (convert the child to a procedure and `CALL` it). Keep the comment in the SQL above so the next reader knows the limit.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker, and the other markers in its chain once they are resolved.
- `EXECUTE TASK` runs root or standalone tasks only. It runs a suspended root task without resuming it, but it skips suspended child tasks. The task owner role needs the global `EXECUTE TASK` privilege and `OWNERSHIP` or `OPERATE` on the child task.
- If the child graph is already running, the new run is queued according to the child's `OVERLAP_POLICY`. Two parents starting the same child do not each get their own run.
- Parameter bindings: [SSC-EWI-SSIS0006](SSC-EWI-SSIS0006.md). Property expressions on the task: [SSC-EWI-SSIS0007](SSC-EWI-SSIS0007.md).
