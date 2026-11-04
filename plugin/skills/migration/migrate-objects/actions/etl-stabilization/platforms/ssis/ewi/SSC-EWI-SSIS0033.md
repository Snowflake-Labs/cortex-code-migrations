# SSC-EWI-SSIS0033 — Excel Source SQL Command Not Applied

The Excel Source used access mode 2 (SQL command): a Jet/ACE query such as `SELECT ... FROM [Sheet$] WHERE ...`. SnowConvert does not translate it. The model reads the whole sheet named by the component's `OpenRowset` (`Sheet1` when empty) through `excel_source_udf`, and selects the component's output columns by name, so filters, joins, aggregates and computed columns are lost. The marker **breaks compilation**. Only the Excel Source emits it.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low-moderate (once per Excel Source in SQL command mode) |
| Common action | Fix the sheet argument, then add the query's logic as CTEs after `parsed_data` |

## Identification

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0033 - EXCEL SOURCE USES SQL COMMAND ACCESS MODE WITH QUERY: 'SELECT Region, SUM(Amount) AS Total FROM [Sales$] WHERE [Year] = 2024 GROUP BY Region'. THE GENERATED MODEL READS THE FULL SHEET VIA UDF WITHOUT APPLYING THE ORIGINAL SQL FILTERING, JOINS, OR AGGREGATION LOGIC. ADD THE EQUIVALENT FILTERING AS DOWNSTREAM CTES IN THE DBT MODEL. ***/!!!
WITH excel_raw_data AS
(
   SELECT data
   FROM TABLE(excel_source_udf('@public.landing_stage/ssis/<Package>/sales.xlsx', 'Sheet1', 'YES'))
),
parsed_data AS
(
   SELECT data['Region'] :: VARCHAR AS Region, TRY_TO_DOUBLE(data['Total'] :: VARCHAR) AS Total
   FROM excel_raw_data
)
SELECT * FROM parsed_data
```

The query is quoted in the marker and in the component's `SqlCommand` property. With `?` placeholders, [SSC-EWI-SSIS0029](SSC-EWI-SSIS0029.md) is also present.

## Fix Patterns

### Pattern 1: Rebuild the query over the sheet's columns

1. Set the sheet argument to the query's `FROM [Sales$]` (`'Sales'`).
2. In `parsed_data`, read the sheet's own header names, not the query's aliases: `data['Total']` above does not exist in the sheet and is always NULL.
3. Add the query as a CTE and keep the output column names and types the downstream models expect.

```sql
WITH excel_raw_data AS
( SELECT data FROM TABLE(excel_source_udf('@public.landing_stage/ssis/<Package>/sales.xlsx', 'Sales', 'YES')) ),
parsed_data AS
(
   SELECT data['Region'] :: VARCHAR AS Region,
          TRY_TO_DOUBLE(data['Amount'] :: VARCHAR) AS Amount,
          TRY_TO_DOUBLE(data['Year'] :: VARCHAR) AS Year
   FROM excel_raw_data
),
query_result AS
( SELECT Region, SUM(Amount) AS Total FROM parsed_data WHERE Year = 2024 GROUP BY Region )
SELECT * FROM query_result
```

| Jet / ACE SQL | Snowflake |
|---|---|
| `[Sheet$]`, `[Sheet$A1:D100]` | the sheet argument `'Sheet'`, `'Sheet!A1:D100'` |
| `[Column Name]` | `data['Column Name']` in `parsed_data` |
| `IIF(c, a, b)` | `IFF(c, a, b)` |
| `a & b` | `a \|\| b` |
| `TOP n` | `LIMIT n` |
| text `=` (case-insensitive) | `UPPER(a) = UPPER(b)` when case varies |

### Pattern 2: Query joins another sheet or workbook

Read each sheet with its own `excel_source_udf` CTE and join the parsed CTEs. A second workbook needs its own staged file; if it is not landed anywhere, add `-- NEEDS-USER: stage <file>` and mark needs-user.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker.
- `data['...']` keys are case-sensitive and must match the header cell exactly, spaces included.
- `SELECT *` queries with only a `WHERE` need just step 1 and the filter.
- The original query is also recorded in the assessment report as `Original SQL Command`.
