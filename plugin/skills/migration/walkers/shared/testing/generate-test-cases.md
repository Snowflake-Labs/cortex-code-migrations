# Generate Test Cases (Seed → Maybe-Fill)

`generateTestCases` for one function or procedure. The step's `run` (`walk_run op=seed`) runs `scai test seed`
for this object and reads the YAML it leaves; when `test_cases:` comes back empty, a swarm fills **rows only**.
Never hand-author `steps:`; the *multiple result sets* recipe is the one edit.

## 1. Inputs

The run's reply carries everything §4–§5 use. `files` (first step) is for §7 only.

## 2. Seed

Call the step's `run`. Never run `scai test seed` yourself, and never hand-write the YAML.

## 3. Failures (seed or a live `EXEC`)

- Source cannot run as written on **every** legal dataset (INSERT…EXEC column-count mismatch, a comment that it
  fails at runtime, the same defect on a live `EXEC`) → escalate now. Do not re-seed, spawn the swarm, or paper
  over it in YAML.
- A name that does not resolve (42S02, unknown function) → `walk(action="lookup", name="<name>")`: no row, not
  `onDependsOn`, or not `bindable` → `cur_reconciler`, then `walk(action="next")`; not `done` → `walk(action="next")`
  and return `partial`; `done` (a missing AIMSBX table) → `sandbox_specialist`.
- Fails only because of **this fixture's rows** ([general_task §3](../../../../../agents/general_task.md#3-rules))
  → `sandbox_specialist` (`task=generateTestCases`, the evidence). Leftover sandbox yaml is the binding.
  Helper `result`s per [general_task §4](../../../../../agents/general_task.md#4-helpers); "re-run `run`" here
  means retry the seed.

Anything else: keep `error` as the evidence and `walk escalate` — do not hand-write the YAML.

## 4. Read the reply

- **The next step** (`recorded`): the YAML already had cases; the task is recorded. Carry on with that step.
- **`multi_result_set: true`**: the target returns several result sets (`RETURNS ARRAY` / `SSC-FDM-0020`).
  Apply the *multiple result sets* recipe in [edit-test-yaml.md](edit-test-yaml.md) to the CALL step in
  `yaml_path` before anything else.
- **`fill: true`**: `test_cases:` is empty — §5. Decide on this, not on `test_seed_source` (a log may not
  mention this object).
- **`failed` / `fix`**: §3, then what `fix` says.

## 5. Fill `test_cases:` with the swarm

The reply carries what the writers need: `yaml_path`, `object_name`, `signature`, `referenced_tables`,
`key_samples`, and `prompt` (those facts in the writers' prompt). `signature_omitted`: leave the prompt's
`signature:` line as it is. `key_samples_omitted` names why the key query was not built: one `query_source`
(`TOP 10` of the columns the key parameters are compared to, tables spelled `${token}.schema.table`) if it
says how, else keep `key_samples: none`.

Launch one each of `data_driven`, `edge_cases`, `business_logic` in one message, `run_in_background=true`, as
their `subagent_type`, with `prompt` verbatim — the agent definition is the contract, no pasted instructions.
Each writes `<project_dir>/.scai/tmp/<object_name>_<data_driven|edge_cases|business_logic>.yml` and replies
with the same rows. Collect every writer; a complex object needs the slowest one's rows too:

1. Wait on the writers one at a time, in launch order:
   `agent_output(agent_id=<id>, wait=true, timeout_ms=120000)`. A writer still running when its wait
   returns: go on to the next, and come back to it until it is in. Never `sleep`.
2. A writer is **in** once its `Status` is `completed` and it left rows (its tmp file, else the
   `Agent Response` yaml). One whose response is a model error (`Error: internal error`, `server_error`,
   `response incomplete`) never ran: relaunch it once, at once, no sleep — unless the writers in already gave
   15 or more usable rows; then leave it out. A second model error: write that writer's rows yourself, by its
   agent definition (`<pluginDir>/agents/<writer>.md`).
3. Merge once every writer is in or left out.

Concatenate their `test_cases:`, drop exact duplicates, keep 15–25 rows. When trimming, keep `# expects rows`
rows over `# expects empty` ones (at most two of those per object), then data-driven rows. Zero rows from
`data_driven` usually means no data path for the referenced tables — check the `branch_values` it reports.
Prefix each kept row's comment with its writer, `# <data_driven|edge_cases|business_logic>: <its comment>` —
§7 routes a vacuous row back to the writer that made it.

Replace `validation.test_cases:` in `yaml_path` with the merged list. Do not touch `steps:`, `modifies_data:`, or
`affected_tables:`. Row shape: [step-based-yaml.md → Placeholders](step-based-yaml.md#placeholders-and-test_cases).

## 6. Done

`walk(action="done")` once the rows are in (or the recipe applied). The status source checks the YAML has populated
`test_cases:`; `not_done` means it is still a stub — fill it (§5) and retry; do not escalate for that alone. A
YAML-shape mismatch found later is the fix loop's ([edit-test-yaml.md](edit-test-yaml.md)), not this task's.

## 7. Cover vacuous rows (once)

A capture names each case that tests nothing in `vacuous` — `[{case, kind, reason}]`, kind `source_error`
(the source raised for these inputs), `no_rows` or `only_nulls`. Add rows that test what they could not when
the capture reply says `regenerate`, or when it failed with *No case tests anything* and its `fix` sends you here.

1. A line `# vacuous rows covered` directly above `test_cases:` means this pass already ran: do not run it
   again — carry on with the step, or `walk escalate` with the vacuous reasons if the capture failed.
2. `case` ends in `(case N)`: the Nth row of `test_cases:`, 1-based. Its comment prefix names the writer
   (none → `data_driven`). Up to two rows whose comment says `# expects empty` need no cover; cover the rest.
3. Launch each writer that owns a row to cover, in the background, with the §5 prompt plus
   `cover: [{row, reason}]` and `count: <how many>`. Each writes `<object_name>_<writer>_cover.yml`.
   Collect as §5 does, until all are in. No `prompt` at hand (a later step): build it from
   `files.source` and `walk lookup` as §5 lists its facts.
4. Append the new rows after the existing ones, writer-prefixed, add `# vacuous rows covered` above
   `test_cases:`, and `walk_run(op="capture")` again.

Every existing row stays, the vacuous ones included: this pass only adds.
