# SSC-EWI-SSIS0009 — Unexpected Exception Converting Component

SnowConvert hit an internal error while translating a data flow component, so the component's dbt model is a placeholder. It has the right name and the upstream `ref()`s, but none of the component's logic, and its column list holds pass-through names or `null AS <col>` (empty when the component has no output columns). The marker **breaks compilation**. The exception message is not in the marker; it is only in the conversion log.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Rare (a converter defect, not an unsupported feature) |
| Common action | Rebuild the model from the component's definition in the `.dtsx` |

## Identification

At the top of the component's model, after the `config` block:

```sql
{{ config(
    tags=['DFT']
) }}
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0009 - UNEXPECTED EXCEPTION CONVERTING COMPONENT. ***/!!!
WITH derived_column AS
(
   SELECT CURRENT_TIMESTAMP() AS DepreciatedAt, TaskID, Title, Status, CreatedAt
   FROM {{ ref('stg_raw__tasks_source') }}
)
SELECT
FROM
   {{ ref('int_package_dft_derived_column') }}
```

Here a destination's translation failed after an upstream Derived Column was folded into it: the `SELECT` has no columns. Find the component under `<pipeline><components>` by the `refId` (`Package\<Data Flow>\<Component>`) of the model's component. Its `componentClassID`, `<properties>`, `<inputColumns>` and `<outputColumns>` describe what it did. To see why the converter failed, look for `Exception generating dbt model from element <name>` in the SnowConvert log.

## Fix Patterns

### Pattern 1: Rebuild the component's SQL

Write the model as SnowConvert writes that component type elsewhere in the project. Use another model of the same type as a template if there is one. Keep the model name, since downstream models `ref()` it. Check that every `ref()` in the placeholder names a model that exists: an upstream component folded into this model, like `derived_column` above, has no model of its own. Read from the CTE instead:

```sql
-- After: the destination writes the derived column's rows
{{ config(tags=['DFT']) }}
WITH derived_column AS
(
   SELECT CURRENT_TIMESTAMP() AS DepreciatedAt, TaskID, Title, Status, CreatedAt
   FROM {{ ref('stg_raw__tasks_source') }}
)
SELECT TaskID, Title, Status, CreatedAt, DepreciatedAt
FROM derived_column
```

For a destination, the columns are the ones mapped in its `<inputColumns>` to the external columns, in the target table's order. For a transform, use its `<outputColumns>`, with each expression taken from the component's properties.

### Pattern 2: The component is too involved to rebuild with confidence

Keep the placeholder so downstream models still compile, give it a valid column list (`null AS <col>` for each output column), remove the marker, and add `-- NEEDS-USER: <component> (<componentClassID>) failed to convert; logic not reproduced`. Mark as needs-user.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker; an empty `SELECT` list must be filled before it compiles.
- When a whole Data Flow task fails, the ETL report lists each of its components with SSC-EWI-SSIS0009 and status NotSupported. No model has the marker, and the data flow's models may be missing; rebuild them from the `.dtsx` the same way.
- Same placeholder shape as an unsupported component: [SSC-EWI-SSIS0001](SSC-EWI-SSIS0001.md). The cause is different, though: the component type is supported, and the failure is worth reporting as a converter bug.
- A second destination to the same table may show [SSC-EWI-SSIS0010](SSC-EWI-SSIS0010.md) when the first one failed this way.
