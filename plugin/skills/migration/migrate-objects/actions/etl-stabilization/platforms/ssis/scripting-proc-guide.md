# SSIS Data-Flow Procedure Guide (Snowflake Scripting)

How an SSIS data flow looks after `code convert --ssis-to-snowflake-scripting`, and what
[proc-test-gen](../../proc-test-gen/SKILL.md) and [proc-fixer](../../proc-fixer/SKILL.md) do differently
for it than for an Informatica mapping procedure. To read the `.dtsx` itself (components, columns,
expressions, paths), use [dataflow-guide.md](dataflow-guide.md). For what each component does, use
[element-types.md](element-types.md).

## Contents
- [Unit shape](#unit-shape)
- [Procedure shape](#procedure-shape)
- [Locating and editing a component](#locating-and-editing-a-component)
- [Deploy and CALL](#deploy-and-call)
- [SSIS semantics for the seed and the expected target](#ssis-semantics-for-the-seed-and-the-expected-target)
- [SSIS expressions in SQL](#ssis-expressions-in-sql)

## Unit shape

One SSIS package is one `kind=etl` unit, `snowflake/_etl/<Package>/`:

| File | Holds |
|------|-------|
| `<Package>.sql` | The control flow: one `CREATE OR REPLACE TASK` per executable (`public.package`, `public.package_data_flow_task`, …). Tested and fixed by the orchestration pair. |
| `<Data_Flow>.sql` | One `CREATE OR REPLACE PROCEDURE` per data flow that needs one. Tested and fixed by proc-test-gen and proc-fixer. |

The procedure is named after the data flow, with spaces as underscores (`Data Flow Task` →
`public.Data_Flow_Task`). A package converted with a scoped name prefixes it
(`public.<Package>_Data_Flow_Task`). It is **not** named `m_<mapping>`. The scan links the
task to the proc through its `CALL` (`linked_mapping_proc` in `scan.json`):

```sql
CREATE OR REPLACE TASK public.package_data_flow_task
WAREHOUSE=DUMMY_WAREHOUSE
AFTER public.package
AS
BEGIN
   LET scope VARCHAR := 'Package';
   CALL public.Data_Flow_Task(:scope);
END;
```

A data flow that is a single direct relational load (source → destination, nothing in between) gets
no procedure. It is folded into the task as an `INSERT ... SELECT` between `---- Start block` /
`---- End block` markers. That one belongs to the orchestration pair, not to a `dataflow-proc` phase.

## Procedure shape

```sql
CREATE OR REPLACE PROCEDURE public.Data_Flow_Task (scope VARCHAR)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS CALLER
AS
$$
   BEGIN
      INSERT INTO dbo.DeprecatedTasks (TaskId, DeprecatedAt)   -- OLE DB Destination
      WITH cte_ole_db_source AS                                -- OLE DB Source
      (
         SELECT TaskId, DepreciatedAt FROM dbo.Tasks
      ),
      cte_derived_column AS                                    -- Derived Column
      (
         SELECT ..., <expression> AS <new column> FROM cte_ole_db_source
      )
      SELECT TaskId, DepreciatedAt AS DeprecatedAt FROM cte_derived_column;
   END
$$;
```

- **One CTE per component**, named `cte_<component name>` (lower case, spaces and punctuation as
  underscores), chained in data-flow path order. The final `SELECT` feeds the destination.
- **The destination is the `INSERT INTO <table> (<columns>)`.** Its column list comes from the
  destination's external metadata columns. Each input column maps to an external column by
  `externalMetadataColumnId`, and that is where SSIS renames a column. A lost rename there (the
  final `SELECT` projects the source name where the target expects another) is a common defect,
  and the proc then fails to CREATE or inserts into the wrong column.
- **There are no block markers inside the procedure.** `block-locate` finds nothing in it, and
  `block-replace` cannot splice into it. Work by CTE instead (next section).
- **An unsupported component** becomes a CTE stub: a `!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0001 ... ***/!!!`
  line before it, the component's DTSX XML as `--` comments inside it, and a `SELECT null AS <col>, ...`
  projection. The commented XML carries the component's `refId` (`Package\Data Flow Task\<Component>`),
  its properties and its incoming `<path>`: read it, then the same component in the `.dtsx`.
- **Variables** are read with `LET <v> := <schema>.GetControlVariableUDF(<name>, :scope)`, from the
  `control_variables` table the orchestration infrastructure creates. Seed the rows the proc reads
  under the scope you will pass to `CALL`.

## Locating and editing a component

| Step | How, for an SSIS data-flow proc |
|------|-------|
| Find the defective components | `stabilization_tools.py ewi-extract <proc.sql> --json` (EWI markers) and `stabilization_tools.py stub-detect <proc.sql> --json` (all-NULL placeholders; each hit names its `cte`) |
| Map a CTE to its source | the `refId` in the CTE's commented XML, else match the CTE name to the component `name` in the `.dtsx` |
| Map a CREATE/CALL error to a component | the error's line number → the enclosing `cte_<name>` (`task-error-locate` needs block markers, so it does not apply) |
| Apply the fix | edit that CTE in place: replace the `!!!RESOLVE EWI!!!` line, the commented XML and the `null AS` projection with working SQL. Keep the CTE name, its position in the chain and the column names later CTEs read |
| Check the edit | rerun `ewi-extract` and `stub-detect` on the file: no hit may remain in the CTE you fixed |

Keep the `INSERT INTO` column list and the final `SELECT` column order as they are, except to fix a
lost destination mapping, which you confirm against the destination's `<inputColumn ... externalMetadataColumnId>`
entries in the `.dtsx`.

## Deploy and CALL

Pass the scope the task passes: the value of its `LET scope VARCHAR := '<scope>'` (usually the package name).

```bash
scai code deploy-and-call -c <conn> -d <db> --schema <test_schema> \
  --proc-file <UNIT>/Data_Flow_Task.sql --call "CALL public.Data_Flow_Task('Package')"
```

The procedure writes to the destination table named in its `INSERT INTO`. Create that table and the
source tables in the test schema with the schema qualifiers the procedure uses (`dbo.Tasks` →
create schema `dbo` in the test database, or the qualifier the deploy maps it to). Read the
column types from the `.dtsx` external metadata (see
[dataflow-guide.md](dataflow-guide.md#ssis-data-types-to-seed-values)).

## SSIS semantics for the seed and the expected target

Compute the expected target from these rules applied to the seed. Never from the converted SQL.

- **OLE DB / ADO.NET Source**: the `SqlCommand` (or the table in `OpenRowset`) is the input. A source
  query with a `WHERE` already filters.
- **Derived Column**: every expression reads the component's *input* values, not another derived column
  of the same component. Each output either adds a column ("<add as new column>") or replaces an input
  column of the same lineage ("Replace '<col>'").
- **Data Conversion**: adds a converted copy (`Copy of <col>` by default) and keeps the original.
- **Lookup**: matches on the joined columns, and returns the first match only, so it never fans out. A
  full-cache Lookup compares case-sensitively and counts trailing spaces. When nothing matches, what
  happens depends on `NoMatchBehavior` and the error disposition. If the error is ignored, the row goes
  on with NULL lookup columns (a `LEFT JOIN`). If it is redirected to a no-match or error output that
  is not wired to this destination, the row is dropped. If the component fails, the whole data flow
  fails. Seed both a matching and a non-matching key, and expect what the package's setting says.
- **Conditional Split**: the conditions are tried in `Order`, and a row goes to the first one that is
  true. A row that matches none goes to the default output. Only the output wired to this destination
  reaches the target.
- **Merge Join**: `JoinType` 0 is full outer, 1 is left outer, 2 is inner. **Union All** and **Merge**
  keep duplicates. **Multicast** sends every row to every output.
- **Sort**: with `EliminateDuplicates`, one row per sort key. Which duplicate survives isn't pinned:
  assert on the key, not on non-key columns of a duplicate group. A table has no row order, so never
  assert on order.
- **Aggregate**: group by the columns whose `AggregationType` is group-by, and apply each output's
  aggregate. With no group-by column, the whole input is one group.
- **Row Count**: sets a variable. The rows pass through unchanged.

## SSIS expressions in SQL

| SSIS expression | Snowflake |
|---|---|
| `cond ? a : b` | `IFF(cond, a, b)` |
| `ISNULL(x)` | `x IS NULL` |
| `==`, `!=`, `&&`, `\|\|`, `!` | `=`, `<>`, `AND`, `OR`, `NOT` |
| `(DT_WSTR, n) x`, `(DT_STR, n, 1252) x` | `x::VARCHAR(n)` |
| `(DT_I4) x`, `(DT_NUMERIC, p, s) x` | `x::INT`, `x::NUMBER(p, s)` |
| `(DT_DBTIMESTAMP) x`, `(DT_DBDATE) x` | `x::TIMESTAMP_NTZ`, `x::DATE` |
| `GETDATE()` | `CURRENT_TIMESTAMP()` |
| `SUBSTRING(s, start, len)` | `SUBSTRING(s, start, len)` (both start at 1) |
| `FINDSTRING(s, sub, n)` | `REGEXP_INSTR(s, <escaped sub>, 1, n)` |
| `REPLACENULL(x, y)` | `COALESCE(x, y)` |
| `@[User::Var]` | the `LET` variable the procedure reads from `control_variables` |
