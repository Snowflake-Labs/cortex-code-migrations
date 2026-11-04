# SSC-EWI-SSIS0049 — Data Flow Error-Output Path Not Supported

This dbt model stands for a component reached through an SSIS error output (the red line): rows that failed a conversion or a lookup upstream and were redirected. SnowConvert does not translate error outputs, so the model selects **every row** of the upstream component's regular output. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low-moderate (once per error-output path) |
| Common action | Split the upstream rows into a failure branch and a success branch with the same test |

## Identification

After the `config()` block of the error branch's model:

```sql
{{ config(materialized='table', alias='Flat File Connection Manager') }}
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0049 - THIS COMPONENT IS REACHED THROUGH AN SSIS DATA FLOW ERROR-OUTPUT PATH (RED LINE). ERROR OUTPUTS ARE NOT CURRENTLY SUPPORTED BY THE CONVERTER; THE GENERATED DBT MODEL CARRIES THE REGULAR-FLOW COLUMNS AND WILL NOT REFLECT THE SSIS ERROR-REDIRECTION BEHAVIOR. REVIEW THE GENERATED MODEL AND IMPLEMENT THE ERROR-HANDLING BRANCH MANUALLY. ***/!!!
WITH source_data AS
(
   SELECT NAME, SALARY, DEPARTMENT
   FROM {{ ref('int_data_conversion') }}
)
SELECT sd.NAME AS NAME, sd.SALARY AS SALARY, sd.DEPARTMENT AS DEPARTMENT
FROM source_data AS sd
```

In the package, the path starts at an output with `isErrorOut="true"`. The upstream component's columns with `errorRowDisposition="RedirectRow"` (or `truncationRowDisposition="RedirectRow"`) are the ones whose failure sends a row down it.

## Fix Patterns

### Pattern 1: Data Conversion or Derived Column with redirected errors

The failure test is "the value is there but does not convert". Put it in the error model, and its negation in the regular branch, so each row goes one way:

```sql
-- Error branch model (this file)
WITH source_data AS (SELECT * FROM {{ ref('stg_bordereaux') }})
SELECT sd.*,
       CASE WHEN sd.GrossPremium IS NOT NULL AND TRY_TO_NUMBER(sd.GrossPremium, 19, 4) IS NULL THEN 'GrossPremium'
            WHEN sd.PeriodEnd IS NOT NULL AND TRY_TO_DATE(sd.PeriodEnd) IS NULL THEN 'PeriodEnd' END AS ErrorColumn
FROM source_data AS sd
WHERE (sd.GrossPremium IS NOT NULL AND TRY_TO_NUMBER(sd.GrossPremium, 19, 4) IS NULL)
   OR (sd.PeriodEnd IS NOT NULL AND TRY_TO_DATE(sd.PeriodEnd) IS NULL)

-- Regular branch model (the conversion's downstream model): the negation, with the typed values
WHERE NOT ((GrossPremium IS NOT NULL AND TRY_TO_NUMBER(GrossPremium, 19, 4) IS NULL)
        OR (PeriodEnd IS NOT NULL AND TRY_TO_DATE(PeriodEnd) IS NULL))
```

Use the `TRY_` function for the SSIS target type: `DT_CY` / `DT_NUMERIC` → `TRY_TO_NUMBER(x, p, s)`, `DT_DBDATE` → `TRY_TO_DATE`, `DT_DBTIMESTAMP` → `TRY_TO_TIMESTAMP_NTZ`, `DT_DBTIMESTAMPOFFSET` → `TRY_TO_TIMESTAMP_TZ`, `DT_I4` → `TRY_TO_NUMBER(x)` with a range check. A truncation redirect is `LENGTH(x) > n`.

### Pattern 2: Lookup with no-match redirected as an error

`NoMatchBehavior` 0 with `RedirectRow` sends unmatched rows to the error output. Left-join the lookup; unmatched rows go to the failure model, matched rows go on:

```sql
-- Failure model
SELECT s.* FROM {{ ref('int_claim_txn') }} s
LEFT JOIN {{ source('dim', 'DimTransactionType') }} d ON d.TransactionTypeCode = s.TransactionTypeCode
WHERE d.TransactionTypeKey IS NULL
```

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker.
- Change both branches: a failure branch added without filtering the regular branch double-counts the bad rows.
- SSIS `ErrorCode` and `ErrorColumn` are lineage ids with no Snowflake meaning. Synthesize a readable column name (as above) or NULL, and note it.
- Several error outputs merged by a Union All become one `UNION ALL` of the failure selects.
