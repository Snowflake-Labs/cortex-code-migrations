# SAS Logic Trace (expected baselines for T2)

## When to Load

Load in T2 of `workflows/validation-pipeline.md` when no SAS-produced outputs were supplied.
Trace the original SAS against the seeded test data and write the expected output **before**
running the converted SQL, so the baseline cannot be shaped by the SQL's answer.

---

### Generate Expected Baseline (SAS Logic Trace)

This is the core validation capability. Manually trace the original SAS code against the synthetic data to produce expected output.

#### 1. Read Inputs

1. Read the original SAS code (block by block)
2. Read the seeded test rows (the `synthetic_data.sql` inserts, or the user's test tables):


#### 2. Trace SAS Logic Row-by-Row

For each SAS block that produces an output table:

**DATA Step tracing rules:**
1. Initialize the PDV (Program Data Vector) with all variables
2. Process each input row according to SET/MERGE/INPUT statement
3. Apply SAS missing value semantics:
   - Missing numeric (`.`) is less than ANY number (including negative)
   - Missing + value = missing (SAS sum statement `x + y;` is the exception -- it treats missing as 0)
   - IF condition with missing: `IF x > 0` is FALSE when x is missing
   - `PUT(x, fmt.)` of a missing numeric is the text `.` (right-aligned in the format width), never
     empty; a user format with no matching range renders the value as that same text
4. Track RETAIN values across iterations (do NOT reset to missing)
5. Apply FIRST./LAST. flags based on BY-group boundaries
6. Execute OUTPUT/DELETE/RETURN/STOP behavior
7. At end of DATA step iteration, implicit OUTPUT if no explicit OUTPUT statement

**PROC SQL tracing rules:**
1. Execute the SQL logic mentally against the synthetic data
2. Follow standard SQL semantics (not SAS DATA step semantics), with SAS's missing rules:
   a missing key **joins** a missing key, and missing sorts lowest
3. A `CALCULATED` column, `MONOTONIC()` or a remerged summary statistic is evaluated as SAS does

**MERGE tracing rules:**
1. Both datasets MUST be sorted by BY variables
2. MERGE is NOT a SQL JOIN -- it interleaves records within BY-groups
3. One-to-one: matched rows combine, unmatched rows fill with missing
4. One-to-many: the single row is repeated for each row in the many-side
5. Many-to-many: SAS processes row-by-row within the BY-group (NOT a Cartesian product)
6. IN= flags: track which dataset contributed each row

#### 3. Produce Expected Output (Local)

For each output table, present the expected result as a table:

```
Expected output for OUTPUT_TABLE (traced from SAS logic):

| ID | NAME   | TOTAL_AMOUNT | REGION |
|----|--------|-------------|--------|
| 1  | Alice  | 350.50      | EAST   |
| 2  | Bob    | 65.00       | WEST   |
| 3  | Carol  | 0           | EAST   |
| 4  | Dave   | NULL        | SOUTH  |
```

**Persist** with the stdlib `csv` module (header = output column names, empty field = missing)
to `tests/<script_name>/expected/expected_<output_name>.csv`, then stamp it with the tables it was
traced against: `tables.py stamp tables.json <csv> <TABLE> ...`. Numbers unformatted; dates as
`YYYY-MM-DD` or SAS day numbers (compare-sql equates them). A dataset with no registry
name yet (WORK intermediates) is named by its SAS name without `WORK.` — the bare name the SQL uses.

Show the expected table in the output (no stop: the user approved the tier at Step 1). If a
later comparison proves the trace wrong, correct it as `BASELINE_CORRECTED` and re-stamp.
