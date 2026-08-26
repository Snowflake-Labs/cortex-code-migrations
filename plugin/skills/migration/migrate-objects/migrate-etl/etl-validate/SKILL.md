---
name: etl-validate
description: Run scai test etl-validate to compare live SSIS/Informatica package output against the converted Snowflake output. The CLI stamps codeStatus.etlValidate — do not invent advance outcomes.
parent_skill: migrate-etl
license: Proprietary. See License-Skills for complete terms
---

# ETL Validate

Runs `scai test etl-validate --platform <platform>` against a single ETL code unit, verifying that the original source package and its Snowflake equivalent produce identical output. Requires the ETL unit to be **deployed** and a **test YAML** to exist for it.

**Deploy, the test YAML, and connections are all enforced by the state machine, not this skill.** `etlValidate` has deterministic preconditions: `deploy` (the unit is deployed to Snowflake), `artifactExists` on `etl-test/*.y*ml` (a `kind: etl` test YAML — `.yml` or `.yaml`, from `etlSeed`/`scai test seed` or hand-authored — is present under the unit's artifacts dir), and `configureSourceConnection` + `configureSnowflakeTarget`. The executor only dispatches this skill once all hold, so it is safe to run standalone (targeted directly at `etlValidate`): the machine will not dispatch it against an undeployed unit, one with no test YAML, or an unconfigured session. `scai test etl-validate` reads the connection details from the project's `settings/test_config.yaml`; named-connection overrides can be passed with `-c` / `-s`.

## Step 0: Resolve Unit

Read the registry entry (the executor passes `object_id`; if entered by name, locate via `migration_status(mode="my_objects_summary")`):

| Field | Used as |
|---|---|
| `id` | `{ETL_ID}` for the `--where` filter |
| `source.platform` | `{PLATFORM_ID}` for `--platform` (`ssis`, `informatica`, …) |

## Step 1: Live Environment Pre-flight

The state machine guarantees the connections are *configured*; it cannot know whether the live systems are *reachable*. Run the built-in probe once to catch a down SQL Server, an expired Snowflake token, or a missing SSISDB catalog before starting a long comparison:

```bash
scai test etl-validate --platform {PLATFORM_ID} --check-env
```

The probe must test the **same** connection the real run in Step 2 will use, so if the session uses named-connection overrides append the identical flags here (`--connection {SNOWFLAKE_CONNECTION}` / `--source-connection {SOURCE_CONNECTION}`) — otherwise the probe green-lights the default connection while Step 2 runs against a different one.

| Check | What it tests |
|---|---|
| `sql_server_connectivity` | Can reach the source SQL Server instance |
| `snowflake_connectivity` | Can reach the Snowflake account |
| `ssisdb_catalog_access` | Can query `SSISDB.catalog.packages` (SSIS only) |

If any check fails: **STOPPING POINT** — surface the failing check name and the error from the output, and help the user fix the live-system issue (start the server, refresh credentials, grant catalog access). Do not proceed to Step 2 with a failing probe. This is a runtime reachability check, not a config gate — a failure here means the environment is down, not that the plugin is misconfigured.

## Step 2: Run Live Comparison

```bash
scai test etl-validate --platform {PLATFORM_ID} \
  --where "id = '{ETL_ID}'"
```

If the session uses named-connection overrides, append:
- `--connection {SNOWFLAKE_CONNECTION}` (Snowflake)
- `--source-connection {SOURCE_CONNECTION}` (source DB)

The command streams per-package results. Watch for the summary line reporting the failed-unit count.

**The CLI owns the registry stamp.** On each unit it actually ran, `scai test etl-validate` writes `codeStatus.etlValidate`:

| CLI outcome | Registry stamp |
|---|---|
| Unit passed | `{ status: "completed", updatedAt }` |
| Unit failed | `{ status: "failed", updatedAt, error: "comparison" }` |
| Skipped (no ETL test YAML) | *no stamp* — field stays pending |

## Step 3: Confirm stamp — do not invent advance

**Do not** call `transition_status(status="advance", …)` to invent a green or red outcome from narration. Re-read the unit via `query_registry` / `migration_status` and confirm `codeStatus.etlValidate` matches the CLI summary.

- All packages passed → registry should already read `completed`; the ETL flow is terminal.
- One or more packages failed → registry should read `failed` with `error: "comparison"`. Surface the failed package names and row-level differences from the CLI output so the user can investigate the conversion gap.

If the CLI exited non-zero but the stamp is missing (registry write failed), say so explicitly and do **not** stamp green yourself — ask the user to re-run or investigate the registry write error.

## Step 4: Exclusion

To skip live validation, disable the task at the project level in `.scai/config/plugin.yml`:

```yaml
tasks:
  etlValidate:
    enabled: false
```

A disabled task reads as **excluded** by the state machine, so the ETL flow reaches its terminal state without running the comparison. This is **project-wide** — it disables `etlValidate` for every ETL unit. Per-unit exclusion is not supported: writing `codeStatus.etlValidate=excluded` on a single entry reads back as *completed*, not excluded.
