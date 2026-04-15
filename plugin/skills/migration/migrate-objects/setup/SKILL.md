---
name: unit-test-migrator-setup
description: One-time setup for the unit test migration framework. Configures source database (SQL Server or Redshift) and Snowflake connections, deploys the validation infrastructure to Snowflake, and loads existing baselines.
parent_skill: migrate-objects
license: Proprietary. See License-Skills for complete terms
---

# Setup - Validation Framework

One-time setup to prepare the 2-sided testing infrastructure. Run this once per project before capturing baselines or migrating code units.

## Prerequisites

- A Snowflake account with CREATE SCHEMA, CREATE TABLE, CREATE PROCEDURE privileges
- Network access to source database (SQL Server or Redshift) for baseline capture later
- `scai` CLI installed

## Step 1: Confirm Snowflake Connection

Show the user the current Snowflake connection:

```sql
SELECT CURRENT_ACCOUNT(), CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE();
```

Ask the user:

> "You are connected to Snowflake as:
> - **Account:** <account>
> - **User:** <user>
> - **Role:** <role>
> - **Database:** <database>
> - **Warehouse:** <warehouse>
>
> Is this the correct connection for the migration?"

If not, ask the user to set the correct connection before continuing.

## Step 2: Verify Source Database Connection

Check if a source connection already exists:

```bash
# Check for SQL Server connections
scai connection list -l sqlserver 2>/dev/null

# Check for Redshift connections
scai connection list -l redshift 2>/dev/null
```

**If a connection exists**, test it:

```bash
scai connection test -l <sqlserver|redshift> -c <CONNECTION_NAME>
```

**If no connection exists**, follow the appropriate connection skill:
- **SQL Server** → [../../connection/sql-server-connection/SKILL.md](../../connection/sql-server-connection/SKILL.md)
- **Redshift** → [../../connection/redshift-connection/SKILL.md](../../connection/redshift-connection/SKILL.md)

Once connected, return here to continue setup.

## Step 2b: Configure Redshift Staging (Redshift only)

If the source platform is Redshift, load [./configure-redshift-source.md](./configure-redshift-source.md) to set up the S3 bucket, Snowflake stage, and IAM role required for data migration staging.

If the source is SQL Server, skip to Step 3.

## Step 3: Verify scai Project

The validation framework assumes a scai migration project exists with converted code.

```bash
# Check for existing project
scai project info

# Verify converted code exists
ls snowflake/procedure/ 2>/dev/null
ls snowflake/function/ 2>/dev/null
ls artifacts/ 2>/dev/null
```

If no project exists, see the parent [migration/SKILL.md](../../SKILL.md) to set one up.

## Step 4: Create Validation Schema and Stage

The validation framework stores results in a `VALIDATION` schema. Confirm with the user and create it if it does not exist:

```sql
CREATE SCHEMA IF NOT EXISTS VALIDATION;
CREATE STAGE IF NOT EXISTS VALIDATION.VALIDATOR_STAGE;
```

## Step 5: Deploy Validation Schema

Deploy the validation infrastructure used by `scai test` (uses `configure` database):

```bash
scai test validate --create-schema -c <CONNECTION_NAME>
```

This creates:

| Object | Type | Purpose |
|--------|------|---------|
| `RESULTS` | Table | Test execution results from Snowflake |
| `BASELINE_ROWS` | Table | Materialized baseline row data |
| `BASELINES` | Stage | Baseline JSON files |
| `JSON_FORMAT` | File Format | For reading baseline JSON |
| `SUMMARY` | View | Pass/fail counts per code unit |
| `LATEST` | View | Latest result per test case |
| `FAILURES` | View | Failed tests with details |

## Step 6: Verify Setup

Run a quick health check:

```sql
SHOW TABLES IN SCHEMA VALIDATION;
SHOW VIEWS IN SCHEMA VALIDATION;

SELECT COUNT(*) AS total_results FROM VALIDATION.RESULTS;
```

## CHECKPOINT

Confirm with the user:
- [ ] Snowflake connection tested successfully
- [ ] Source database connection configured (SQL Server or Redshift)
- [ ] Redshift staging configured (Redshift only — S3 bucket, stage, IAM role)
- [ ] scai project exists with converted code
- [ ] Test config generated (`settings/test_config.yaml` — auto-created by `configure()`)
- [ ] VALIDATION schema created
- [ ] Validation schema deployed (`scai test validate --create-schema`)
- [ ] Baselines captured (or ready to capture)

## Next Steps

Go back to the main skill to pick the next object to migrate [../SKILL.md](../SKILL.md)

| User says | Action |
|-----------|--------|
| Capture baselines | Load [baseline-capture/SKILL.md](../baseline-capture/SKILL.md) |
| Start migrating | Load [migrate-object/SKILL.md](../migrate-object/SKILL.md) |
