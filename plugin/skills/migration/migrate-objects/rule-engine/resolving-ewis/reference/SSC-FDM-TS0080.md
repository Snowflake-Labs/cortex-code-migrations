# SSC-FDM-TS0080 - COLLATE DATABASE_DEFAULT Removed

`COLLATE DATABASE_DEFAULT` means "compare with this database's default collation". The converted code does not know the source database's default, so SnowConvert comments the clause out and the comparison falls back to Snowflake's default: binary, so case- and accent-sensitive. The code compiles; the data may not match.

This guide also covers the [source database's default collation](#source-database-collation), which matters for every string comparison, marked or not.

## Quick Reference

| Source database default | Snowflake fix for `x COLLATE DATABASE_DEFAULT = y` |
|---|---|
| case-insensitive (`SQL_Latin1_General_CP1_CI_AS`, `Latin1_General_CI_AS`, ...) | `x COLLATE 'en-ci' = y` |
| case- and accent-insensitive (`..._CI_AI`) | `x COLLATE 'en-ci-ai' = y` |
| binary (`..._BIN2`) | nothing: Snowflake's binary default compares the same way |
| case-sensitive (`Latin1_General_CS_AS`) | nothing for `=`; `COLLATE 'en-cs'` where the order matters (`ORDER BY`, `<`, `MIN`/`MAX`): it sorts `a` before `B`, binary sorts `B` before `a` |
| another language (`French_CI_AS`, `Japanese_CI_AS`) | that locale, mapped as in [SSC-FDM-TS0002](SSC-FDM-TS0002.md#mapping) (`'fr-ci'`, `'ja-ci'`) |

## Identification

The marker and the clause are both commented out in place:

```sql
WHERE
  col1
-- --** SSC-FDM-TS0080 - COLLATE DATABASE_DEFAULT REMOVED - THE SOURCE DATABASE DEFAULT COLLATION IS NOT PART OF THE CONVERTED CODE, SO THE COMPARISON FALLS BACK TO SNOWFLAKE'S BINARY COLLATION. ADD AN EXPLICIT COLLATE IF A CASE OR ACCENT INSENSITIVE COMPARISON IS REQUIRED. **
-- COLLATE DATABASE_DEFAULT
  = 'x';
```

It is common in joins across databases with different collations: SQL Server refuses such a join (`Msg 468`, "Cannot resolve the collation conflict"), so the author added `COLLATE DATABASE_DEFAULT` on one or both sides.

## Fix Process

1. **Find which database's default applied.** `DATABASE_DEFAULT` takes the current database's collation: for a view, procedure or function, the database it is created in, not the database of the table it reads; for a temporary table, the connection's current user database.
2. **Read that default from the source**, once per project: `query_source` with `SELECT name, collation_name FROM sys.databases` (and `SELECT SERVERPROPERTY('Collation')` for the server default).
3. **Case- or accent-insensitive default** → uncomment nothing; add `COLLATE '<spec>'` from the table above to the same side of the comparison, and delete the two commented lines.
4. **Case-sensitive or binary default** → no change is needed. Leave the comment, or delete it.
5. Run the tests. A join that lost rows in Snowflake only by letter case is this FDM.

## Examples

```sql
-- Before: Reporting's default is SQL_Latin1_General_CP1_CI_AS
JOIN PolicyAdmin.dbo.Policy AS p ON p.PolicyNo = c.PolicyNo
-- --** SSC-FDM-TS0080 - COLLATE DATABASE_DEFAULT REMOVED - ... **
-- COLLATE DATABASE_DEFAULT

-- After
JOIN PolicyAdmin.dbo.Policy AS p ON p.PolicyNo = c.PolicyNo COLLATE 'en-ci'
```

## Source database collation

SQL Server compares strings with the column's collation, which defaults to the database's, which defaults to the server's. SnowConvert carries over only collations written in the code. A column with none becomes a plain Snowflake string, which compares in binary, **with no marker**.

**Case-insensitive source database** (the default on an en-US install is `SQL_Latin1_General_CP1_CI_AS`): `=`, `IN`, `GROUP BY`, `DISTINCT`, `UNION` and joins on strings treat `'abc'` and `'ABC'` as equal in the source and different in Snowflake. Test diffs show missing join rows, extra groups, or a `NOT EXISTS` that keeps rows.

- Fix the object under repair: `COLLATE 'en-ci'` on the comparison, or on the column in the table's DDL when every query on it needs it. A case-insensitive column compares more slowly, which SnowConvert flags as `SSC-PRF-0002`; that is expected.
- Changing `DEFAULT_DDL_COLLATION` on the target database or schema changes every later table in the project. That is a project-wide decision: escalate it with the evidence, do not set it from one object.

**Case-sensitive source database** (for example one created `COLLATE Latin1_General_CS_AS`):

- Equality already matches Snowflake's binary default. Ordering can differ: a linguistic collation sorts `a` before `B`, binary sorts `B` before `a`. If only `ORDER BY` output differs, add `COLLATE 'en-cs'` to the `ORDER BY` key.
- Object names are case-sensitive in such a database: `dbo.Claim` and `dbo.CLAIM` can be two tables. Snowflake folds unquoted names to upper case, so they collide. Escalate with "rename one of them" / "quote the identifiers project-wide"; do not merge them or drop one.
- A reference whose case differs from the object's definition (`dbo.claim` for `dbo.Claim`) can be reported as a missing dependency (`SSC-FDM-0007`) although the object is in the project. Check the registry for the name ignoring case before treating it as missing.

**Two databases with different defaults**: a join between them is exactly where the source needed `COLLATE` (this FDM, or [SSC-FDM-TS0002](SSC-FDM-TS0002.md)). A join with no `COLLATE` at all between a case-sensitive and a case-insensitive column fails on the source with `Msg 468` when it runs, so the source cannot produce a baseline: escalate per DIAGNOSE_FIX ("source cannot run as written").

## Key Points

- `DATABASE_DEFAULT` belongs to the object's own database. Read it from the source; do not assume `CI`.
- Add `COLLATE` to one side of the comparison only; Snowflake applies it to the comparison.
- A comparison of two columns with different explicit collations can be refused by Snowflake; put the `COLLATE` on the comparison so both sides use one.
- `note` the collation you chose and which source default it came from.

## Resources

- [Snowflake collation support](https://docs.snowflake.com/en/sql-reference/collation), [COLLATE](https://docs.snowflake.com/en/sql-reference/functions/collate), [DEFAULT_DDL_COLLATION](https://docs.snowflake.com/en/sql-reference/parameters#default-ddl-collation)
- [SQL Server collation and Unicode support](https://learn.microsoft.com/en-us/sql/relational-databases/collations/collation-and-unicode-support)
