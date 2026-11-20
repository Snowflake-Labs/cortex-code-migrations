# SSC-EWI-TS0077 — SQL Server Collation Not Supported

SnowConvert could not map the SQL Server collation in a `COLLATE` clause to a Snowflake collation specification, so it commented out the clause together with its marker. The code **compiles**, but the column or comparison now uses Snowflake's default, a binary comparison (case- and accent-sensitive, code-point order). A collation SnowConvert can map (`Latin1_General_CI_AS` → `COLLATE 'EN-CI-AS'`, any `_BIN2` → `COLLATE 'utf8'`) gets no SSC-EWI-TS0077, at most an SSC-FDM-TS0002 for an option it dropped.

Write the clause back with the Snowflake specification that compares the same way: [the T-SQL guide](../../../../rule-engine/resolving-ewis/reference/SSC-EWI-TS0077.md) maps each SQL Server collation, and [SSC-FDM-TS0080](../../../../rule-engine/resolving-ewis/reference/SSC-FDM-TS0080.md) covers `COLLATE DATABASE_DEFAULT` and the source database's default. Leave the clause out only where the source collation was binary too.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!`, commented out with the `COLLATE` clause |
| Breaks compilation? | **No** (the comparison silently becomes binary) |
| Frequency | Low (once per `COLLATE` with an unmapped collation) |
| Common action | Replace the two commented lines with a live `COLLATE '<spec>'` (`Turkish_CI_AS` → `'tr-ci'`, `Albanian_CI_AI` → `'sq-ci-ai'`; legacy `_BIN` → `'utf8'` as the closest) |

## Identification

The marker names the collation, and the clause follows it, both commented out in place:
```
-- !!!RESOLVE EWI!!! /*** SSC-EWI-TS0077 - COLLATION <name> NOT SUPPORTED ***/!!!
-- COLLATE <name>
```

```sql
SELECT
   CustomerName
   -- !!!RESOLVE EWI!!! /*** SSC-EWI-TS0077 - COLLATION Turkish_CI_AS NOT SUPPORTED ***/!!!
   -- COLLATE Turkish_CI_AS
   AS CustomerName
FROM customers
```

## Fix Patterns

### Pattern 1: Case-insensitive collation on a column expression

```sql
-- After: replaces the two commented lines
SELECT
   CustomerName COLLATE 'tr-ci' AS CustomerName
FROM customers
```

### Pattern 2: Case- and accent-insensitive collation on a comparison

```sql
-- Before
WHERE
   col_a
   -- !!!RESOLVE EWI!!! /*** SSC-EWI-TS0077 - COLLATION Albanian_CI_AI NOT SUPPORTED ***/!!!
   -- COLLATE Albanian_CI_AI
   = col_b

-- After: 'abc' = 'ÀBC' stays true, as in the source
WHERE col_a COLLATE 'sq-ci-ai' = col_b
```

### Pattern 3: Legacy binary collation on ORDER BY

SnowConvert maps `_BIN2` to `'utf8'` itself; legacy `_BIN` in a language it does not map gets this marker.

```sql
-- Before
ORDER BY
   LastName
   -- !!!RESOLVE EWI!!! /*** SSC-EWI-TS0077 - COLLATION Albanian_BIN NOT SUPPORTED ***/!!!
   -- COLLATE Albanian_BIN

-- After: code-point order, the closest Snowflake has to legacy BIN
ORDER BY LastName COLLATE 'utf8'
```

`'utf8'` is also Snowflake's default, so `ORDER BY LastName` alone sorts the same; writing it keeps the intent visible.

Legacy `_BIN` is not exact code-point order: SQL Server sorts the first character by code point and the rest by byte value (UTF-16 little-endian bytes for `nvarchar`), so two values that share a first character can sort the other way round in Snowflake (`'aĀ'` and `'aÿ'`). Equality is unaffected. Where values hold characters above U+00FF after the first, check affected `ORDER BY`, `MIN` and `MAX` results against the source, and `note` a difference only there as a documented ordering difference.

## Key Points

- **Must** replace the commented-out marker and clause with a live `COLLATE` that names the Snowflake specification. The code compiles without it, so a missed marker shows up only as wrong results.
- Only `_BIN2` matches Snowflake's binary default exactly. Legacy `_BIN` compares equal strings the same way but can sort differently after the first character (Pattern 3). A case-sensitive linguistic collation (`_CS_AS`) compares equal strings the same way, but sorts linguistically (`a` before `B`) where binary sorts `B` before `a`: use `COLLATE '<lang>-cs'` where the order matters.
- A case-insensitive source collation (`_CI_`) needs `-ci`; the binary default makes `'abc'` and `'ABC'` different, which shows up as missing join rows, extra groups or failed lookups.
- Multiple `SSC-EWI-TS0077` markers may appear in a single query if several columns used COLLATE.
