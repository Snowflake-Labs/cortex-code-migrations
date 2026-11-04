# SSC-EWI-TS0143 - SQL CLR Routine Declared With EXTERNAL NAME

SnowConvert keeps a SQL CLR function or procedure (`CREATE FUNCTION|PROCEDURE ... AS EXTERNAL NAME Assembly.[Namespace.Class].Method`) as written, because the .NET assembly that holds the method body is not part of the migrated code. The `!!!RESOLVE EWI!!!` marker breaks compilation, so the object never deploys until it is rewritten.

A CLR routine is **not** a "no Snowflake equivalent" park. Most CLR code in the field is a thin wrapper around a .NET library call (regex, string distance, string aggregation, number series, check digits) that Snowflake has as a builtin, a SQL UDF or a Python UDF. Rewrite it when you know what the method does; park only the cases in [What still parks](#what-still-parks).

## Quick Reference

| CLR object (typical) | Snowflake rewrite | Trap |
|---|---|---|
| `Regex.IsMatch(input, pattern)` scalar | `REGEXP_INSTR(input, pattern) > 0` | **Not** `REGEXP_LIKE`: it is anchored at both ends, `IsMatch` matches anywhere. See [Regex](#regex) |
| `Regex.Replace(input, pattern, replacement)` | `REGEXP_REPLACE(input, pattern, replacement)` | `$1` in the replacement becomes `\\1` (groups 1–9 only) |
| `Regex.Split` TVF | Python UDTF (`re.split`), or `SPLIT_TO_TABLE` when the delimiter is plain text | `SPLIT_TO_TABLE` splits on text, not a regex |
| Levenshtein distance | `EDITDISTANCE(a, b)` | both are case-sensitive and ignore collation |
| Normalize white space | Python UDF `' '.join(s.split())` | .NET counts NBSP (U+00A0) and the other Unicode spaces as white space; Snowflake's `\s` and `TRIM` do not |
| String-concatenation aggregate (`dbo.Concat(value, ', ')`) | `LISTAGG(value, ', ')` | add `WITHIN GROUP (ORDER BY ...)` only if an order is wanted; the CLR aggregate has none |
| Number-series TVF (`dbo.Series(start, stop, step)`) | SQL UDTF over `ARRAY_GENERATE_RANGE`, or `GENERATOR` | the CLR series includes `stop`, `ARRAY_GENERATE_RANGE` excludes it; step 0 is an error in Snowflake |
| Check digits (Luhn, VIN, IBAN) | SQL UDF, or Python UDF ported from the .NET source | |
| Great-circle distance on a point UDT | `HAVERSINE(lat1, lon1, lat2, lon2)` | same 6371 km sphere as the usual .NET code |

## Identification

The marker sits above the kept declaration:

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-TS0143 - SQL CLR ROUTINES DECLARED WITH EXTERNAL NAME ARE NOT SUPPORTED IN SNOWFLAKE, AND THE ASSEMBLY HOLDING THE METHOD IS NOT PART OF THE MIGRATED CODE, SO NO EQUIVALENT BODY CAN BE GENERATED. THE DECLARATION IS KEPT AS WRITTEN FOR A REDESIGN. ***/!!!
CREATE FUNCTION dbo.RegexIsMatch (@input NVARCHAR(4000), @pattern NVARCHAR(4000))
RETURNS BIT
AS EXTERNAL NAME MeridianRegex.[Meridian.Sql.RegexFunctions].IsMatch;
```

Related objects that get no TS0143:

- `CREATE ASSEMBLY` and `CREATE AGGREGATE ... EXTERNAL NAME` register no code unit. A CLR aggregate shows up only at its call sites (`dbo.Concat(col, ', ')`), usually as an unknown function at deploy.
- `CREATE TYPE ... EXTERNAL NAME` (a CLR UDT) gets `SSC-EWI-0073`. Snowflake has no user-defined types.
- A CLR trigger (`CREATE TRIGGER ... AS EXTERNAL NAME`) parks: see below.

## Fix Process

1. **Find out what the method does.** In order of preference:
   - The .NET source, when the project has it (a `clr-src/`, `CLR/`, `*.cs` / `*.vb` folder next to the SQL, or the assembly's project in the customer's repo). Read the method named in `EXTERNAL NAME Assembly.[Namespace.Class].Method`.
   - The source system: the CLR routine runs there, so `query_source` with representative inputs (NULLs, empty strings, edge values) pins its behaviour down. The test baseline does the same.
   - A well-known library, recognised from the assembly and method names (for example a regex or string utility pack). Say in a `note` which one you assumed.

   If none of these tells you what it does, escalate with the asks "provide the CLR source" / "skip the object". Do not guess a body from the routine's name alone.
2. **Check [What still parks](#what-still-parks).** If the routine is one of those, escalate with that section's options.
3. **Write the Snowflake object under the same name and signature**, so the converted call sites keep working: a SQL UDF, a SQL UDTF (`RETURNS TABLE (...)`), or a Python UDF/UDTF (`LANGUAGE PYTHON RUNTIME_VERSION = '3.11' HANDLER = ...`) when SQL cannot express the logic. Map `SqlString` to `VARCHAR`, `SqlInt32` to `INT`, `SqlBoolean` (T-SQL `BIT`) to `BOOLEAN`, `SqlDouble` to `FLOAT`.
4. **Keep the NULL behaviour.** CLR methods usually return NULL when an argument is NULL (`if (input.IsNull) return SqlString.Null`). Snowflake builtins mostly do too; a Python handler receives `None` and must return `None`.
5. **Replace the file's whole `CREATE ... EXTERNAL NAME` statement** in the converted file with the new object, and remove the `!!!RESOLVE EWI!!!` line.
6. **Deploy and run the tests.** The baseline was captured from the real CLR on the source, so a semantic trap (anchoring, white space, inclusive bounds) shows up as a diff, not a deploy error.

## Regex

.NET `System.Text.RegularExpressions` and Snowflake's POSIX-style regex differ:

- **Anchoring.** `Regex.IsMatch` finds a match anywhere. `REGEXP_LIKE` and `RLIKE` match the *whole* string, so `REGEXP_LIKE('ABC-123', '\\d+')` is FALSE where `IsMatch` is true. Use `REGEXP_INSTR(input, pattern) > 0`, or wrap the pattern as `'.*(' || pattern || ').*'` with the `s` parameter.
- **Unsupported syntax.** Lookahead and lookbehind (`(?=`, `(?!`, `(?<=`, `(?<!`), named groups (`(?<name>...)`), atomic groups and inline options (`(?i)`) fail at run time with an invalid-regex error. Lazy quantifiers (`*?`, `+?`) are worse: Snowflake accepts them and matches greedily, with no error, so `REGEXP_SUBSTR('<a><b>', '<.+?>')` returns `'<a><b>'` where .NET returns `'<a>'`. Always move a pattern with a lazy quantifier to Python. For the others, when the pattern is a literal at the call site, rewrite it; when patterns come from a table or a parameter, use a Python UDF with `re` (it supports lookarounds and lazy quantifiers) and keep the name.
- **Character classes.** Snowflake's `\d` and `\w` are ASCII only; .NET's match any Unicode digit or letter. Only matters for non-ASCII data.
- **Case and options.** A CLR method that passes `RegexOptions.IgnoreCase` becomes the `'i'` parameter (`REGEXP_INSTR(s, p, 1, 1, 0, 'i')`). `RegexOptions.CultureInvariant` alone changes nothing.
- **Replacement strings.** .NET `$1` … `$9` become `\\1` … `\\9`. `$0`, `${name}` and `$$` have no direct form: wrap the whole pattern in a group, number the named groups, write a literal `$`.
- **Backslashes in literals.** In a Snowflake single-quoted literal a backslash is an escape, so a T-SQL call `dbo.RegexIsMatch(Zip, '^\d{5}$')` becomes `'^\\d{5}$'` (or `$$^\d{5}$$`). A pattern passed in a variable or read from a table needs no change.
- **Split.** `Regex.Split` keeps empty tokens, and a pattern with capture groups also returns the captured text as tokens. Python `re.split` does the same; `SPLIT_TO_TABLE` (1-based `INDEX`) only splits on a fixed string.

## Examples

### Scalar wrapper: regex IsMatch

```sql
-- Before
!!!RESOLVE EWI!!! /*** SSC-EWI-TS0143 - SQL CLR ROUTINES DECLARED WITH EXTERNAL NAME ARE NOT SUPPORTED IN SNOWFLAKE, ... ***/!!!
CREATE FUNCTION dbo.RegexIsMatch (@input NVARCHAR(4000), @pattern NVARCHAR(4000))
RETURNS BIT
AS EXTERNAL NAME MeridianRegex.[Meridian.Sql.RegexFunctions].IsMatch;

-- After
CREATE OR REPLACE FUNCTION dbo.RegexIsMatch(input VARCHAR, pattern VARCHAR)
RETURNS BOOLEAN
AS
$$
    REGEXP_INSTR(input, pattern) > 0
$$;
```

`REGEXP_INSTR` returns NULL for a NULL argument, so `NULL > 0` keeps the CLR's NULL result. If converted call sites compare the result with `1` or `0` and the comparison fails to compile or to match, return `NUMBER(1)` instead, keeping the NULL: `CASE WHEN input IS NULL OR pattern IS NULL THEN NULL WHEN REGEXP_INSTR(input, pattern) > 0 THEN 1 ELSE 0 END`. Not `IFF(REGEXP_INSTR(input, pattern) > 0, 1, 0)`: `IFF` returns its false branch for a NULL condition, so a NULL input would become `0` and match `= 0` call sites.

### Aggregate: Concat

There is no object to write: rewrite each call site.

```sql
-- Before (call site; dbo.Concat is a CLR aggregate)
SELECT ClaimId, dbo.Concat(NoteText, '; ') AS Notes FROM dbo.ClaimNote GROUP BY ClaimId;

-- After
SELECT ClaimId, IFF(COUNT(NoteText) = 0, NULL, LISTAGG(NoteText, '; ')) AS Notes
FROM dbo.ClaimNote GROUP BY ClaimId;
```

`LISTAGG` skips NULLs like the CLR aggregate, but returns `''` for a group with no non-NULL value where the CLR's `IsNullIfEmpty` returns NULL; the `IFF` keeps that. Its delimiter must be a constant.

### Table-valued: Series

```sql
-- Before
!!!RESOLVE EWI!!! /*** SSC-EWI-TS0143 - ... ***/!!!
CREATE FUNCTION dbo.Series (@start INT, @stop INT, @stepBy INT)
RETURNS TABLE (Value INT)
AS EXTERNAL NAME MeridianValidation.[Meridian.Validation.Series].Generate;

-- After: inclusive stop, either direction, no rows for a zero or NULL step
CREATE OR REPLACE FUNCTION dbo.Series(start_value INT, stop_value INT, step_by INT)
RETURNS TABLE (VALUE INT)
AS
$$
    SELECT f.value::INT AS VALUE
    FROM TABLE(FLATTEN(INPUT => IFF(step_by IS NULL OR step_by = 0,
                                    ARRAY_CONSTRUCT(),
                                    ARRAY_GENERATE_RANGE(start_value, stop_value + SIGN(step_by), step_by)))) f
$$;
```

Callers change from `FROM dbo.Series(1, 10, 1)` to `FROM TABLE(dbo.Series(1, 10, 1))`.

### White space: a Python UDF where SQL is not faithful

```sql
CREATE OR REPLACE FUNCTION dbo.NormalizeWhitespace(s VARCHAR)
RETURNS VARCHAR
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
HANDLER = 'normalize'
AS
$$
def normalize(s):
    return None if s is None else ' '.join(s.split())
$$;
```

Python's `str.split()` splits on Unicode white space, as .NET `char.IsWhiteSpace` does. `TRIM(REGEXP_REPLACE(s, '\\s+', ' '))` misses NBSP and the other non-ASCII spaces.

## What still parks

Escalate these with real options; they need a redesign, not a rewrite:

| CLR construct | Why | Options to offer |
|---|---|---|
| Assembly with `PERMISSION_SET = EXTERNAL_ACCESS` or `UNSAFE` (file I/O, network, registry, COM) | the method reaches outside the database | re-platform the file read as a stage plus `COPY INTO`; an external access integration with a Python UDF; skip |
| CLR trigger (`CREATE TRIGGER ... EXTERNAL NAME`) | Snowflake has no triggers | a stream on the table plus a task; skip |
| CLR user-defined type (`CREATE TYPE ... EXTERNAL NAME`, `SSC-EWI-0073`) | Snowflake has no UDTs; every column, variable and method call (`col.Lat`, `Type::Parse(...)`) changes | redesign the column as `GEOGRAPHY` (`ST_MAKEPOINT(lon, lat)`), an `OBJECT`, or separate columns; skip |
| Aggregate or routine with no source and no way to observe it (an F# or C++/CLI assembly that is not in the project and does not load on the source) | its behaviour cannot be known | provide the source; a Python UDAF or window-function rewrite from a spec; skip |
| Dynamic invocation (`EXEC` of a CLR procedure through dynamic SQL) | the target is not known statically | same as the dynamic-SQL park |

## Key Points

- Same name, same arguments, same NULL behaviour: call sites should not need to change, except `TABLE(...)` around a UDTF and aggregate call sites.
- Rewrite from evidence (source, the source system's output, or a named library), never from the name alone, and `note` which evidence you used.
- Never use `REGEXP_LIKE` for `IsMatch`. Check the pattern for lookarounds and lazy quantifiers before choosing SQL over Python.
- A routine's deploy fixes nothing until its callers deploy too: a caller blocked on `Unknown function dbo.X` unblocks once `dbo.X` exists.

## Resources

- [REGEXP_INSTR](https://docs.snowflake.com/en/sql-reference/functions/regexp_instr), [REGEXP_REPLACE](https://docs.snowflake.com/en/sql-reference/functions/regexp_replace), [String functions (regular expressions)](https://docs.snowflake.com/en/sql-reference/functions-regexp)
- [EDITDISTANCE](https://docs.snowflake.com/en/sql-reference/functions/editdistance), [LISTAGG](https://docs.snowflake.com/en/sql-reference/functions/listagg), [ARRAY_GENERATE_RANGE](https://docs.snowflake.com/en/sql-reference/functions/array_generate_range), [HAVERSINE](https://docs.snowflake.com/en/sql-reference/functions/haversine)
- [Python UDFs](https://docs.snowflake.com/en/developer-guide/udf/python/udf-python-introduction), [SQL UDTFs](https://docs.snowflake.com/en/developer-guide/udf/sql/udf-sql-tabular-functions)
- [SQL Server CLR integration](https://learn.microsoft.com/en-us/sql/relational-databases/clr-integration/common-language-runtime-integration-overview)
