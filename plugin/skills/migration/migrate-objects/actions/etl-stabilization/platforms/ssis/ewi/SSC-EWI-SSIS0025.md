# SSC-EWI-SSIS0025 — Flat File Source File Name Not Resolved

A Flat File Source's connection manager has a `ConnectionString` with no file name (empty, or a folder ending in `\`), no Foreach loop supplies the file, and no `ConnectionString` expression could be turned into a path. SnowConvert generated the full staging model, but its `FROM` reads `.../UNKNOWN_FILE` under the connection's land prefix. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (once per Flat File Source whose file name is unknown) |
| Common action | Read the connection's folder and select the real file by its exact `METADATA$FILENAME`, or read several files with a `PATTERN` |

## Identification

At the top of the staging model (`models/staging/stg_flat_file__<source>.sql`). `{0}` is the land path:

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0025 - FLAT FILE SOURCE FILE NAME COULD NOT BE RESOLVED. LANDING PATH '@public.landing_stage/ssis/LoadOrders/OrdersFlatFile/UNKNOWN_FILE' REQUIRES A MANUAL FILE BINDING. ***/!!!
SELECT
   $1 :: NUMERIC AS customer_id,
   $2 :: VARCHAR(50) AS customer_name
FROM
   @public.landing_stage/ssis/LoadOrders/OrdersFlatFile/UNKNOWN_FILE (FILE_FORMAT => 'LoadOrders_Data_Flow_Task_Orders_Source')
WHERE
   METADATA$FILE_ROW_NUMBER > 1
```

The columns, casts and `FILE_FORMAT` (in `etl_configuration/file_formats/file_formats.sql`) are normal; only the file is missing. The connection's `DTS:ConnectionString` is in the package's `DTS:ConnectionManagers` or in the project's `.conmgr`. If the connection also had a `ConnectionString` property expression, the issues report lists [SSC-EWI-SSIS0026](SSC-EWI-SSIS0026.md) for it, with no marker in the code.

## Fix Patterns

### Pattern 1: The file name is known

Look where the package got it at run time: a variable a Script Task or Execute SQL Task set, a `.dtsConfig` / SSIS catalog environment value, or the same connection in another package or `.conmgr`. Keep the prefix, which is where the land process puts the connection's files, and select the one file by its exact name:

```sql
FROM
   @public.landing_stage/ssis/LoadOrders/OrdersFlatFile/ (FILE_FORMAT => 'LoadOrders_Data_Flow_Task_Orders_Source')
WHERE
   METADATA$FILENAME = 'ssis/LoadOrders/OrdersFlatFile/orders.csv'
   AND METADATA$FILE_ROW_NUMBER > 1
```

Do not just replace `UNKNOWN_FILE` with the name: a stage path in `FROM` is a prefix, so `.../orders.csv` also reads `orders.csv.bak` and `orders.csv_old`, and a `PATTERN` such as `'.*orders[.]csv'` also reads `old_orders.csv`. `METADATA$FILENAME` holds the file's path inside the stage, without the `@stage/`, so the equality names exactly that file. Run `SELECT DISTINCT METADATA$FILENAME FROM @public.landing_stage/ssis/LoadOrders/OrdersFlatFile/ (FILE_FORMAT => '...')` once to confirm the form: if the names look different, the equality matches nothing and the model loads no rows.

### Pattern 2: The connection names a folder, or the name changes per run

Read every file under the prefix and narrow it with a regex `PATTERN`:

```sql
FROM
   @public.landing_stage/ssis/LoadOrders/OrdersFlatFile/ (FILE_FORMAT => 'LoadOrders_Data_Flow_Task_Orders_Source', PATTERN => '.*/orders_[0-9]{8}[.]csv')
```

Start the pattern with `.*/` so the name must begin right after a `/`: `'.*orders_[0-9]{8}[.]csv'` also reads `old_orders_20240630.csv`. The pattern still reads matching files in subfolders; if the folder has any, add `AND METADATA$FILENAME RLIKE 'ssis/LoadOrders/OrdersFlatFile/orders_[0-9]{8}[.]csv'` to the `WHERE` (`RLIKE` matches the whole name).

`METADATA$FILE_ROW_NUMBER` restarts at 1 in each file, so the header filter still skips each file's header. When only the latest file must load, filter on `METADATA$FILENAME` (or have the land process archive loaded files) rather than reading the whole history.

### Pattern 3: Nothing says which file

Read the folder with Pattern 1's exact `METADATA$FILENAME` filter on the expected name, add `-- NEEDS-USER: which file does <connection> read? (ConnectionString is '<value>')` and mark as needs-user.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker, and leave no `UNKNOWN_FILE` in the path.
- A stage path in `FROM` is a prefix: read one file from its folder with an exact `METADATA$FILENAME` filter, never by putting its name at the end of the path.
- Do not move the read off `public.landing_stage`: the stage itself is retargeted once, project-wide, in `etl_configuration/stages/stages.sql`.
- `PATTERN` is a regex, not a Windows wildcard: `*.csv` becomes `.*[.]csv`.
- Same idea for File System Task paths: [SSC-FDM-SSIS0025](SSC-FDM-SSIS0025.md), [SSC-FDM-SSIS0028](SSC-FDM-SSIS0028.md); Bulk Insert stages: [SSC-EWI-SSIS0024](SSC-EWI-SSIS0024.md).
