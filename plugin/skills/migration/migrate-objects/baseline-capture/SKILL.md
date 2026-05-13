---
name: baseline-capture
description: Capture source stored procedure and function output as baselines for Snowflake validation. Supports query log parsing and AI-assisted test case generation with agent swarms.
parent_skill: migrate-objects
license: Proprietary. See License-Skills for complete terms
---

# Baseline Capture

Capture the expected output of a **single** source stored procedure or function to use as a baseline for Snowflake validation. Baselines are JSON files recording what the object returns for a given set of parameters.

> **⚠️ SCOPE: This skill operates on ONE object at a time.**
> You must already know `<object_name>` (passed from [../SKILL.md](../SKILL.md) Step 4).
> All commands below must target only this object.

## On Entry

Tell the user:
> **Capturing test baselines for `<object_name>`** — I'll record what this object returns from your source database so we can compare it against Snowflake after deployment.

## Prerequisites

- Source database connection configured (SQL Server or Redshift) and Snowflake validation framework deployed (see [setup/SKILL.md](../setup/SKILL.md))
- Source SQL files available (in `source/` directory of scai project)

## Step 1: Choose a Seeder

The seeder to use is determined by `testing_data_source` (set via `configure()` from the upfront prompt in [../SKILL.md](../SKILL.md) Step 2). Seeders produce the test YAML artifacts; the capture step is the same for all of them.

| `testing_data_source` | Seeder | When to Use | Input Required |
|-----------------------|--------|-------------|----------------|
| `source_database` + has CSV | **Query Logs** | Real source procedure calls are available as CSV | CSV file with `EXEC`/`CALL` statements |
| `source_database` + no CSV | **AI-Assisted Swarm** | No logs, but source DB has representative data | Source SQL + live source DB connection |
| `synthetic` | **Branch-Driven Synthetic** | No source data available; generate from SQL analysis | Source SQL files only |

If `testing_data_source == "source_database"`, ask the user which of the two source-DB seeders to use (Query Logs or AI-Assisted). If `testing_data_source == "synthetic"`, go straight to the synthetic seeder — no sub-prompt.

## Step 2: Route to Seeder

- **Query Logs** → Load [QUERY_LOGS.md](QUERY_LOGS.md) for `<object_name>`
- **AI-Assisted Swarm** → Load [SWARM.md](SWARM.md) for `<object_name>`
- **Branch-Driven Synthetic** → Load [synthetic-seeder/SKILL.md](synthetic-seeder/SKILL.md) for `<object_name>`

All three seeders write YAML test artifacts under `artifacts/` that are directly consumable by `scai test capture` + `scai test validate`.

## Step 3: Capture Baselines from Source System and Upload to Snowflake

After the seeder returns, load [CAPTURE.md](CAPTURE.md) to capture and upload baselines. Use `--objects <object_name>` to capture only this object. This is the same step regardless of which seeder ran.

## Return to Parent

After baselines are captured and uploaded, report back to the parent agent with:

```
Baseline capture complete for <object_name>.
- Path: <query_logs | ai_assisted>
- Test cases: <N> cases in <yaml_file_path>
- Baselines: <N> captured to <baseline_dir>
- Upload: <success | failed | skipped>
```

Do NOT load any further skills — return control to the caller.
