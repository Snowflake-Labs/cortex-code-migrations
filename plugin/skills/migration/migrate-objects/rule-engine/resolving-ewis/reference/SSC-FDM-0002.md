# SSC-FDM-0002 - Correlated Subqueries May Have Functional Differences

Snowflake supports correlated subqueries. This FDM is a **caution flag on a converted
construct, not a reported break** — most occurrences need no edit at all.

Do not "fix" it by reflexively rewriting every correlated subquery into a join. That is a large
diff, it changes the shape of code a reviewer has to trust, and it is unnecessary in the
majority of cases. Confirm there is a real difference first.

When there *is* a real difference, it is almost never correlation semantics. It is
**non-deterministic row choice** — a `TOP 1` / `LIMIT 1` with no total ordering, which picks a
different row on Snowflake than it did on SQL Server, and can pick a different row on two
consecutive Snowflake runs. That is the failure this reference mainly exists for.

## Decision Tree

```
Does the object's test actually fail, or the query actually error?
├── NO  → Leave the query alone. Remove the marker. Done.
└── YES → What is the symptom?
    ├── "Unsupported subquery type cannot be evaluated"
    │     → Snowflake cannot evaluate this correlation. Rewrite (Case 2).
    ├── Row counts match, VALUES differ, differs run-to-run
    │     → Non-deterministic pick. Add a total ORDER BY (Case 1).
    ├── Correlated scalar subquery returned more than one row
    │     → Same error exists in SQL Server; the data differs, not the dialect (Case 3).
    └── Row counts differ
          → Check NULL handling in NOT IN / NOT EXISTS (Case 4).
```

## Identification

```sql
--** SSC-FDM-0002 - CORRELATED SUBQUERIES MAY HAVE SOME FUNCTIONAL DIFFERENCES. **
```

Attached to a subquery that references a column from an enclosing query block.

## Fix Process

1. **Deploy and run the test first.** This FDM is advisory; a passing object needs no edit.
2. If it fails, classify with the decision tree — the symptom names the case.
3. Apply only the narrow fix for that case.
4. Remove the marker line.
5. **Re-run the test twice.** A pass that is not reproducible is Case 1 and is not fixed yet.

---

## Case 1: Non-deterministic pick (`TOP 1` / `LIMIT 1` without a total order)

This is the common real failure. Both dialects are free to return any qualifying row when the
ordering is not total, so the two sides legitimately disagree — and so do two Snowflake runs.

### Before
```sql
SELECT p.PackageId,
       (SELECT TOP 1 t.TaxRate
        FROM TaxRates t
        WHERE t.LocId = p.LocId          -- correlated
        ORDER BY t.EffectiveDate DESC)   -- ties are unresolved
       AS Rate
FROM Package p;
```

`ORDER BY EffectiveDate DESC` looks ordered, but if two rows share an `EffectiveDate` the pick
is arbitrary.

### After — make the order total
```sql
SELECT p.PackageId,
       (SELECT t.TaxRate
        FROM TaxRates t
        WHERE t.LocId = p.LocId
        ORDER BY t.EffectiveDate DESC, t.Id DESC   -- unique tie-break
        LIMIT 1)
       AS Rate
FROM Package p;
```

### Or express the pick once, with `QUALIFY`
Clearer when several columns come from the same picked row:

```sql
SELECT p.PackageId, t.TaxRate, t.EffectiveDate
FROM Package p
LEFT JOIN (
    SELECT LocId, TaxRate, EffectiveDate
    FROM TaxRates
    QUALIFY ROW_NUMBER() OVER (PARTITION BY LocId
                               ORDER BY EffectiveDate DESC, Id DESC) = 1
) t ON t.LocId = p.LocId;
```

**Important:** adding a tie-break changes which row is returned, so it can differ from what the
SQL Server baseline captured. If the baseline itself was captured from a non-total ordering,
that is a property of the source query, not a migration defect — record it with `note` and, if a
case still differs, let an independent verifier decide it. Do not tune the tie-break until the
numbers match; that is fitting the fix to the baseline.

---

## Case 2: Snowflake cannot evaluate the correlation

Some correlated shapes are rejected outright — typically correlation reaching more than one
query block up, or a correlated aggregate in a position Snowflake cannot flatten. The error is
explicit:

```
Unsupported subquery type cannot be evaluated
```

Rewrite as a join. A correlated aggregate becomes a pre-aggregated derived table:

### Before
```sql
SELECT s.ShipmentId,
       (SELECT SUM(i.Amount) FROM ShipmentItemTaxes i
        WHERE i.ShipmentId = s.ShipmentId) AS TaxTotal
FROM tbl_MDShipment s;
```

### After
```sql
SELECT s.ShipmentId, COALESCE(i.TaxTotal, 0) AS TaxTotal
FROM tbl_MDShipment s
LEFT JOIN (
    SELECT ShipmentId, SUM(Amount) AS TaxTotal
    FROM ShipmentItemTaxes
    GROUP BY ShipmentId
) i ON i.ShipmentId = s.ShipmentId;
```

Two things to preserve:

- **`LEFT JOIN`, not `JOIN`.** A correlated scalar subquery yields `NULL` for a row with no
  match; an inner join drops the row. That silently changes row counts.
- **`SUM` of no rows is `NULL`, not `0`.** Keep `COALESCE` only if the original produced `0` —
  do not add it by habit.

For a row-wise dependency that genuinely cannot be pre-aggregated, `LATERAL` keeps the
correlation:

```sql
SELECT p.PackageId, r.TaxRate
FROM Package p,
     LATERAL (SELECT TaxRate FROM TaxRates t
              WHERE t.LocId = p.LocId
              ORDER BY t.EffectiveDate DESC, t.Id DESC LIMIT 1) r;
```

Note `LATERAL` with a comma join behaves as an inner join — no match drops the row. Use
`LEFT JOIN LATERAL … ON TRUE` to keep it.

---

## Case 3: "Subquery returned more than one row"

A scalar correlated subquery must yield at most one row. **SQL Server raises the same error**, so
this is not a dialect difference — it means the migrated data admits duplicates the source data
did not. Usual cause: a uniqueness guarantee that did not survive, because Snowflake does not
enforce `UNIQUE` / `PRIMARY KEY` (see [SSC-FDM-0021](SSC-FDM-0021.md), UNIQUE indexes).

Investigate the data before touching the query. Adding `LIMIT 1` here **hides a real data
defect** and turns a loud failure into a wrong answer.

---

## Case 4: Row counts differ — `NOT IN` / `NOT EXISTS` with NULLs

`NOT IN` over a subquery that can produce `NULL` yields no rows in both dialects — three-valued
logic is the same. So a count difference here is usually a data difference, not a semantics
difference. Verify before rewriting.

If the intent was "not present", `NOT EXISTS` states it and is NULL-safe:

```sql
-- intent-revealing, and unaffected by NULLs in the inner column
WHERE NOT EXISTS (SELECT 1 FROM Excluded e WHERE e.PackageId = p.PackageId)
```

Changing `NOT IN` to `NOT EXISTS` **can change results** when the inner column has NULLs — that
is the point of the change, and it means the two sides will legitimately differ. Treat it as a
deliberate semantic decision and `note` it, not as a silent cleanup.

---

## Quick Reference

| Symptom | Cause | Action |
|---|---|---|
| Test passes | Advisory only | Remove the marker; change nothing |
| Values differ, unstable across runs | `TOP 1`/`LIMIT 1` without total order | Add a unique tie-break, or `QUALIFY ROW_NUMBER()` |
| `Unsupported subquery type cannot be evaluated` | Correlation Snowflake cannot flatten | Pre-aggregated `LEFT JOIN`, or `LATERAL` |
| `Subquery returned more than one row` | Duplicate data; unenforced uniqueness | Fix the data — do **not** add `LIMIT 1` |
| Row counts differ on `NOT IN` | NULLs in the inner column | Verify data; `NOT EXISTS` only as a deliberate change |

## Resources

- [Working with subqueries](https://docs.snowflake.com/en/user-guide/querying-subqueries)
- [QUALIFY](https://docs.snowflake.com/en/sql-reference/constructs/qualify)
- [LATERAL joins](https://docs.snowflake.com/en/sql-reference/constructs/join-lateral)
- [Constraints are not enforced](https://docs.snowflake.com/en/sql-reference/constraints-overview)
