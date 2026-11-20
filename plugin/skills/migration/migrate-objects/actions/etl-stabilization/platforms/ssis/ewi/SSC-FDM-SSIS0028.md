# SSC-FDM-SSIS0028 — Stage Paths Are Prefixes, Not Directories

A File System Task deleted, emptied or moved a directory, and became a `REMOVE` on a stage path. A stage has no real directories: `REMOVE @stage/out/201702` removes every file whose path *starts with* that text, which also matches `@stage/out/2017021/...` and `@stage/out/201702_old.csv`.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Low (once per DeleteDirectory / DeleteDirectoryContent / MoveDirectory task) |
| Common action | Make sure the path ends in `/` |

## Identification

Look for the marker:
```
--** SSC-FDM-SSIS0028 - SNOWFLAKE STAGES USE PREFIX-BASED PATHS, NOT REAL DIRECTORIES. THE REMOVE COMMAND WITH A TRAILING SLASH DELETES ALL FILES MATCHING THE PREFIX PATTERN. **
```

```sql
---- Start block 'Package\Clean Temp Directory'
--** SSC-FDM-SSIS0025 - THE VARIABLE(S) VALUE(S) MUST CONTAIN A VALID SNOWFLAKE STAGE PATH. **
--** SSC-FDM-SSIS0028 - SNOWFLAKE STAGES USE PREFIX-BASED PATHS, NOT REAL DIRECTORIES. THE REMOVE COMMAND WITH A TRAILING SLASH DELETES ALL FILES MATCHING THE PREFIX PATTERN. **
REMOVE :User_TempFolder;
EXECUTE IMMEDIATE 'COPY INTO ' || :User_TempFolder || '/.keep FROM (SELECT ''empty'') FILE_FORMAT = (TYPE = CSV COMPRESSION = NONE) OVERWRITE = TRUE SINGLE = TRUE';
---- End block 'Package\Clean Temp Directory'
```

The `COPY INTO .../.keep` line (DeleteDirectoryContent) writes a placeholder so the "folder" still shows up.

## Fix Patterns

### Pattern 1: Add the trailing slash

Where the variable's value is set in one place, end it in `/` there ([SSC-FDM-SSIS0025](SSC-FDM-SSIS0025.md) Patterns 1 and 2) and keep the generated `REMOVE :User_TempFolder;`: `REMOVE` binds a scalar variable whose value is a full stage reference. Otherwise append the slash in the statement; an assembled path needs a string:

```sql
-- After
EXECUTE IMMEDIATE 'REMOVE ''' || REPLACE(RTRIM(:User_TempFolder, '/') || '/', '''', '''''') || '''';
```

### Pattern 2: Drop the `.keep` placeholder

Nothing in Snowflake needs an empty folder to exist. The `.keep` file appears in later `LIST` output and can match a `PATTERN = '.*'` load. Remove the `COPY INTO .../.keep` line unless something lists the folder and expects it.


## Key Points

- Do **NOT** remove the FDM comment.
- `REMOVE` with no trailing slash on a variable that may be empty removes the whole stage path above it. Guard it: `IF (:User_TempFolder <> '') THEN ... END IF;`.
- Run deletes after the loads that read the files, as the SSIS precedence constraints did.
