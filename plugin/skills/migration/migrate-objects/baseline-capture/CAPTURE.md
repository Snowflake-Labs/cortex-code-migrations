# Capture and Upload Baselines

After creating the test YAML files (from query logs or AI swarm), capture baselines from the source database and upload to Snowflake.

> **⚠️ SCOPE: Capture baselines for ONE object at a time.**

## Step 1: Capture Baselines from Source Database

```bash
scai test capture \
  -s <SOURCE_CONNECTION_NAME> \
  -c <SNOWFLAKE_CONNECTION_NAME> \
  --where "source.schema = '<schema>' AND source.name = '<object_name>'"
```

**Flags:**
- `-s, --source-connection` — Name of the source connection (from `scai connection list`). Uses default if not specified.
- `-c, --connection` — Snowflake connection name (enables auto-upload to stage). Uses project/default connection if not specified.
- `--where` — Registry filter to select which objects to capture (e.g. `"source.schema = 'dbo' AND source.name = 'MyProc'"`)

## Step 2: Verify

Check that baselines were captured and uploaded:

```bash
# Check local baseline files
ls <project_dir>/.scai/baselines/*/<object_name>*/

# Check Snowflake stage (if -c was provided)
snow stage ls @<DATABASE>.VALIDATION.BASELINES -c <CONNECTION_NAME>
```

## CHECKPOINT

Confirm:
- [ ] Baselines captured for `<object_name>` from source database
- [ ] Baselines uploaded to Snowflake stage (automatic with `-c` flag)
- [ ] At least 15-25 test cases for this object

## Next Steps

Load [migrate-object/SKILL.md](../migrate-object/SKILL.md) to start the deploy-test-fix loop for `<object_name>`.
