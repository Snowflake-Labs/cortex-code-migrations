# SSC-FDM-0021 - CREATE INDEX Is Not Supported

Snowflake standard tables have no user-defined secondary indexes. Pruning comes from
micro-partition metadata, which is maintained automatically. So a converted `CREATE INDEX`
has no direct equivalent — and in most cases it needs no replacement at all.

The whole decision is: **was that index a performance hint, or was it enforcing something?**

## Decision Tree

```
What is the index on?
├── A #temp table / table variable inside a procedure
│   └── DELETE the statement. Nothing replaces it. (Most common by far.)
├── A permanent table, non-UNIQUE
│   ├── Table is small/medium → DELETE. Micro-partition pruning covers it.
│   └── Table is very large AND queries filter/join on the leading column
│       └── Consider ALTER TABLE ... CLUSTER BY. Do not add it reflexively.
└── A UNIQUE index
    └── This was a CONSTRAINT, not a hint. Snowflake does not enforce
        uniqueness — see "UNIQUE indexes" below.
```

## Identification

The converted file keeps the statement with the marker:

```sql
--** SSC-FDM-0021 - CREATE INDEX IS NOT SUPPORTED BY SNOWFLAKE **
--CREATE INDEX IX_LocId ON MD.Doctors(LocId);
```

It may be commented out already, or left live and failing. Either way the marker is what
`resolve` looks for.

## Fix Process

1. **Find the index target.** Is it `#something` / `@something`, or a permanent table?
2. **Check for UNIQUE.** `CREATE UNIQUE INDEX` is a different problem — see below.
3. **Delete the statement** in every case except a deliberate clustering decision.
4. **Remove the marker line.**
5. **Verify the object still compiles and its test still returns the same rows.** An index
   never changes results, so a row-count or checksum change after this edit means something
   else was edited too.

---

## Case 1: Index on a temp table (most common)

The T-SQL report idiom is: build a `#temp`, index it, join it, drop it. The index exists only
to make the join cheaper on a row store.

### Before
```sql
SELECT PackageId, LspId, SoldDate
INTO #pkg
FROM Package
WHERE LspId = :LSPID;

CREATE INDEX IX_pkg_PackageId ON #pkg(PackageId);   -- SSC-FDM-0021

SELECT ...
FROM #pkg p JOIN ShipmentItemTaxes s ON s.PackageId = p.PackageId;
```

### After
```sql
CREATE OR REPLACE TEMPORARY TABLE pkg AS
SELECT PackageId, LspId, SoldDate
FROM Package
WHERE LspId = :LSPID;

SELECT ...
FROM pkg p JOIN ShipmentItemTaxes s ON s.PackageId = p.PackageId;
```

The index line is gone and nothing takes its place. Snowflake prunes on the micro-partition
metadata it already keeps for `pkg`.

**Do not** replace it with a clustering key. A temp table that lives for the length of one
procedure call cannot amortise the cost of clustering.

---

## Case 2: Index on a permanent table

Delete it. Reach for a clustering key only when all of these hold:

- the table is genuinely large (clustering is aimed at multi-terabyte tables, and is a
  background credit cost, not a free hint), **and**
- queries consistently filter or join on the same leading column(s), **and**
- you have a reason to believe pruning is poor — not just that SQL Server had an index there.

```sql
-- only with the conditions above
ALTER TABLE MD.Doctors CLUSTER BY (LocId);
```

For highly selective point lookups on a large table, the
[Search Optimization Service](https://docs.snowflake.com/en/user-guide/search-optimization-service)
is the closer analogue to a secondary index — also a paid, table-level service, so it is an
explicit decision rather than a mechanical conversion.

If the workload genuinely needs row-store indexing semantics, that is
[Hybrid Tables](https://docs.snowflake.com/en/user-guide/tables-hybrid), which do support
secondary indexes. Moving a table to hybrid is a design change and out of scope for resolving
this FDM — escalate rather than decide it inside one object's walk.

---

## Case 3: UNIQUE indexes

`CREATE UNIQUE INDEX` was doing two jobs: performance *and* enforcement. Dropping it silently
drops the enforcement, because **Snowflake does not enforce UNIQUE, PRIMARY KEY or FOREIGN KEY
constraints** (they are metadata only; `NOT NULL` is the exception and is enforced).

So decide what the code relied on:

| The original relied on | Do this |
|---|---|
| Nothing — it was documentation | Delete; optionally declare `UNIQUE` for metadata |
| Deduplicating a load | Dedupe explicitly in the query that writes the table |
| An insert *failing* on a duplicate | The failure will no longer happen — this is a behaviour change worth a `note` |

Deduplicating explicitly:

```sql
INSERT INTO target (id, val)
SELECT id, val
FROM (
  SELECT id, val, ROW_NUMBER() OVER (PARTITION BY id ORDER BY loaded_at DESC) rn
  FROM staging
)
WHERE rn = 1;
```

If the procedure depended on a uniqueness *violation* to signal something, that is a real
semantic gap: record it with `note` on the object rather than papering over it.

---

## Case 4: Clustered index on the primary key

A SQL Server clustered PK index defines physical row order. Snowflake has no equivalent and
needs none — delete the statement. Row order is not a contract in Snowflake, so any query that
depended on it was already relying on undefined behaviour; add an explicit `ORDER BY` where the
result order matters.

---

## Quick Reference

| SQL Server | Snowflake |
|------------|-----------|
| `CREATE INDEX ix ON #t(c)` | *(delete — nothing needed)* |
| `CREATE INDEX ix ON t(c)` on a small/medium table | *(delete)* |
| `CREATE INDEX ix ON t(c)` on a very large, consistently-filtered table | `ALTER TABLE t CLUSTER BY (c)` — deliberate, costed |
| Selective point lookups on a large table | Search Optimization Service |
| `CREATE UNIQUE INDEX ix ON t(c)` | Not enforced — dedupe explicitly, or `note` the gap |
| Clustered PK index | *(delete)* — row order is not a contract |
| Row-store index semantics required | Hybrid Tables — a design change; escalate |

## Why this is an FDM and not an EWI

Nothing fails to compile. The statement is simply dropped, and the migration is functionally
equivalent unless the index was `UNIQUE`. That is why the default action is delete-and-move-on,
and why the only cases worth slowing down for are uniqueness enforcement and a genuine
clustering decision.

## Resources

- [Micro-partitions and data clustering](https://docs.snowflake.com/en/user-guide/tables-clustering-micropartitions)
- [Clustering keys](https://docs.snowflake.com/en/user-guide/tables-clustering-keys)
- [Search Optimization Service](https://docs.snowflake.com/en/user-guide/search-optimization-service)
- [Constraints are not enforced](https://docs.snowflake.com/en/sql-reference/constraints-overview)
- [Hybrid tables](https://docs.snowflake.com/en/user-guide/tables-hybrid)
