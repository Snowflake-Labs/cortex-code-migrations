---
name: edge_cases
description: Produce test_cases rows for an existing step-based YAML stub covering NULLs, zeros, empty strings, type limits, overflow, and precision boundaries. Triggers: edge_cases, edge case tests, boundary value tests, null handling tests.
license: Proprietary. See License-Skills for complete terms
---

You produce **`test_cases:` rows** for the object in your prompt focusing
on edge cases and boundary values.

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

Produce rows covering:

### Edge cases

- `null` for each parameter, one at a time, then all `null` at once.
- `0` for numeric parameters.
- `""` (empty string) for string parameters, only when the source accepts an empty string.
- Type-min / type-max values for the proc's declared types, only when the source can execute them.

### Boundary values

- Off-by-one neighbors of meaningful values: `-1`, `0`, `1` for integers; one less and one more than thresholds the source code branches on.
- Decimal precision limits (e.g. `999999.99` for `DECIMAL(8,2)`).
- Date boundaries: min/max SQL dates, year/month boundaries.
- Values likely to trigger overflow or truncation in either dialect, only when the source accepts them.

Emit a row only when the source statement can run it. Do not invent a row whose only purpose is an unhandled engine error.

- If the body calls `RIGHT`, `LEFT`, or `SUBSTRING` with a length of `LEN(arg) - N` or `LENGTH(arg) - N`, and that call is not guarded by a length check, every non-null string for `arg` must have length >= N. A length of exactly N is legal. SQL Server raises on a negative length; it does not return an empty string.
- `null` stays in scope when the expression propagates NULL.

When `split` is `A`, focus on NULL handling and zero / empty values.
When it is `B`, focus on type limits, overflow, and precision boundaries.

## Output

Write your rows to `<project_dir>/.scai/tmp/<object_name>_edge_cases.yml`,
or `_edge_cases_a.yml` / `_edge_cases_b.yml` when `split` is set.

The file must contain only valid YAML starting with `test_cases:`. Also print the rows to stdout as a backup.

```yaml
test_cases:
  - [null, null]          # all-null
  - [0, 0]                # zeros
  - [-1, 0]               # negative ID
  - [2147483647, 0]       # INT max
  - [1, 999999.99]        # DECIMAL(8,2) max
```

Each row is a JSON-ish array of literals matching the proc's parameter order.

## Shell commands on Windows

On Windows your shell tool runs PowerShell, usually Windows PowerShell 5.1, not
bash or cmd. Never chain with `&&` or `||`, which 5.1 rejects: use `;`, or
`cmd1; if ($?) { cmd2 }` when the second must wait for the first to succeed. No
cmd syntax (`if not exist`, `set VAR=x`, `%VAR%`): use `Test-Path`,
`New-Item -ItemType Directory -Force <dir> | Out-Null` and `$env:VAR`. No bash
syntax (heredocs, `export`, `2>/dev/null`): use `2>$null`.
