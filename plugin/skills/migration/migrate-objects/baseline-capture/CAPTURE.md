# Capture and Upload Baselines

After creating the test YAML files, capture baselines from the source database and upload to Snowflake.

> **⚠️ SCOPE: Capture baselines for ONE object at a time.**

## Step 1: Capture Baselines from Source Database

Call the `run_tests` MCP tool with `mode=capture` and `object_name` or `where`. Do **not**
pass `--profile` or `--database-bindings` — the tool injects them from the object's leftover
sandbox yaml after `deploySandbox`, else `.scai/bindings/database-bindings.yaml`.

Both connections come from `configure` for this project — read them back from
`migration_status` rather than from anything in your own environment. In particular the
connection your `sql_execute` tool uses is **not** one of them: it is a read-only reader
scoped to its own databases, and passing it here fails with `CNX0021` /
`390201 The requested database does not exist or not authorized`, which reads as the project
being misconfigured rather than as the wrong connection having been named.

## Step 2: Verify

List the stage, filtering server-side to just this object's baselines:

```bash
snow stage list-files @<TESTING_RESULTS_DATABASE>.VALIDATION.BASELINES \
  --pattern ".*<schema>\.<object_name>.*" \
  -c <SNOWFLAKE_CONNECTION_NAME>
```

## Step 3 (BTEQ scripts only): mark capture complete

For BTEQ scripts the baseline is uploaded to the stage and `VALIDATION.BASELINE_METADATA` is not written, so the state machine cannot infer capture from Snowflake — stamp the task explicitly:

```
transition_status status=advance task=captureBaseline --where "id = '<unit_id>'"
```

Procedures/functions skip this — their `captureBaseline` completes once `VALIDATION.BASELINE_METADATA` has a row for the object whose `ROW_COUNTS` sum to more than zero.

If capture fails because **the source object cannot run as written on any
legal dataset** (column-count mismatch on `INSERT…EXEC`, missing columns, a
numeric overflow the object's own SQL always hits), escalate on
`captureBaseline`. Do not `ALTER` the source to make the capture green and
do not skip ahead to deploy.

If capture fails only because **this fixture's rows** are the wrong shape
(concat of in-domain values into a narrower temp column, a join the
fixture never produced), spawn
(`subagent_type="sandbox_specialist"`) with `task=captureBaseline`. Do not stamp
`error=sql`. After `done`, note the reshape and retry capture. Leftover
sandbox yaml is the binding.

## CHECKPOINT

Confirm:
- [ ] Baselines captured for `<object_name>` from source database
- [ ] Baselines visible on Snowflake stage `@<TESTING_RESULTS_DATABASE>.VALIDATION.BASELINES`
- [ ] At least 15-25 test cases for this object
