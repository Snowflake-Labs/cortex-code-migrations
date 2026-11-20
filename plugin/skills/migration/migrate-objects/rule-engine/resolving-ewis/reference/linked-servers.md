# Linked Servers - Four-Part Names, OPENQUERY, EXEC AT, Remote Calls and Distributed Transactions

SQL Server reaches other servers through linked servers (`sp_addlinkedserver`). Snowflake has none: every object a query reads must be in the Snowflake account, where any database is reachable by a three-part name. So each linked-server reference becomes one of two things:

- **The remote object is migrated by this project** (or already lives in the account): rewrite the reference as that object's Snowflake name. This is the common case: a second SQL Server whose databases are part of the same estate.
- **The remote object is not in Snowflake** (another product such as an Oracle GL, or a server outside the migration): it is a missing dependency, not a conversion defect. Hand it to `cur_reconciler`; it escalates when the data has no home in Snowflake yet.

SnowConvert marks only some of these shapes. Four-part names, remote procedure calls and distributed transactions get **no** marker, and Snowflake rejects them at deploy.

## Quick Reference

| SQL Server | What SnowConvert emits | Snowflake fix |
|---|---|---|
| `RPTSRV.Ops.dbo.ErrorLog` (four-part name, any DML) | kept as written; at most `SSC-FDM-0007` (missing dependent object) | the remote object's target name, e.g. `OPS.DBO.ERRORLOG` |
| `LEGACY_ORA..GL.ACCOUNTS` (server, default catalog, schema, object) | kept as written | the migrated table's target name |
| `SELECT ... FROM OPENQUERY(SRV, 'remote SQL')` | `SSC-EWI-TS0086`, call kept | a derived table: `FROM ( <remote SQL translated to Snowflake> ) AS g`. See [SSC-EWI-TS0086](SSC-EWI-TS0086.md) |
| `EXEC ('stmt', @p) AT SRV` | `SSC-EWI-0021 - EXECUTE AT LINKED SERVER CONNECTION NOT SUPPORTED`, `EXECUTE IMMEDIATE 'stmt'` | the statement as static Snowflake SQL against the migrated objects; `?` becomes a bind (`:p`) |
| `EXEC (@sql) AT SRV` (SQL built at run time) | same EWI | **park**: see [What still parks](#what-still-parks) |
| `EXEC ... AT [SRV]` or `EXEC [SRV].[db].[sch].[proc]` (bracketed server) | the **whole unit becomes a stub**: `/*** SSC-EWI-0021 ... ***/ NULL; RETURN 'deferred';` | rebuild the body from the source file using this guide; the stub is not a conversion |
| `EXEC RPTSRV.EDW.dbo.usp_X @a = @a` (remote proc call) | `CALL RPTSRV.EDW.dbo.usp_X(...)`, no marker | `CALL <target db>.<schema>.USP_X(:a)`, arguments in the target signature's order |
| synonym `FOR RPTSRV.EDW.dim.DimClaim` | synonym commented out (`SSC-FDM-TS0059`), references replaced by the four-part name | same as a four-part name |
| `BEGIN DISTRIBUTED TRANSACTION` | no marker | `BEGIN TRANSACTION`: one Snowflake transaction spans databases in the account |
| `SET REMOTE_PROC_TRANSACTIONS ON` | `SSC-EWI-TS0089`, statement kept | delete the statement and the marker |
| `OPENROWSET` / `OPENDATASOURCE` | `SSC-EWI-0073` | not a linked server: a file or ad hoc connection. Re-platform as a stage plus `COPY INTO`, or escalate |

## Identification

Search the converted file for:

- `OPENQUERY(` and `!!!RESOLVE EWI!!! /*** SSC-EWI-TS0086`
- `SSC-EWI-0021 - EXECUTE AT LINKED SERVER CONNECTION NOT SUPPORTED IN SNOWFLAKE`
- `SSC-EWI-TS0089 - SET REMOTE_PROC_TRANSACTIONS`
- `DISTRIBUTED TRANSACTION`
- a dotted name with four parts (`a.b.c.d`) or with an empty catalog (`a..c.d`), in `FROM`, `JOIN`, `INSERT INTO`, `UPDATE`, `DELETE FROM`, `MERGE INTO` or `CALL`
- `RETURN 'deferred'` in a procedure body: the stubbed bracketed case

The first part is the linked server's name. When the source project has the `sp_addlinkedserver` script, its `@provider` / `@srvproduct` / `@datasrc` / `@catalog` say what the server is; otherwise the name and the remote SQL's dialect usually do (Oracle syntax in an `OPENQUERY` string means an Oracle server).

## Fix Process

1. **Resolve each remote object.** Drop the server part and look the rest up in the registry: `query_registry` for the object by source database, schema and name, then use its `target` name. `SRV..SCH.OBJ` uses the linked server's default catalog (`@catalog`).
2. **Found** → rewrite the reference to the target name. Deploy order follows `dependsOn`, as for any cross-database reference.
3. **Not found** → it is a missing dependency: spawn `cur_reconciler` (see DIAGNOSE_FIX Step 4). Do not stub the remote table, point the query at a look-alike local table, or delete the statement. When it returns `escalate`, the choices for the person are "migrate or land the remote tables in Snowflake (then rerun)" and "skip the object".
4. **OPENQUERY** → follow [SSC-EWI-TS0086](SSC-EWI-TS0086.md): the string is the *remote* server's SQL, so translate it from that dialect, not from T-SQL.
5. **`EXEC (...) AT`** with a literal statement → write the statement as static Snowflake SQL against the resolved objects. Replace `?` placeholders with the variables passed after the string, in order. Remove the `EXECUTE IMMEDIATE` wrapper and the marker.
6. **Remote procedure calls** → `CALL` the target procedure. T-SQL passes `@name = value`: pass the values positionally in the order of the target procedure's signature (or as `name => :value` when the target's argument names match), and capture a return value as SnowConvert does for local calls.
7. **Transactions** → `BEGIN DISTRIBUTED TRANSACTION` becomes `BEGIN TRANSACTION`; delete `SET REMOTE_PROC_TRANSACTIONS` and its `SSC-EWI-TS0089` marker. If any statement in the transaction still targets an object outside Snowflake, there is no two-phase commit to fall back on: escalate.
8. **Bracketed-server stub** (`RETURN 'deferred'`) → the converted file holds no logic. Rebuild the body from the source file with these rules. If the procedure is too large to rebuild faithfully, escalate with "rebuild by hand" / "skip".
9. Deploy and run the tests. A source-side failure (`Msg 7202` undefined linked server, `Msg 7314` remote object missing, `Msg 7405` `ANSI_NULLS` off for a heterogeneous query) means the source cannot run as written: escalate per DIAGNOSE_FIX, do not edit around it.

## Examples

### Four-part names, remote call and a distributed transaction

```sql
-- Before (converted, nothing compiles)
BEGIN DISTRIBUTED TRANSACTION;
UPDATE RPTSRV.EDW.etl.LoadControl SET Status = 'RUNNING' WHERE BatchID = :BATCHID;
CALL RPTSRV.EDW.dbo.usp_MergeDimPolicy(:BATCHID);
!!!RESOLVE EWI!!! /*** SSC-EWI-TS0089 - SET REMOTE_PROC_TRANSACTIONS ON IS NOT SUPPORTED IN SNOWFLAKE. ***/!!!
SET REMOTE_PROC_TRANSACTIONS ON;
COMMIT;

-- After (EDW is migrated by this project; the registry gives its target names)
BEGIN TRANSACTION;
UPDATE EDW.ETL.LOADCONTROL SET Status = 'RUNNING' WHERE BatchID = :BATCHID;
CALL EDW.DBO.USP_MERGEDIMPOLICY(:BATCHID);
COMMIT;
```

### EXEC AT with a literal statement

```sql
-- Before
!!!RESOLVE EWI!!! /*** SSC-EWI-0021 - EXECUTE AT LINKED SERVER CONNECTION NOT SUPPORTED IN SNOWFLAKE ***/!!!
EXECUTE IMMEDIATE 'DELETE FROM GL.STAGE_PREMIUM WHERE BATCH_ID = ?';

-- After (GL.STAGE_PREMIUM was landed in Snowflake as LEGACYGL.GL.STAGE_PREMIUM)
DELETE FROM LEGACYGL.GL.STAGE_PREMIUM WHERE BATCH_ID = :BATCHID;
```

## What still parks

| Construct | Why | Options to offer |
|---|---|---|
| `EXEC (@sql) AT SRV`, or `OPENQUERY` built in dynamic SQL | the remote statement is only known at run time | rebuild as static SQL from the cases the code builds; skip |
| A remote system with no copy of its data in Snowflake | nothing to point the query at | land or migrate the remote tables first; skip |
| A write to a remote system that stays outside Snowflake | Snowflake cannot write to it | re-platform the write (an export the other system loads, or an external access integration); skip |

## Key Points

- Never drop the server part blindly: `RPTSRV.EDW.dim.DimClaim` and a local `EDW.dim.DimClaim` are the same object only when the registry says so.
- The engine's silence is not a pass: four-part names, remote calls and distributed transactions carry no `!!!RESOLVE EWI!!!`, so search for them.
- An `OPENQUERY` string is remote SQL: Oracle `NVL`, `SYSDATE`, `ROWNUM` and doubled quotes `''Y''` need translating like any other source.
- A join of a remote result to a local table often carries `COLLATE DATABASE_DEFAULT`: see [SSC-FDM-TS0080](SSC-FDM-TS0080.md).
- `note` each remote-to-local mapping you made, so a person can check it.

## Resources

- [Snowflake: object name resolution](https://docs.snowflake.com/en/sql-reference/name-resolution), [Transactions](https://docs.snowflake.com/en/sql-reference/transactions)
- [SQL Server linked servers](https://learn.microsoft.com/en-us/sql/relational-databases/linked-servers/linked-servers-database-engine), [OPENQUERY](https://learn.microsoft.com/en-us/sql/t-sql/functions/openquery-transact-sql), [EXECUTE ... AT](https://learn.microsoft.com/en-us/sql/t-sql/language-elements/execute-transact-sql)
