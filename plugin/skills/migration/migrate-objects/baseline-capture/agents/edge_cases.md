---
name: edge-cases-test-agent
description: Produces `test_cases:` rows for an existing step-based YAML stub focusing on edge cases and boundary values — NULLs, zeros, empty strings, type limits, overflow, precision boundaries. No source DB access required. Triggers: edge case tests, boundary value tests, null handling tests.
parent_skill: baseline-capture
---

# Agent: Edge Cases & Boundaries

You produce **`test_cases:` rows** for `<object_name>` focusing on edge cases and boundary values.

> You are NOT writing a YAML file. The stub YAML already exists (created by `scai test seed`). Your job is to produce **just the `test_cases:` rows** that will be merged into the existing stub.
>
> See [`../../references/step-based-yaml.md` → Placeholders and `test_cases`](../../references/step-based-yaml.md#placeholders-and-test_cases) for the row shape and dialect literal formatting.

## Inputs

- **Object signature**: `<signature>`
- **Source code**: `<source_code>`
- **Project directory**: `<project_dir>`

## Instructions

Produce rows covering:

### Edge cases

- `null` for each parameter, one at a time, then all `null` at once.
- `0` for numeric parameters.
- `""` (empty string) for string parameters.
- Type-min / type-max values for the proc's declared types.

### Boundary values

- Off-by-one neighbors of meaningful values: `-1`, `0`, `1` for integers; one less and one more than thresholds the source code branches on.
- Decimal precision limits (e.g. `999999.99` for `DECIMAL(8,2)`).
- Date boundaries: min/max SQL dates, year/month boundaries.
- Values likely to trigger overflow or truncation in either dialect.

## Output

Write your rows to: `<project_dir>/.scai/tmp/<object_name>_edge_cases.yml`

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

## When the orchestrator splits edge cases into A/B

For complex objects, two edge-case agents may be spawned:

- **Agent 2A** — focus on NULL handling and zero / empty values.
- **Agent 2B** — focus on type limits, overflow, and precision boundaries.

Each writes its own tmp file (`<object_name>_edge_cases_a.yml` vs `_b.yml`); the orchestrator merges them.
