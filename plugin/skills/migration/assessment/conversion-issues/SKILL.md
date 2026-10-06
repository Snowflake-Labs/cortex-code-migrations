---
name: conversion-issues
description: Builds the AIM conversion-issues artifact and Jira ZIP from registry SSC-EWI markers, then fills Problem Description and Recommended Fix.
parent_skill: assessment
license: Proprietary. See License-Skills for complete terms
---

# Conversion issues

Non-interactive child. Do not ask questions. Call `configure` with `project_dir` from the parent, then run the command from that project.

## Generate

```bash
scai assessment conversion-issues
```

This reads the code unit registry and converted files. It writes:

- `<project_dir>/artifacts/assessment/conversion-issues.json`
- `<project_dir>/artifacts/assessment/conversion-issues/conversion_issues.csv`
- `<project_dir>/artifacts/assessment/conversion-issues/conversion_issues.zip`

Zero `SSC-EWI-` pairs is success: JSON only, no CSV, no ZIP. `ASM0045` (no registry) is `error`, not `skipped`.

## Fill problem and fix

Read `panels` where `id` is `summary`. For each row, take `code` and `description` only.

For each distinct pair, write a Problem Description and a Recommended Fix that name the construct in the description. Use sources in this order:

1. AIM conversion-issue documentation in the Snowflake migrations documentation
2. The source dialect documentation
3. Snowflake SQL documentation

The fix must name a concrete replacement. Do not leave `<!-- ewi-skill:agent-must-fill -->`.

Write `<project_dir>/artifacts/assessment/conversion-issues/updates.json`:

```json
[{ "code": "SSC-EWI-0040", "description": "THE 'SET XACT_ABORT' CLAUSE IS NOT SUPPORTED IN SNOWFLAKE",
   "problem_description": "...", "recommended_fix": "..." }]
```

When the summary panel has no rows, skip the updates file.

When `updates.json` already exists, the command reapplies it on every run. Keep its entries and research only the rows whose `problem_description` is still empty.

## Rerun

```bash
scai assessment conversion-issues --updates artifacts/assessment/conversion-issues/updates.json
```

Run that only when `updates.json` was written. The parent does not upload the ZIP. The report shows the ZIP path and the Share issues link.

## Return

JSON only:

```json
{ "sub_skill": "conversion-issues", "status": "ok", "output_json": "<abs>/artifacts/assessment/conversion-issues.json",
  "summary": "<distinct pairs> pairs, <instances> instances", "error": null }
```

Any other failure: `status` `"error"`, `output_json` `null`, `error` `"<message>"`.
