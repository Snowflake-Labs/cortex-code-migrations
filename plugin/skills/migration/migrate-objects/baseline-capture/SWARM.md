---
name: seed-source-db
description: Seed-first orchestrator for a single source-database test target. Runs `scai test seed` to scaffold the step-based YAML stub (optionally hydrating from a query-log CSV), then — if `test_cases:` is still empty — spawns an AI swarm to fill them.
parent_skill: baseline-capture
---

# Seed Source-DB Tests (Seed → Maybe-Fill)

State-machine entry point for `testing_data_source = "source_database"`. Handles **one object (`<object_name>`)** at a time. Two stages:

1. **Seed** — run `scai test seed` to scaffold the step-based YAML stub. If `test_seed_source = logs`, pass `--execution-log <path>` to hydrate `test_cases:` from real captured calls.
2. **Maybe-fill** — if the stub came back with empty `test_cases:`, spawn an AI swarm to fill them. The swarm fills *rows only*; it never edits `steps:`.

> **SCOPE: One object only.** Triggered per-object by the `seedSourceDb` state-machine task. Do not loop here — the state machine handles the next object after `captureBaseline` completes.

---

## On entry

Tell the user one line:

> Generating test cases for `<object_name>`.

## Step 1: Pull settings from `configure()`

Call `configure()` and read:

- `project_dir`
- `source_connection`, `snowflake_connection`, `snowflake_database`
- `testing_data_source` (expected: `source_database`)
- `test_seed_source` (`logs` or `source_db_query`; may be absent on fallback)
- `execution_log_path` (only meaningful when `test_seed_source = logs`)

`test_seed_source` and `execution_log_path` come from the Q2 prompts in [`../SKILL.md`](../SKILL.md) Step 2 and are persisted across sessions.

**Fallback when `test_seed_source` is unset** (a state-machine entry that didn't go through Step 2 — rare): default to `source_db_query`. Don't prompt — the state machine doesn't have a user surface here. The user can rerun the parent flow to re-prompt.

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
- `target.canonicalName` — `<database>.<schema>.<name>` of the proc on Snowflake. The YAML's path on disk uses these segments.

The expected YAML path is `artifacts/<database>/<schema>/<object_type>/<sanitized_name>/test/<sanitized_name>.yml` (single file per object; `scai test seed` writes here).

## Step 3: Run `scai test seed`

Always invoke seed — it's the universal scaffolder. The flags depend on `test_seed_source`:

```bash
# test_seed_source = logs
scai test seed \
  --where "source.canonicalName ILIKE '%<object_name>%'" \
  --append \
  --execution-log "<execution_log_path>"

# test_seed_source = source_db_query (or fallback)
scai test seed \
  --where "source.canonicalName ILIKE '%<object_name>%'" \
  --append
```

Notes:

- `--append` is always on. If a YAML already exists for this object, `scai test seed` will leave existing rows alone and only add new ones (relevant when the user re-runs with a different log).
- `--where` is scoped to one object so we don't rescaffold the whole project.
- Source / Snowflake connection names come from `configure()`; `scai` picks them up via the per-project config — don't pass them on the command line unless probing fails.
- The seed command writes the stub YAML to the artifacts path even if no log row matched. The stub uses **step-based schema** (`validation.steps[]` with `source_query`/`target_query`, plus `test_cases: []`).

If `scai test seed` returns a non-zero exit:

- Print its stderr verbatim.
- **Stop.** Don't try to recover by hand-writing the YAML — that defeats the seed-first contract. Reroute via `DIAGNOSE_FIX.md` if the state machine retries this task; otherwise the user fixes the seed input (bad log path, malformed CSV) and reruns.

## Step 4: Inspect the resulting YAML

Read the file at `artifacts/<database>/<schema>/<object_type>/<sanitized_name>/test/<sanitized_name>.yml`. Look at `validation.test_cases`:

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
| **Complex** | 4+ params, multiple branches, table lookups, OUT params | 6 (two of each type — see A/B split in each agent file) |

### 5.3 — Spawn agents in parallel

Use the Task tool. Each agent reads its own instruction file; do **not** paste instructions inline.

| Agent | Instruction file | Needs source DB | Focus |
|---|---|---|---|
| **Data-Driven** (most important) | `agents/data_driven.md` | Yes (or testbed CSVs as fallback) | Real parameter values from actual data |
| **Edge Cases & Boundaries** | `agents/edge_cases.md` | No | NULLs, zeros, type limits, overflow |
| **Business Logic** | `agents/business_logic.md` | No | Branch coverage from source SQL analysis |

Spawn prompt for each agent:

```
Read the instructions at <baseline_capture_dir>/agents/<agent_type>.md
then produce test_cases for <object_name>.

Object signature: <signature>
Source code: <source_code>
Referenced tables: <table_list>            # data-driven only
Source connection name: <source_connection>  # data-driven only
Project directory: <project_dir>
```

For **complex** objects spawn 2 agents per type — the agent files describe the A/B split.

### 5.4 — Collect, dedupe, target 15–25 rows

Each agent writes its rows to `<project_dir>/.scai/tmp/<object_name>_<agent_type>.yml` (also prints them to stdout as a backup). After all agents complete:

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
  Path:   artifacts/<database>/<schema>/<object_type>/<sanitized_name>/test/<sanitized_name>.yml
```

Don't load `CAPTURE.md` — the state machine transitions to `captureBaseline` next, which loads it.

---

## Things this skill is not for

- **Editing `steps:`** (multi-RS, OUT param compare, table-read, side-effect DML, before/after capture). That's a failure-mode response — see [`../migrate-object/EDIT_TEST_YAML.md`](../migrate-object/EDIT_TEST_YAML.md), loaded on demand from `DIAGNOSE_FIX.md`.
- **Authoring a YAML from scratch.** If `scai test seed` won't produce a stub for an object (e.g. dialect quirk), that's a testing-infrastructure bug — file it upstream. Don't hand-write step-based YAMLs here.
- **Loop control.** One object per invocation. State machine handles the queue.

## Troubleshooting

| Symptom | What to do |
|---|---|
| `scai test seed` reports `no matching objects` | Verify `<object_name>` matches `source.canonicalName` in the registry (check casing / schema prefix). The `--where` is a literal SQL ILIKE; quote escaping matters. |
| `scai test seed --execution-log ...` runs but YAML still empty | The log didn't contain a row for this proc. Continue to Step 5 — the swarm will fill from source SQL + (optionally) live source DB. |
| Swarm agents return zero rows | Source SQL likely refers to objects not in the registry, so the data-driven agent fell back to testbed-CSV mode (Teradata) or had no data path. Inspect the agent's stdout — it should report `branch_values` it used. |
| Test cases written but `scai test validate` later fails on YAML shape | The stub `steps:` block didn't match the proc's actual shape (multi-RS, OUT param, DML side effect, ...). That's not this skill's problem — `DIAGNOSE_FIX.md` Step 2.5 catches it and routes to `EDIT_TEST_YAML.md`. |
