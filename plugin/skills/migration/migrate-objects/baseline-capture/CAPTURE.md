# Capture and Upload Baselines

After creating the test YAML files (from query logs or AI swarm), capture baselines from the source database and upload to Snowflake.

> **⚠️ SCOPE: Capture baselines for ONE object at a time.**

## Step 1: Capture Baselines from Source Database

Baselines upload to the Snowflake stage `@<DATABASE>.VALIDATION.BASELINES`; no copy is kept on the user's laptop (customer data residency).

```bash
scai test capture \
  -s <SOURCE_CONNECTION_NAME> \
  -c <SNOWFLAKE_CONNECTION_NAME> \
  --where "source.canonicalName ILIKE '%<schema>.<object_name>%'"
```

**Flags:**
- `-s, --source-connection` — Name of the source connection (from `scai connection list`). Uses default if not specified.
- `-c, --connection` — Snowflake connection (destination for baseline upload). Required unless `target_connection.name` is set in `settings/test_config.yaml`.
- `--where` — Registry filter, SQL-like (same syntax as `scai code deploy --where`). The canonical form used across the plugin is `source.canonicalName ILIKE '%<name>%'`.

## Step 2: Verify

List the stage, filtering server-side to just this object's baselines:

```bash
snow stage list-files @<DATABASE>.VALIDATION.BASELINES \
  --pattern ".*<schema>\.<object_name>.*" \
  -c <SNOWFLAKE_CONNECTION_NAME>
```

## CHECKPOINT

Confirm:
- [ ] Baselines captured for `<object_name>` from source database
- [ ] Baselines visible on Snowflake stage `@<DATABASE>.VALIDATION.BASELINES`
- [ ] At least 15-25 test cases for this object

## Next Steps

Load [migrate-object/SKILL.md](../migrate-object/SKILL.md) to start the deploy-test-fix loop for `<object_name>`.
