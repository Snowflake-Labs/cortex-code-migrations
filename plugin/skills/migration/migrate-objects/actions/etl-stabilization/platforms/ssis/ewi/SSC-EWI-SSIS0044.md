# SSC-EWI-SSIS0044 — COPY FILES Destination Is a Directory Prefix

A File System Task copy, move or rename became Snowflake `COPY FILES`. `COPY FILES` treats the destination as a folder (a stage prefix) and keeps the source file name, so a destination that names a *file* ends up as `<file>/<source name>`. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low-moderate (once per CopyFile / MoveFile / RenameFile task) |
| Common action | Confirm the destination is a folder ending in `/`; rewrite renames with the query form |

## Identification

```sql
---- Start block 'Package\Copy Last File'
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0044 - THE COPY FILES COMMAND TREATS THE DESTINATION AS A DIRECTORY PREFIX AND APPENDS THE SOURCE FILENAME. IF THE DESTINATION PATH REFERS TO A SPECIFIC FILE RATHER THAN A DIRECTORY, THE RESULTING PATH MAY BE INCORRECT. REVIEW AND ADJUST MANUALLY IF NEEDED. ***/!!!
--** SSC-FDM-SSIS0025 - THE VARIABLE(S) VALUE(S) MUST CONTAIN A VALID SNOWFLAKE STAGE PATH. **
EXECUTE IMMEDIATE 'COPY FILES INTO ''@public.landing_stage/ssis/filesystemtask_copy_current_file_foreach/DestFile/'' FROM ''' || REPLACE(:User_CurrentFile, '''', '''''') || '''';
---- End block 'Package\Copy Last File'
```

A MoveFile is the same `COPY FILES` followed by a `REMOVE` of the source. Stage commands take a bound scalar variable (`COPY FILES INTO :d FROM :s`, `REMOVE :User_TempFolder`) when its value is already a full stage reference starting with `@`; SnowConvert splices a path into `EXECUTE IMMEDIATE` only where a bind does not work, for a cursor row field or a path it assembles. Keep a working bind as it is ([SSC-FDM-SSIS0025](SSC-FDM-SSIS0025.md) Pattern 3).

## Fix Patterns

### Pattern 1: The destination is a folder (most common: archive, rejected, inbound)

The prefix behaviour is what SSIS did. Make sure the destination is a stage path ending in `/` (see [SSC-FDM-SSIS0025](SSC-FDM-SSIS0025.md) when it comes from a variable), then remove the marker.

Act on the one file only. A source path is a prefix too: `FROM` or `REMOVE` on a path ending in `report.csv` also copies or deletes `report.csv.bak`. Copy from the file's folder with `FILES = ('<name>')`, which names exactly that file; `COPY FILES` skips a named file it cannot find, without an error. `REMOVE` has no such option, so guard it twice:

- **Before the copy**, `LIST` the path, which reads the same prefix `REMOVE` deletes, and fail unless it returns one row and that row is the file itself. A count alone is not enough: with `report.csv` missing and `report.csv.bak` staged, the count is 1.
- **After the copy**, fail unless its output (one row per copied file, in a column `file`) names the file. Only then `REMOVE`.

```sql
DECLARE
   not_one_file EXCEPTION (-20044, 'The source file is missing, or other staged files start with its path');
   not_copied EXCEPTION (-20045, 'COPY FILES did not copy the source file; nothing was removed');
   listed INTEGER;
   exact INTEGER;
   copied INTEGER;
BEGIN
   LET src_path STRING := REPLACE(:STAGE_FILE_PATH, '''', '''''');
   LET src_folder STRING := REGEXP_SUBSTR(:src_path, '^.*/');                        -- '@public.landing_stage/in/bordereaux/'
   LET src_name STRING := REGEXP_SUBSTR(:STAGE_FILE_PATH, '[^/]+$');                 -- 'report.csv'
   LET src_rel STRING := REGEXP_SUBSTR(:STAGE_FILE_PATH, '^@[^/]+/(.*)$', 1, 1, 'e'); -- 'in/bordereaux/report.csv'
   EXECUTE IMMEDIATE 'LIST ''' || :src_path || '''';
   SELECT COUNT(*), COALESCE(COUNT_IF(ENDSWITH("name", '/' || :src_rel)), 0)
     INTO :listed, :exact
     FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
   IF (listed <> 1 OR exact <> 1) THEN
      RAISE not_one_file;
   END IF;
   EXECUTE IMMEDIATE 'COPY FILES INTO ''@public.landing_stage/archive/bordereaux/'' FROM ''' || :src_folder
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

Snowflake documents `LIST`'s `name` column only as the staged file's name, and it holds more than the path inside the stage, so the check compares the name's end, `/<path in the stage>`, rather than the whole name. Run one `LIST` on the stage to confirm its names end that way; if they do not, the check fails safe, raising instead of deleting. Keep the `COALESCE(..., 0)`: over zero input rows (an empty `LIST`, or a `COPY FILES` that copied nothing, which returns no rows) `COUNT_IF` returns NULL, not 0, and Snowflake Scripting treats a NULL `IF` condition as FALSE, so without it the copy check would skip the `RAISE`. Both checks run before `REMOVE`, so a failure leaves the source in place. A regex `PATTERN` on `REMOVE` does not make it exact: `'.*/report[.]csv'` also matches `in/subfolder/report.csv`. When other files can share the prefix, add `-- NEEDS-USER: can the move delete every file starting with <name>?`.

### Pattern 2: The destination names a file (a rename)

A stage-to-stage `COPY FILES` cannot rename. Use the query form, which takes the one source file and the new name. Its `REMOVE` deletes by prefix too, so it takes both of Pattern 1's checks:

```sql
-- SSIS: RenameFile  @[User::SourceFile] -> @[User::DestFile]
DECLARE
   not_one_file EXCEPTION (-20044, 'The source file is missing, or other staged files start with its path');
   not_copied EXCEPTION (-20045, 'COPY FILES did not copy the source file; nothing was removed');
   listed INTEGER;
   exact INTEGER;
   copied INTEGER;
BEGIN
   LET src_path STRING := REPLACE(:User_SourceFile, '''', '''''');
   LET src_rel STRING := REGEXP_SUBSTR(:User_SourceFile, '^@[^/]+/(.*)$', 1, 1, 'e');
   EXECUTE IMMEDIATE 'LIST ''' || :src_path || '''';
   SELECT COUNT(*), COALESCE(COUNT_IF(ENDSWITH("name", '/' || :src_rel)), 0)
     INTO :listed, :exact
     FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
   IF (listed <> 1 OR exact <> 1) THEN
      RAISE not_one_file;
   END IF;
   EXECUTE IMMEDIATE 'COPY FILES INTO @public.landing_stage/out/ FROM (SELECT ''' || :src_path || ''', '''
      || REPLACE(:User_DestName, '''', '''''') || ''')';
   SELECT COALESCE(COUNT_IF(ENDSWITH("FILE_NAME", '/' || :User_DestName)), 0)
     INTO :copied
     FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
   IF (copied <> 1) THEN
      RAISE not_copied;
   END IF;
   EXECUTE IMMEDIATE 'REMOVE ''' || :src_path || '''';
END;
```

`User_DestName` is the file name alone; the folder goes in `INTO`. The query form's output differs from the stage-to-stage form's: one column, `FILE_NAME`, holding the fully qualified destination (`DB.SCHEMA.STAGE/out/<name>`), so the copy check compares its end with `/<User_DestName>`.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker.
- `COPY FILES` overwrites a destination file with the same name, as SSIS did with `OverwriteDestination` true. When the package had it false, check first with `LIST`, comparing the name exactly: `LIST` matches by prefix.
- Move order matters: check with `LIST`, copy, check the copy's output, then `REMOVE`. Do not remove a file a later `COPY INTO` in the same run still needs.
- A UNC path (`\\fs01\share\...`) in a variable is not a stage path: fix the variable first ([SSC-FDM-SSIS0025](SSC-FDM-SSIS0025.md)).
