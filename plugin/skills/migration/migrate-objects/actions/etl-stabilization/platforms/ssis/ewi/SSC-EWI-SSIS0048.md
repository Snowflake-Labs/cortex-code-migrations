# SSC-EWI-SSIS0048 — Fail-If-Destination-Exists Not Reproduced

A File System Task copy, move or rename (`CopyFile`, `CopyDirectory`, `MoveFile`, `MoveDirectory`, `RenameFile`) did not have `OverwriteDestination` set, so in SSIS it failed when the destination file or folder already existed. The generated `COPY FILES` always overwrites files with the same name. SnowConvert treats a missing `TaskOverwriteDestFile` as false, so this fires for every such task that did not set it to `True`. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Moderate (once per copy/move/rename task without overwrite) |
| Common action | Accept the overwrite and remove the marker; add an existence check only if the failure mattered |

## Identification

First on the `COPY FILES` line, before [SSC-EWI-SSIS0044](SSC-EWI-SSIS0044.md) on file operations:

```sql
---- Start block 'Package\Move File No Overwrite'
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0048 - THE ORIGINAL SSIS TASK WAS CONFIGURED TO FAIL IF THE DESTINATION EXISTS. SNOWFLAKE DOES NOT SUPPORT THIS BEHAVIOR AND WILL SILENTLY OVERWRITE. ***/!!!!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0044 - ... ***/!!!
--** SSC-FDM-SSIS0025 - THE VARIABLE(S) VALUE(S) MUST CONTAIN A VALID SNOWFLAKE STAGE PATH. **
EXECUTE IMMEDIATE 'COPY FILES INTO ''' || REPLACE(:User_DestFilePath, '''', '''''') || ''' FROM ''' || REPLACE(:User_SourceFilePath, '''', '''''') || '''';
REMOVE :User_SourceFilePath;
---- End block 'Package\Move File No Overwrite'
```

In the `.dtsx`: `<FileSystemData ... TaskOverwriteDestFile="False">`, or no `TaskOverwriteDestFile` at all. To see whether the failure was used, look for a precedence constraint leaving this task with `DTS:Value="1"` (on failure).

## Fix Patterns

### Pattern 1: Overwrite is fine (most common)

Archive, staging and outbound copies that rerun on the same names are better off overwriting: a rerun after a partial failure then succeeds. Nothing downstream handles the failure. Remove the marker and note it:

```sql
-- SSIS failed if the destination existed (OverwriteDestination = False); COPY FILES overwrites.
COPY FILES INTO '@public.landing_stage/archive/' FROM '@public.landing_stage/in/' FILES = ('orders.csv');
```

Name the file with `FILES` rather than ending the `FROM` path in it: a `FROM` path is a prefix, so `FROM '@public.landing_stage/in/orders.csv'` also copies `orders.csv.bak` and `orders.csv_old`. For a path in a variable, split it as in Pattern 2.

### Pattern 2: Keep the failure

When an on-failure path follows the task, or overwriting would lose data (a file name that is supposed to be unique per run), check before copying. `COPY FILES` keeps the source name under the destination folder, so check `<destination folder>/<source file name>`; `LIST` matches by prefix, so compare the name exactly.

Act on the one file only. The generated `FROM ''' || :User_SourceFilePath || '''` and `REMOVE :User_SourceFilePath` treat the path as a prefix: for a source ending in `report.csv` they also copy and delete `report.csv.bak`. Split the path into its folder and file name, and copy with `FILES = ('<name>')`, which names exactly that file. `REMOVE` has no such option, so guard it as [SSC-EWI-SSIS0044](SSC-EWI-SSIS0044.md) Pattern 1 does. Before the copy, `LIST` the source path, which reads the same prefix `REMOVE` deletes, and fail unless it returns one row and that row is the file itself: a count alone is not enough, since with `report.csv` missing and `report.csv.bak` staged the count is 1. After the copy, fail unless its output (one row per copied file, in a column `file`) names the file. Only then `REMOVE`:

```sql
DECLARE
   destination_exists EXCEPTION (-20048, 'Destination file already exists');
   not_one_file EXCEPTION (-20049, 'The source file is missing, or other staged files start with its path');
   not_copied EXCEPTION (-20050, 'COPY FILES did not copy the source file; nothing was removed');
   listed INTEGER;
   exact INTEGER;
   n INTEGER;
   copied INTEGER;
BEGIN
   LET src_path STRING := REPLACE(:User_SourceFilePath, '''', '''''');
   LET src_folder STRING := REGEXP_SUBSTR(:User_SourceFilePath, '^.*/');                  -- '@public.landing_stage/in/'
   LET src_name STRING := REGEXP_SUBSTR(:User_SourceFilePath, '[^/]+$');                  -- 'report.csv'
   LET src_rel STRING := REGEXP_SUBSTR(:User_SourceFilePath, '^@[^/]+/(.*)$', 1, 1, 'e'); -- 'in/report.csv'
   EXECUTE IMMEDIATE 'LIST ''' || :src_path || '''';
   SELECT COUNT(*), COALESCE(COUNT_IF(ENDSWITH("name", '/' || :src_rel)), 0)
     INTO :listed, :exact
     FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
   IF (listed <> 1 OR exact <> 1) THEN
      RAISE not_one_file;
   END IF;
   EXECUTE IMMEDIATE 'LIST ''@public.landing_stage/archive/' || REPLACE(:src_name, '''', '''''') || '''';
   SELECT COALESCE(COUNT_IF(ENDSWITH("name", '/archive/' || :src_name)), 0)
     INTO :n
     FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
   IF (n > 0) THEN
      RAISE destination_exists;
   END IF;
   EXECUTE IMMEDIATE 'COPY FILES INTO ''@public.landing_stage/archive/'' FROM ''' || REPLACE(:src_folder, '''', '''''')
      || ''' FILES = (''' || REPLACE(:src_name, '''', '''''') || ''')';
   SELECT COALESCE(COUNT_IF("file" = :src_name OR ENDSWITH("file", '/' || :src_name)), 0)
     INTO :copied
     FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
   IF (copied <> 1) THEN
      RAISE not_copied;
   END IF;
   EXECUTE IMMEDIATE 'REMOVE ''' || :src_path || '''';
END;
```

The source and destination checks run before the `COPY FILES`, so either failure leaves every file in place. The copy check runs before `REMOVE`: `COPY FILES` skips a named file it cannot find, without an error, and then the source stays where it is. Keep the `COALESCE(..., 0)`: over zero rows `COUNT_IF` returns NULL, and a NULL `IF` condition is FALSE, so the check would skip the `RAISE`. A regex `PATTERN` on `REMOVE` does not make it exact: even `'^(.*/)?report[.]csv$'` matches `in/subfolder/report.csv`. When `not_one_file` can fire because other files in the folder start with the source's name, add `-- NEEDS-USER: can the move delete every file starting with <name>?`.

For a variable destination folder, run the `LIST` with `EXECUTE IMMEDIATE 'LIST ''' || :User_DestFolder || ''''`. For `CopyDirectory`/`MoveDirectory`, the prefix is the point: copy and remove the whole folder path, ending in `/` (see [SSC-FDM-SSIS0028](SSC-FDM-SSIS0028.md)), and fail when the `LIST` of the destination prefix returns any row, as SSIS failed when the destination folder existed at all.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker.
- Resolve [SSC-EWI-SSIS0044](SSC-EWI-SSIS0044.md) on the same statement first: the check must look where the file really lands.
- In a move, the check goes before the `COPY FILES`, so a failure leaves the source in place, as SSIS did.
- A file copy names the file with `FILES`; a file move removes the source's own path only after `LIST` shows it holds the file itself and nothing else, and the copy's output names the file. Only a directory operation copies or removes a whole prefix.
- `RAISE` fails the task, so the tasks after it in the graph do not run, as after the failed SSIS task.
