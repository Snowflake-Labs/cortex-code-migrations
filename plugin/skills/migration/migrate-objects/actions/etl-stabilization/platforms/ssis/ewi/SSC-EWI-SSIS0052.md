# SSC-EWI-SSIS0052 — Fuzzy Lookup Reference Metadata Cannot Be Parsed

SnowConvert takes the Fuzzy Lookup reference table's columns from the component's `ReferenceMetadataXml` property. This one was missing or unreadable, so it found no columns. Both `SELECT` lists that should hold them are empty: the `lookup_reference` CTE in the `int_<component>` model and the whole `stg_raw__<component>` staging model. The join, scores and copied columns are still generated and refer to reference columns that are not selected. The marker **breaks compilation**, and so do the empty `SELECT`s.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Rare (once per Fuzzy Lookup with unreadable reference metadata) |
| Common action | Fill both empty select lists with the reference columns the lookup uses |

## Identification

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0052 - SSIS FUZZY LOOKUP REFERENCE METADATA CANNOT BE PARSED. LOOKUP COLUMNS ARE OMITTED FROM THE CONVERTED SQL. ***/!!!
--** SSC-FDM-SSIS0024 - ... **
WITH lookup_reference AS
(
   SELECT
   FROM
      {{ ref('stg_raw__fuzzy_lookup') }}
),
...
SELECT
   input_data.CompanyName,
   lookup_reference.CompanyName RefCompanyName,
   lookup_reference.Industry,
   ...
```

```sql
-- models/staging/stg_raw__fuzzy_lookup.sql
SELECT
FROM
   {{ source('raw', 'ReferenceData') }}
```

The reference columns the lookup needs are in the `.dtsx` (`componentClassID="Microsoft.FuzzyLookup"`): each input column's `JoinToReferenceColumn`, and each output column's `CopyFromReferenceColumn`. The table is in `ReferenceTableName` (e.g. `[dbo].[ReferenceData]`). Its full column list is in the table's converted DDL in the project, or in `INFORMATION_SCHEMA.COLUMNS` of the source.

## Fix Patterns

### Pattern 1: Select the referenced columns

```sql
-- stg_raw__fuzzy_lookup.sql, After
SELECT
   RefID,
   CompanyName,
   Industry
FROM
   {{ source('raw', 'ReferenceData') }}

-- int_fuzzy_lookup.sql, lookup_reference CTE, After
WITH lookup_reference AS
(
   SELECT
      RefID,
      CompanyName,
      Industry
   FROM
      {{ ref('stg_raw__fuzzy_lookup') }}
),
```

Include every `JoinToReferenceColumn` and `CopyFromReferenceColumn` plus the table's key, which [SSC-FDM-SSIS0024](SSC-FDM-SSIS0024.md) uses as a tie-break. Use the names as the Snowflake table has them.

### Pattern 2: The reference is not a plain table

The package may use a reference table that a previous step builds or that only exists on the source. In that case, check that `sources.yml` names a table that exists in Snowflake. If it does not, point the staging model at the table that holds the same rows, or write `-- NEEDS-USER: reference table <name> for Fuzzy Lookup '<component>' does not exist in Snowflake` and mark as needs-user.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker. Do **not** remove the SSC-FDM-SSIS0024 comment under it.
- Fix both files. Filling only the CTE still leaves the staging model's `SELECT FROM` invalid.
- After the columns are back, apply the other Fuzzy Lookup markers on the same model, if any: [SSC-EWI-SSIS0038](SSC-EWI-SSIS0038.md) and [SSC-EWI-SSIS0039](SSC-EWI-SSIS0039.md).
