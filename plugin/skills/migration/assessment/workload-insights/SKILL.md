---
name: workload-insights
description: Builds SQL Server Query Store workload insights by running `scai assessment workload-insights --input <csv>`. SQL Server only. Any CSV filename works. Reads the CSV in place.
parent_skill: assessment
license: Proprietary. See License-Skills for complete terms
---

# Workload Insights

Thin wrapper over `scai assessment workload-insights`. Parent supplies absolute `--input` path(s). Writes timestamped JSON under the project. Never parse or rewrite the file. Never copy the CSV. Never ask the user questions.

- **Supported dialects:** SQL Server. Any other dialect aborts with `ASM0034` — report `skipped`, not an error.

## Run

```bash
scai assessment workload-insights --input /abs/path/query-store.csv
# several databases:
scai assessment workload-insights --input /abs/db1.csv --input /abs/db2.csv
```

Writes `<project_dir>/artifacts/assessment/workload-insights-YYYYMMDD_HHMMSS.json`.

## Sub-agent contract

On entry, `configure()` with `project_dir` from the parent's context block. Take no user prompts. On completion return **JSON only**:

```json
{
  "sub_skill": "workload-insights",
  "status": "ok",
  "output_json": "<abs path to workload-insights-*.json>",
  "summary": "<one-line: databases, executions, shapes>",
  "error": null
}
```

- Unsupported dialect (`ASM0034`): `status` `"skipped"`, `output_json` `null`, `error` `null`.
- Any other failure: `status` `"error"`, `output_json` `null`, `error` `"<message>"`.
- A large-extract warning on stdout is **not** an error — exit code 0 means `"ok"`. Fold the warning text into `summary`.

## References

- `references/extract.sql` — the Query Store extract the customer runs **inside each user database** to produce a CSV (any filename). The parent skill pastes it (with `@Days` filled in); this sub-skill never runs it.
- `references/enable-query-store.sql` — the `ALTER DATABASE` the parent skill pastes when Query Store is off.
