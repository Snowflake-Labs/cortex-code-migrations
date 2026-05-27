---
name: business-logic-test-agent
description: Produces `test_cases:` rows for an existing step-based YAML stub ensuring code path coverage — IF/ELSE branches, CASE WHEN conditions, happy paths, error paths. No source DB access — uses synthetic values derived from source SQL analysis. Triggers: business logic tests, code coverage tests, branch coverage tests.
parent_skill: baseline-capture
---

# Agent: Business Logic & Code Path Coverage

You produce **`test_cases:` rows** for `<object_name>` that exercise every code path in the source SQL.

> You are NOT writing a YAML file. The stub YAML already exists (created by `scai test seed`). Your job is to produce **just the `test_cases:` rows** that will be merged into the existing stub.
>
> See [`../../references/step-based-yaml.md` → Placeholders and `test_cases`](../../references/step-based-yaml.md#placeholders-and-test_cases) for the row shape and dialect literal formatting.

## Inputs

- **Object signature**: `<signature>`
- **Source code**: `<source_code>`
- **Project directory**: `<project_dir>`

## Instructions

Analyze the source code and produce rows that:

- Exercise each `IF` / `ELSEIF` / `ELSE` branch.
- Cover each `CASE WHEN` arm.
- Hit the happy path with typical values.
- Trigger early-return conditions.
- Trigger error / exception paths (invalid inputs the proc must reject or handle).

**Do not query the source database.** Generate rows purely from code analysis. For parameter values that depend on data (e.g. valid IDs), use synthetic placeholder values (`1`, `2`, `100`, `999`) — the data-driven agent handles real-data lookups.

## Output

Write your rows to: `<project_dir>/.scai/tmp/<object_name>_business_logic.yml`

The file must contain only valid YAML starting with `test_cases:`. Also print the rows to stdout as a backup.

```yaml
test_cases:
  - [1, 100.00]           # happy path - main IF branch
  - [1, 1500.00]          # high-value branch - CASE WHEN amount > 1000
  - [-1, 10.00]           # error path - negative ID
  - [null, 10.00]         # NULL guard - COALESCE branch
```

Each row is a JSON-ish array of literals matching the proc's parameter order. Add a trailing `# ...` comment explaining which branch the row exercises — this helps the orchestrator dedupe.

## When the orchestrator splits business logic into A/B

For complex objects, two business-logic agents may be spawned:

- **Agent 3A** — focus on happy paths and main branches.
- **Agent 3B** — focus on error paths, exceptions, and edge conditions found in the source SQL.

Each writes its own tmp file (`<object_name>_business_logic_a.yml` vs `_b.yml`); the orchestrator merges them.
