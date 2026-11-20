# SSC-EWI-SSIS0043 — File System Task SetAttributes Not Supported

A File System Task set file attributes (`SetAttributes`: ReadOnly, Hidden, Archive, System). Stage files have no attributes, so SnowConvert generated no command: only the task's settings as comments over an empty ` ;` statement. It always comes with [SSC-EWI-SSIS0047](SSC-EWI-SSIS0047.md). The markers **break compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (once per SetAttributes task) |
| Common action | Drop the operation (no equivalent); keep the comments and the ` ;` |

## Identification

```sql
---- Start block 'Package\Set File Attributes'
---- TaskOperationType="SetAttributes"
---- TaskSourcePath="Data/report.txt"
---- TaskIsSourceVariable="False"
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0043 - SNOWFLAKE STAGES DO NOT SUPPORT FILE ATTRIBUTES (READ-ONLY, HIDDEN, ETC.). THIS OPERATION CANNOT BE TRANSLATED. ***/!!!!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0047 - THE PATH(S) REQUIRES MANUAL MAPPING TO A SNOWFLAKE STAGE(S). ***/!!!
 ;
---- End block 'Package\Set File Attributes'
```

`TaskSourcePath` is the connection manager's file path with the drive dropped (or the variable's name), not a stage path. The attributes set are not in the output: read `TaskFileAttributes` (for example `TaskFileAttributes="ReadOnly"`) on the task's `<FileSystemData>` in the `.dtsx`.

## Fix Patterns

### Pattern 1: The attribute only mattered on the file share (most common)

ReadOnly or Hidden on an archived or published file protected it from people on the share. Nothing in the converted flow reads it. Remove both markers, keep the comments and the ` ;` (a no-op), and add one line saying what was dropped:

```sql
---- Start block 'Package\Set File Attributes'
---- TaskOperationType="SetAttributes"
---- TaskSourcePath="Data/report.txt"
---- TaskIsSourceVariable="False"
-- SSIS set ReadOnly on the file; stage files have no attributes. Dropped.
 ;
---- End block 'Package\Set File Attributes'
```

### Pattern 2: The attribute protected the file from later writes

Snowflake protects stage files with privileges, not per file: a stage that only a read role can see, or no `WRITE` grant on the internal stage for roles that must not change it. Which roles and stages is an environment decision: add a `-- NEEDS-USER:` comment naming the file and the attribute, and mark as needs-user.

### Pattern 3: Another task reads the attribute

A Script Task or expression that checks the Archive or ReadOnly flag to tell processed files from new ones needs a different marker: move processed files to another prefix (`COPY FILES` then `REMOVE`, as in [SSC-EWI-SSIS0044](SSC-EWI-SSIS0044.md)) or record them in a control table, and change the reader to match.

## Key Points

- **Must** remove both `!!!RESOLVE EWI!!!` markers (SSIS0043 and SSIS0047): there is no path to map, since no stage command was generated.
- Keep the block valid: if the ` ;` goes, leave `NULL;` so the block is not empty.
- Do not invent an attribute-like substitute (a renamed `.readonly` file, a tag): nothing would read it.
