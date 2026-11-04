# SSC-FDM-SSIS0009 — Send Mail CC Recipients Added to To

A Send Mail task had a `CC` line. `SYSTEM$SEND_EMAIL` takes one recipient list, so SnowConvert merged the task's From, To, CC and BCC addresses (split on `;` or `,`, de-duplicated) into that list and into the integration's `ALLOWED_RECIPIENTS`. Everyone still receives the mail, but the Cc recipients appear on the To line. The FDM is informational.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Low (once per Send Mail task with a CC line) |
| Common action | No change; use `SYSTEM$SEND_SNOWFLAKE_NOTIFICATION` only when the Cc line matters |

## Identification

Look for the marker:
```
--** SSC-FDM-SSIS0009 - SNOWFLAKE'S SYSTEM$SEND_EMAIL DOES NOT SUPPORT CC ADDRESSING. ALL CC RECIPIENTS HAVE BEEN ADDED TO THE MAIN RECIPIENTS LIST. **
```

```sql
   --** SSC-FDM-SSIS0008 - ... **
   --** SSC-FDM-SSIS0009 - SNOWFLAKE'S SYSTEM$SEND_EMAIL DOES NOT SUPPORT CC ADDRESSING. ALL CC RECIPIENTS HAVE BEEN ADDED TO THE MAIN RECIPIENTS LIST. **
   CALL SYSTEM$SEND_EMAIL('send_mail_basic_Send_Mail_Task', 'noreply@test.com,admin@example.com,team@example.com', 'Error Notification', 'Email sent by: noreply@test.com

An error occurred during package execution.');
```

The original lines are the `To`, `From` and `CC` attributes of `<SendMailTaskData>` in the task's `<DTS:ObjectData>` (here `To="admin@example.com"`, `CC="team@example.com"`).

## Fix Patterns

### Pattern 1: No change (most common)

Alerts and status mails rarely depend on who is on Cc. Leave the comment and the `CALL`.

### Pattern 2: The Cc line matters (replies, mail rules)

`SYSTEM$SEND_SNOWFLAKE_NOTIFICATION` keeps To and Cc apart, through the same email integration:

```sql
CALL SYSTEM$SEND_SNOWFLAKE_NOTIFICATION(
  SNOWFLAKE.NOTIFICATION.TEXT_PLAIN('Email sent by: noreply@test.com

An error occurred during package execution.'),
  SNOWFLAKE.NOTIFICATION.EMAIL_INTEGRATION_CONFIG(
    'send_mail_basic_Send_Mail_Task',
    'Error Notification',
    ARRAY_CONSTRUCT('admin@example.com'),
    ARRAY_CONSTRUCT('team@example.com'),
    NULL));
```


## Key Points

- Do **NOT** remove the FDM comment.
- Every address, Cc included, must be a verified email address of a user in the account and be listed in `ALLOWED_RECIPIENTS`; one address that is not blocks the whole mail. A distribution list on Cc is the usual failure: mark as needs-user.
- The From address is in the merged list too: see [SSC-FDM-SSIS0008](SSC-FDM-SSIS0008.md). For the integration DDL, see [SSC-FDM-SSIS0007](SSC-FDM-SSIS0007.md); for Bcc, [SSC-FDM-SSIS0010](SSC-FDM-SSIS0010.md).
