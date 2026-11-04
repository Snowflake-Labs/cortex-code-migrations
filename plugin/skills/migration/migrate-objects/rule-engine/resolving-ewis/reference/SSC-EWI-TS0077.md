# SSC-EWI-TS0077 - Collation Not Supported

SnowConvert could not map a SQL Server collation to a Snowflake collation specification (see the [mapping rules](SSC-FDM-TS0002.md#mapping)), so it commented out the `COLLATE` clause together with its marker. The code compiles, but the column or comparison now uses Snowflake's binary default, which is case- and accent-sensitive and sorts by code point. Most unmapped collations do have a Snowflake locale: write it.

For a `COLLATE` inside an SSIS or other ETL SQL statement, see also [the ETL fix-up guide](../../../actions/etl-stabilization/reference/ewi/SSC-EWI-TS0077.md).

## Quick Reference

| SQL Server collation | Snowflake specification | Difference to check |
|---|---|---|
| `Turkish_CI_AS` | `'tr-ci'` | dotted and dotless `i` (`I`, `ı`, `İ`, `i`): check rows that hold them |
| `German_PhoneBook_CI_AS` | `'de-ci'` | Snowflake lists no phone-book variant of `'de'`, so `ORDER BY` on names with `ä`, `ö`, `ü` can differ |
| `Traditional_Spanish_CI_AS` | `'es-ci'` | Snowflake lists no traditional variant of `'es'`, so `ORDER BY` on words with `ch` or `ll` can differ |
| `Cyrillic_General_CI_AS` | `'ru-ci'` (or the column's actual language) | |
| `Albanian_CI_AS`, `Greek_CI_AS`, `Polish_CI_AS`, ... | the language's ISO code: `'sq-ci'`, `'el-ci'`, `'pl-ci'` | |
| `*_BIN2` | `'utf8'` | none |
| `*_BIN` (old binary) | `'utf8'` (closest) | SQL Server sorts only the first character by code point and the rest by byte value, so `ORDER BY`, `MIN` and `MAX` can differ after the first character on characters above U+00FF |
| `Japanese_Bushu_Kakusu_*`, `Japanese_XJIS_*` | `'ja'` plus `-ci` / `-ai` | radical-stroke and XJIS orders have no Snowflake equivalent |
| `_CI` / `_AI` parts of any of these | `-ci` / `-ai` | |

## Identification

The marker is commented out with the clause, in place:

```sql
CREATE OR REPLACE TABLE dbo.Claimant (
  LastName VARCHAR(60)
--                     !!!RESOLVE EWI!!! /*** SSC-EWI-TS0077 - COLLATION German_PhoneBook_CI_AS NOT SUPPORTED ***/!!!
--                     COLLATE German_PhoneBook_CI_AS
  ,
```

In a query:

```sql
WHERE name = 'x'
  -- !!!RESOLVE EWI!!! /*** SSC-EWI-TS0077 - COLLATION Albanian_BIN NOT SUPPORTED ***/!!!
  -- COLLATE Albanian_BIN
  ;
```

## Fix Process

1. **Read the collation name** from the marker.
2. **Pick the Snowflake specification** from the table above: the language's locale, plus `-ci` for `_CI` and `-ai` for `_AI`; `'utf8'` for any binary collation.
3. **Write it where the clause was**: `LastName VARCHAR(60) COLLATE 'de-ci'` in the DDL, or `name COLLATE 'utf8' = 'x'` in a query (`Albanian_BIN` is binary). Delete the two commented lines.
4. **Run the tests.** Equality usually matches; an `ORDER BY` or a `MIN`/`MAX` on the column can still differ where the source used a special sort order (phone book, traditional, radical-stroke, legacy `_BIN`). If a test differs only there, `note` it as a documented ordering difference rather than inventing a sort key.
5. When a table changes, objects that compare its column change too: they now compare with the column's collation.

## Examples

```sql
-- Before
  City VARCHAR(60)
--                     !!!RESOLVE EWI!!! /*** SSC-EWI-TS0077 - COLLATION Turkish_CI_AS NOT SUPPORTED ***/!!!
--                     COLLATE Turkish_CI_AS
  ,

-- After
  City VARCHAR(60) COLLATE 'tr-ci',
```

## Key Points

- Leaving the clause out is a choice of binary comparison. Make it only when the source collation was binary too.
- `Japanese_CI_AS` is mapped by SnowConvert (`'ja-ci'`) and gets no TS0077.
- Do not apply a project-wide `DEFAULT_DDL_COLLATION` from one object: see [Source database collation](SSC-FDM-TS0080.md#source-database-collation).

## Resources

- [Snowflake collation specifications](https://docs.snowflake.com/en/sql-reference/collation#collation-specification)
- [SQL Server Windows collation names](https://learn.microsoft.com/en-us/sql/t-sql/statements/windows-collation-name-transact-sql)
