---
name: generate-test-cases
description: Seed-first orchestrator for a single source-database test target. Runs `scai test seed` to scaffold the step-based YAML stub (optionally hydrating from a query-log CSV), then — unless the seed already covers every mined branch and has an edge case — spawns only the AI swarm agents for what is missing, on top of the seeded rows.
parent_skill: baseline-capture
---

# Generate Test Cases (Seed → Maybe-Fill)

State-machine entry point for `testing_data_source = "source_database"`
or `"testbed"`. Handles **one object (`<object_name>`)** at a time. Two stages:

1. **Seed** — run `scai test seed` to scaffold the step-based YAML stub. If `test_seed_source = logs`, pass `--execution-log <path>` to hydrate `test_cases:` from real captured calls. On the testbed path, omit the flag: seed reads the synthetic log `scai testbed generate` wrote to `.scai/testbed/exec_log.csv`.
2. **Fill** — read the seed's report (`<stem>.seed.json`, beside the YAML). A procedure whose seeded rows reach every mined branch and include an `edge_cases` row is sufficient: skip the swarm. Otherwise spawn only the agents for the categories the report says are missing, and pass them the seeded rows as already covered. Seeded rows are kept as a head start. The swarm fills *rows only*; it never edits `steps:`.

> **SCOPE: One object only.** Triggered per-object by the `generateTestCases` state-machine task. Do not loop here — the state machine handles the next object after `captureBaseline` completes.

---

## Step 0: Record skill start

Before any work, record a `started` TASK_EVENT for this object's `generateTestCases` task:

```
transition_status(status="started", task="generateTestCases", where="id = '<object_id>'")
```

Do this once at entry. Finish with `transition_status` in Step 6 — do not call `transition_status(status='start')` / `begin` here.

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

If `files.source` cannot execute as written on **every legal dataset**
(INSERT…EXEC column-count mismatch, a comment that the object fails at
runtime, or the same defect on a live `EXEC`), **escalate on
`generateTestCases` now**. Do not seed, do not spawn the swarm, and do not
paper over it in YAML. The customer owns source.

If seed / `EXEC` fails only because **this fixture's rows** are the wrong
shape, or because the AIMSBX pair is missing a table: do not stamp
`error=sql` or `infra`. Do not edit WAVE_SRC or a table unit's shared CSV.

| Evidence | Do |
|---|---|
| `failure_class=missing_object` / 42S02 / unknown function and a named id is not on `dependsOn`, `id` is null, **or** that object's SQL/CUR is not bindable | Spawn **one** foreground `cur_reconciler`, then `next_task`. |
| `failure_class=missing_object` and every named id is already on `dependsOn` **and** SQL/CUR is bindable | `next_task` (`blockedOn` → `partial`) **or** one foreground `sandbox_specialist` to remint the pair |
| empty join, VARCHAR concat into a narrower temp column, a filter the fixture never produced | Spawn **one** foreground `sandbox_specialist` (`run_in_background=false`, `subagent_type="sandbox_specialist"`) with `task=generateTestCases` and the evidence |

Would the object succeed on a different legal dataset that still fits the
table DDL? Then this is the specialist. After `done`, `note` the reshape
(inverse = drop this AIMSBX pair / reload generated CSVs) and retry seed.
`escalate` → park with that child's `asks`. `needs_cur` → spawn
`cur_reconciler`. Leftover sandbox yaml is the binding.

## Step 3: Run `scai test seed`

When the rows come from a generated testbed, call `setup_sandbox` (scoped to
`<object_name>` after a dot) before seed so the source tables are not empty.
Do not shell `scai testbed load` — `setup_sandbox` runs that load itself.
A shorter stem selects siblings and the YAML then names the wrong object.

Always invoke seed — it's the universal scaffolder. The flags depend on `test_seed_source`:

```bash
# test_seed_source = logs
scai test seed \
  --where "id = <object_id>" \
  --append \
  --execution-log "<execution_log_path_if_set>" \
  --max-cases 25

# testing_data_source = testbed
scai test seed \
  --where "id = <object_id>" \
  --append \
  --max-cases 25

# testing_data_source = source_database, test_seed_source = source_db_query
scai test seed \
  --where "id = <object_id>" \
  --append \
  --no-execution-log
```

Notes:

- `--append` is always on to avoid overwriting an existing YAML.
- `--where` is scoped to one object so we don't rescaffold the whole project.
- Without `--execution-log`, seed uses `.scai/testbed/exec_log.csv` when it exists and says so in its output; otherwise it writes an empty stub. `--no-execution-log` turns that lookup off, so a source-data project never seeds from a leftover testbed log.
- `--max-cases 25` on the logs and testbed paths matches the 15–25 cases Step 5 fills to, and the 25 calls per proc the testbed log holds at most. With the default of 10, seed can drop calls that reach a branch, so Step 4 would find an arm unseeded that the log covers.
- The seed command writes the stub YAML to the artifacts path even if no log row matched.

If `scai test seed` returns a non-zero exit:

- Print its stderr verbatim.
- 42S02 / `failure_class=missing_object` / unknown function, or this fixture's rows (empty
  join, VARCHAR concat) → follow Step 2's specialist / `cur_reconciler`
  split. Do not stamp `error=sql`. Do not hand-write the YAML.
- Otherwise **stop.** Don't recover by hand-writing the YAML — that
  defeats the seed-first contract. Reroute via `DIAGNOSE_FIX.md` if the
  state machine retries this task; otherwise the user fixes the seed
  input (bad log path, malformed CSV) and reruns.

## Step 4: Inspect the resulting YAML

Read the YAML under `<project_dir>/<files.artifacts.path>/test/` (glob `*.yml`; `scai test seed` writes one file per object). Look at `validation.test_cases`:

Then read the seed's report beside it, `<stem>.seed.json` (the same name with `.seed.json` for `.yml`). Seed writes it for every YAML that has seeded rows. It files each seeded row under one of the swarm's three categories (`data_driven`, `business_logic`, `edge_cases`), says which mined branch arms those rows reach, and decides sufficiency. The fields you use:

- `sufficient` — every mined branch arm is reached by a seeded row **and** at least one row is `edge_cases`.
- `missing_categories` — the agents to launch, in the order `data_driven`, `business_logic`, `edge_cases`; empty when `sufficient`.
- `branches.unseeded` — the mined branch arms no seeded row reaches (`branch_id`, `line`, `predicate`, `arm`). Absent when `coverage` is `none`.
- `cases[]` — each seeded row with its `category`, `kind` and `tolerates_source_error`.

Decide:

- **`sufficient` is true** → the seed is enough. **Skip to Step 6 (report).**
- **`sufficient` is false** → keep the seeded rows and continue to Step 5, launching exactly the agents in `missing_categories`. The list is the one source of truth: seed fills it from what it measured.
- **No `.seed.json`**, or `coverage` is `none` (a customer query log carries no mined branches) → coverage is unknown, so the seed cannot be judged sufficient; `missing_categories` then lists all three agents. Continue to Step 5 and launch them. With no `.seed.json` at all, launch all three.
- **Empty** (`test_cases: []`, or commented `# TODO`) → no seeded rows and no report; continue to Step 5 with no seeded set and launch all three agents.

A `logs` or testbed run can produce an empty stub if the log didn't reference this proc; a `source_db_query` run is always empty after seed.

> **YAML reference.** Need to read the stub structure? See [`../references/step-based-yaml.md`](../references/step-based-yaml.md). Never hand-author `steps:` — `scai test seed` writes that block; you only add `test_cases:` rows.

## Step 5: Fill `test_cases:` with the AI swarm

The swarm produces *only* `test_cases:` rows for this object. It never touches `steps:`.

### 5.1 — Read the source SQL

Use the `files.source.path` from Step 2. Internalize:

- Parameter names + types.
- Tables/views referenced.
- Branches (IF/CASE), NULL paths, boundary values.
- Any obvious error paths (e.g. negative IDs).

### 5.2 — Launch agents in the background

Use the Task tool. Launch the agents Step 4 selected in one message, `run_in_background=true`, as its
`subagent_type` with a facts-only prompt — the agent definition is the contract. Do not paste
instructions inline and do not tell it to read a path. With a seed report, launch only the agents in
`missing_categories`; without one, launch one of each type.

| Agent | `subagent_type` | Needs source DB | Focus |
|---|---|---|---|
| **Data-Driven** (most important) | [`data_driven`](../../../../agents/data_driven.md) | Yes (or testbed CSVs as fallback) | Real parameter values from actual data |
| **Edge Cases & Boundaries** | [`edge_cases`](../../../../agents/edge_cases.md) | For key parameters (or testbed CSVs) | NULLs, zeros, type limits, precision on values; real keys |
| **Business Logic** | [`business_logic`](../../../../agents/business_logic.md) | For key parameters (or testbed CSVs) | Branch coverage from source SQL analysis, real keys per branch |

```
Produce test_cases for this object, following your agent definition.

object_name:         <object_name>
signature:           <signature>
source_code:         <source_code>
project_dir:         <project_dir>
referenced_tables:   <table_list>
source_connection:   <source_connection>
already_covered:     <the seeded rows with their category, from `cases[]`; omit when nothing is seeded>
unseeded_branches:   <`branches.unseeded`; business_logic only; omit when none or unknown>
```

`already_covered` tells the agent which rows exist, so it adds rows that are not repeats. `unseeded_branches` tells
`business_logic` which branch arms to reach first.
Every row must reach data: a case the source rejects, or one that returns nothing, is vacuous — capture
reports it and it proves nothing.

### 5.3 — Collect every agent

Each agent writes its rows to
`<project_dir>/.scai/tmp/<object_name>_<data_driven|edge_cases|business_logic>.yml` (and prints them to
stdout as a backup). Wait for all of them; a complex object needs the slowest one's rows too:

1. Poll every agent with `agent_output(agent_id=<id>, wait=false)` in one message, then `sleep 30`, and
   repeat.
2. An agent is **in** once its `Status` is `completed` and it left rows. One whose response is a model
   error (`Error: internal error`, `server_error`, `response incomplete`) never ran:
   relaunch it once, at once, no sleep — unless the agents in already gave 15 or more usable rows; then
   leave it out. A second model error: write that agent's rows yourself, by its agent definition.
3. Merge once every agent is in or left out.

### 5.4 — Merge, dedupe, target 15–25 rows

1. Read each tmp file of an agent that is in. Fall back to its `Agent Response` if the file is missing.
2. Concatenate `test_cases:` lists. Drop exact duplicates.
3. Aim for 15–25 rows total. If you have more, prefer keeping data-driven rows over synthetic ones.
4. Drop rows the source cannot execute before writing the YAML. Read the source at `files.source.path`. If an unguarded `RIGHT`, `LEFT`, or `SUBSTRING` uses a length of `LEN(arg) - N` or `LENGTH(arg) - N`, omit every non-null string for that argument shorter than N. A length of exactly N is legal. SQL Server raises on a negative length; it does not return empty. Keep `null`. Also omit every string longer than its parameter's declared width (`NVARCHAR(255)`: more than 255 UTF-16 units, an emoji counting 2; a `CHAR` / `VARCHAR` / `NCHAR` / `NVARCHAR` with no width: more than 1): SQL Server silently truncates it and the converted `STRING` parameter does not, so the row cannot compare. `scai test capture` and `scai test validate` drop any row that still violates either rule and rewrite `validation.test_cases`, but the file you write must already be clean.

### 5.5 — Apply rows to the YAML

Start from the seeded set (Step 4), then append the merged list from 5.4. Drop exact duplicates, including rows that repeat a seeded one. Aim for 15–25 rows total, seeded rows included. If you have more, keep every seeded row, then prefer data-driven rows over synthetic ones. Apply the executable-input filter from 5.4 to the combined list before writing it.

Open the YAML at the artifacts path. Replace its `validation.test_cases:` with the combined list. **Do not touch `steps:`, `modifies_data:`, or `affected_tables:`** — those come from `scai test seed` + CUR inference and are correct by construction.

The cheat sheet's placeholder table ([`../references/step-based-yaml.md` → Placeholders](../references/step-based-yaml.md#placeholders-and-test_cases)) explains how each row's values become `{0}`, `{1}`, ... substitutions. The agents already produce values in array form; no escaping needed.

## Step 6: Advance and report

When the YAML under `<project_dir>/<files.artifacts.path>/test/` has populated `test_cases:` (from seed, swarm, or both), advance the walk. The status source re-checks the file — do not invent completion:

```
transition_status(status="advance", task="generateTestCases", outcome="completed", where="id = '<object_id>'")
```

If advance refuses (`does not confirm completion`), the YAML is still a stub — fill it (Step 5) and retry. Do not escalate solely because advance refused a stub.

Then tell the user one line and return to the state machine:

```
Test cases for <object_name>: <N> cases (<source>).

  source ∈ { "from scai test seed",
             "from AI swarm fill",
             "<S> from scai test seed (sufficient, swarm skipped)",
             "<S> from scai test seed + <N-S> from AI swarm fill (<agents launched>)" }
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
| `scai test seed` runs with a log but YAML still empty | The log didn't contain a row for this proc. Continue to Step 5 — the swarm will fill from source SQL + (optionally) live source DB. |
| Swarm agents return zero rows | Source SQL likely refers to objects not in the registry, so the data-driven agent fell back to testbed-CSV mode (Teradata) or had no data path. Inspect the agent's stdout — it should report `branch_values` it used. |
| Test cases written but `scai test validate` later fails on YAML shape | The stub `steps:` block didn't match the proc's actual shape (multi-RS, OUT param, DML side effect, ...). That's not this skill's problem — `DIAGNOSE_FIX.md` Step 2.5 catches it and routes to `EDIT_TEST_YAML.md`. |
