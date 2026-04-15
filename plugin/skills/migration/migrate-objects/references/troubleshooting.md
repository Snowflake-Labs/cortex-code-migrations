# Troubleshooting Guide

## All Tests Return 0 Rows

**Symptoms:** Every test case returns 0 actual rows when baseline has data.

**Possible causes:**

1. **Wrong schema prefix**
   - Check procedure calls use the correct schema prefix for the target environment
   - Verify the procedure was deployed with the expected prefix

2. **Missing base data**
   - Query the source tables directly to verify data exists:
   ```sql
   SELECT COUNT(*) FROM <SCHEMA>.TableName WHERE <filter>;
   ```

3. **Filter too restrictive**
   - Compare WHERE clauses between source and Snowflake target
   - Check date range parameters — timezone adjustments may exclude all data

4. **Missing dependency**
   - Check if the procedure calls another procedure that returns empty
   - Look for `CALL` statements and verify those procedures work

**Debug steps:**
```sql
-- Run procedure manually with same parameters
CALL <PREFIX><SCHEMA>.ProcedureName(param1 => value1, param2 => value2);

-- Check parameters from test case
SELECT parameters FROM VALIDATION.BASELINES 
WHERE code_unit_name = '<SCHEMA>.Name' AND params_hash = '<hash>';
```

## ERROR: Function/Procedure Not Found

**Symptoms:** `SQL compilation error: Unknown function` or similar.

**Fix:**
1. Find the missing function in the converted output:
   ```bash
   find snowflake/ -iname "*functionname*" -type f
   ```

2. Deploy it first:
   ```bash
   scai code deploy -c <CONNECTION_NAME> --where "source.canonicalName ILIKE '%<functionname>%'"
   ```

3. Then re-run the procedure's tests.

## ERROR: Table/View Not Found

**Symptoms:** `Object does not exist` error.

**Fix:**
1. Check if the object exists in Snowflake:
   ```sql
   SHOW TABLES LIKE '%tablename%' IN SCHEMA <SCHEMA>;
   SHOW VIEWS LIKE '%viewname%' IN SCHEMA <SCHEMA>;
   ```

2. If missing, deploy it:
   ```bash
   scai code deploy -c <CONNECTION_NAME> --where "source.canonicalName ILIKE '%<objectname>%'"
   ```

## ERROR: Invalid Identifier

**Symptoms:** `invalid identifier 'COLUMNNAME'`

**Possible causes:**

1. **Column name case mismatch**
   - Snowflake uppercases unquoted identifiers
   - Check if column should be quoted: `"columnName"` vs `COLUMNNAME`

2. **Column doesn't exist**
   - Verify column exists in the table:
   ```sql
   DESC TABLE <SCHEMA>.TableName;
   ```

3. **Typo in column name**
   - Compare against source database code

4. **Dynamic PIVOT column names have quotes**
   - If error shows `invalid identifier '"ColumnName"'` with mixed quotes
   - This indicates PIVOT column naming issue
   - See "Hardcoded PIVOT Columns" section below

## All Rows Show as Different

**Symptoms:** Row counts match but every row shows as `missing_in_actual` and `extra_in_actual`.

**Possible causes:**

1. **Column ordering differs**
   - The comparison may be order-sensitive
   - Check SELECT list matches baseline column order

2. **Column name case**
   - Baseline may have `ColumnName`, actual has `COLUMNNAME`
   - Use aliases to match: `SELECT col AS "ColumnName"`

3. **Data type formatting**
   - Numbers: `1000` vs `1E+3`
   - Dates: `2024-01-01` vs `2024-01-01T00:00:00`
   - These may be normalization issues

## Small Row Count Differences

**Symptoms:** Baseline has 43 rows, actual has 45 (or similar small difference).

**Debug steps:**

1. **Find the extra/missing rows:**
   ```sql
   SELECT differences FROM VALIDATION.LATEST
   WHERE code_unit_name = 'RPT.Name' AND params_hash = 'abc123';
   ```

2. **Check for filter differences:**
   - Compare WHERE clauses in source vs Snowflake
   - Look for: `IS NOT NULL`, status filters, date ranges

3. **Check for data drift:**
   - Query source tables with the test parameters
   - Compare against baseline capture date if known

## Decimal/Rounding Differences

**Symptoms:** Values like `11.336666` vs `11.336667` (1 in last digit).

**Cause:** Some source databases (e.g., SQL Server) use banker's rounding, Snowflake uses standard rounding.

**Resolution:**
- If difference is always ≤1 in the last decimal place, use `MANUAL_PASS`
- Flag for normalization if this affects many procedures
- Consider reducing precision in the cast if business doesn't need 6 decimals

## Timestamp Differences

**Symptoms:** Dates off by hours, or different precision.

**Common causes:**

1. **Timezone offset**
   - Source GETDATE()/GETDATE()-equivalent may be in local time
   - Snowflake CURRENT_TIMESTAMP() may be UTC
   - Check timezone adjustment functions

2. **Precision differences**
   - Source: `2024-01-22 00:00:00`
   - Snowflake: `2024-01-22T00:00:00.000000`
   - May be formatting issue (flag for normalization)

## Connection Errors

**Symptoms:** Cannot connect to Snowflake.

**Fix:**
1. Verify connection config:
   ```bash
   snow connection test -c <CONNECTION_NAME>
   ```

2. Check `~/.snowflake/connections.toml` has correct settings

3. If using key-pair auth, verify private key path and permissions:
   ```bash
   ls -la ~/.ssh/rsa_key.p8
   ```

## Test Runner Errors

**Symptoms:** `scai test capture` or `scai test validate` fails.

**Fix:**
1. Verify a scai project is initialized:
   ```bash
   scai project info
   ```

2. Verify test YAML files exist:
   ```bash
   ls <project_dir>/artifacts/**/test/*.yml
   ```

3. Verify the Snowflake connection works:
   ```bash
   snow connection test -c <CONNECTION_NAME>
   ```

4. Verify the source connection works:
   ```bash
   scai connection test -l <sqlserver|redshift> -c <CONNECTION_NAME>
   ```

## Deploy Errors

**Symptoms:** Deployment fails with syntax error.

**Debug:**
1. Read the SQL file and check for obvious syntax issues:
   ```bash
   # View the file that failed
   cat snowflake/<type>/<schema>/<objectname>.sql
   ```

2. Check for Snowflake-incompatible syntax in the file

3. Look for SnowConvert EWI comments (`--** SSC-`) that indicate unresolved conversion issues

4. Try deploying directly to see the full error:
   ```bash
   scai code deploy -c <CONNECTION_NAME> --where "source.canonicalName ILIKE '%<objectname>%'"
```
