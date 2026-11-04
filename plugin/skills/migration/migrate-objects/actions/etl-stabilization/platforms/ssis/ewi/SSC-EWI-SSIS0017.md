# SSC-EWI-SSIS0017 — Send Mail Body From a File Connection Not Supported

A Send Mail task's `MessageSourceType` was File Connection: SSIS read the body from a file. SnowConvert does not read the file; it passes the task's `MessageSource` value as the body, which for this type is the File connection manager's reference, not the file's text. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (once per Send Mail task whose body comes from a file) |
| Common action | Replace the body with the file's text, or build it in Snowflake from the data the file held |

## Identification

Above the `CALL`, after the integration block, with the other Send Mail markers:

```sql
   END;
   !!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0017 - LOADING EMAIL BODY FROM A FILE CONNECTION IS NOT SUPPORTED. THE MESSAGE SOURCE MUST BE DIRECT INPUT OR FROM A VARIABLE. ***/!!!
   --** SSC-FDM-SSIS0008 - ... **
   CALL SYSTEM$SEND_EMAIL('pkg_Send_Summary', 'noreply@test.com,etl-support@example.com', 'Nightly summary', 'Email sent by: noreply@test.com

<MessageSource value>');
```

The body's last part is the task's `MessageSource` attribute (on `<SendMailTaskData>` in `<DTS:ObjectData>`): the name or `{GUID}` of a File connection manager. Look it up in the package's `<DTS:ConnectionManagers>` or the project's `.conmgr` files: its `DTS:ConnectionString` is the file path, and a `<DTS:PropertyExpression DTS:Name="ConnectionString">` on it means the path changes per run. Then find whether the file is static (a template in the source tree) or written by an earlier task.

## Fix Patterns

### Pattern 1: A static template file

Put the file's text in the literal, doubling any `'`, and keep the `Email sent by:` line if [SSC-FDM-SSIS0008](SSC-FDM-SSIS0008.md) added one:

```sql
CALL SYSTEM$SEND_EMAIL('pkg_Send_Summary', 'etl-support@example.com', 'Nightly summary', 'Email sent by: noreply@test.com

The nightly load finished. Check the dashboard for today''s counts.');
```

If the file is not in the source tree, add `-- NEEDS-USER: body text from <path> is missing`, and mark as needs-user.

### Pattern 2: An earlier task wrote the file

The rows that went into the file are in a Snowflake table or model now. Build the body from them:

```sql
LET body STRING := '';
SELECT LISTAGG(TableName || ': ' || RowCount, '\n') WITHIN GROUP (ORDER BY TableName)
  INTO :body FROM etl.LoadSummary WHERE RunId = :User_RunId;
body := 'Email sent by: noreply@test.com\n\n' || COALESCE(NULLIF(:body, ''), 'No tables were loaded.');
CALL SYSTEM$SEND_EMAIL('pkg_Send_Summary', 'etl-support@example.com', 'Nightly summary', :body);
```

If the file itself lands in a stage, read its lines with a file format that does not split fields (`TYPE = CSV, FIELD_DELIMITER = NONE`): `SELECT LISTAGG($1, '\n') WITHIN GROUP (ORDER BY METADATA$FILE_ROW_NUMBER) INTO :body FROM @public.landing_stage/mail/ (FILE_FORMAT => 'public.ff_whole_line') WHERE METADATA$FILENAME = 'mail/body.txt';` (name the file in the `WHERE`: a stage path is a prefix, so `.../body.txt` also reads `body.txt.bak`).

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker, and replace the connection reference in the body.
- `SYSTEM$SEND_EMAIL` rejects an empty body: keep a fallback text.
- `MessageSourceType` Variable gets no marker, but the body is still the `MessageSource` value as written (`User::MailBody`), not the variable's value: replace it with `:User_MailBody` as in [SSC-FDM-SSIS0007](SSC-FDM-SSIS0007.md) Pattern 3.
- A stage path needs the stage to exist: see [SSC-EWI-SSIS0024](SSC-EWI-SSIS0024.md).
