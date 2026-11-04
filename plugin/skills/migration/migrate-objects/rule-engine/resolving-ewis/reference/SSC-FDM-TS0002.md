# SSC-FDM-TS0002 - Collation For Some Values Not Supported

SnowConvert mapped a SQL Server collation to a Snowflake collation specification but had parts left over that Snowflake has no specifier for. The `COLLATE '<spec>'` it wrote compiles; the FDM names the parts it dropped. Most leftovers change nothing. One (`BIN`) changes the meaning.

## Quick Reference

| Leftover in the FDM | What it meant in SQL Server | Action |
|---|---|---|
| `CP1`, `CP1252`, ... | code page for `varchar` storage | none: Snowflake stores UTF-8 |
| `90`, `100`, `140` | collation version | none |
| `SC` | supplementary characters (surrogate pairs) handled as one character | none: Snowflake strings are UTF-8 |
| `UTF8` | UTF-8 storage for `varchar` | none |
| `KS`, `WS` | kana- and width-sensitive | none in most data; Snowflake has no kana or width specifier, and `-ci` also ignores character width, so a `_CI_..._WS` source becomes width-insensitive. Check only if the column holds Japanese text |
| `BIN` | binary comparison (old style) | **change the spec to `'utf8'`**: SnowConvert wrote a linguistic spec such as `'EN'` |

## Identification

An inline comment after the spec, with no `!!!RESOLVE EWI!!!`:

```sql
s VARCHAR(10) COLLATE 'EN-CI-AS' /*** SSC-PRF-0002 - CASE INSENSITIVE COLUMNS CAN DECREASE THE PERFORMANCE OF QUERIES ***/ /*** SSC-FDM-TS0002 - COLLATION FOR VALUE CP1 NOT SUPPORTED ***/,
```

In a query:

```sql
ON c.PolicyNo COLLATE 'EN-CI-AS' /*** SSC-FDM-TS0002 - COLLATION FOR VALUE CP1 NOT SUPPORTED ***/ = lim.PolicyNo
```

`VALUE X` names one leftover, `VALUES X,Y` several.

## Mapping

How SnowConvert maps a SQL Server collation (the first rule that applies wins):

| SQL Server | Snowflake |
|---|---|
| any name ending `_BIN2` or `_BIN2_UTF8` | `'utf8'`, no FDM |
| `Latin1_General_*`, `SQL_Latin1_General_*` | `'EN'` plus `-ci` / `-cs` / `-ai` / `-as` as written; other parts become this FDM |
| `Modern_Spanish_*`, `French_*` | `'ES'`, `'FR'`, the same way |
| `Japanese_CI_AS`, `Japanese_CI_AI`, `Japanese_CS_AS` | `'ja-ci'`, `'ja-ci-ai'`, `'ja'` |
| other `Japanese_*` with only `CI`/`CS`/`AI`/`AS`/`KS`/`WS` | `'ja'` plus `-ci`/`-ai`; `KS`/`WS` become this FDM |
| `Chinese_PRC_CI_AS`, `_CI_AI`, `_CS_AS`, `_CS_AI` | `'zh_hans_cn-ci'`, `'zh_hans_cn-ci-ai'`, `'zh_hans_cn'`, `'zh_hans_cn-ai'` |
| anything else (`Turkish_*`, `German_PhoneBook_*`, `Cyrillic_General_*`, `Japanese_BIN`, `Chinese_PRC_100_*`, ...) | not mapped: [SSC-EWI-TS0077](SSC-EWI-TS0077.md) |

Snowflake specifications are case-insensitive (`'EN-CI-AS'` = `'en-ci-as'`), and `-as` / `-cs` are the defaults.

## Fix Process

1. Read the leftover values in the FDM.
2. **`BIN` among them** → replace the spec with `'utf8'` (binary). `Latin1_General_BIN` sorts the first character by code point and the rest by byte value; `'utf8'` (code-point order) is the closest Snowflake spec, while `'EN'` compares linguistically and sorts differently.
3. **Only `CP1`, a version, `SC`, `UTF8`** → no change. The FDM comment is harmless; leave it.
4. **`KS` or `WS`** → no change unless the tests show a diff on Japanese text that differs only by kana or width. Then escalate: there is no Snowflake specifier for it.
5. Run the tests. If a join or filter still differs only by letter case, the other side of the comparison may be a column with no collation in a case-insensitive database: see [Source database collation](SSC-FDM-TS0080.md#source-database-collation).

## Examples

```sql
-- Before: Latin1_General_BIN became a linguistic spec
AccountCode VARCHAR(12) COLLATE 'EN' /*** SSC-FDM-TS0002 - COLLATION FOR VALUE BIN NOT SUPPORTED ***/,

-- After
AccountCode VARCHAR(12) COLLATE 'utf8',
```

## Key Points

- `BIN` is the only leftover that needs a change.
- A computed column with `COLLATE ..._BIN2` maps cleanly to `'utf8'` and gets no FDM.
- Snowflake applies a column's collation to every comparison of it. Some string functions do not accept collated input; if one fails with an error naming the collation, apply the collation to the comparison instead of the column.

## Resources

- [Snowflake collation support](https://docs.snowflake.com/en/sql-reference/collation)
- [SQL Server collation names](https://learn.microsoft.com/en-us/sql/t-sql/statements/windows-collation-name-transact-sql)
