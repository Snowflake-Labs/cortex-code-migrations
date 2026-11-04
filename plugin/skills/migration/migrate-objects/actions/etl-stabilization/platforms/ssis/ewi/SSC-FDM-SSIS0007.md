# SSC-FDM-SSIS0007 — Send Mail SMTP Connection Not Applicable

A Send Mail task became `CALL SYSTEM$SEND_EMAIL(...)` through a notification integration. The task's SMTP connection (server, port, SSL, credentials) has no meaning in Snowflake, which delivers the mail itself. The FDM needs no change of its own, but the same task has two things worth checking: the integration is created on every run, and the task's property expressions were dropped.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Low (once per Send Mail task with an SMTP connection) |
| Common action | No change for the SMTP settings; check the per-run integration DDL and the dropped property expressions |

## Identification

Look for the marker:
```
--** SSC-FDM-SSIS0007 - CUSTOM SMTP SERVER SETTINGS ARE NOT APPLICABLE. SNOWFLAKE MANAGES EMAIL DELIVERY THROUGH THE NOTIFICATION INTEGRATION. **
```

```sql
BEGIN
   LET pkg_Send_Email_integration_sql STRING := 'CREATE OR REPLACE NOTIFICATION INTEGRATION pkg_Send_Email
  TYPE=EMAIL
  ENABLED=TRUE
  ALLOWED_RECIPIENTS=(''noreply@test.com'', ''admin@example.com'')';
   EXECUTE IMMEDIATE :pkg_Send_Email_integration_sql;
END;
--** SSC-FDM-SSIS0007 - CUSTOM SMTP SERVER SETTINGS ARE NOT APPLICABLE. SNOWFLAKE MANAGES EMAIL DELIVERY THROUGH THE NOTIFICATION INTEGRATION. **
--** SSC-FDM-SSIS0008 - ... **
CALL SYSTEM$SEND_EMAIL('pkg_Send_Email', 'noreply@test.com,admin@example.com', 'Test Email', 'Email sent by: noreply@test.com

Testing all features.');
```

## Fix Patterns

### Pattern 1: SMTP settings only (the FDM itself)

No code change. Leave the comment.

### Pattern 2: The integration is created on every run

`CREATE OR REPLACE NOTIFICATION INTEGRATION` needs the `CREATE INTEGRATION` privilege (usually `ACCOUNTADMIN`), which the role running the task graph rarely has. Move the DDL out of the task into one-time setup, keep only the `CALL`, and mark as needs-user so an admin creates the integration:

```sql
-- NEEDS-USER: an admin runs once:
-- CREATE NOTIFICATION INTEGRATION pkg_Send_Email TYPE=EMAIL ENABLED=TRUE ALLOWED_RECIPIENTS=('etl-support@example.com');
CALL SYSTEM$SEND_EMAIL('pkg_Send_Email', 'etl-support@example.com', :User_MailSubject, :User_MailBody);
```

### Pattern 3: The task had property expressions

SnowConvert writes the task's design-time `ToLine`, `Subject` and `MessageSource` as literals and drops their expressions with no marker. Check the package for `<DTS:PropertyExpression>` on the Send Mail task. Rebuild each one as a variable or expression and pass it to `SYSTEM$SEND_EMAIL` (it takes bind variables):

```sql
-- SSIS: MessageSource = @[User::MailBody] == "" ? "No exceptions were recorded." : @[User::MailBody]
CALL SYSTEM$SEND_EMAIL('pkg_Send_Email', 'etl-support@example.com', :User_MailSubject,
                       IFF(:User_MailBody = '', 'No exceptions were recorded.', :User_MailBody));
```


## Key Points

- Do **NOT** remove the FDM comment.
- Recipients must be verified email addresses of users in the Snowflake account, and every one must be in `ALLOWED_RECIPIENTS`. A distribution list that is not a user's verified address will not receive mail: mark as needs-user.
- See [SSC-FDM-SSIS0008](SSC-FDM-SSIS0008.md) for the sender address.
