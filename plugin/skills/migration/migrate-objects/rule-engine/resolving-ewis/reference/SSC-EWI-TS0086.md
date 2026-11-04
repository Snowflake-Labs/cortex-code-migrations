# SSC-EWI-TS0086 - OPENQUERY Node Needs To Be Checked

`OPENQUERY(server, 'query')` sends the string to a linked server and returns its result as a table. Snowflake has no linked servers, so SnowConvert keeps the call and adds a compilation-breaking marker. It removes the call by itself only when the string reads nothing but its own CTEs and literals.

Read [linked-servers.md](linked-servers.md) first: it decides whether the remote tables exist in Snowflake. This guide covers the `OPENQUERY` call once they do.

## Quick Reference

| SQL Server | Snowflake |
|---|---|
| `FROM OPENQUERY(SRV, 'SELECT a, b FROM S.T WHERE f = ''Y''') AS g` | `FROM (SELECT a, b FROM <target of S.T> WHERE f = 'Y') AS g` |
| `SELECT * INTO #Src FROM OPENQUERY(SRV, '...')` | `CREATE OR REPLACE TEMPORARY TABLE Src AS SELECT * FROM (...)` (SnowConvert's own temp-table form) |
| `UPDATE OPENQUERY(SRV, '...') SET ...` (gets `SSC-EWI-0073`) | `UPDATE <target table> SET ... WHERE <the query's filter>` |
| OPENQUERY string built at run time | park (see [linked-servers.md](linked-servers.md#what-still-parks)) |

## Identification

```sql
SELECT
  *
FROM
  !!!RESOLVE EWI!!! /*** SSC-EWI-TS0086 - OPENQUERY NODE NEEDS TO BE CHECKED. ***/!!!
  OPENQUERY(OracleSvr, 'SELECT name FROM sampleschema.titles WHERE name = ''NewTitle''');
```

## Fix Process

1. **Find the remote server's kind** (see [linked-servers.md](linked-servers.md#identification)). The string is written in *that* server's dialect.
2. **Resolve every table in the string** to its Snowflake target name ([linked-servers.md](linked-servers.md#fix-process), steps 1–3). A table with no target is a missing dependency: `cur_reconciler`, not a stub.
3. **Un-double the quotes.** Inside the T-SQL literal `''Y''` is the remote query's `'Y'`.
4. **Translate the query** from the remote dialect to Snowflake: for Oracle, `NVL` and `DECODE` exist in Snowflake, `SYSDATE` → `CURRENT_TIMESTAMP()`, `ROWNUM <= n` → `LIMIT n`, and `TO_DATE(x, fmt)` keeps its name but check the format elements. For SQL Server, translate as any T-SQL.
5. **Replace the call with a derived table** and keep the alias the query used (`AS g`). Delete the marker.
6. **Check comparisons against local columns.** The remote server compared strings with its own rules (Oracle is case-sensitive; a SQL Server is usually case-insensitive). A join written `g.ACCT = d.Key COLLATE DATABASE_DEFAULT` has a [SSC-FDM-TS0080](SSC-FDM-TS0080.md) next to it.
7. Deploy and run the tests.

## Examples

### Before

```sql
CREATE OR REPLACE VIEW etl.vw_GlAccounts AS
SELECT g.ACCT, g.DESCRIPTION, g.ACCT_TYPE
FROM
  !!!RESOLVE EWI!!! /*** SSC-EWI-TS0086 - OPENQUERY NODE NEEDS TO BE CHECKED. ***/!!!
  OPENQUERY(LEGACY_ORA, 'SELECT ACCT, DESCRIPTION, ACCT_TYPE, ENABLED_FLAG FROM GL.ACCOUNTS WHERE ENABLED_FLAG = ''Y''') AS g;
```

### After

```sql
-- GL.ACCOUNTS was landed in Snowflake as LEGACYGL.GL.ACCOUNTS (registry target)
CREATE OR REPLACE VIEW etl.vw_GlAccounts AS
SELECT g.ACCT, g.DESCRIPTION, g.ACCT_TYPE
FROM (
  SELECT ACCT, DESCRIPTION, ACCT_TYPE, ENABLED_FLAG
  FROM LEGACYGL.GL.ACCOUNTS
  WHERE ENABLED_FLAG = 'Y'
) AS g;
```

## Key Points

- Translate the string from the remote server's dialect, not from T-SQL.
- Keep the query's columns and filter exactly; a pass-through query often filters on the remote side for a reason (enabled rows, one period).
- Do not point the derived table at a local object that only looks like the remote one. If the registry has no target, the object is a missing dependency.
- `OPENQUERY` against the local server itself (a loopback) is just a local query: unwrap it the same way.

## Resources

- [SQL Server OPENQUERY](https://learn.microsoft.com/en-us/sql/t-sql/functions/openquery-transact-sql)
- [Snowflake: subqueries](https://docs.snowflake.com/en/user-guide/querying-subqueries)
