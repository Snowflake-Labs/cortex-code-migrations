---
name: workload-insights
description: Builds Discovery from SQL Server Extended Events `.xel` captures or Teradata DBQL metrics CSV exports by running `scai assessment workload-insights --input <file>`. SQL Server and Teradata only. Reads inputs in place.
parent_skill: assessment
license: Proprietary. See License-Skills for complete terms
---

# Discovery

Thin, non-interactive wrapper over `scai assessment workload-insights`. The
parent supplies absolute input paths. The command streams them and writes
timestamped JSON under the project. Never parse or rewrite the input or the
JSON. Never copy input files into the project. Never ask the user questions.

- **Supported dialects:** SQL Server and Teradata. Any other dialect aborts
  with `ASM0034`; report `skipped`, not an error.
- **SQL Server input:** one or more binary Extended Events `.xel` files.
  Rollover files from the same capture are separate `--input` arguments. Any
  filename works.
- **Teradata input:** one or more uncompressed `.csv` files of DBQL request
  metrics. Split files are separate `--input` arguments. Any filename works.
  Do not pass statement text.
- The project's dialect selects the reader. A `.xel` on a Teradata project, a
  CSV on a SQL Server project, or a metrics CSV missing a required column
  fails with `ASM0032` / `ASM0033`; report the message as `error`.

## Run

SQL Server, one `--input` per rollover file:

```bash
scai assessment workload-insights \
  --input /abs/path/WorkloadReport_XE_0.xel \
  --input /abs/path/WorkloadReport_XE_1.xel
```

Teradata, one `--input` per export file:

```bash
scai assessment workload-insights \
  --input /abs/path/querylogs.csv
```

Run from `project_dir`. The command writes:

`<project_dir>/artifacts/assessment/workload-insights-YYYYMMDD_HHMMSS.json`

## Sub-agent contract

On entry, call `configure()` with `project_dir` from the parent's context
block. Take no user prompts. On completion return JSON only:

```json
{
  "sub_skill": "workload-insights",
  "status": "ok",
  "output_json": "<absolute path to workload-insights-*.json>",
  "summary": "<one line: databases, total events, user executions, errors>",
  "error": null
}
```

- Unsupported dialect (`ASM0034`): `status` `"skipped"`, `output_json` `null`,
  `error` `null`.
- Any other failure: `status` `"error"`, `output_json` `null`,
  `error` `"<message>"`.
- A large-file or long-running parse message on stdout is not an error. Exit
  code 0 plus a written artifact means `"ok"`; fold the message into `summary`.
- Skipped-row warnings from a Teradata export are not an error either. Exit
  code 0 plus a written artifact means `"ok"`; note the skipped rows in
  `summary`.
- Do not include SQL text, parameters, or error messages in the response.

## Reference

These files hold the copy the **parent** pastes when the user chooses to
provide files later. This sub-skill never runs any of them.

- `references/create-extended-events-session.sql` — SQL Server starter session
  SQL. `CREATE` leaves the session stopped; the user reviews all values,
  replaces `YourDatabase`, and explicitly runs the commented `STATE = START`.
- `references/teradata-probe.sql` — four statements that find the DBQL table
  the user can actually read.
- `references/teradata-fallback.sql` — the request-metrics `SELECT` the user
  runs against that table and exports to CSV.
