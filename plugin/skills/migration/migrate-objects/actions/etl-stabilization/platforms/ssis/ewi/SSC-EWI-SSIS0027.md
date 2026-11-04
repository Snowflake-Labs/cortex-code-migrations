# SSC-EWI-SSIS0027 — Flat File Source Connection Manager Not Found

A Flat File Source references a connection manager SnowConvert could not find in the converted input, typically a project-level `.conmgr` (`connectionManagerID="{GUID}:external"` or `Project.ConnectionManagers[...]`) that was not part of the conversion. Without it there is no file, delimiter or column layout, so SnowConvert generated a placeholder model that selects `null` for every output column, with no `FROM` and no `FILE FORMAT`. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (once per Flat File Source whose connection is missing) |
| Common action | Rebuild the stage read from the `.conmgr`; needs-user if the `.conmgr` is not in the source tree |

## Identification

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0027 - FLAT FILE SOURCE CONNECTION MANAGER NOT FOUND. ***/!!!
SELECT
   null AS col_a,
   null AS col_b
```

In the `.dtsx`, the source's `<connection connectionManagerID="...">` names the manager. Search the project folder for a `.conmgr` whose `DTS:DTSID` or `DTS:ObjectName` matches.

## Fix Patterns

### Pattern 1: The `.conmgr` is in the source tree

Write the read the way SnowConvert writes it for a resolved connection. From `DTS:ObjectData/DTS:ConnectionManager`:

| `.conmgr` | Generated code |
|---|---|
| first column's `DTS:ColumnDelimiter` | `FIELD_DELIMITER` (`_x002C_` = `,`, `_x007C_` = `\|`, `_x0009_` = `\t`, `_x003B_` = `;`) |
| last column's `DTS:ColumnDelimiter` | `RECORD_DELIMITER`; omit it for `_x000D__x000A_` or `_x000A_` (newline is the default) |
| `DTS:TextQualifier` (one character) | `FIELD_OPTIONALLY_ENCLOSED_BY` |
| `DTS:CodePage`, `DTS:Unicode` | `ENCODING` (1252 → `'WINDOWS1252'`, Unicode → `'UTF16'`, 65001 → omit) |
| `DTS:HeaderRowsToSkip` | `SKIP_HEADER` |
| `DTS:ColumnNamesInFirstDataRow` + `DTS:DataRowsToSkip` | `WHERE METADATA$FILE_ROW_NUMBER > n` |
| file name of `DTS:ConnectionString` | the `METADATA$FILENAME` equality in the `WHERE`; the `FROM` path stops at its folder |
| each `DTS:FlatFileColumn`, in order | `$1`, `$2`, ... cast to the source's output column types |

```sql
-- etl_configuration/file_formats/file_formats.sql
CREATE FILE FORMAT IF NOT EXISTS LoadOrders_Data_Flow_Task_Orders_Source
TYPE = 'CSV'
FIELD_DELIMITER = ','
FIELD_OPTIONALLY_ENCLOSED_BY = '"'
ENCODING = 'WINDOWS1252'
EMPTY_FIELD_AS_NULL = TRUE;

-- models/staging/stg_flat_file__orders_source.sql
SELECT
   $1 :: NUMERIC AS col_a,
   $2 :: VARCHAR(50) AS col_b
FROM
   @public.landing_stage/ssis/projects/<connection folder>/ (FILE_FORMAT => 'LoadOrders_Data_Flow_Task_Orders_Source')
WHERE
   METADATA$FILENAME = 'ssis/projects/<connection folder>/orders.csv'
   AND METADATA$FILE_ROW_NUMBER > 1
```

Name the file in the `WHERE`, never at the end of the `FROM` path: a stage path is a prefix, so `.../orders.csv` also reads `orders.csv.bak` ([SSC-EWI-SSIS0025](SSC-EWI-SSIS0025.md), Pattern 1).

Keep the column names and order of the placeholder `SELECT`: downstream models select them. Take the land folder from another converted source of the same connection when there is one; otherwise use `ssis/<Package>/<Connection>/` and note the guess.

### Pattern 2: The `.conmgr` is not available

Leave the placeholder `SELECT` in place, add `-- NEEDS-USER: connection manager '<name>' (<GUID>) is missing from the input; provide its .conmgr or the file layout` and mark as needs-user.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker, but never by just deleting it: the placeholder then "works" and loads one row of NULLs.
- Re-converting with the `.conmgr` included gives the same result with less risk, when that is an option.
- After writing the read, check it against the other Flat File guides: [SSC-EWI-SSIS0025](SSC-EWI-SSIS0025.md) (no file name), [SSC-EWI-SSIS0034](SSC-EWI-SSIS0034.md) (format), [SSC-EWI-SSIS0036](SSC-EWI-SSIS0036.md) (code page, locale, qualifiers).
