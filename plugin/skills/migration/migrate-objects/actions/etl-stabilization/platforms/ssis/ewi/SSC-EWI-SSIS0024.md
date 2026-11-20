# SSC-EWI-SSIS0024 — Bulk Insert Stage and File Upload Not Created

Every Bulk Insert task becomes a `COPY INTO ... FROM '@{STAGE_PLACEHOLDER}'`. The stage, and getting the source file into it, are not part of the conversion. The marker **breaks compilation**, and so does the placeholder.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Once per Bulk Insert task |
| Common action | Point the `COPY` at the stage the files land in; mark needs-user if no such stage exists yet |

## Identification

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0024 - THE STAGE AND FILE UPLOAD ARE NOT INCLUDED IN THE TRANSLATION. CREATE A SNOWFLAKE STAGE AND UPLOAD THE SOURCE FILE BEFORE EXECUTING THE COPY INTO STATEMENT. REPLACE {STAGE_PLACEHOLDER} WITH YOUR STAGE NAME. ***/!!!
--** SSC-FDM-SSIS0013 - ... **
COPY INTO dbo.Employees
FROM '@{STAGE_PLACEHOLDER}'
PATTERN = '.*employees\\.csv.*'
FILE_FORMAT = (TYPE = 'CSV', FIELD_DELIMITER = ',', RECORD_DELIMITER = '\n', SKIP_HEADER = 1, NULL_IF = ('', 'NULL', 'null'), ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE)
ON_ERROR = SKIP_FILE_10;
```

`PATTERN` is the file name from the source connection's design-time `ConnectionString`.

## Fix Patterns

### Pattern 1: A stage already exists for the package's files

Other SSIS file sources in the same conversion read from a landing stage (look for `@public.landing_stage/ssis/<package>/...` or the stage the project's setup created). Use the same stage and the folder the file lands in:

```sql
COPY INTO dbo.Employees
FROM @public.landing_stage/hr/
FILES = ('employees.csv')
FILE_FORMAT = (...)
ON_ERROR = SKIP_FILE_10;
```

Name one file with `FILES`, not a `PATTERN`: `'.*employees[.]csv'` also loads `old_employees.csv` and `archive/employees.csv`.

### Pattern 2: Inside a Foreach File loop

The source connection's `ConnectionString` usually follows the loop variable (`@[User::CurrentFile]`), so the design-time `PATTERN` is pinned to one sample file. Either:

- load from the loop's current file: `EXECUTE IMMEDIATE 'COPY INTO raw.T FROM ''' || :STAGE_FILE_PATH || ''' FILE_FORMAT = (...)';`, using the cursor column the engine generated; or
- replace the loop with one `COPY INTO ... PATTERN = '.*/CLM_HIST_[^/]*[.]csv'` when every file loads the same way. `/CLM_HIST_` keeps the match at the start of a file name and `[^/]*` inside it, as the SSIS file spec `CLM_HIST_*.csv` did; files in subfolders under the `FROM` path still match, so check there are none. `COPY` skips files it already loaded, which matches the usual "archive after load" intent.

### Pattern 3: No stage, or the files come from a share outside Snowflake

`PUT` runs only from a client, never inside a task or procedure, so the conversion cannot upload the file itself. Write the `COPY` against the stage the files are expected in, add `-- NEEDS-USER: create stage <name> and land <path> files there (external stage, Snowpipe or a client PUT)`, and mark as needs-user.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker and replace `'@{STAGE_PLACEHOLDER}'`.
- `ON_ERROR = SKIP_FILE_n` skips a file silently once it has *n* errors; SSIS failed the task at `MaximumErrors`. Use `ABORT_STATEMENT` when the package's later tasks assume a complete load.
- A follow-up task that stamps the file name (`UPDATE ... SET FILE_NAME = ?`) can be folded into the `COPY` with `METADATA$FILENAME`.
- With a format file, also apply [SSC-EWI-SSIS0023](SSC-EWI-SSIS0023.md).
