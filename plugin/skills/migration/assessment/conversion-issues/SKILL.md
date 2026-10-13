---
name: conversion-issues
description: Builds the AIM conversion-issues artifact and Jira ZIP from registry SSC-EWI markers, then fills Problem Description and Recommended Fix.
parent_skill: assessment
license: Proprietary. See License-Skills for complete terms
---

# Conversion issues

Non-interactive child. Do not ask questions. Call `configure` with `project_dir` from the parent, then run the command from that project.

The first command is not the result. It collects issues and leaves `problem_description` and `recommended_fix` empty. Returning after that command, or checking only counts and files, is a failure. Done means the regenerated JSON has both fields filled for every summary row, or there are zero pairs.

## 1. Collect

```bash
scai assessment conversion-issues
```

This reads the code unit registry and converted files. It writes:

- `<project_dir>/artifacts/assessment/conversion-issues.json`
- `<project_dir>/artifacts/assessment/conversion-issues/conversion_issues.csv`
- `<project_dir>/artifacts/assessment/conversion-issues/conversion_issues.zip`

Zero `SSC-EWI-` pairs is success: JSON only, no CSV, no ZIP, and no enrichment. Stop there and return `ok`. `ASM0045` (no registry) is `error`, not `skipped`.

## 2. Enrich

Required whenever the summary panel has rows. Read `panels` where `id` is `summary`. For each row, take `code` and `description` only.

For each distinct pair, write a Problem Description and a Recommended Fix that name the construct in the description. Use sources in this order:

1. AIM conversion-issue documentation in the Snowflake migrations documentation
2. The source dialect documentation
3. Snowflake SQL documentation

The fix must name a concrete replacement. Do not leave `<!-- ewi-skill:agent-must-fill -->`. Do not add an AI disclaimer or the heading "AI-generated recommendation — not a mandatory fix". The CSV adds the disclaimer for Jira. The report and dashboard show only the fix.

Write `<project_dir>/artifacts/assessment/conversion-issues/updates.json`:

```json
[{ "code": "SSC-EWI-0040", "description": "THE 'SET XACT_ABORT' CLAUSE IS NOT SUPPORTED IN SNOWFLAKE",
   "problem_description": "...", "recommended_fix": "..." }]
```

When `updates.json` already exists, keep its entries and research only the rows whose `problem_description` is still empty.

## 3. Regenerate

```bash
scai assessment conversion-issues --updates artifacts/assessment/conversion-issues/updates.json
```

Run this after writing `updates.json`, before the HTML report. Then read `conversion-issues.json` again. Every summary row must have a non-empty `problem_description` and `recommended_fix`. If any field is empty, fill it and regenerate. Do not return `ok` while any summary field is empty. The parent does not upload the ZIP. The report shows the ZIP path and the Share issues link.

## Return

JSON only:

```json
{ "sub_skill": "conversion-issues", "status": "ok", "output_json": "<abs>/artifacts/assessment/conversion-issues.json",
  "summary": "<distinct pairs> pairs, <instances> instances", "error": null }
```

Any other failure: `status` `"error"`, `output_json` `null`, `error` `"<message>"`.
