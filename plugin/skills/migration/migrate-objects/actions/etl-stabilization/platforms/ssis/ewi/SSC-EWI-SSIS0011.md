# SSC-EWI-SSIS0011 — Result Binding on a Non-Query Statement

An Execute SQL task binds its result to a variable, but SnowConvert could not produce a query whose result it can assign: the SQL is several statements, the `ResultSetType` is None, or the statement is not a `SELECT`. The variable is **never set**, so it keeps its default and every later task that reads it gets the wrong value. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Moderate (common in "open batch" / "open run" tasks that insert a row and return its id) |
| Common action | Split the statement from the query, assign with `SELECT ... INTO`, then publish the variable |

## Identification

```
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0011 - RESULT BINDING IS CONFIGURED FOR NON-QUERY STATEMENT. RESULT BINDING ONLY WORKS WITH SELECT QUERIES. ***/!!!
```

It sits at the start of the task's block, often chained with other markers (`...***/!!!!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0011 ...`). The result bindings are in the package: `<SQLTask:ResultBinding SQLTask:ResultName="..." SQLTask:DtsVariableName="User::BatchID" />`.

The working form SnowConvert writes for a single-row result is the target shape:

```sql
SELECT EmployeeName INTO :User_EmployeeName FROM ...;
...
CALL public.UpdateControlVariable('User_EmployeeName', '<package>', TO_VARIANT(:User_EmployeeName));
```

## Fix Patterns

### Pattern 1: INSERT, then the new identity (`SCOPE_IDENTITY()`)

```sql
-- Source batch
INSERT INTO etl.Batch (Status, OpenedAt, Source) VALUES ('OPEN', GETDATE(), 'BDX');
SELECT CAST(SCOPE_IDENTITY() AS bigint) AS BatchID;

-- After: read the row back by a key this insert alone set
LET run_key VARCHAR := UUID_STRING();
INSERT INTO etl.Batch (Status, OpenedAt, Source, RunKey) VALUES ('OPEN', CURRENT_TIMESTAMP(), 'BDX', :run_key);
SELECT BatchID INTO :User_BatchID FROM etl.Batch WHERE RunKey = :run_key;
CALL public.UpdateControlVariable('User_BatchID', '<package>', TO_VARIANT(:User_BatchID));
```

This is the safe form when other runs can insert into the same table at the same time. Use a column the insert already fills with a value unique to this run (a run id the package passes in, a UUID); when the table has none, adding one (`RunKey` above) is a schema change, so ask before making it.

SnowConvert's own rewrite of `SCOPE_IDENTITY()` in procedures reads `MAX` as of the insert:

```sql
INSERT INTO etl.Batch (Status, OpenedAt, Source) VALUES ('OPEN', CURRENT_TIMESTAMP(), 'BDX');
LET insert_qid VARCHAR := LAST_QUERY_ID();
SELECT MAX(BatchID) INTO :User_BatchID FROM etl.Batch AT(STATEMENT => :insert_qid);
```

It is **not** scoped to this insert: the `AT(STATEMENT => ...)` view is the whole table, and it includes changes other sessions committed while the insert ran, so a concurrent run's higher id can be returned. Use it only when the package is guaranteed to be the table's single writer, the table has Time Travel (a `DATA_RETENTION_TIME_IN_DAYS` of 0 makes it fail) and the identity only increases.

### Pattern 2: Several statements, the last one returns the row

Run the statements, then turn the final `SELECT` into `SELECT ... INTO :User_x`. One variable per bound column, in the `ResultName` order (`0`, `1`, ... for positional bindings).

### Pattern 3: `ResultSetType` is None

The binding never worked in SSIS either. Check whether anything reads the variable after this task. If nothing does, remove the marker and leave the variable alone; if something does, ask what value was intended and mark as needs-user.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker line.
- Publish the variable with `public.UpdateControlVariable` as SnowConvert does for its own bindings, or later tasks read the old value.
- `GETDATE()` / `SYSUTCDATETIME()` / `SUSER_SNAME()` inside the batch need translating too (`CURRENT_TIMESTAMP()`, `SYSDATE()`, `CURRENT_USER()`).
- A full-result-set binding (`ResultSetType` Full) into an Object variable feeds a Foreach ADO loop: rewrite the loop to read the query directly instead.
