# Test Case Generation: Batch (All Wave Objects)

Generate test cases for **the next 5 functions and procedures in the current wave** in parallel. Spawns background agents to generate test cases (via the AI swarm) concurrently, processing 5 objects at a time.

> **SCOPE: Operates on every function/procedure in the current wave.**
> Called from [../SKILL.md](../SKILL.md) Step 3 when the user opts for batch test case generation.

## Step 1: Enumerate Wave Objects

Call `testing_progress()` to get next 5 functions and procedures in the current wave.

From the response, collect every object listed under the **not_started** and **ready** categories — these are the objects that still need test cases.

The response also includes a **has_test_cases** list — objects that already have test YAML files. Exclude those from the batch. If all objects already have test cases, report that and return to the parent skill.

Build a final list: `objects_needing_test_cases`.

Confirm with the user:

> Found **N** functions/procedures needing test cases in wave **W**: `<object_list>`.
> Proceeding with parallel generation. This may take a few minutes.

## Step 2: Gather Source Context

Query the registry for the next 5 objects in `objects_needing_test_cases` in a single call:

```
query_registry(
  where="source.objectType IN ('function', 'procedure') AND (source.canonicalName ILIKE '%<name1>%' OR source.canonicalName ILIKE '%<name2>%')",
  fields="source,files,signature,dependencies"
)
```

This returns everything needed for each object — name, type, schema, source file path (`files.source.path`), parameter signature (`signature.parameters`), and dependencies (`dependencies.dependsOn`).

Read the source SQL file at `files.source.path` for each object to get the full source code.

## Step 3: Spawn Parallel Agents

Launch background agents using the Task tool to generate test cases in parallel. **Process 5–10 objects at a time** — spawn a batch of agents, wait for them to complete, then spawn the next batch. This avoids overwhelming the system with too many concurrent agents.

Each agent generates test cases for its assigned object via the AI swarm (as described in [SWARM.md](SWARM.md)).

### Agent Prompt Template

For each object, spawn a Task with:

```
You are creating test cases for a single database object as part of a batch operation.
Read and follow the instructions in <baseline_capture_dir>/SWARM.md to generate test cases for <object_name>.
Only generate the test cases and write the YAML, then report back.

Context:
- Object name: <source.name>
- Object type: <source.objectType>
- Schema: <source.schema>
- Source file: <files.source.path>
- Source code: <contents of source file>
- Parameters: <signature.parameters>
- Dependencies: <dependencies.dependsOn>
- Project directory: <project_dir>
- Source connection: <source_connection_name>
- Snowflake connection: <snowflake_connection_name>
- Database: <database_name>
- Baseline capture dir: <absolute_path_to_baseline-capture_dir>

Report back with:
- Object name
- Test case count
- Any errors encountered
```

Where `<baseline_capture_dir>` is the directory containing this file.

**IMPORTANT:** Propagate the current SQL connections to each agent.

## Step 4: Collect Results

Wait for all agents (across all batches) to complete. Gather results into a summary table:

| Object | Type | Test Cases | Status |
|--------|------|------------|--------|
| `schema.ProcA` | procedure | 20 | success |
| `schema.FuncB` | function | 15 | success |
| `schema.ProcC` | procedure | 0 | failed |

## Step 5: Handle Failures

If any agents failed:

1. List the failed objects and their error messages
2. Ask the user:

> **N** out of **M** objects failed test case generation:
> - `schema.ProcC`: <error_message>
>
> Would you like to:
> 1. **Retry failed objects** — re-run test case generation for failures only
> 2. **Skip and continue** — proceed to migration; these objects will generate test cases individually later

If retrying, spawn new agents only for the failed objects (same prompt template as Step 3, same 5–10 at a time limit).

## Step 6: Summary and Return

Present the final summary:

```
Batch test case generation complete for wave <W>.
  Total objects:     <M>
  Successful:        <N>
  Failed/Skipped:    <F>
  Total test cases:  <T> across all objects
```

Return control to the parent skill ([../SKILL.md](../SKILL.md) Step 4: Dispatch Loop).
