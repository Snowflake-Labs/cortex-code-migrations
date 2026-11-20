# SSC-EWI-SSIS0037 — SSIS Expression Function Not Reviewed

An SSIS expression calls a function that SnowConvert has not mapped to Snowflake, so it emitted the call unchanged. The function does not exist in Snowflake under that name (or behaves differently), and the marker **breaks compilation**. It lands in a dbt model (Derived Column, Conditional Split) or in orchestration SQL (Expression task, variable expression).

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low-moderate (once per unreviewed call) |
| Common action | Replace the call with its Snowflake equivalent from the table below |

## Identification

```sql
SELECT
   !!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0037 - SSIS EXPRESSION FUNCTION 'TOKEN' HAS NOT BEEN REVIEWED FOR SNOWFLAKE EQUIVALENCE ***/!!!
   TOKEN(Name, ',', 1) AS TokenResult,
   Name AS Name
FROM
   source_data
```

## Fix Patterns

| SSIS function | Snowflake | Watch for |
|---|---|---|
| `TOKEN(s, delims, n)` | `REGEXP_SUBSTR(s, '[^<delims>]+', 1, n)` | a NULL `s` gives NULL in both. Past the last token, Microsoft's remarks say NULL, as `REGEXP_SUBSTR` gives, but its own example shows `""`: when the next step compares the token with `""` or the target column is NOT NULL, use `IFF(s IS NULL, NULL, COALESCE(REGEXP_SUBSTR(...), ''))` |
| `TOKENCOUNT(s, delims)` | `COALESCE(REGEXP_COUNT(s, '[^<delims>]+'), 0)` | SSIS returns 0 for a NULL `s`, while `REGEXP_COUNT` returns NULL, hence the `COALESCE` |
| `CODEPOINT(s)` | `IFF(s = '', NULL, UNICODE(s))` | both use the first character; SSIS returns NULL for `""` where `UNICODE` returns 0 |
| `REPLICATE(s, n)` | `REPEAT(s, n)` | SSIS fails on a negative `n`, and Snowflake documents 0 as the least valid `n`: keep `n` from going negative |
| `REVERSE(s)` | `REVERSE(s)` | |
| `LN(x)` | `LN(x)` | |

Every *character* of `delims` is a delimiter, and leading delimiters are skipped. The regex also skips repeated delimiters mid-string (`a--b` has 2 tokens); Microsoft's pages don't say how SSIS counts those, so check a sample row when the data has them.

Inside the bracket expression, escape `-`, `]`, `^` and `\` with a backslash, doubled in a Snowflake string literal: delimiters `"-, "` become `'[^\\-, ]+'`.

```sql
-- Before
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0037 - SSIS EXPRESSION FUNCTION 'TOKEN' HAS NOT BEEN REVIEWED FOR SNOWFLAKE EQUIVALENCE ***/!!!
TRIM(TOKEN(AgencyPolicy, '-', 1))::VARCHAR(12) AS AgencyCode,
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0037 - SSIS EXPRESSION FUNCTION 'TOKENCOUNT' HAS NOT BEEN REVIEWED FOR SNOWFLAKE EQUIVALENCE ***/!!!
TOKENCOUNT(AgencyPolicy, '-')::INT AS TokenCount,

-- After
TRIM(REGEXP_SUBSTR(AgencyPolicy, '[^\\-]+', 1, 1))::VARCHAR(12) AS AgencyCode,
COALESCE(REGEXP_COUNT(AgencyPolicy, '[^\\-]+'), 0)::INT AS TokenCount,
```

`SPLIT_PART(s, '-', n)` is only equivalent when the value never has leading, trailing or repeated delimiters, because it keeps empty parts.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker.
- Keep each function's NULL result: `TOKEN` of NULL is NULL, so never `COALESCE` it to `''` when `s` is NULL; `TOKENCOUNT` of NULL is 0.
- Keep the casts SnowConvert wrote around the call (`(DT_STR,12,1252)` became `::VARCHAR(12)`).
- Check where the value goes next: a Conditional Split on `TokenCount != 2` keeps working only if the count matches SSIS's.
- For a function not in this table, find its documented SSIS behaviour, write the Snowflake expression, and add a row here.
