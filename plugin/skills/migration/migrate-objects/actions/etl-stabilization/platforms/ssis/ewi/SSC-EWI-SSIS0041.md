# SSC-EWI-SSIS0041 — File System Task Connection Manager Not Found

A File System Task copy (`CopyFile`, the default operation) names a source or destination connection manager that SnowConvert could not resolve: the manager is not in the converted input (typically a project-level `.conmgr` left out of the conversion) or its connection string is empty (set only at run time by an expression or configuration). The unresolved side of the `COPY FILES` became the bare placeholder `@<STAGE_PLACEHOLDER>`. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (once per CopyFile task with an unresolved manager) |
| Common action | Look up the manager's file, put its stage path in place of `@<STAGE_PLACEHOLDER>` |

## Identification

Usually chained with [SSC-EWI-SSIS0044](SSC-EWI-SSIS0044.md):

```sql
---- Start block 'Package\Copy From External Source'
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0041 - THE CONNECTION MANAGER REFERENCED BY TASKSOURCEPATH OR TASKDESTINATIONPATH IS NOT DEFINED IN THE DTSX FILE. IT MAY BE A PROJECT-LEVEL CONNECTION MANAGER. THE PATH CANNOT BE RESOLVED. ***/!!!!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0044 - THE COPY FILES COMMAND TREATS THE DESTINATION AS A DIRECTORY PREFIX ... ***/!!!
--** SSC-FDM-SSIS0025 - THE VARIABLE(S) VALUE(S) MUST CONTAIN A VALID SNOWFLAKE STAGE PATH. **
EXECUTE IMMEDIATE 'COPY FILES INTO ''' || REPLACE(:User_DestFilePath, '''', '''''') || ''' FROM ''@<STAGE_PLACEHOLDER>''';
---- End block 'Package\Copy From External Source'
```

With two literal managers the statement is a plain `COPY FILES INTO '...' FROM '@<STAGE_PLACEHOLDER>';`. The manager's name is not in the output. In the `.dtsx`, the task's `<FileSystemData TaskSourcePath="{GUID}" TaskDestinationPath="...">` holds the reference; find that DTSID (or name) in the project's `*.conmgr` files and read its `DTS:ConnectionString`, and any `<DTS:PropertyExpression DTS:Name="ConnectionString">` that sets it at run time.

## Fix Patterns

### Pattern 1: The manager names a fixed file (most common)

Replace the placeholder with the stage path where that file lands. If another task or Flat File load of the project already reads the same manager, reuse its stage path exactly. Copying one file is exact with `FILES =`; a `FROM` path alone is a prefix:

```sql
-- SSIS: TaskSourcePath -> project manager "Claims Extract" = \\fs01\exports\claims.csv
EXECUTE IMMEDIATE 'COPY FILES INTO ''' || REPLACE(:User_DestFilePath, '''', '''''') || ''' FROM ''@public.landing_stage/exports/'' FILES = (''claims.csv'')';
```

Then resolve the destination as [SSC-EWI-SSIS0044](SSC-EWI-SSIS0044.md) says.

### Pattern 2: The connection string is set at run time

When an expression builds the path (`@[$Project::ExportRoot] + "\\claims_" + ... + ".csv"`), compute the stage path into a variable and splice it in, as [SSC-FDM-SSIS0025](SSC-FDM-SSIS0025.md) shows for expression variables.

### Pattern 3: The manager cannot be found

No `.conmgr` in the project and no other trace of the file: leave a `-- NEEDS-USER: where does connection manager <name or GUID> point, and which stage holds it?` comment and mark as needs-user.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker; no `@<STAGE_PLACEHOLDER>` may remain in the statement.
- Backslash UNC paths are never stage paths: map the share to its stage, with `/` separators.
- Only `CopyFile` gets this marker. A move, rename, directory copy or delete with an unresolved manager gets `@<STAGE_PLACEHOLDER>` with no marker at all: search the output for it.
- A `!!!RESOLVE EWI!!!` [SSC-EWI-SSIS0048](SSC-EWI-SSIS0048.md) on the same statement is a separate decision.
