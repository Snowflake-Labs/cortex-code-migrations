---
name: generate-test-cases
description: Seed-first orchestrator for a single source-database test target. Runs `scai test seed` to scaffold the step-based YAML stub (optionally hydrating from a query-log CSV), then — if `test_cases:` is still empty — spawns an AI swarm to fill them.
parent_skill: baseline-capture
---

# Generate Test Cases (Seed → Maybe-Fill)

State-machine entry point for `testing_data_source = "source_database"`
or `"testbed"`. Handles **one object (`<object_name>`)** at a time. Two stages:

1. **Seed** — run `scai test seed` to scaffold the step-based YAML stub. If `test_seed_source = logs`, pass `--execution-log <path>` to hydrate `test_cases:` from real captured calls.
2. **Maybe-fill** — if the stub came back with empty `test_cases:`, spawn an AI swarm to fill them. The swarm fills *rows only*; it never edits `steps:`.

> **SCOPE: One object only.** Triggered per-object by the `generateTestCases` state-machine task. Do not loop here — the state machine handles the next object after `captureBaseline` completes.

---

## Step 1: Pull settings from `configure()`

Call `configure()` and read the relevant details.

## Step 2: Look up the source SQL file

Use `query_registry` (don't `find`) so paths are reliable:

```
query_registry(
  where = "source.canonicalName ilike '%<object_name>%'",
  fields = "id,source,files,target",
  include_dependencies = false
)
```

From the response, hold onto:

- `files.source.path` — used by the swarm in Step 4.
- `files.artifacts.path` — PROJECT-RELATIVE directory where seed writes YAMLs. Use it verbatim; do not reconstruct from `target.canonicalName` or `configure().snowflake_database`. It may contain a placeholder database segment (e.g. `database_unspecified`) and lowercased names — that is correct.
- `target.canonicalName` — `<database>.<schema>.<name>` of the proc on Snowflake. For CALL/SQL only — **not** the YAML path on disk.

The YAML lives under `<project_dir>/<files.artifacts.path>/test/` — discover it with a glob (`*.yml`) rather than assuming the filename. `scai test seed` derives the filename from the object's scope name and writes one file per object here.

If `files.source` cannot execute as written (INSERT…EXEC column-count mismatch, a comment that the object fails at runtime, or the same defect on a live `EXEC`), **escalate on `generateTestCases` now**. Do not seed, do not spawn the swarm, and do not paper over it in YAML. The customer owns source.

If seed / `EXEC` fails only because **this fixture's rows** are the wrong
shape (concat into a narrower temp column, a join the fixture never
produced), spawn
(`subagent_type="sandbox_specialist"`) with `task=generateTestCases`. Do not
stamp `error=sql`. After `done`, note the reshape and retry seed.

## Step 3: Run `scai test seed`

Always invoke seed — it's the universal scaffolder. The flags depend on `test_seed_source`:

```bash
# test_seed_source = logs
scai test seed \
  --where "id = <object_id>" \
  --append \
  --execution-log "<execution_log_path_if_set>"
```

Notes:

- `--append` is always on to avoid overwriting an existing YAML.
- `--where` is scoped to one object so we don't rescaffold the whole project.
- The seed command writes the stub YAML to the artifacts path even if no log row matched.

If `scai test seed` returns a non-zero exit:

- Print its stderr verbatim.
- **Stop.** Don't try to recover by hand-writing the YAML — that defeats the seed-first contract. Reroute via `DIAGNOSE_FIX.md` if the state machine retries this task; otherwise the user fixes the seed input (bad log path, malformed CSV) and reruns.

## Step 4: Inspect the resulting YAML

Read the YAML under `<project_dir>/<files.artifacts.path>/test/` (glob `*.yml`; `scai test seed` writes one file per object). Look at `validation.test_cases`:

- **Populated** (`test_cases:` contains one or more rows) → the seed (probably via `--execution-log`) covered this proc. **Skip to Step 6 (report).**
- **Empty** (`test_cases: []`, or commented `# TODO`) → continue to Step 5.

This branch decision is content-based, not flag-based. A `logs` run can produce an empty stub if the log didn't reference this proc; a `source_db_query` run is always empty after seed (no `--execution-log`).

> **YAML reference.** Need to read the stub structure? See [`../references/step-based-yaml.md`](../references/step-based-yaml.md). Never hand-author `steps:` — `scai test seed` writes that block; you only add `test_cases:` rows.

## Step 5: Fill `test_cases:` with the AI swarm

The swarm produces *only* `test_cases:` rows for this object. It never touches `steps:`.

### 5.1 — Read the source SQL

Use the `files.source.path` from Step 2. Internalize:

- Parameter names + types.
- Tables/views referenced.
- Branches (IF/CASE), NULL paths, boundary values.
- Any obvious error paths (e.g. negative IDs).

### 5.2 — Determine complexity

| Complexity | Signals | Agents to spawn |
|---|---|---|
| **Simple** | 1–3 params, straightforward logic | 3 (one of each type) |
| **Complex** | 4+ params, multiple branches, table lookups, OUT params | 6 (two of each type — pass `split: A` and `split: B`) |

### 5.3 — Spawn agents in parallel

Use the Task tool. Spawn each as its `subagent_type` with a facts-only
prompt — the agent definition is the contract. Do not paste instructions
inline and do not tell it to read a path.

| Agent | `subagent_type` | Needs source DB | Focus |
|---|---|---|---|
| **Data-Driven** (most important) | [`data_driven`](../../../../agents/data_driven.md) | Yes (or testbed CSVs as fallback) | Real parameter values from actual data |
| **Edge Cases & Boundaries** | [`edge_cases`](../../../../agents/edge_cases.md) | No | NULLs, zeros, type limits, overflow |
| **Business Logic** | [`business_logic`](../../../../agents/business_logic.md) | No | Branch coverage from source SQL analysis |

```
Produce test_cases for this object, following your agent definition.

object_name:         <object_name>
signature:           <signature>
source_code:         <source_code>
project_dir:         <project_dir>
referenced_tables:   <table_list>            # data_driven only
source_connection:   <source_connection>     # data_driven only
split:               A|B                     # complex only
```

For **complex** objects spawn 2 of each type, one with `split: A` and
one with `split: B`.

### 5.4 — Collect, dedupe, target 15–25 rows

Each agent writes its rows to
`<project_dir>/.scai/tmp/<object_name>_<data_driven|edge_cases|business_logic>.yml`
(or `_*_a.yml` / `_*_b.yml` when `split` was set; also prints them to
stdout as a backup). After all agents complete:

1. Read each tmp file. Fall back to stdout parsing if a tmp file is missing.
2. Concatenate `test_cases:` lists. Drop exact duplicates.
3. Aim for 15–25 rows total. If you have more, prefer keeping data-driven rows over synthetic ones.

### 5.5 — Apply rows to the YAML

Open the YAML at the artifacts path. Replace its `validation.test_cases:` (currently empty) with the merged list. **Do not touch `steps:`, `modifies_data:`, or `affected_tables:`** — those come from `scai test seed` + CUR inference and are correct by construction.

The cheat sheet's placeholder table ([`../references/step-based-yaml.md` → Placeholders](../references/step-based-yaml.md#placeholders-and-test_cases)) explains how each row's values become `{0}`, `{1}`, ... substitutions. The agents already produce values in array form; no escaping needed.

## Step 6: Report and return

Tell the user one line, then return to the state machine:

```
Test cases for <object_name>: <N> cases (<source>).

  source ∈ { "from scai test seed --execution-log",
             "from AI swarm fill",
             "from scai test seed + AI swarm fill" }
  Path:   <project_dir>/<files.artifacts.path>/test/*.yml
```

Don't load `CAPTURE.md` — the state machine transitions to `captureBaseline` next, which loads it.

---

## Things this skill is not for

- **Editing `steps:`** (multi-RS, OUT param compare, table-read, side-effect DML, before/after capture). That's a failure-mode response — see [`../migrate-object/EDIT_TEST_YAML.md`](../migrate-object/EDIT_TEST_YAML.md), loaded on demand from `DIAGNOSE_FIX.md`.

## Troubleshooting

| Symptom | What to do |
|---|---|
| `scai test seed` reports `no matching objects` | Verify `<object_name>` matches `source.canonicalName` in the registry (check casing / schema prefix). The `--where` is a literal SQL ILIKE; quote escaping matters. |
| `scai test seed --execution-log ...` runs but YAML still empty | The log didn't contain a row for this proc. Continue to Step 5 — the swarm will fill from source SQL + (optionally) live source DB. |
| Swarm agents return zero rows | Source SQL likely refers to objects not in the registry, so the data-driven agent fell back to testbed-CSV mode (Teradata) or had no data path. Inspect the agent's stdout — it should report `branch_values` it used. |
| Test cases written but `scai test validate` later fails on YAML shape | The stub `steps:` block didn't match the proc's actual shape (multi-RS, OUT param, DML side effect, ...). That's not this skill's problem — `DIAGNOSE_FIX.md` Step 2.5 catches it and routes to `EDIT_TEST_YAML.md`. |
