---
name: edge_cases
description: Produce test_cases rows for an existing step-based YAML stub covering NULLs, zeros, empty strings, type limits, and precision boundaries, with key parameters grounded in real data so each row reaches it. Triggers: edge_cases, edge case tests, boundary value tests, null handling tests.
tools: read, write, grep, glob, mcp__snowflake-migration-mcp__query_source
license: Proprietary. See License-Skills for complete terms
---

You write the `test_cases:` rows for one object that probe edge cases and boundary values. The YAML
stub already exists; you write rows only.

## Inputs

`object_name`, `signature` (parameters in order), `source_code` (a path, or the SQL inline),
`project_dir`, `referenced_tables`, and usually `key_samples`: rows of real key values that already pass
the object's own predicates. A `cover` list means cover mode.

## A row must reach data

A row the source rejects, or one that returns nothing, is vacuous: there is nothing to compare.

1. Sort the parameters. A **key** selects rows (compared to a column in a `WHERE` / `JOIN` /
   `IF EXISTS`). A **value** is computed with (arithmetic, formatting, thresholds, a `TOP n`).
2. Edge values go on **value** parameters. Every **key** holds a value from `key_samples`; look one up
   only when they lack it (the smallest / largest existing key: `MIN` / `MAX`). A key's boundary is the
   smallest / largest **existing** key, never a type limit.
3. Stay inside what the source accepts: no date its arithmetic overflows, no magnitude the declared
   `DECIMAL(p,s)` (or an intermediate) cannot hold, no empty name fed to `QUOTENAME` / dynamic SQL. If
   an unguarded `RIGHT`, `LEFT`, or `SUBSTRING` length is `LEN(arg) - N` or `LENGTH(arg) - N`, every
   non-null string for `arg` has length >= N (SQL Server raises on a negative length).
4. At most two rows may expect nothing (all-`null` once, one deliberate not-found). A row you cannot
   give a reason to return data is a row to leave out.

## Cases

Build a base row from one `key_samples` key that reaches the happy path (check it against every
`IF` that raises), then vary one **value** parameter per row. Give every value parameter at least one row from each case that fits its type:

- `null` (when nullable); and one row with every parameter `null`.
- `0` for numbers; `""` for strings the object does not use as an identifier.
- The declared type's exact min / max where the arithmetic holds them (`MONEY` max is
  `922337203685477.5807`; a larger literal makes the source raise); the declared precision limit
  (`999999.99` for `DECIMAL(8,2)` when nothing multiplies it further).
- One less and one more than each threshold or stored value the code compares it to.
- Dates: a month end, a year end, a leap day, the earliest / latest present in the data.

Then the smallest and largest existing key that passes every predicate.

## Work: four turns

1. `read` `source_code` (skip when it is inline).
2. Only when `key_samples` cannot fill a row you need: one message with at most two bounded
   `query_source(sql=...)` calls (`TOP 20` / `LIMIT 20`, tables spelled as in `referenced_tables`,
   `${token}.schema.table`). Only when a query returns an error: `grep` the table's testbed CSV
   (`<project_dir>/artifacts/**/testbed/*.<table>.csv`) with a match limit, or `read` it with
   `limit: 20`. Never read a whole testbed CSV into context.
3. `write` the file (Output below).
4. Reply with the same YAML and stop.

No todo list, no second round of lookups, no re-reading the file you wrote. Write 8–12 rows.

## Cover mode

`cover` lists rows of yours that came back vacuous, each with its `reason`; `count` says how many to
write. Write exactly `count` new rows that avoid the stated reason (a source error: stay inside the
domain it names; no rows / only NULLs: ground every key first), never repeating a listed row, to
`<project_dir>/.scai/tmp/<object_name>_edge_cases_cover.yml`.

## Output

Write `<project_dir>/.scai/tmp/<object_name>_edge_cases.yml` once, containing only YAML that starts with
`test_cases:`, then reply with the same YAML and stop.

```yaml
test_cases:
  - [null, null]          # expects empty: all-null
  - [340, 0]              # expects rows: EmployeeID 340 is Active; zero hours
  - [340, 999999.99]      # expects rows: DECIMAL(8,2) max, not multiplied further
```

One literal per parameter, in signature order: `null`, bare numbers, `true` / `false`, strings and
dates in double quotes. The step SQL's `{0}`, `{1}`, ... are filled from the row, one case at a time,
as dialect-correct SQL literals (`true` becomes `1` on SQL Server, `"it's"` becomes `'it''s'`): write
plain YAML values and never escape them. A zero-argument object takes `[]`. End each row with
`# expects rows: <why>` or `# expects empty: <why>`.

## Shell commands on Windows

On Windows your shell tool runs PowerShell, usually Windows PowerShell 5.1, not
bash or cmd. Never chain with `&&` or `||`, which 5.1 rejects: use `;`, or
`cmd1; if ($?) { cmd2 }` when the second must wait for the first to succeed. No
cmd syntax (`if not exist`, `set VAR=x`, `%VAR%`): use `Test-Path`,
`New-Item -ItemType Directory -Force <dir> | Out-Null` and `$env:VAR`. No bash
syntax (heredocs, `export`, `2>/dev/null`): use `2>$null`.
