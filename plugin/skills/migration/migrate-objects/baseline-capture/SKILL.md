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

## Step 1: Choose a Path

**Ask the user which approach to use for `<object_name>`:**

| Path | When to Use | Input Required |
|------|-------------|----------------|
| **Query Logs** | You have CSV logs of real source procedure calls | CSV file with EXEC/CALL statements |
| **AI-Assisted** | No logs available, need to generate test cases | Source SQL files with CREATE PROCEDURE/FUNCTION |

## Step 2: Route to Create Baselines

- **Query Logs** → Load [QUERY_LOGS.md](QUERY_LOGS.md) for `<object_name>`
- **AI-Assisted** → Load [SWARM.md](SWARM.md) for `<object_name>`

## Step 3: Capture Baselines from Source System and Upload to Snowflake

After creating test config for `<object_name>`, load [CAPTURE.md](CAPTURE.md) to capture and upload baselines. Use `--objects <object_name>` to capture only this object.

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
