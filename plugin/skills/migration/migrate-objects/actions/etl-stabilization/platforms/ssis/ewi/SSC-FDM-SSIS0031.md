# SSC-FDM-SSIS0031 — Output Column Renamed for a Name Collision

A Derived Column added a **new** column whose name is already used by an input column (SSIS tells them apart by lineage ID, so both live in the buffer). SQL cannot have two columns with one name, so SnowConvert renamed the new one to `<Component_Name>_<Column>` (with `_2`, `_3`, ... if that is taken too) and followed each lineage downstream: every later model, and the destination mapping, reads the column it meant. The FDM is informational.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Low (once per renamed column) |
| Common action | No code change; check custom code that names the column |

## Identification

At the top of the Derived Column's model:

```sql
--** SSC-FDM-SSIS0031 - SSIS OUTPUT COLUMN 'SALARY' WAS RENAMED TO 'Derived_Column_SALARY' TO PRESERVE COLUMNS WITH DISTINCT LINEAGE. **
WITH source_data AS
( SELECT NAME, SALARY, DEPARTMENT FROM {{ ref('stg_raw__ole_db_source') }} )
SELECT
   1000 AS Derived_Column_SALARY,
   NAME AS NAME,
   SALARY AS SALARY,
   DEPARTMENT AS DEPARTMENT
FROM source_data
```

Downstream, a destination fed by the new column maps it back to the target column (`sd.Derived_Column_SALARY :: VARCHAR(100) AS TXT`); one fed by the original reads `SALARY`. In the `.dtsx`, the new column is an `outputColumn` of the Derived Column with the same `name` as an `inputColumn` but its own `lineageId`; each downstream `inputColumn` says which one it uses through `lineageId`.

## Fix Patterns

### Pattern 1: No change (most common)

Generated models already use the renamed column where the package used the new lineage. Leave the comment.

### Pattern 2: Hand-written code names the column

Code written later by hand (a test, a seed, a fixed-up Script Component model, a reconciliation query) that says `SALARY` while meaning the derived value must say `Derived_Column_SALARY`. Check by lineage in the `.dtsx`, not by name.

## Key Points

- Do **NOT** remove the FDM comment.
- The renamed column never reaches a target table under its new name: destinations map by lineage to the target column. A target column named `Derived_Column_...` is a mapping bug; check the destination input column's `externalMetadataColumnId` in the `.dtsx`.
- Expressions in later components that reference the new lineage are translated with the new name; an unconverted one ([SSC-EWI-SSIS0002](SSC-EWI-SSIS0002.md)) shows the SSIS name `[SALARY]` and needs the right one picked by lineage.
