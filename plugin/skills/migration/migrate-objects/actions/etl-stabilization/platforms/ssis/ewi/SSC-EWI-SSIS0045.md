# SSC-EWI-SSIS0045 — Character Map New-Column Mode Not Supported

A Character Map column set to "New column" (`usageType="readOnly"` on the input column, with the operation on a new output column such as `Copy of FullName`) was not translated, so the original column passes through and the new column has no operation. **The current engine does not emit this code**: it translates new-column mode, as `UPPER(FullName) AS "Copy of FullName"`. You will only see the marker in output from an older SnowConvert. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Rare (not emitted by the current engine) |
| Common action | Add the new column to the model, computed from the source column |

## Identification

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0045 - SSIS CHARACTER MAP COLUMN 'FullName' USES NEW-COLUMN MODE (USAGETYPE=READONLY). ONLY IN-PLACE MODE (USAGETYPE=READWRITE) IS TRANSLATED. THE ORIGINAL COLUMN PASSES THROUGH UNCHANGED WITHOUT THE CHARACTER MAP OPERATION. ***/!!!
```

It sits at the top of the Character Map's `int_<component>` model. In the `.dtsx` (`componentClassID="Microsoft.CharacterMap"`), the new column is an `<outputColumn>` of the Character Map Output with two properties: `MapFlags` (the operation) and `InputColumnLineageId` (`#{...Columns[FullName]}`, the source column).

## Fix Patterns

### Pattern 1: Add the new column

Keep the original column as it is and add the new one under its SSIS name, in the position the current engine uses (right after its source column):

```sql
-- Before
SELECT
   FullName,
   Score
FROM
   source_data

-- After (MapFlags = 512)
SELECT
   FullName,
   UPPER(FullName) AS "Copy of FullName",
   Score
FROM
   source_data
```

Quote the alias when the SSIS name has spaces or mixed case, and use the same spelling the downstream models and the destination use. For a `MapFlags` other than `512` or `256`, take the expression from [SSC-EWI-SSIS0019](SSC-EWI-SSIS0019.md).

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker.
- The original column must stay unchanged. Only the new column carries the operation.
- One input column can feed several new columns, each with its own `MapFlags`. Add one line for each.
- Re-converting with a current SnowConvert produces this shape automatically.
