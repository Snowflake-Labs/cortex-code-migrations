# Synthetic Data Generation Rules for SAS Validation

Rules for generating smart synthetic test data that catches common SAS-to-Snowflake translation errors.

## General Rules

| Rule | Details |
|------|---------|
| Rows per table | 5-8 rows (enough to test logic, small enough for LLM to trace) |
| Column coverage | Only columns referenced in the converted code (SELECT, WHERE, JOIN, GROUP BY) |
| Which tables get rows | `tables.py seed-targets tables.json` — source leaves only (read, never created in scope). Never seed intermediate or output tables: the pipeline rewrites them, and pre-seeding hides upstream defects |
| Where they live | Create source tables at the exact name the converted code reads (inside the validation schema). Only SAS WORK datasets are TEMPORARY/bare |
| Column width | Truncate every generated string to the declared length — one overflow aborts the whole load |
| Data realism | Values should be plausible for the column type; realism never outranks join/filter alignment |

## Join-Aware Data Generation

For every JOIN or MERGE in the converted code, the synthetic data MUST include these key distribution patterns:

### Key Alignment Matrix

| Scenario | Left Table | Right Table | Purpose |
|----------|-----------|-------------|---------|
| Match (both sides) | key = 1, 2, 3 | key = 1, 2, 3 | Tests normal join behavior |
| Left-only key | key = 4 | (no key 4) | Tests LEFT JOIN produces NULL for right-side columns |
| Right-only key | (no key 5) | key = 5 | Tests RIGHT/FULL join; inner join should exclude |
| Duplicate key (one side) | key = 1 (one row) | key = 1 (two rows) | Tests one-to-many join (row multiplication) |
| Duplicate key (both sides) | key = 2 (two rows) | key = 2 (two rows) | Tests many-to-many (SAS MERGE vs SQL JOIN difference) |
| Missing key both sides | key = NULL | key = NULL | PROC SQL matches missing to missing; SQL `=` does not |
| LEFT JOIN `ON` filter | a matched key whose right row fails the extra `ON` condition | — | Row must survive with NULL right columns |
| MERGE shared column | same key, different values in a shared non-key column | — | Last-listed dataset must win |

### Example: Two-Table JOIN

```sql
CREATE TEMPORARY TABLE customers (id NUMBER, name VARCHAR, region VARCHAR);
INSERT INTO customers VALUES
  (1, 'Alice', 'EAST'),
  (2, 'Bob', 'WEST'),
  (2, 'Bob Jr', 'WEST'),    -- duplicate key (many-to-many test)
  (3, 'Carol', 'EAST'),
  (4, 'Dave', 'SOUTH'),     -- left-only key
  (5, NULL, NULL);           -- missing value row

CREATE TEMPORARY TABLE orders (order_id NUMBER, customer_id NUMBER, amount NUMBER, order_date DATE);
INSERT INTO orders VALUES
  (101, 1, 100.00, '2024-01-15'),
  (102, 1, 250.50, '2024-02-20'),  -- duplicate key (one-to-many)
  (103, 2, -10.00, '2024-01-01'),  -- negative amount
  (104, 3, 0, '2024-06-30'),       -- zero amount + mid-year date
  (105, 3, NULL, '2024-12-31'),    -- NULL amount + year-end date
  (106, 6, 500.00, NULL),          -- right-only key + NULL date
  (107, 2, 75.00, '2024-01-01');   -- second row for key=2
```

## Range-Join & Cross-Table Value Alignment (CRITICAL)

The equality-join matrix above is necessary but NOT sufficient. The most common cause of silently-empty pipeline outputs is a **range join or unit mismatch** where rows exist on both sides but never overlap. Detect and handle these BEFORE generating data.

### Detect non-equality join predicates

Scan the converted SQL for join predicates beyond `a.key = b.key`:

| Predicate pattern | Join type | Alignment requirement |
|-------------------|-----------|----------------------|
| `x BETWEEN t.lo AND t.hi` | Range / interval | child `x` MUST fall inside ≥1 parent `[lo, hi]` interval |
| `a.x >= t.lo AND a.x <= t.hi` | Range (expanded) | same as BETWEEN |
| `a.d BETWEEN t.d - tol AND t.d + tol` | Tolerance / nearest | child `d` within `tol` of a parent `d` |
| `ROUND(a.x) = ROUND(b.x)` | Bucketed | both sides round to the same bucket |
| `CONTAINS(a.key, b.name)` / `LIKE` | Substring | child substring actually appears in parent key |

### Range-join data rule

For every range join, generate child-table values so that:
1. **At least one child row falls strictly inside a parent interval** — guarantees the join produces rows (positive test). Place it mid-interval, e.g. parent `[100, 200]` → child at `150`.
2. **At least one child row falls outside all intervals** — negative test (verifies the join filters correctly).
3. **Boundary rows** at exactly `lo` and exactly `hi` — verifies inclusive/exclusive bound handling.

```sql
INSERT INTO price_band VALUES ('B1', 100, 200);        -- [lo, hi]
INSERT INTO line_item  VALUES ('L1', 150);             -- inside   (positive)
INSERT INTO line_item  VALUES ('L2', 100);             -- lo boundary
INSERT INTO line_item  VALUES ('L3', 950);             -- outside  (negative)
```

### Unit-consistency rule

When the same quantity appears in different tables under different names or unit labels (amounts in two currencies, distances in two units, timestamps in two zones) and the tables join or compare on it, seed every column of that family in ONE overlapping range. Do not convert units for test data: overlap beats realism, or every cross-table join silently returns zero rows while each file "passes" on its own. Note the choice in a comment.

### Literal-predicate polarity

A row that satisfies every join is still dropped by a literal filter it fails. For each literal in a `WHERE`/`ON`/`CASE` on a seeded column:
- **Inclusion** (`= 'X'`, `IN (...)`, `LIKE 'X%'`, after any `TRIM`/`UPPER`): seed at least one row carrying the surviving value.
- **Exclusion** (`<> 'X'`, `NOT IN`, `NOT LIKE`, `CASE WHEN col IN (...) THEN NULL`): keep the golden-path row *off* the literal; add one separate row *on* it as the negative test.

### Multi-hop survival rule

A seed row must survive ALL the way to the terminal output tables, not just the first join. For each terminal table in the cross-file DAG:
1. Walk the dependency chain backward to the source tables it ultimately derives from.
2. Ensure at least one fully-aligned "golden path" row exists at every hop: matching equality keys AND overlapping range values at each join along the path.
3. This guarantees the T3 terminal-output assertion (non-empty) can pass for a correctly-converted pipeline.

Verification heuristic: pick one entity (e.g. `S1`) and ensure it has aligned rows in EVERY source table on the golden path, so it flows through every layer to the terminal tables.

## SAS Missing Value Test Rows

Every table MUST include at least one row that exercises SAS missing value semantics:

| Column Type | Test Value | What It Tests |
|-------------|-----------|---------------|
| NUMBER | NULL | SAS `.` missing numeric → Snowflake NULL |
| VARCHAR | NULL | SAS character missing → Snowflake NULL |
| VARCHAR | `''` (empty string) | SAS blank character → Snowflake empty string |
| DATE | NULL | Missing date handling |
| NUMBER | 0 | Zero is NOT missing in SAS (common confusion) |

### Missing Value Row Pattern

```sql
-- Every table should have one row like:
INSERT INTO table_name VALUES
  (99, NULL, '', NULL, 0);  -- id, numeric_col, char_col, date_col, zero_col
```

## Boundary Value Test Rows

Include at least one row per table with boundary/edge-case values:

| Data Type | Boundary Values | Purpose |
|-----------|----------------|---------|
| NUMBER | 0, -1, -999.99 | Zero and negative (SAS treats missing < negative) |
| NUMBER | 999999.99 | Large value (overflow test) |
| VARCHAR | `''` (empty) | Empty string vs NULL distinction |
| VARCHAR | `'A'` (single char) | Minimum-length string |
| DATE | `'2024-01-01'` | Year boundary |
| DATE | `'2024-12-31'` | Year-end boundary |
| DATE | `'2024-02-29'` | Leap year (if date logic involves month arithmetic) |

## Duplicate Key Rows

For GROUP BY, FIRST./LAST., PROC SORT NODUPKEY, or any aggregation:

| Pattern | Minimum Requirement |
|---------|---------------------|
| GROUP BY key | At least one key value with 2+ rows |
| BY + FIRST./LAST./RETAIN | One BY group with 2 rows tied on every sort key (exercises the tiebreak) |
| FIRST./LAST. processing | At least one BY-group with 3+ rows (to test first, middle, last) |
| PROC SORT NODUPKEY | Duplicate rows that differ only in non-key columns |
| SAS MERGE BY | Same key in both tables with different row counts |

### Example: BY-Group Test Data

```sql
CREATE TEMPORARY TABLE transactions (
  customer_id NUMBER, txn_date DATE, amount NUMBER, txn_type VARCHAR
);
INSERT INTO transactions VALUES
  (1, '2024-01-01', 100, 'DEBIT'),   -- customer 1, first
  (1, '2024-01-15', 200, 'CREDIT'),  -- customer 1, middle
  (1, '2024-02-01', 50, 'DEBIT'),    -- customer 1, last
  (2, '2024-01-10', 300, 'CREDIT'),  -- customer 2, only row (first=last)
  (3, '2024-03-01', NULL, 'DEBIT'),  -- customer 3, missing amount
  (3, '2024-03-15', 0, NULL);        -- customer 3, zero amount + missing type
```

## RETAIN / Window Function Test Data

When the SAS code uses RETAIN, LAG, or running totals:

| Requirement | Rationale |
|-------------|-----------|
| At least 4 rows per partition | Need enough rows to verify running totals, LAG(n), LEAD(n) |
| Include partition boundary | At least 2 distinct partition values to test reset behavior |
| Include NULL in retained column | SAS RETAIN ignores missing values (keeps previous) |

## PROC FORMAT / Lookup Table Test Data

When SAS uses PUT(value, format.) or PROC FORMAT:

| Requirement | Test Case |
|-------------|-----------|
| Value in range | At least one value that matches a defined format range |
| Value NOT in range | At least one value that falls through to OTHER= default |
| Boundary value | Value exactly at range boundary (e.g., low <= val < high) |
| Missing value | NULL input to test format handling of missing |

## Multi-Block Test Data

When validating code with multiple blocks (stored procedures with multiple steps):

| Rule | Details |
|------|---------|
| Shared input tables | Create once, used by multiple blocks |
| Intermediate tables | Do NOT pre-create -- these are outputs of earlier blocks, inputs to later blocks |
| Cross-block variables | If session variables are used, set initial values before execution |
| Execution order | Execute blocks sequentially (stored procedure handles this) |

## Data Generation Checklist

Before finalizing synthetic data, verify:

- [ ] Every JOIN key has: matching rows, left-only key, right-only key
- [ ] Every table has at least one row with NULL in numeric columns
- [ ] Every table has at least one row with NULL or empty string in character columns
- [ ] At least one date boundary value exists (year-start, year-end, or leap day)
- [ ] At least one duplicate key exists for GROUP BY / aggregation testing
- [ ] Zero and negative numbers are present for numeric columns
- [ ] For BY-group processing, at least one group has 3+ rows
- [ ] For RETAIN/LAG code, at least 2 partitions with 4+ rows each
- [ ] INSERT VALUES match the CREATE TABLE column order exactly
- [ ] Source tables created at the names the converted code reads
- [ ] Every RANGE join (BETWEEN / >=...<=) has ≥1 child row inside a parent interval (positive test) and ≥1 outside (negative test)
- [ ] Columns of the same quantity family seeded in ONE overlapping range so cross-table joins overlap
- [ ] Only `seed-targets` tables seeded; generated strings fit declared widths
- [ ] Inclusion literals carried by a golden-path row; exclusion literals only on negative rows
- [ ] Each join has a missing-key row, each LEFT JOIN `ON` filter a failing right row, each MERGE a shared column with differing values
- [ ] At least one "golden path" entity has aligned rows in EVERY source table along its dependency chain so it survives multi-hop joins to the terminal output tables
