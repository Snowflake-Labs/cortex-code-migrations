# SSC-FDM-SSIS0008 — Send Mail From Address Added to the Body

Snowflake sends email from a fixed sender address, so a Send Mail task's `From` cannot be kept. SnowConvert prepends `Email sent by: <From>` to the body, and also adds the `From` address to the recipients and to the integration's `ALLOWED_RECIPIENTS`, so the old sender receives a copy of every mail.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Low (once per Send Mail task with a From address) |
| Common action | Usually none; remove the From address from the recipients when it is not a real user's address |

## Identification

Look for the marker:
```
--** SSC-FDM-SSIS0008 - SNOWFLAKE'S EMAIL INTEGRATION USES A FIXED SENDER ADDRESS. THE ORIGINAL FROM ADDRESS HAS BEEN PREPENDED TO THE MESSAGE BODY FOR REFERENCE. **
```

It sits above the `CALL SYSTEM$SEND_EMAIL(...)`, whose body starts with `'Email sent by: <From>` followed by a blank line.

## Fix Patterns

### Pattern 1: Keep the body note (most common)

No change. The note is cosmetic.

### Pattern 2: The From address is a service mailbox

An address such as `ssis-etl@example.com` is usually not a Snowflake user's verified address, and `SYSTEM$SEND_EMAIL` fails when a recipient is not allowed. Remove it from the recipient string and from `ALLOWED_RECIPIENTS`:

```sql
-- Before
CALL SYSTEM$SEND_EMAIL('pkg_Send_DQ', 'ssis-etl@example.com,etl-support@example.com', 'DQ summary', 'Email sent by: ssis-etl@example.com

...');

-- After
CALL SYSTEM$SEND_EMAIL('pkg_Send_DQ', 'etl-support@example.com', 'DQ summary', 'Email sent by: ssis-etl@example.com

...');
```


## Key Points

- Do **NOT** remove the FDM comment.
- Recipients whose replies went to the `From` address now reply to Snowflake's sender. If replies matter, put a contact address in the body.
- See [SSC-FDM-SSIS0007](SSC-FDM-SSIS0007.md) for the integration and dropped property expressions.
