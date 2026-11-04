# SSC-EWI-SSIS0036 — Flat File Source Feature Not Supported

A Flat File connection uses a setting SnowConvert cannot express in the generated `FILE FORMAT`. `{0}` names it; the engine emits exactly six values (below). For a Multiple Flat Files connection SnowConvert generated a placeholder model of `null` columns; for the other five it generated the full staging model and left the setting out of the format. Several of these markers can head the same model. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (once per unsupported setting per Flat File Source) |
| Common action | Depends on `{0}`: see the table |

| `{0}` | Trigger in the connection manager | What was generated |
|---|---|---|
| `MULTIPLE FLAT FILES CONNECTION MANAGER` | `DTS:CreationName="MULTIFLATFILE"` | `SELECT null AS ...` placeholder, no `FROM`, no format |
| `PER-COLUMN DELIMITERS` | `DTS:ColumnDelimiter` differs between columns (the last column's, the row end, not counted) | `FIELD_DELIMITER` = the first column's delimiter |
| `PER-COLUMN TEXT QUALIFIED SETTINGS` | `DTS:TextQualified` differs between columns | `FIELD_OPTIONALLY_ENCLOSED_BY` (if any) applied to every column |
| `MULTI-CHARACTER TEXT QUALIFIER` | `DTS:TextQualifier` decodes to 2+ characters | no `FIELD_OPTIONALLY_ENCLOSED_BY` |
| `CODEPAGE <n>` | non-Unicode file, `DTS:CodePage` not 65001 and not in SnowConvert's map | no `ENCODING` (read as UTF-8) |
| `LOCALEID <n>` | `DTS:LocaleID` not 1033 (en-US), 2057, 3081 or 10250; `0` = not set | no `DATE_FORMAT` |

The three delimiter/qualifier checks are skipped for `FixedWidth` files. The format is in `etl_configuration/file_formats/file_formats.sql`, created `IF NOT EXISTS`: after changing it in an account where it already exists, run it as `CREATE OR REPLACE FILE FORMAT`.

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0036 - PER-COLUMN DELIMITERS IS NOT SUPPORTED. ***/!!!
SELECT
   $1 :: NUMERIC AS source_customer_id,
   $2 :: VARCHAR(50) AS source_customer_name,
   $3 :: VARCHAR(10) AS source_region
FROM
   @public.landing_stage/ssis/FallbackFlatFileLoad/OrdersFlatFile/input.csv (FILE_FORMAT => 'FallbackFlatFileLoad_Data_Flow_Task_Orders_Source')
WHERE
   METADATA$FILE_ROW_NUMBER > 1
```

## Fix Patterns

### Pattern 1: `MULTIPLE FLAT FILES CONNECTION MANAGER`

The `ConnectionString` lists files separated by `|`, or holds a wildcard (`C:\in\orders_*.csv`); SSIS read them one after another as one input. Write the format from the connection's settings (as in [SSC-EWI-SSIS0027](SSC-EWI-SSIS0027.md)) and read the whole land folder with a regex `PATTERN`:

```sql
FROM
   @public.landing_stage/ssis/LoadOrders/OrdersFiles/ (FILE_FORMAT => 'LoadOrders_Data_Flow_Task_Orders_Source', PATTERN => '.*/orders_[^/]*[.]csv')
WHERE
   METADATA$FILE_ROW_NUMBER > 1
```

`C:\in\orders_*.csv` becomes `'.*/orders_[^/]*[.]csv'`: the `.*/` makes the name begin right after a `/` (`'.*orders_.*[.]csv'` also reads `old_orders_1.csv`), and `[^/]*` keeps `*` within one name, as the Windows wildcard did. The pattern can still match a file of that name in a subfolder; if the folder has any, add `AND METADATA$FILENAME RLIKE 'ssis/LoadOrders/OrdersFiles/orders_[^/]*[.]csv'` to the `WHERE`. For a `|`-separated list, name each file exactly: `METADATA$FILENAME IN ('ssis/LoadOrders/OrdersFiles/a.csv', ...)` with the folder as the `FROM` path. `METADATA$FILE_ROW_NUMBER` restarts in every file, so each file's header row is skipped. Keep the placeholder's column names and order.

### Pattern 2: `PER-COLUMN DELIMITERS`

One `FIELD_DELIMITER` cannot split `a,b|c`. Change the format to `FIELD_DELIMITER = NONE` (each line is `$1`) and split with one regex group per column, in column order:

```sql
WITH lines AS (
   SELECT $1 AS line
   FROM @public.landing_stage/ssis/FallbackFlatFileLoad/OrdersFlatFile/ (FILE_FORMAT => 'FallbackFlatFileLoad_Data_Flow_Task_Orders_Source')
   WHERE METADATA$FILENAME = 'ssis/FallbackFlatFileLoad/OrdersFlatFile/input.csv'
     AND METADATA$FILE_ROW_NUMBER > 1
)
SELECT
   REGEXP_SUBSTR(line, '^([^,]*),([^|]*)[|](.*)$', 1, 1, 'e', 1) :: NUMERIC AS source_customer_id,
   REGEXP_SUBSTR(line, '^([^,]*),([^|]*)[|](.*)$', 1, 1, 'e', 2) :: VARCHAR(50) AS source_customer_name,
   REGEXP_SUBSTR(line, '^([^,]*),([^|]*)[|](.*)$', 1, 1, 'e', 3) :: VARCHAR(10) AS source_region
FROM lines
```

The generated `FROM .../input.csv` is a prefix that also reads `input.csv.bak`, so the rewrite reads the folder and names the file in `METADATA$FILENAME` ([SSC-EWI-SSIS0025](SSC-EWI-SSIS0025.md), Pattern 1). Write `|` as `[|]` and `.` as `[.]` in the pattern. If the file is also text-qualified and values contain delimiters, the regex no longer fits: needs-user.

### Pattern 3: `PER-COLUMN TEXT QUALIFIED SETTINGS`

If the format has no `FIELD_OPTIONALLY_ENCLOSED_BY`, the flags change nothing: remove the marker. Otherwise Snowflake strips the qualifier only from fields that start with it, so the difference matters only when a column SSIS did not unquote has values starting with the qualifier. Check a sample; if none do, remove the marker. If some do, set `FIELD_OPTIONALLY_ENCLOSED_BY = NONE` and unquote just the qualified columns: `REGEXP_REPLACE($2, '^"(.*)"$', '\\1')` (valid only when those values never contain the delimiter).

### Pattern 4: `MULTI-CHARACTER TEXT QUALIFIER`

Snowflake's `FIELD_OPTIONALLY_ENCLOSED_BY` takes one character (`"` or `'`). The values arrive with the qualifier still on them. When qualified values never contain the delimiter, strip it per text column: `REGEXP_REPLACE($2, '^~~|~~$', '')` for qualifier `~~` (escape regex characters: `[|]`, `[.]`, `[*]`). When they can contain the delimiter, the columns split wrongly: add `-- NEEDS-USER: <file> uses qualifier '<q>' around values containing '<delimiter>'; needs pre-processing or a single-character qualifier` and mark as needs-user.

### Pattern 5: `CODEPAGE <n>`

Add the `ENCODING` Snowflake has for that code page; without one, non-ASCII bytes are read as UTF-8 and fail or turn into replacement characters.

| SSIS code page | `ENCODING` | SSIS code page | `ENCODING` |
|---|---|---|---|
| 28592 | `'ISO88592'` | 874 | `'WINDOWS874'` |
| 28595 | `'ISO88595'` | 20866 | `'KOI8R'` |
| 28596 | `'ISO88596'` | 51932 | `'EUCJP'` |
| 28597 | `'ISO88597'` | 51949 | `'EUCKR'` |
| 28598 | `'ISO88598'` | 50220 | `'ISO2022JP'` |
| 28599 | `'ISO88599'` | 50225 | `'ISO2022KR'` |
| 28605 | `'ISO885915'` | 12000 / 12001 | `'UTF32LE'` / `'UTF32BE'` |
| 20127 (ASCII) | omit (UTF-8 default) | 20420 / 20424 | `'IBM420'` / `'IBM424'` |
| 936 (GBK) | `'GB18030'` (superset) | | |

Code pages with no Snowflake encoding (1257, 1258, OEM 437/850/852/866, EBCDIC 37/500/1140): the file must be converted to UTF-8 before it lands. Add `-- NEEDS-USER: code page <n> has no Snowflake ENCODING; convert <file> to UTF-8 when landing it` and mark as needs-user.

### Pattern 6: `LOCALEID <n>`

The locale only changed how SSIS parsed dates and numbers into typed output columns. If every column the model casts is a string, remove the marker. Otherwise look at a sample of the file and put the format in the conversion itself; the stage read returns text, and a plain `::DATE` cast parses it with the session's `DATE_INPUT_FORMAT`:

```sql
TO_DATE($3, 'DD.MM.YYYY') AS loss_dt,                                        -- de-DE 1031, nb-NO 1044
TO_TIMESTAMP($4, 'DD.MM.YYYY HH24:MI:SS') AS created_at,
TO_NUMBER(REPLACE(REPLACE($5, '.', ''), ',', '.'), 18, 2) AS amount          -- 1.234,56
```

Keep any `COALESCE(..., default)` wrapper SnowConvert generated (sources with `RetainNulls` false). `LOCALEID 0` means the connection has no `DTS:LocaleID`: check the sample, and the package's own `DTS:LocaleID`; when the file holds ISO or US-format values, the generated casts are fine and only the marker goes.

## Key Points

- **Must** remove every `!!!RESOLVE EWI!!!` marker; for the Multiple Flat Files placeholder never by deleting it alone (it would load one row of NULLs).
- Check the generated `FIELD_DELIMITER` too: SnowConvert decodes only `,`, `|`, tab and `;`; any other delimiter (`~`, a multi-character one) comes out as `','`. Snowflake accepts multi-character delimiters, so write the real one.
- A file with no file name is [SSC-EWI-SSIS0025](SSC-EWI-SSIS0025.md); a non-newline header row delimiter is [SSC-EWI-SSIS0035](SSC-EWI-SSIS0035.md); `RaggedRight` is [SSC-EWI-SSIS0034](SSC-EWI-SSIS0034.md).
