# SSC-EWI-SSIS0008 — Execute Package Task References an External Package

An Execute Package task points at a package outside the project: a `.dtsx` on the file system (a File connection manager) or one stored in SQL Server (msdb). SnowConvert did not treat the child as a reusable package that it converts to a procedure. For a File reference, that means the child's `.dtsx` was not in the conversion input. So the task became `EXECUTE TASK public.<child>`, a task that exists only if the child was converted somewhere else. The marker **breaks compilation**, and it always comes with [SSC-EWI-SSIS0005](SSC-EWI-SSIS0005.md).

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Once per Execute Package task with an external reference |
| Common action | Find the child's converted object and point the call at it; mark needs-user if it was never converted |

## Identification

```sql
---- Start block 'Package\ExecuteExternalSqlServerPackage'
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0008 - EXECUTE PACKAGE TASK REFERENCES AN EXTERNAL PACKAGE ***/!!!!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0005 - SSIS EXECUTE PACKAGE TASK WAS CONVERTED TO A SNOWFLAKE EXECUTE TASK STATEMENT THAT RUNS ASYNCHRONOUSLY. ***/!!!
EXECUTE TASK public.data_collector_queryactivitycollect;
```

The name comes from the reference in the parent `.dtsx`:

```xml
<!-- SQL Server (msdb): the name is the package path, \Data Collector\QueryActivityCollect -> data_collector_queryactivitycollect -->
<ExecutePackageTask>
  <PackageName>\Data Collector\QueryActivityCollect</PackageName>
  <Connection>{12BC6AFD-400C-4B64-A7F0-FF3E24884AFB}</Connection>
</ExecutePackageTask>
<!-- File system: no PackageName; the File connection manager's ConnectionString is the .dtsx path -->
<ExecutePackageTask>
  <Connection>{3571E6B0-1BA3-4059-9FCD-6F64C2BA11E5}</Connection>
</ExecutePackageTask>
```

Look the connection's `DTS:DTSID` up in the package's `<DTS:ConnectionManagers>` or in a `.conmgr` file.

## Fix Patterns

### Pattern 1: The child was converted as a procedure

Search the output for `CREATE OR REPLACE PROCEDURE public.<child>`. If it is there, replace the statement with `CALL public.<child>();` and remove both markers. Pass any parameter assignments as [SSC-EWI-SSIS0006](SSC-EWI-SSIS0006.md) describes.

### Pattern 2: The child was converted as a task graph

When `CREATE OR REPLACE TASK public.<child>` is in the output (another conversion included it), the name is right. Remove this marker and resolve [SSC-EWI-SSIS0005](SSC-EWI-SSIS0005.md).

### Pattern 3: The child was never converted

The call names an object that does not exist, so it fails at run time. Leave the statement, add `-- NEEDS-USER: package <PackageName or file path> is outside this project; supply its .dtsx for conversion, or confirm the call can be dropped`, and mark as needs-user. Only remove the statement if the user confirms the child is obsolete (a Data Collector or maintenance package that has no place in Snowflake, for example).

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker once the call targets an object that exists.
- Check how the name was derived: SnowConvert turns `\Folder\Name` into `folder_name` and drops `.dtsx`. A child converted under a different name needs the name corrected here.
- A property expression on `PackageName` or `Connection` picks the child at run time ([SSC-EWI-SSIS0007](SSC-EWI-SSIS0007.md)). The generated name is then only the design-time value.
