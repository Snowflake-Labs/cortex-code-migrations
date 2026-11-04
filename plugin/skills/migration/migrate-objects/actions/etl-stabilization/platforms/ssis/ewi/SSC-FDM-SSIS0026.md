# SSC-FDM-SSIS0026 — CreateDirectory Writes a .dummy File

A File System Task created a directory (`CreateDirectory`). A stage has no directories, only path prefixes, so SnowConvert unloads a one-row placeholder file `<path>/.dummy` with `COPY INTO <location>` to make the prefix appear. The FDM is informational.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Low (once per CreateDirectory task) |
| Common action | No change; keep `.dummy` out of loads that read the folder |

## Identification

Look for the marker:
```
--** SSC-FDM-SSIS0026 - SINCE SNOWFLAKE STAGES USE PREFIX-BASED PATHS, THE DIRECTORY IS CREATED BY WRITING A .DUMMY PLACEHOLDER FILE TO THE TARGET PATH VIA COPY INTO. **
```

With a connection manager:

```sql
---- Start block 'Package\Create Output Directory'
--** SSC-FDM-SSIS0026 - SINCE SNOWFLAKE STAGES USE PREFIX-BASED PATHS, THE DIRECTORY IS CREATED BY WRITING A .DUMMY PLACEHOLDER FILE TO THE TARGET PATH VIA COPY INTO. **
EXECUTE IMMEDIATE 'COPY INTO @public.landing_stage/ssis/filesystemtask_create_directory_connmgr/OutputDirConnection/.dummy FROM (SELECT ''empty'') FILE_FORMAT = (TYPE = CSV COMPRESSION = NONE) OVERWRITE = TRUE SINGLE = TRUE';
---- End block 'Package\Create Output Directory'
```

With a variable, followed by [SSC-FDM-SSIS0025](SSC-FDM-SSIS0025.md):

```sql
EXECUTE IMMEDIATE 'COPY INTO ' || :User_NewDirectory || '/.dummy FROM (SELECT ''empty'') FILE_FORMAT = (TYPE = CSV COMPRESSION = NONE) OVERWRITE = TRUE SINGLE = TRUE';
```

`OVERWRITE = TRUE` is there when the task's `UseDirectoryIfExists` was true (`TaskOverwriteDestFile="True"` in the `.dtsx`); without it, the unload fails once `.dummy` exists, which stands in for SSIS failing on an existing directory.

## Fix Patterns

### Pattern 1: No change (most common)

Leave the comment and the statement as they are.

### Pattern 2: A load or listing reads the same folder

`.dummy` is a real file holding the line `empty`. A `COPY INTO <table>` from that prefix with no `PATTERN`, or `PATTERN = '.*'`, loads it as a row (or fails on it); a Foreach File `LIST` whose pattern matches it visits it. Narrow the reader's pattern to the real files (`PATTERN = '.*[.]csv'`), or, when nothing needs the folder to exist beforehand, delete the `COPY INTO .../.dummy` statement and keep the comment: `COPY FILES`, `PUT` and unloads create their prefixes themselves.

### Pattern 3: A variable path

The variable is concatenated without quotes and before `/.dummy`. Its value must be a stage path with no trailing `/` (a trailing one makes `...//.dummy`) and no spaces:

```sql
EXECUTE IMMEDIATE 'COPY INTO ' || RTRIM(:User_NewDirectory, '/') || '/.dummy FROM (SELECT ''empty'') FILE_FORMAT = (TYPE = CSV COMPRESSION = NONE) OVERWRITE = TRUE SINGLE = TRUE';
```

## Key Points

- Do **NOT** remove the FDM comment.
- Without `OVERWRITE = TRUE`, a rerun fails only because `.dummy` is there, not because other files are: if the package recreated the folder each run after deleting it, keep the delete ([SSC-FDM-SSIS0028](SSC-FDM-SSIS0028.md)) before this task.
- A DeleteDirectoryContent writes a similar `.keep` placeholder: see [SSC-FDM-SSIS0028](SSC-FDM-SSIS0028.md).
