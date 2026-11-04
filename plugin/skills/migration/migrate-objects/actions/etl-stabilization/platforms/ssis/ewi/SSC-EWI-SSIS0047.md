# SSC-EWI-SSIS0047 — File System Task Path Needs a Stage

A File System Task path is a literal one SnowConvert could not bind to a landing-stage path, so the stage command holds `@<STAGE_PLACEHOLDER>` where the stage should be. It fires on every `SetAttributes` task (with [SSC-EWI-SSIS0043](SSC-EWI-SSIS0043.md)), and on other operations when a literal path did not bind: the task has no source or destination path, or a file operation names a manager whose connection string ends in a folder (no file name). Variable paths get [SSC-FDM-SSIS0025](SSC-FDM-SSIS0025.md) instead and unresolved managers [SSC-EWI-SSIS0041](SSC-EWI-SSIS0041.md). The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (every SetAttributes task; rare otherwise) |
| Common action | Replace `@<STAGE_PLACEHOLDER>` with the real stage path |

## Identification

```sql
---- Start block 'Package\Delete Old Extract'
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0047 - THE PATH(S) REQUIRES MANUAL MAPPING TO A SNOWFLAKE STAGE(S). ***/!!!
REMOVE '@<STAGE_PLACEHOLDER>/<path>';
---- End block 'Package\Delete Old Extract'
```

`<path>` is the connection string with the drive dropped and `/` separators (`C:\Data\Input\` → `Data/Input/...`); a missing task path is the bare `@<STAGE_PLACEHOLDER>`. In a copy, move or rename one side may already be bound (`@public.landing_stage/ssis/<package>/<manager>/...`) and only the other holds the placeholder. Source facts: the task's `<FileSystemData TaskOperationType=... TaskSourcePath=... TaskDestinationPath=...>` and the manager's `DTS:ConnectionString` and `FileUsageType` (`0` file, `1` create file, `2` existing folder, `3` create folder).

## Fix Patterns

### Pattern 1: SetAttributes

There is no stage command to fix: follow [SSC-EWI-SSIS0043](SSC-EWI-SSIS0043.md) and remove both markers.

### Pattern 2: A manager that names a folder for a file operation

The task acts on a folder (a file name supplied elsewhere, or the manager mis-typed). Write the stage path the share maps to, keeping the layout the package's bound paths use, and the file name the source actually handled:

```sql
-- SSIS: DeleteFile, manager "ExtractFolder" = D:\extracts\  (FileUsageType 0), file extract.csv
DECLARE
   not_one_file EXCEPTION (-20047, 'ExtractFolder/extract.csv is missing, or other staged files start with its path; nothing was deleted');
   listed INTEGER;
   exact INTEGER;
BEGIN
   LIST '@public.landing_stage/ssis/nightly_extract/ExtractFolder/extract.csv';
   SELECT COUNT(*), COALESCE(COUNT_IF(ENDSWITH("name", '/ssis/nightly_extract/ExtractFolder/extract.csv')), 0)
     INTO :listed, :exact
     FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
   IF (listed <> 1 OR exact <> 1) THEN
      RAISE not_one_file;
   END IF;
   REMOVE '@public.landing_stage/ssis/nightly_extract/ExtractFolder/extract.csv';
END;
```

`REMOVE` takes a path prefix: on `.../ExtractFolder/extract.csv` it deletes every file whose path starts with that, `extract.csv.bak` and `extract.csv/old.csv` too. It cannot name one file the way `COPY FILES ... FILES =` can, and a regex `PATTERN` is no way out: `'.*extract[.]csv'` matches `old_extract.csv` as well, and even an anchored `'^(.*/)?extract[.]csv$'` matches `ExtractFolder/archive/extract.csv`. `LIST` reads the same prefix `REMOVE` deletes, so the check fails unless it returns one row and that row is `extract.csv` itself. A count alone is not enough: with `extract.csv` missing and `extract.csv.bak` staged, the count is 1 and `REMOVE` would delete the backup. The check compares the end of `name` with `/<path in the stage>`, because `name` holds more than the path inside the stage; run one `LIST` on the stage to confirm its names end that way (if they do not, the check fails safe, raising instead of deleting). Keep the `COALESCE(..., 0)`: over an empty `LIST`, `COUNT_IF` returns NULL, and Snowflake Scripting treats a NULL `IF` condition as FALSE, so the check would skip the `RAISE`. A missing file fails the task, as SSIS's DeleteFile did. When the folder can hold other files whose names start with this one (a `.bak`, a dated copy), add `-- NEEDS-USER: can '<task>' delete every file starting with extract.csv?`.

If the task really meant the whole folder, it is a directory operation: end the path in `/` and read [SSC-FDM-SSIS0028](SSC-FDM-SSIS0028.md) first, since `REMOVE` on a prefix deletes everything under it.

### Pattern 3: No path at all

A task with an empty `TaskSourcePath` or `TaskDestinationPath` set it at run time (a property expression) or was never finished. Rebuild the path from the expression as in [SSC-FDM-SSIS0025](SSC-FDM-SSIS0025.md); if there is nothing to rebuild it from, add `-- NEEDS-USER: which stage path does '<task>' act on?` and mark as needs-user.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker; no `@<STAGE_PLACEHOLDER>` may remain.
- A placeholder path inside a literal `REMOVE` or `COPY FILES` must become a literal stage path; to use a variable, build the statement with `EXECUTE IMMEDIATE` ([SSC-FDM-SSIS0025](SSC-FDM-SSIS0025.md), Pattern 3).
- Which stage a share maps to is an environment fact: when the project has no stage for it, write the path you expect and mark as needs-user.
- A single-file `REMOVE` goes through the `LIST` check in Pattern 2, which checks the listed name, not just the count; only a directory operation removes a whole prefix.
- Copy, move and rename destinations also carry [SSC-EWI-SSIS0044](SSC-EWI-SSIS0044.md): the destination is a folder.
