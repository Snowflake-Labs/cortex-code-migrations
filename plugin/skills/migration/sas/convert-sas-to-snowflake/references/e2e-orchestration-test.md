# T3 harness: Integration & End-to-End Orchestration Test

## When to Load

Load in T3 of `workflows/validation-pipeline.md`. T2 runs each file on test data; T3 runs the
**whole pipeline as one flow** on full data, from a reusable harness on disk, and asserts that
terminal outputs are populated. A pipeline can pass T2 file by file and still be broken end to
end (a terminal table empty because an intermediate join produced zero rows).

## Step 1: Layer order

Use the order `sf_exec.py plan --mode run` wrote to `exec_plan_run.json` (`order`, `deps`):
parameter files first, then producers before consumers. Do not compute a second order. Files
with no upstream converted file are layer 0; terminal files are those whose outputs no other
file reads. The harness, `task_dag.sql` and the T3 run all use this one order and the same files
-- a sub-flow the parent SAS `%include`s is a CALL in the parent, not a separate root.

---

## Step 2: Generate the Reusable Harness (on disk)

Generate five files. These are deliverables — they let the user re-run the integration test and deploy orchestration without regenerating.

### 2.1 `orchestration/sp_e2e_pipeline.sql`

A master stored procedure that runs every converted file in DAG layer order. For Tier-2 files, `CALL` the procedure; for Tier-1 files, inline the file's primary `CREATE TABLE AS` statement (or `CALL` a thin wrapper). Track step count and catch errors.

```sql
CREATE OR REPLACE PROCEDURE <SCHEMA>.SP_E2E_PIPELINE()
RETURNS STRING LANGUAGE SQL EXECUTE AS CALLER AS
$$
DECLARE
  v_step STRING DEFAULT '';
  v_passed INTEGER DEFAULT 0;
  v_count INTEGER;
BEGIN
  -- Layer 1
  v_step := 'L1: <proc_or_file>'; CALL <SCHEMA>.SP_...(); v_passed := v_passed + 1;
  -- ... one statement per file, in layer order ...
  -- Layer N (terminal)
  v_step := 'VALIDATION';
  SELECT COUNT(*) INTO :v_count FROM <SCHEMA>.<TERMINAL_TABLE>;
  RETURN OBJECT_CONSTRUCT('status','SUCCESS','steps_passed',v_passed,
                          'steps_failed',0,'last_step',v_step,
                          'terminal_rows',v_count)::STRING;
EXCEPTION WHEN OTHER THEN
  RETURN OBJECT_CONSTRUCT('status','FAILED','failed_at',v_step,
                          'steps_passed',v_passed,'code',sqlcode,'message',sqlerrm)::STRING;
END;
$$;
```

### 2.2 `orchestration/task_dag.sql`

Snowflake Task DAG mirroring the layers: a root task + `AFTER` children, one task (or one bundled task per layer). Tasks created `SUSPENDED`; include `ALTER TASK ... RESUME` lines bottom-up. Include a comment noting `EXECUTE TASK` requires the `EXECUTE TASK` account privilege (ACCOUNTADMIN grant).

### 2.3 `orchestration/adf_pipeline.sql` (only when the orchestration target is ADF)

ADF master-orchestrator definition (JSON in a comment block): a Script activity that CALLs the staging SP, then a Script activity that CALLs `SP_E2E_PIPELINE()`, then a Lookup activity that validates a terminal table row count. ADF is the master scheduler; Snowflake Tasks handle intra-DAG parallelism.

### 2.4 `testing/setup_test_data.sql`

The aligned test-data loader (the T2 seed). MUST follow the range-join + unit-consistency rules in `references/synthetic-data-rules.md` so multi-hop joins survive to terminal tables. Include a `TRUNCATE` block so it is idempotent.

### 2.5 `testing/expected_results.sql`

Expected terminal-table row counts and key values (from T2/SAS baselines), as comments + sample assertion `SELECT`s.

---

## Step 3: Execute End-to-End

1. Inputs point at full data (`tables.json full_data_fqn`), read-only; `testing/setup_test_data.sql`
   is for re-running on test data.
2. Deploy all procedures (they already exist if T2 ran).
3. Run the harness statements through `sf_exec.py next/record` (`--files` the harness files), so
   the first blocker and its class are recorded like any other run.
4. Parse the returned JSON. Require `steps_failed = 0`. If a step failed, the `failed_at` field localizes the broken file — fix the converted SQL (not the SAS interpretation) and re-run.

---

## Step 4: Terminal-Output Assertion (the key check)

For every **terminal** table (no downstream consumer), assert row count > 0:

```sql
SELECT '<TERMINAL_TABLE>' AS TBL, COUNT(*) AS ROW_CNT FROM <SCHEMA>.<TERMINAL_TABLE>
UNION ALL ...;
```

Classify each terminal table:
- **POPULATED** (> 0 rows): pass.
- **EMPTY — JUSTIFIED**: the table is empty only because a genuine source/reference table is empty by design (e.g. an unused regional reference). Record the empty upstream in `notes`.
- **EMPTY — DEFECT**: empty despite populated sources. This is a real failure (almost always a join that did not overlap — see the range-join/unit-consistency rules). Flag for fix.

A run where any terminal table is `EMPTY — DEFECT` does NOT pass T3.

---

## Step 5: Compare Terminal Outputs to Baselines

For terminal tables with a baseline (SAS outputs, or the T2 trace on test data), compare per `references/comparison-rules.md` (full data: §Full-data sampling). Trivial pass rule: `expected = 0 AND actual = 0` is a WARNING (`TRIVIAL_PASS`), not a silent pass.

---

## Step 6: Write Results

```python
e2e = {
  "executed_at": "<ISO>",
  "warehouse": "<wh>",
  "layers": <n>,
  "steps_total": <n>, "steps_passed": <n>, "steps_failed": <n>,
  "terminal_tables": [
    {"table": "<T>", "rows": <n>, "status": "POPULATED|EMPTY_JUSTIFIED|EMPTY_DEFECT",
     "empty_source": "<table or null>", "baseline_match": "PASS|FAIL|NO_BASELINE|TRIVIAL_PASS"}
  ],
  "harness_files": ["orchestration/sp_e2e_pipeline.sql","orchestration/task_dag.sql",
                    "orchestration/adf_pipeline.sql (ADF target only)","testing/setup_test_data.sql",
                    "testing/expected_results.sql"],
  "status": "PASS|FAIL"
}
# write <output_dir>/e2e_test_results.json
```

`status = PASS` requires: `steps_failed == 0` AND no terminal table is `EMPTY_DEFECT`.

---

## Step 7: Cleanup

Drop validation-only objects in the validation schema; never touch source data.

---

## Modular Execution (Context-Aware)

Generating the master SP for a large pipeline (40+ files) can be large. Build it incrementally:
1. Generate the SP layer-by-layer, appending each layer's CALLs.
2. After writing the harness files, update `execution_progress` in `conversion_state.json` and append a checkpoint line.
3. If context nears the limit mid-generation: save the partial harness + state, inform the user, exit. Resume reads `execution_progress` and continues from the next layer.

---

## Gate

`e2e_test_results.json` and `orchestration/sp_e2e_pipeline.sql` exist; set `gates.t3_e2e`.
