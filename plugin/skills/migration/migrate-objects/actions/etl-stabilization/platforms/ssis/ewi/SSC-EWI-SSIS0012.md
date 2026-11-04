# SSC-EWI-SSIS0012 — XML Result Set Not Supported

An Execute SQL task has `ResultSetType` XML: SQL Server returned the query result as one XML document (usually from `FOR XML`), and SSIS stored it in a String or Object variable. SnowConvert left the statement as converted, with the marker in front of it, and **did not assign the variable**. Later tasks read its old value. The marker **breaks compilation**. The engine has no test that shows this shape.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Rare (once per Execute SQL task with an XML result binding) |
| Common action | Find what reads the variable; build the value it needs with `SELECT ... INTO` and publish it |

## Identification

```sql
---- Start block 'Package\Get Claims XML'
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0012 - XML RESULT SET TYPE IS NOT SUPPORTED. ONLY SINGLEROW AND FULLRESULTSET RESULT SET TYPES ARE SUPPORTED. ***/!!!
SELECT ...;
```

Emitted only when the task has a result binding and its SQL is one statement. In the `.dtsx`: `SQLTask:ResultType="ResultSetType_XML"` and `<SQLTask:ResultBinding SQLTask:ResultName="0" SQLTask:DtsVariableName="User::ClaimsXml" />`. A `FOR XML` query may also carry the T-SQL marker SSC-EWI-TS0044 (FOR XML clause is not supported). Either way, rewrite it: Snowflake can parse XML (`PARSE_XML`, `XMLGET`) but has no function that generates it.

## Fix Patterns

Start from the consumer: a Script Task, a Send Mail body, a file write, or an XML task that reads `User::ClaimsXml`.

### Pattern 1: The consumer can take JSON

The consumer was rewritten in Snowflake, or only passes the document on to something you control. Build JSON:

```sql
-- After
SELECT ARRAY_AGG(OBJECT_CONSTRUCT('ClaimNo', ClaimNo, 'Status', Status))::VARCHAR
INTO :User_ClaimsXml
FROM claims.Claim
WHERE BatchID = :User_BatchID;
CALL public.UpdateControlVariable('User_ClaimsXml', '<package>', TO_VARIANT(:User_ClaimsXml));
```

### Pattern 2: The XML text itself is needed

An external system expects the document. Build it as a string, and escape `&`, `<` and `>` in each value:

```sql
SELECT '<Claims>' || LISTAGG('<Claim><ClaimNo>' || REPLACE(REPLACE(REPLACE(ClaimNo, '&', '&amp;'), '<', '&lt;'), '>', '&gt;')
                           || '</ClaimNo></Claim>', '') WITHIN GROUP (ORDER BY ClaimNo) || '</Claims>'
INTO :User_ClaimsXml
FROM claims.Claim;
```

Match the element names that `FOR XML PATH('Claim'), ROOT('Claims')` produced. When the shape is hard to reproduce exactly, mark as needs-user with the original query quoted.

### Pattern 3: Nothing reads the variable

Remove the marker and keep the statement only if it has a side effect. Otherwise replace it with `NULL;`.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker.
- Check that the task block declares the variable (`LET User_ClaimsXml VARCHAR := public.GetControlVariableUDF('User_ClaimsXml', '<package>') :: VARCHAR;`) and publishes it with `public.UpdateControlVariable` at the end. Add whichever is missing, as for [SSC-EWI-SSIS0011](SSC-EWI-SSIS0011.md).
- For a full result set, SnowConvert writes `CREATE OR REPLACE TABLE public.SC_RS_<task> AS <query>`. When the consumer is a Foreach loop, that is often the better target than a string.
