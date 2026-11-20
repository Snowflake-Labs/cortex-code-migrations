# Iceberg target gates (SKILL.md Step 3a)

**Run this only when the workflow targets Iceberg** (`target_table_type=iceberg`, i.e. any
`tables[]` / `defaultTableConfiguration.target.tableType: iceberg`). Skip it for native targets.

## 3a.1 — Source must be fully relational (hard gate)

This migration builds a **new Snowflake-managed Iceberg table from relational data**. It is **not** a
path for data that is already Iceberg. **The source object must be a plain relational table.**

For each source table in the workflow, confirm it is a regular relational table on the source — **not an
Iceberg, external, or catalog-backed table**. Use the source catalog via `query_source` (dialect
examples):

- **SQL Server / Synapse:** `sys.tables` is relational; reject `sys.external_tables`.
- **Redshift:** reject `SVV_EXTERNAL_TABLES` / Spectrum / Glue-Iceberg tables; a `pg_class` / `SVV_TABLE_INFO` base table is relational.
- **Oracle / PostgreSQL / Teradata / DB2 / BigQuery:** reject external / Iceberg / foreign tables; accept ordinary heap/base tables.

**If any source object is Iceberg (or external / catalog-backed), do not continue.** Stop and tell the
user which tables are disqualified and why; do not fall back to `native` silently and do not run the
workflow. Iceberg-source adoption paths (`catalog_link` / `convert_to_managed`) are **out of scope** —
this gate exists specifically to block them.

## 3a.2 — Target must not already be a regular table

Interactive Iceberg tables are **not** deployed first: `table` units skip `scai code deploy`, and the
orchestrator **creates the Iceberg table itself** during this migration. It **owns the target** and
**refuses to replace an existing table** (`IcebergTargetExistsError`), failing closed. Subagent mode
still deploys the table (sandbox migration is native). So the only thing that blocks an interactive
Iceberg run is a pre-existing regular (non-Iceberg) table already sitting at the target FQN —
typically a stale leftover from an earlier native deploy, or a table someone created by hand.

**Run the dedicated check — do not skip it, and do not hand-roll it with `SHOW TABLES`:**

```
check_iceberg_targets(workflow_path="<path from setup>")
```

It reads the workflow's Iceberg targets, probes Snowflake, and classifies each one. The response has an
overall `status` (`ok` | `action_required`), per-table `state`, and the `blocked` list.

- **`state: "ready"`** — the target is missing (the orchestrator creates it) or already Iceberg. Nothing
  to do.
- **`state: "blocked"`** — a regular table already occupies the target FQN. The orchestrator will **not**
  drop it or convert it in place, so the run would fail closed. **Never auto-drop it.**

`status: "ok"` (no `blocked`) → go straight to SKILL.md **Step 4**.

If anything is `blocked`, **surface it and let the user decide** — list the tables and explain the run
can't proceed until the target is clear:

> These target FQNs already hold **regular (non-Iceberg)** tables, so the orchestrator can't create the
> Iceberg tables there (it won't replace an existing table):
>
> - `<db>.<schema>.<t1>`
> - `<db>.<schema>.<t2>`
>
> How would you like to resolve them? (drop/rename a stale table from an earlier native deploy, or point
> the workflow at a fresh target)

Only run a `DROP` if the **user explicitly confirms** a specific table is safe to discard — then
`DROP TABLE IF EXISTS <fqn>;` (or `DROP ICEBERG TABLE IF EXISTS <fqn>;` for a stale Iceberg table).
Re-run `check_iceberg_targets` to confirm `status: "ok"` before continuing.

> If the run fails on an Iceberg target for a different reason (missing `CREATE ICEBERG TABLE` grant,
> external volume not authorized, `baseLocationPrefix` outside the volume), fix that prerequisite from
> [iceberg-setup-reference.md](./iceberg-setup-reference.md) rather than touching the table.
