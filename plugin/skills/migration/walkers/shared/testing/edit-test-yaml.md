# Edit Test YAML — Cookbook

Fix a test whose `steps:` do not match the proc (not a SQL bug). Edit `<project_dir>/<files.artifacts>/test/<Name>.yml`
(`files.artifacts` verbatim), `steps:` only — never delete a `test_cases:` row
([generate-test-cases §7](generate-test-cases.md#7-cover-vacuous-rows-once) adds rows beside vacuous ones). Then recapture with
`walk_run(op="capture")` per [capture-baseline.md](capture-baseline.md), not a `scai test capture` shell. Keys:
[step-based-yaml.md](step-based-yaml.md).
```yaml
validation:
  steps:
    - source_query: EXECUTE ${defaultdb}.dbo.GetOrders @Region = {0}
      target_query: CALL <%defaultdb%>.dbo.GetOrders(REGION => {0})
  test_cases: [['West']]   # one row per case
```

## Multi-result-set validation

N source result sets, target `RETURNS ARRAY` (SSC-FDM-0020): "baseline=N actual=1", "Dataframe dimensions
mismatch". SQL Server source only. On the CALL step, one entry per source result set, in order, 0-based (all sets
in one table with `_RESULT_SET_ID` → `- target_query: "SELECT … WHERE _RESULT_SET_ID = N"` entries instead):
```yaml
      validate:
        - array_index: 0
        - array_index: 1      # `- false` skips a set
```

## OUT / INOUT parameter comparison

The OUT slot's row value is a placeholder (`""` / `0`). Redshift: no `DECLARE`; compare `source_params: ["name"]`.
```yaml
    - {source_query: "DECLARE @Name VARCHAR(100) = {1}", target_query: "LET NAME STRING := {1}", validate: false}
    - source_query: EXECUTE ${defaultdb}.dbo.GetProduct @ID = {0}, @Name = @Name OUTPUT
      target_query: CALL <%defaultdb%>.dbo.GetProduct({0}, :NAME)
      validate: false
    - {source_params: ["@Name"], target_params: ["NAME"]}
```

## Table-read assertion

`validate: false` on the CALL, then `- table: MyDB.dbo.OrderSummary`, or `- both: "SELECT … WHERE Region = {0}"`
to filter. A `#temp` table: name it literally in SQL.

## Side-effect-only DML

"No rows captured": `validate: false` on the CALL, then `- both: "SELECT … WHERE Name = {0}"` post-conditions.
Set `modifies_data` / `affected_tables` only when CUR's inference is wrong.

## Cursor-read step

Redshift only: `validate: false` on the CALL, then `- cursor: result_cursor`. One open cursor at a time.

## Redshift scalar INOUT aliasing

```yaml
    - source_query: CALL mydb.dbo.calc_result({0}, 0)
      target_query: "BEGIN LET out_var NUMERIC := 0; CALL MyDB.dbo.CalcResult({0}, :out_var); RETURN :out_var; END;"
      validate: [{target_query: 'SELECT "ANONYMOUS BLOCK" AS P_RESULT FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))'}]
```

## Teradata cross-database GRANTs

Source error 5315: [`teradata.md`](../../../migrate-objects/baseline-capture/synthetic-seeder/platforms/teradata.md).
Oracle: [`oracle.md`](../../../migrate-objects/baseline-capture/synthetic-seeder/platforms/oracle.md).
