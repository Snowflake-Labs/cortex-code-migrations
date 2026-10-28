---
name: business_logic
description: Produce test_cases rows for an existing step-based YAML stub that cover IF/ELSE branches, CASE WHEN arms, happy paths, and error paths. Triggers: business_logic, business logic tests, code coverage tests, branch coverage tests.
license: Proprietary. See License-Skills for complete terms
---

You produce **`test_cases:` rows** for the object in your prompt that
exercise every code path in the source SQL.

> You are NOT writing a YAML file. The stub YAML already exists (created by `scai test seed`). Your job is to produce **just the `test_cases:` rows** that will be merged into the existing stub.
>
> Each row is an array of literals in the object's parameter order. The step SQL's `{0}`, `{1}`, ... are filled from it, one case at a time, as dialect-correct SQL literals; you write plain YAML values and never escape them:
>
> | YAML value | SQL Server | Snowflake | Redshift |
> |---|---|---|---|
> | `null` | `NULL` | `NULL` | `NULL` |
> | `true` / `false` | `1` / `0` | `TRUE` / `FALSE` | `TRUE` / `FALSE` |
> | `42` | `42` | `42` | `42` |
> | `"hello"` | `'hello'` | `'hello'` | `'hello'` |
> | `"it's"` | `'it''s'` | `'it''s'` | `'it''s'` |
>
> A zero-argument object takes `[]`.

## Inputs

The prompt carries `object_name`, `signature`, `source_code`, and
`project_dir`. A `split` of `A` or `B` means this is one half of a pair
— write the matching tmp file below.

## Instructions

Analyze the source code and produce rows that:

- Exercise each `IF` / `ELSEIF` / `ELSE` branch.
- Cover each `CASE WHEN` arm.
- Hit the happy path with typical values.
- Trigger early-return conditions.
- Trigger error / exception paths the source handles (a branch that returns a status, a `TRY`/`CATCH` that continues, an `IF` that guards a call). Do not emit an input that raises an unhandled engine error. If an unguarded `RIGHT`, `LEFT`, or `SUBSTRING` length is `LEN(arg) - N` or `LENGTH(arg) - N`, do not emit a non-null string for `arg` shorter than N.

**Do not query the source database.** Generate rows purely from code analysis. For parameter values that depend on data (e.g. valid IDs), use synthetic placeholder values (`1`, `2`, `100`, `999`) — the `data_driven` agent handles real-data lookups.

When `split` is `A`, focus on happy paths and main branches. When it is
`B`, focus on error paths, exceptions, and edge conditions found in the
source SQL.

## Output

Write your rows to `<project_dir>/.scai/tmp/<object_name>_business_logic.yml`,
or `_business_logic_a.yml` / `_business_logic_b.yml` when `split` is set.

The file must contain only valid YAML starting with `test_cases:`. Also print the rows to stdout as a backup.

```yaml
test_cases:
  - [1, 100.00]           # happy path - main IF branch
  - [1, 1500.00]          # high-value branch - CASE WHEN amount > 1000
  - [-1, 10.00]           # error path - negative ID
  - [null, 10.00]         # NULL guard - COALESCE branch
```

Each row is a JSON-ish array of literals matching the proc's parameter order. Add a trailing `# ...` comment explaining which branch the row exercises — this helps the orchestrator dedupe.

## Shell commands on Windows

On Windows your shell tool runs PowerShell, usually Windows PowerShell 5.1, not
bash or cmd. Never chain with `&&` or `||`, which 5.1 rejects: use `;`, or
`cmd1; if ($?) { cmd2 }` when the second must wait for the first to succeed. No
cmd syntax (`if not exist`, `set VAR=x`, `%VAR%`): use `Test-Path`,
`New-Item -ItemType Directory -Force <dir> | Out-Null` and `$env:VAR`. No bash
syntax (heredocs, `export`, `2>/dev/null`): use `2>$null`.
