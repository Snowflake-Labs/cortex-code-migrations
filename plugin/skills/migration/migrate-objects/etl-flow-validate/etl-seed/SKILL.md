---
name: validate-etl-seed
description: Seed the ETL test YAML and arrange both source and Snowflake data for the isolated validate flow.
parent_skill: migrate-objects
license: Proprietary. See License-Skills for complete terms
---

# Validate-flow ETL Seed

Generate the ETL test YAML for one deployed ETL code unit, fill its comparison settings, and arrange both sides before validation. This executor belongs only to `validateEtlSeed`; do not advance or modify the live `etlSeed` task.

## Step 0: Resolve the unit

Read the registry entry and retain:

| Field | Use |
|---|---|
| `id` | `{ETL_ID}` in CLI and registry filters |
| `files.artifacts.path` | `{ARTIFACTS_PATH}`; the YAML is written under `{ARTIFACTS_PATH}/etl-test/` |
| `source.platform`, else `extensions.sourcePlatform` | Source platform (`apacheHop` for Apache Hop, `pentaho` for Pentaho; either may be recorded only on the extension) |
| `files.source.path` | Source definition filename |

The machine enforces the `deploy` precondition.

## Step 0b: Platforms without a native executor (Apache Hop, Pentaho, …)

When the platform is neither `ssis` nor `informatica` (for example `apacheHop`), the source
side runs through a launcher the user owns. `.scai/settings/test_config.yaml` must declare it
**before** Step 1; the seeder reads it once per run and otherwise skips the unit as
`UnsupportedPlatform`.

If the section is missing, add it.

**Apache Hop:** scai ships the launcher (`hop_run_launcher.py`); `{launchers_dir}` resolves to the
directory it is installed in, so never write a repository or install path for it. Ask the user only
for their own Hop install: the Hop directory (`HOP_HOME`, the one holding `hop-run.sh`, or
`hop-run.bat` on Windows), a Java 17+ home for Hop 2.x (`HOP_JAVA_HOME`), the Hop project and
environment whose connection metadata points the pipeline at their database, and the Hop config
folder that registers them (`HOP_CONFIG_FOLDER`; Hop's default is `$HOP_HOME/config`, and the
launcher passes only what `env:` lists, so a folder set in their shell must be written here). Hop's own metadata
holds the JDBC settings and credentials; do not invent them. On Windows use `python` instead of
`python3`.

```yaml
validation_database: <migration target database: where the converted pipeline writes>
etl_source_isolation_strategy: none   # no SQL Server / Teradata source to isolate
external_command:
  side: source
  timeout_seconds: 600                # launcher contract: wait for exit, read {status_file}
  writes_to: <snowflake | source>     # where the pipeline's tables live (below)
  command: [python3, "{launchers_dir}/hop_run_launcher.py", --job, "{job}", --params, "{params_file}", --status, "{status_file}", --timeout, "{timeout}", --unit, "{unit_id}"]
  env:                                # the child does not inherit the harness environment
    HOP_HOME: <Apache Hop install directory>        # or HOP_RUN: <path to hop-run.sh>
    HOP_JAVA_HOME: <Java 17+ home>                  # Hop 2.x refuses older Java
    HOP_PROJECT: <Hop project>
    HOP_ENVIRONMENT: <Hop environment>
    HOP_CONFIG_FOLDER: <Hop config folder>         # omit when it is $HOP_HOME/config
    HOP_RUNCONFIG: local
  database_params:                    # only when the Hop connection names its database by a variable
    <Hop variable>: <database token>  # e.g. TT_SQL_DATABASE: defaultdb
```

`database_params` points the user's job at the database the comparison reads: each run passes the
token's bound `source:` database (a testbed project's `AIMSBX_TB_*` catalog) to the launcher as that
Hop variable. Add it when the user's Hop connection takes its database name from a variable (ask
which one; it is in their Hop connection or environment). Without it the job keeps the database its
own metadata names, which on a testbed project is not the one holding the generated rows.

`writes_to` is where the comparison reads the original pipeline's tables: `snowflake` when the
user's pipeline reads and writes a Snowflake database, `source` when it writes the source database
behind the project's source connection. Take it from what the user said about their pipeline; ask
when they have not said. It matters most when the project also has a source connection, which
would otherwise be used.

The launcher writes Hop's full output to `hop.log` beside the unit's `status.json` (its path is
the status file's `log_path`); read it first when the source side reports FAILED.

**Pentaho Data Integration (Kettle):** scai ships the launcher (`pentaho_run_launcher.py`): `.ktr`
transformations run with `pan.sh`, `.kjb` jobs with `kitchen.sh`. Ask the user only how their PDI is
reached: a long-lived container (`PDI_CONTAINER`, default `pdi`; the job is copied in with `docker cp`
and run with `docker exec`) or a local install (`PDI_HOME`, the `data-integration` directory holding
`pan.sh`). PDI's connection variables (`${MSSQL_HOST}` and so on inside the `.ktr`) come from the
user's `kettle.properties` under `KETTLE_HOME`, not from this file; do not invent them.

```yaml
external_command:
  side: source
  timeout_seconds: 600                # PDI takes 20-30 s to start under amd64 emulation
  writes_to: <snowflake | source>
  command: [python3, "{launchers_dir}/pentaho_run_launcher.py", --job, "{job}", --params, "{params_file}", --status, "{status_file}", --timeout, "{timeout}", --unit, "{unit_id}"]
  env:                                # the child does not inherit the harness environment
    PDI_CONTAINER: <container name>   # or PDI_HOME: <data-integration directory>
    PDI_OPTIONS: <optional, e.g. -Duser.timezone=UTC>
```

The launcher writes PDI's full output to `pdi.log` beside the unit's `status.json`. Validate with
`scai test etl-validate --platform pentaho`.

**Any other platform:** ask the user for the launcher command that runs their pipeline against
its own database, in the same shape (`command: [<launcher>, --job, "{job}", ...]`, optionally a
`check_command:` probe). The command is theirs; do not invent one.

With this section, `scai test seed` and `scai test etl-validate` need **no source connection**: do
not pass `-s` and do not ask for a SQL Server login. Source and target table names resolve through
`.scai/bindings/database-bindings.yaml` (`source:` is the database the pipeline itself writes,
`snow:` is the migration target). The runner requalifies every comparison **target** into
`validation_database`, so it must be the `snow:` database, never the one the original pipeline
writes. Confirm the two differ; a Snowflake source that resolves onto its own target fails the
comparison instead of passing it.

## Step 1: Seed the test YAML

Run:

```bash
scai test seed --where "id = '{ETL_ID}'"
```

If a YAML already exists, preserve hand-edited comparison settings:

```bash
scai test seed --where "id = '{ETL_ID}'" --append
```

The seeder derives source→target table pairs from CUR write dependencies and writes the YAML beneath the registry's `files.artifacts.path`, not beneath an ID-named directory. Do not invent pairs unless the reported skip reason has been investigated and the user confirms the missing pair.

Handle skips at their cause:

| Skip reason | Action |
|---|---|
| `NoWriteDependencies` | Confirm conversion/assessment is complete and whether the unit writes tables. |
| `MissingDependency` | Register or resolve the missing write dependency. |
| `MissingCanonicalName` | Correct the dependency registry entry. |
| `UnknownFormat` / `PendingFormat` / `MixedFormat` | Finish conversion and deployment for routable parts. |
| `NoArtifactsPath` | Correct the unit's conversion/deployment registration. |
| `UnsupportedPlatform` | Configure the project `external_command` opt-in or treat the unit as out of scope. |

## Step 2: Review comparison settings

Open `{ARTIFACTS_PATH}/etl-test/<name>.yml` and read it. **Do not edit it**: not by the edit tool,
not by a script. The seed derives every setting from the registry and the converted unit, so a
setting that is wrong or missing is a seed gap to report, not a line to add.

A unit that writes no table (a File System Task or Foreach package, or a Hop pipeline that only checks rows, run by the launcher) is seeded with `comparison.sink: none` and no `comparison.tables`. It passes when both of its execution branches succeed, so it has no table pairs, keys or exclusions: skip to Step 3. A seed that leaves `comparison.tables: []` with a warning is not sink-less: stop and report the tables the unit writes.

What the seed fills on each `comparison.tables[]` entry:

1. `index_columns`: the table's primary key, else the columns the converted unit's write matches
   rows on (an upsert or merge key; a versioned dimension's key and version). With neither, it
   leaves the key out and the comparison keys rows on every compared column; that is correct, so
   do not add one.
2. `target_index_columns`: only when the target key names differ.
3. `source_columns` / `target_columns` exclusions: the clock columns the converted unit declares
   (a slowly changing dimension's validity and audit dates) and the testbed's load-time defaults.
   `excluded_columns` is not a valid v2 table-entry key.
4. `target_prestate: source`: on a sink whose run keeps the table's existing rows (below).

If a compared column holds a wall-clock value the seed did not exclude (a `GETDATE()` / `NOW()`
the converted unit does not declare), tell the user which column it is and that the comparison
will report it as different; do not add the exclusion yourself.

## Step 3: Arrange both sides

Identify read tables and write sinks from CUR dependencies and `comparison.tables`.

For read tables:

1. Compare source and Snowflake row counts.
2. Require matching, non-zero counts.
3. When the source already has rows, load them with `migrate_data` on the **table** code units
   (the machine's `migrateData` task for those tables). Never copy source rows into Snowflake by
   hand (`INSERT ... VALUES` built from a source query). If `migrate_data` reports the project as
   schema-only or needs data-migration infrastructure that is not set up, stop and tell the user
   the read tables cannot be loaded yet.
4. Only if the source is empty, insert identical deterministic literals on both sides.

For the Workload 4 example:

```sql
-- SQL Server: scai query -q '...' -s <source_connection>
INSERT INTO dbo.Employees (EmployeeID, FirstName, LastName, Email, Department, HireDate, IsActive)
VALUES (1, 'Ada', 'Lovelace', 'ada@example.com', 'Eng', '2020-01-01', 1);

INSERT INTO dbo.Tasks (TaskID, Title, Description, AssigneeID, Priority, Status, CreatedAt, DueDate, CompletedAt)
VALUES (1, 'Sample', NULL, 1, 'Medium', 'Open', '2020-01-02', NULL, NULL);

-- Snowflake: snow sql -c <snowflake_connection> -q '...'
INSERT INTO "EMPLOYEES" ("EMPLOYEEID", "FIRSTNAME", "LASTNAME", "EMAIL", "DEPARTMENT", "HIREDATE", "ISACTIVE")
VALUES (1, 'Ada', 'Lovelace', 'ada@example.com', 'Eng', '2020-01-01', 1);

INSERT INTO "TASKS" ("TASKID", "TITLE", "DESCRIPTION", "ASSIGNEEID", "PRIORITY", "STATUS", "CREATEDAT", "DUEDATE", "COMPLETEDAT")
VALUES (1, 'Sample', NULL, 1, 'Medium', 'Open', '2020-01-02', NULL, NULL);
```

For write sinks (a `sink: none` unit has none to empty, so arrange only its read tables), the
seeded entry says how the unit writes it. An entry with `target_prestate: source` is a sink whose
run **keeps its existing rows**: the unit appends to it, updates, merges or deletes its rows,
inserts only the keys it does not find, or empties it only when it has rows to write (Hop Table
output without truncate or with truncate-only-when-rows, Insert/update, Update, Delete,
Synchronize after merge, Dimension lookup/update, Combination lookup/update). Every other sink
is replaced on each run.

Replace sink (no `target_prestate`):

1. `TRUNCATE` the Snowflake sink. A sink that is a Dynamic Table (`SSC-FDM-SSIS0032`) cannot be truncated or seeded: skip it here and in the empty-sink check, since the unit's run refreshes it from its sources.
2. Leave the source sink empty: read its count with `query_source` (read-only). If it has rows,
   stop and ask the user to empty it; scai never writes the source database. A testbed project's
   `AIMSBX_TB_*` catalog is the exception: it is the project's own, and an earlier validation's run
   left its rows there. Reset the sink to its generated rows with
   `setup_sandbox(mode="load_only", where="id = '<sink table id>'")`, then read the count again.
   Never empty it by SQL.
3. Never call `migrate_data` for a sink.

Sink with `target_prestate: source`: empty and write neither side. The source sink holds the
rows the user's pipeline starts from; read its count and show it. Before each run
`scai test etl-validate` overwrites the target sink with those rows, so both pipelines start
equal. Never `TRUNCATE`, `INSERT`, `MERGE` or `UPDATE` such a sink by hand. An empty source
sink only tests what the unit writes into an empty table: say so to the user.

When the source side is an `external_command` launcher whose pipeline reads and writes a
**Snowflake** database (Apache Hop on Workload 4), both sides are Snowflake: run every statement
with `snow sql -c <snowflake_connection>`, qualified by the bound database. `migrate_data` does not
apply (there is no source database connector), so make the read tables equal with
`INSERT INTO <target_db>.DBO.TASKS SELECT * FROM <source_db>.DBO.TASKS` after a `TRUNCATE` of the
**target** read table, and `TRUNCATE` a replace sink on **both** databases. A sink with
`target_prestate: source` is the user's own table: leave it on both databases. The source read
table is the pipeline's live input: read its count, and never `TRUNCATE` it or insert literals into
it. The literal-insert rule above is only for an empty source.

Never arrange SQL Server only, and never use MCP `query_source` for DML. Stop when read counts differ, either read side is empty, or a replace Snowflake sink is non-empty. Clock columns are the seed's exclusions (Step 2), not a code rewrite. Surface PARTIAL coverage without failing the stamp.

## Step 4: Confirm and advance

Show the user:

- seeded table pairs, or that the unit is seeded `sink: none`;
- keys and exclusions;
- source and Snowflake read counts;
- empty sink checks, and each in-place sink's source row count.

Only after the YAML contains non-empty `comparison.tables` or declares `comparison.sink: none`, arrangement is confirmed, and the user accepts the settings:

```text
transition_status(status="advance", task="validateEtlSeed", outcome="completed", where="id = '{ETL_ID}'")
```

The machine then routes to `validateEtlValidate`. Read its skill (the advance result's
`skillPath`) and follow it from its Step 1 pre-flight (`--check-env`); do not jump straight to
the comparison. It takes `{PLATFORM_ID}` from `source.platform`; a unit with none (Apache Hop)
uses the Step 0 platform (`apacheHop`).

For Informatica, collect unresolved `pmcmd_path`, service, and domain values without writing credentials into committed configuration. Verify them with `scai test etl-validate --platform {PLATFORM_ID} --check-env` before advancing.
