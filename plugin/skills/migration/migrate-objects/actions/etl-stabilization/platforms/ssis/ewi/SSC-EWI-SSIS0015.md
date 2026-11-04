# SSC-EWI-SSIS0015 — Send Mail File Attachments Not Supported

A Send Mail task had `FileAttachments`. `SYSTEM$SEND_EMAIL` has no attachment argument, so SnowConvert generated the `CALL SYSTEM$SEND_EMAIL(...)` without them; the attachment paths appear nowhere in the generated code. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (once per Send Mail task with attachments) |
| Common action | Unload the attachment to a stage and mail a presigned link, or put a small file's text in the body; needs-user when the file lives outside Snowflake |

## Identification

Above the `CALL`, after the integration block, often chained with [SSC-EWI-SSIS0016](SSC-EWI-SSIS0016.md) on the same line:

```sql
   END;
   !!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0015 - SNOWFLAKE'S SYSTEM$SEND_EMAIL DOES NOT SUPPORT FILE ATTACHMENTS. CONSIDER USING STAGED FILES WITH SHARED LINKS OR ALTERNATIVE DELIVERY METHODS. ***/!!!
   --** SSC-FDM-SSIS0008 - ... **
   CALL SYSTEM$SEND_EMAIL('send_mail_with_attachments_Send_Email_With_Attachment', 'noreply@test.com,admin@example.com', 'Report with attachments', 'Email sent by: noreply@test.com

Please see attached files.');
```

The paths are in the `.dtsx`: the `FileAttachments` attribute of `<SendMailTaskData>` in the task's `<DTS:ObjectData>` (SSIS separates several files with `|`), or a `<DTS:PropertyExpression DTS:Name="FileAttachments">` on the task. Find which earlier task writes each file (a Data Flow flat-file destination, a File System task, a Script task).

## Fix Patterns

### Pattern 1: The package produced the attachment (an extract, a report)

Write the same data to a stage and mail a presigned link:

```sql
COPY INTO @public.mail_stage/dq/dq_summary.csv
FROM (SELECT * FROM dq.summary)
FILE_FORMAT = (TYPE = CSV, COMPRESSION = NONE) HEADER = TRUE SINGLE = TRUE OVERWRITE = TRUE;
LET link STRING := '';
SELECT GET_PRESIGNED_URL(@public.mail_stage, 'dq/dq_summary.csv', 86400) INTO :link;
LET body STRING := 'The DQ summary is available for 24 hours at: ' || :link;
CALL SYSTEM$SEND_EMAIL('pkg_Send_DQ', 'etl-support@example.com', 'DQ summary', :body);
```

A presigned URL lets anyone holding it download the file until it expires (`expiration_time` in seconds, default 3600). An internal stage must use `ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE')`, or the downloaded file is unreadable. If no such stage exists, or the data is sensitive, add a `-- NEEDS-USER:` comment and mark as needs-user.

### Pattern 2: A small text attachment (an error log)

When the attachment is a log the package wrote, the same rows are usually in a Snowflake table now. Put them in the body:

```sql
LET body STRING := '';
SELECT LISTAGG(ErrorTime || ' ' || SourceName || ': ' || ErrorDescription, '\n') WITHIN GROUP (ORDER BY ErrorTime)
  INTO :body FROM etl.ErrorLog WHERE RunId = :User_RunId;
body := COALESCE(NULLIF(:body, ''), 'No errors were logged.');
CALL SYSTEM$SEND_EMAIL('pkg_Send_Errors', 'etl-support@example.com', 'Load errors', :body);
```

`SYSTEM$SEND_EMAIL` rejects an empty body, hence the fallback.

### Pattern 3: The file comes from outside the package (a share, a fixed document)

Snowflake cannot read `C:\...` or `\\server\...` paths. Remove the marker, keep the `CALL`, add `-- NEEDS-USER: attachment <path> is not sent; land it in a stage (then Pattern 1) or confirm it can be dropped`, and mark as needs-user.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker. When it is chained with another marker on the same line, remove only this one.
- The mail goes out without the attachment, not with an error: do not leave the marker's removal as the whole fix unless the attachment was confirmed unnecessary.
- `SYSTEM$SEND_SNOWFLAKE_NOTIFICATION` has no attachments either.
- See [SSC-FDM-SSIS0007](SSC-FDM-SSIS0007.md) for the per-run integration DDL and [SSC-FDM-SSIS0008](SSC-FDM-SSIS0008.md) for the From address in the recipients.
