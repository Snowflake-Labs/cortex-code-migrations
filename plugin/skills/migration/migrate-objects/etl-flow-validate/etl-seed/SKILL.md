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
| `source.platform` | Source platform |
| `files.source.path` | Source definition filename |

The machine enforces the `deploy` precondition.

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

## Step 2: Fill comparison settings

Open `{ARTIFACTS_PATH}/etl-test/<name>.yml`. For every `comparison.tables[]` entry:

1. Set `index_columns` to stable row keys.
2. Set `target_index_columns` only when target key names differ.
3. Use `source_columns` and `target_columns` with `mode: exclude` for non-deterministic wall-clock values such as columns populated from `GETDATE()`. `excluded_columns` is not a valid v2 table-entry key.

For the Workload 4 example, use `TaskID` as the key and exclude `DepreciatedAt`.

## Step 3: Arrange both sides

Identify read tables and write sinks from CUR dependencies and `comparison.tables`.

For read tables:

1. Compare source and Snowflake row counts.
2. Require matching, non-zero counts.
3. Prefer `migrate_data` on the **table** code units when the source already has rows.
4. If the source is empty, insert identical deterministic literals on both sides.

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

For write sinks:

1. `TRUNCATE` the Snowflake sink.
2. Leave the source sink empty.
3. Never call `migrate_data` for a sink.

Never arrange SQL Server only, and never use MCP `query_source` for DML. Stop when read counts differ, either read side is empty, or a Snowflake sink is non-empty. Handle clock columns through `source_columns` / `target_columns` exclusions, not a code rewrite. Surface PARTIAL coverage without failing the stamp.

## Step 4: Confirm and advance

Show the user:

- seeded table pairs;
- keys and exclusions;
- source and Snowflake read counts;
- empty sink checks.

Only after the YAML contains non-empty `comparison.tables`, arrangement is confirmed, and the user accepts the settings:

```text
transition_status(status="advance", task="validateEtlSeed", outcome="completed", where="id = '{ETL_ID}'")
```

The machine then routes to `validateEtlValidate`.

For Informatica, collect unresolved `pmcmd_path`, service, and domain values without writing credentials into committed configuration. Verify them with `scai test etl-validate --platform {PLATFORM_ID} --check-env` before advancing.
