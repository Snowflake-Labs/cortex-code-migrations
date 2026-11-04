# SSC-EWI-SSIS0018 — Send Mail HTML Body Not Preserved

A Send Mail task's body format was HTML. SnowConvert passes the HTML markup as the body of a four-argument `CALL SYSTEM$SEND_EMAIL(...)`, which sends `text/plain`, so recipients see raw tags. Contrary to the marker text, `SYSTEM$SEND_EMAIL` does send HTML: its optional fifth argument is the MIME type. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Rare (the stock SSIS Send Mail task sends plain text only) |
| Common action | Add `'text/html'` as the fifth argument |

## Identification

Above the `CALL`, after the integration block, with the other Send Mail markers:

```sql
   END;
   !!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0018 - SYSTEM$SEND_EMAIL ONLY SUPPORTS PLAIN TEXT EMAIL BODIES. HTML FORMATTING WILL NOT BE PRESERVED. ***/!!!
   --** SSC-FDM-SSIS0008 - ... **
   CALL SYSTEM$SEND_EMAIL('pkg_Send_Report', 'noreply@test.com,etl-support@example.com', 'Daily report', 'Email sent by: noreply@test.com

<html><body><h2>Daily report</h2><p>All loads succeeded.</p></body></html>');
```

The setting is the `BodyFormat` attribute of `<SendMailTaskData>` in the task's `<DTS:ObjectData>` (`1` or `HTML`).

## Fix Patterns

### Pattern 1: Send it as HTML (most common)

Add the MIME type. The `Email sent by:` line from [SSC-FDM-SSIS0008](SSC-FDM-SSIS0008.md) sits before the markup; move it inside the body so it renders as a paragraph:

```sql
-- After
CALL SYSTEM$SEND_EMAIL('pkg_Send_Report', 'etl-support@example.com', 'Daily report',
  '<html><body><p>Email sent by: noreply@test.com</p><h2>Daily report</h2><p>All loads succeeded.</p></body></html>',
  'text/html');
```

Snowflake does not validate the HTML. Inline styles work; scripts and external images depend on the recipient's mail client.

### Pattern 2: The markup was not needed

When the HTML only wrapped plain sentences, strip the tags and keep the four-argument call.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker.
- `SYSTEM$SEND_SNOWFLAKE_NOTIFICATION` with `SNOWFLAKE.NOTIFICATION.TEXT_HTML('...')` also sends HTML; use it when the same mail also needs Cc or Bcc ([SSC-FDM-SSIS0009](SSC-FDM-SSIS0009.md), [SSC-FDM-SSIS0010](SSC-FDM-SSIS0010.md)).
- An HTML body built by an expression or variable was dropped like any property expression: see [SSC-FDM-SSIS0007](SSC-FDM-SSIS0007.md) Pattern 3.
