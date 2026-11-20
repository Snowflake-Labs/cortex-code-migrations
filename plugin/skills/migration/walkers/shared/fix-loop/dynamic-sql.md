# SSC-EWI-0030 — Dynamic SQL (SQL Server source)

Rewrite the SQL Server text inside a dynamic SQL string into valid Snowflake.

## Fix process

1. **Find the string.** It is usually **above** the `!!!RESOLVE EWI!!!` marker: search
   upward for the variable assignment / concatenation (`SQL_VAR := '...'`). Otherwise
   it is a literal argument in the marked statement itself. Edit those lines, not the marker line.
2. **Commented-out SQL** (`EXECUTE IMMEDIATE '--CREATE SCHEMA Planning'` is a no-op):
   if the statement is valid Snowflake after conversion, remove the `--` (checklist below).
3. **Transform** every occurrence inside the string per the tables below.
4. Remove the `!!!RESOLVE EWI!!!` marker only after the string is fixed.

## Mappings

| SQL Server | Snowflake |
|---|---|
| `[MyTable]` (simple alphanumeric) | `MyTable` |
| `[My Table]`, `[Order-Details]`, `[123Table]`, reserved word (`[SELECT]`, `[ORDER]`, `[TABLE]`, `[VALUES]`, …) | `"My Table"` — double-quote |
| `'a' + 'b'` | `'a' \|\| 'b'` |
| `@myvar` reference | `:myvar` |
| `' + @myvar + '` inside the string | `' \|\| :myvar \|\| '` |
| `DECLARE @myvar INT` | `myvar INT` in the DECLARE block |
| `SET @myvar = 1` | `myvar := 1` |
| `#temp`, `##global_temp` | `t_temp`, `t_global_temp` — every occurrence (create, insert, select, join, drop) |
| `EXEC(@sql)`, `sp_executesql` | `EXECUTE IMMEDIATE :sql` |
| `EXEC proc` | `CALL proc()` |
| `LIKE '[A-Z]%'` | `REGEXP_LIKE(col, '^[A-Z].*')` |
| `LIKE '%[^abc]%'` | `REGEXP_LIKE(col, '.*[^abc].*')` |
| `COLLATE Latin1_General_CI_AI` | `COLLATE 'en-ci-ai'`, or the `'i'` REGEXP flag |
| `sys.objects` / `sys.tables` | `INFORMATION_SCHEMA.TABLES` |
| `sys.schemas` / `sys.columns` / `sys.procedures` / `sys.views` / `sys.databases` | `INFORMATION_SCHEMA.SCHEMATA` / `COLUMNS` / `PROCEDURES` / `VIEWS` / `DATABASES` |
| `so.name` / `ss.name` / `so.type_desc` | `TABLE_NAME` / `TABLE_SCHEMA` / `TABLE_TYPE`; drop `schema_id` joins |

## Uncomment checklist

| Commented statement | Snowflake |
|---|---|
| `'--CREATE SCHEMA x'` | `'CREATE SCHEMA IF NOT EXISTS x'` |
| `'--CREATE TABLE x (...)'` | `'CREATE TABLE IF NOT EXISTS x (...)'` after type conversion |
| `'--DROP TABLE x'` | `'DROP TABLE IF EXISTS x'` |
| `'--TRUNCATE TABLE x'` | `'TRUNCATE TABLE IF EXISTS x'` |
| `CREATE INDEX` | Leave commented — no Snowflake equivalent |
| `CREATE TRIGGER` | Leave commented — Streams + Tasks is a redesign |
| `SELECT INTO #temp` | `CREATE TEMP TABLE t_temp AS SELECT` |
| `BULK INSERT` | `COPY INTO` |
