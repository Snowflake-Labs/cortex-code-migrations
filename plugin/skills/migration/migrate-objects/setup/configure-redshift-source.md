# Configure Redshift Staging for Data Migration

Redshift data migration requires an S3 bucket as a staging area. Data is unloaded from Redshift to S3 as parquet files, then loaded into Snowflake via an external stage.

> **Prerequisites:** Source Redshift connection must already be configured (via `scai connection`). This skill only covers the staging infrastructure.
>
> For full setup details see: https://docs.snowflake.com/en/migrations/snowconvert-docs/general/user-guide/data-migration

## Step 1: Collect Staging Details

Ask the user for the three required values:

| Parameter | Description | Example |
|-----------|-------------|---------|
| **S3 Bucket URI** | Where Redshift will unload parquet files | `s3://my-migration-bucket/staging` |
| **Snowflake Stage** | Fully-qualified external stage that reads from the S3 bucket | `MY_DB.PUBLIC.REDSHIFT_STAGE` |
| **IAM Role ARN** | IAM role Redshift assumes to write to the S3 bucket | `arn:aws:iam::123456789:role/RedshiftUnload` |

## Step 2: Verify Prerequisites

### S3 Bucket

Confirm the bucket exists and the IAM role has write access. The user should verify:
- Bucket exists in the correct AWS region
- IAM role has `s3:PutObject`, `s3:GetObject`, `s3:ListBucket` permissions on the bucket

### Snowflake Storage Integration & External Stage

The Snowflake stage must already exist and point to the same S3 bucket. If it doesn't exist yet, guide the user:

```sql
-- 1. Create storage integration (requires ACCOUNTADMIN)
CREATE STORAGE INTEGRATION IF NOT EXISTS redshift_migration_integration
  TYPE = EXTERNAL_STAGE
  STORAGE_PROVIDER = 'S3'
  ENABLED = TRUE
  STORAGE_AWS_ROLE_ARN = '<IAM_ROLE_ARN>'
  STORAGE_ALLOWED_LOCATIONS = ('<S3_BUCKET_URI>');

-- 2. Get the Snowflake IAM user ARN and external ID for trust policy
DESC STORAGE INTEGRATION redshift_migration_integration;

-- 3. Create external stage
CREATE STAGE IF NOT EXISTS <STAGE_NAME>
  STORAGE_INTEGRATION = redshift_migration_integration
  URL = '<S3_BUCKET_URI>'
  FILE_FORMAT = (TYPE = PARQUET);
```

> **Note:** After creating the storage integration, the user must update the S3 bucket's IAM trust policy with the `STORAGE_AWS_IAM_USER_ARN` and `STORAGE_AWS_EXTERNAL_ID` from `DESC STORAGE INTEGRATION`.

## Step 3: Save Configuration

Call configure with all three values as a single JSON object:

```
configure(redshift_staging='{"bucket_uri":"<S3_BUCKET_URI>","stage":"<STAGE_NAME>","iam_role_arn":"<IAM_ROLE_ARN>"}')
```

## Step 4: Test with a Single Table

Run a test migration on one small table to verify the staging pipeline works end-to-end:

```
migrate_data(where="source.name = '<SMALL_TABLE_NAME>'")
```

If successful, return to the parent skill ([migrate_table.md](migrate_table.md)) to migrate all tables.

If it fails, check:

| Error | Cause | Fix |
|-------|-------|-----|
| S3 access denied | IAM role missing permissions | Update IAM policy for the bucket |
| Stage not found | Stage doesn't exist or wrong name | Verify stage with `SHOW STAGES` |
| Storage integration error | Trust policy not updated | Run `DESC STORAGE INTEGRATION` and update S3 trust policy |
