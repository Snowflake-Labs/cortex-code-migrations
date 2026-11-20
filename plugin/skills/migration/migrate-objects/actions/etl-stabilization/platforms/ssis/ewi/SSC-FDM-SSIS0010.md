# SSC-FDM-SSIS0010 — Send Mail BCC Recipients Made Visible

A Send Mail task had a `BCC` line. `SYSTEM$SEND_EMAIL` takes one recipient list, so SnowConvert merged the task's From, To, CC and BCC addresses (split on `;` or `,`, de-duplicated) into that list and into the integration's `ALLOWED_RECIPIENTS`. The Bcc recipients still receive the mail, but every recipient now sees their addresses. The FDM generates no broken code, but that disclosure usually has to be fixed.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Low (once per Send Mail task with a BCC line) |
| Common action | Move the Bcc addresses back to a Bcc line with `SYSTEM$SEND_SNOWFLAKE_NOTIFICATION` |

## Identification

Look for the marker:
```
--** SSC-FDM-SSIS0010 - SNOWFLAKE'S SYSTEM$SEND_EMAIL DOES NOT SUPPORT BCC ADDRESSING. ALL BCC RECIPIENTS HAVE BEEN ADDED TO THE MAIN RECIPIENTS LIST, MAKING THEM VISIBLE TO ALL RECIPIENTS. **
```

```sql
   --** SSC-FDM-SSIS0008 - ... **
   --** SSC-FDM-SSIS0010 - SNOWFLAKE'S SYSTEM$SEND_EMAIL DOES NOT SUPPORT BCC ADDRESSING. ALL BCC RECIPIENTS HAVE BEEN ADDED TO THE MAIN RECIPIENTS LIST, MAKING THEM VISIBLE TO ALL RECIPIENTS. **
   CALL SYSTEM$SEND_EMAIL('send_mail_with_bcc_Send_Email_Task', 'noreply@test.com,admin@example.com,secret@example.com,audit@example.com', 'Test Email with BCC', 'Email sent by: noreply@test.com

This email has BCC recipients.');
```

The original lines are the `To`, `From`, `CC` and `BCC` attributes of `<SendMailTaskData>` in the task's `<DTS:ObjectData>` (here `To="admin@example.com"`, `BCC="secret@example.com;audit@example.com"`).

## Fix Patterns

### Pattern 1: Restore the Bcc line (most common)

`SYSTEM$SEND_SNOWFLAKE_NOTIFICATION` takes separate To, Cc and Bcc arrays through the same email integration (pass `NULL` or an empty array for an unused line):

```sql
CALL SYSTEM$SEND_SNOWFLAKE_NOTIFICATION(
  SNOWFLAKE.NOTIFICATION.TEXT_PLAIN('Email sent by: noreply@test.com

This email has BCC recipients.'),
  SNOWFLAKE.NOTIFICATION.EMAIL_INTEGRATION_CONFIG(
    'send_mail_with_bcc_Send_Email_Task',
    'Test Email with BCC',
    ARRAY_CONSTRUCT('admin@example.com'),
    NULL,
    ARRAY_CONSTRUCT('secret@example.com', 'audit@example.com')));
```

A mail with only a Bcc line cannot be sent: when the task had no To or Cc, mark as needs-user for a To address.

### Pattern 2: Separate mails

Keep `SYSTEM$SEND_EMAIL`: one `CALL` with the To and Cc addresses, then one `CALL` for **each** Bcc address on its own. Do not send one copy to all the Bcc addresses together: they would then see each other, which Bcc did not allow.

```sql
CALL SYSTEM$SEND_EMAIL('send_mail_with_bcc_Send_Email_Task', 'admin@example.com', 'Test Email with BCC', 'Email sent by: noreply@test.com

This email has BCC recipients.');
CALL SYSTEM$SEND_EMAIL('send_mail_with_bcc_Send_Email_Task', 'secret@example.com', 'Test Email with BCC', 'Email sent by: noreply@test.com

This email has BCC recipients.');
CALL SYSTEM$SEND_EMAIL('send_mail_with_bcc_Send_Email_Task', 'audit@example.com', 'Test Email with BCC', 'Email sent by: noreply@test.com

This email has BCC recipients.');
```

With many Bcc addresses, prefer Pattern 1: one mail rather than one per address.

## Key Points

- Do **NOT** remove the FDM comment.
- Bcc on an audit or compliance mailbox is common; a mail that exposes it to business users is a disclosure, so do not leave the merged list in place without a reason.
- Every address, Bcc included, must be a verified email address of a user in the account and be listed in `ALLOWED_RECIPIENTS`; one address that is not blocks the whole mail. Mark as needs-user when a Bcc address is a mailbox rather than a user.
- See [SSC-FDM-SSIS0009](SSC-FDM-SSIS0009.md) for Cc, [SSC-FDM-SSIS0008](SSC-FDM-SSIS0008.md) for the From address and [SSC-FDM-SSIS0007](SSC-FDM-SSIS0007.md) for the integration DDL.
