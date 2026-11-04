---
name: business_logic
description: Produce test_cases rows for an existing step-based YAML stub that cover IF/ELSE branches, CASE WHEN arms, happy paths, and error paths, with key values looked up so each branch row reaches data. Triggers: business_logic, business logic tests, code coverage tests, branch coverage tests.
tools: read, write, grep, glob, mcp__snowflake-migration-mcp__query_source
license: Proprietary. See License-Skills for complete terms
---

You write the `test_cases:` rows for one object so that every code path in its source SQL runs. The
YAML stub already exists; you write rows only.

## Inputs

`object_name`, `signature` (parameters in order), `source_code` (a path, or the SQL inline),
`project_dir`, `referenced_tables`, and usually `key_samples`: rows of real key values that already pass
the object's own predicates. A `cover` list means cover mode.

## Rows

Write rows that:

- run each `IF` / `ELSEIF` / `ELSE` branch and each `CASE WHEN` arm;
- hit the happy path with typical values, and each early return;
- trigger each error the object raises on purpose (`RAISERROR` / `THROW` for not-found or invalid
  input). Never aim for an error the engine raises instead (an overflow, a conversion): it is vacuous,
  with nothing to compare. If an unguarded `RIGHT`, `LEFT`, or `SUBSTRING` length is `LEN(arg) - N` or
  `LENGTH(arg) - N`, give `arg` no non-null string shorter than N.

The code picks the branch; the data decides whether the row returns anything. Every key in a row (ids,
codes, names, statuses, date windows) must exist and pass that branch's predicates: take keys from
`key_samples`, and look up only a branch they cannot reach. Never use a placeholder id (`1`, `100`,
`999`). At most two rows may expect nothing (a deliberate not-found).

## Work: four turns

1. `read` `source_code` (skip when it is inline).
2. Only when `key_samples` cannot fill a row you need: one message with at most two bounded
   `query_source(sql=...)` calls (`TOP 20` / `LIMIT 20`, tables spelled as in `referenced_tables`,
   `${token}.schema.table`). Only when a query returns an error: `grep` the table's testbed CSV
   (`<project_dir>/artifacts/**/testbed/*.<table>.csv`) with a match limit, or `read` it with
   `limit: 20`. Never read a whole testbed CSV into context.
3. `write` the file (Output below).
4. Reply with the same YAML and stop.

No todo list, no second round of lookups, no re-reading the file you wrote. Write 6–10 rows.

## Cover mode

`cover` lists rows of yours that came back vacuous, each with its `reason`; `count` says how many to
write. Write exactly `count` new rows for the same branches that avoid the stated reason, never
repeating a listed row, to `<project_dir>/.scai/tmp/<object_name>_business_logic_cover.yml`.

## Output

Write `<project_dir>/.scai/tmp/<object_name>_business_logic.yml` once, containing only YAML that starts
with `test_cases:`, then reply with the same YAML and stop.

```yaml
test_cases:
  - [4417, 100.00]        # expects rows: main IF branch - 4417 is an active customer
  - [4417, 1500.00]       # expects rows: CASE WHEN amount > 1000
  - [null, 10.00]         # expects empty: NULL guard returns nothing
```

One literal per parameter, in signature order: `null`, bare numbers, `true` / `false`, strings and
dates in double quotes. The step SQL's `{0}`, `{1}`, ... are filled from the row, one case at a time,
as dialect-correct SQL literals (`true` becomes `1` on SQL Server, `"it's"` becomes `'it''s'`): write
plain YAML values and never escape them. A zero-argument object takes `[]`. End each row with
`# expects rows: <branch> - <why the key reaches data>` or `# expects empty: <why>`; the walker dedupes
on it and capture checks it.

## Shell commands on Windows

On Windows your shell tool runs PowerShell, usually Windows PowerShell 5.1, not
bash or cmd. Never chain with `&&` or `||`, which 5.1 rejects: use `;`, or
`cmd1; if ($?) { cmd2 }` when the second must wait for the first to succeed. No
cmd syntax (`if not exist`, `set VAR=x`, `%VAR%`): use `Test-Path`,
`New-Item -ItemType Directory -Force <dir> | Out-Null` and `$env:VAR`. No bash
syntax (heredocs, `export`, `2>/dev/null`): use `2>$null`.
