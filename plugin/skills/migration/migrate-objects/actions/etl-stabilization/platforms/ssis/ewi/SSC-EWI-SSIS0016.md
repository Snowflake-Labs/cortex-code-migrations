# SSC-EWI-SSIS0016 — Send Mail Priority Not Supported

A Send Mail task had a `Priority` other than Normal (High or Low). `SYSTEM$SEND_EMAIL` has no priority or importance setting, so SnowConvert generated the `CALL SYSTEM$SEND_EMAIL(...)` without it and the mail arrives at normal priority. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Low (once per Send Mail task with High or Low priority) |
| Common action | Remove the marker; tag the subject when recipients filter on priority |

## Identification

Above the `CALL`, after the integration block, often chained after [SSC-EWI-SSIS0015](SSC-EWI-SSIS0015.md) on the same line:

```sql
   END;
   !!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0016 - EMAIL PRIORITY SETTINGS (HIGH/NORMAL/LOW) ARE NOT SUPPORTED BY SYSTEM$SEND_EMAIL AND WILL BE IGNORED. ***/!!!
   --** SSC-FDM-SSIS0008 - ... **
   CALL SYSTEM$SEND_EMAIL('send_mail_with_priority_Send_High_Priority_Email', 'noreply@test.com,admin@example.com', 'Urgent: System Alert', 'Email sent by: noreply@test.com

This is a high priority alert.');
```

The setting is the `Priority` attribute of `<SendMailTaskData>` in the task's `<DTS:ObjectData>`.

## Fix Patterns

### Pattern 1: Remove the marker (most common)

Most priority flags are cosmetic. Delete the marker and keep the `CALL` as it is.

### Pattern 2: Recipients or mail rules rely on High priority

Make the urgency visible in the subject, unless it already is (`Urgent: System Alert`):

```sql
-- Before
CALL SYSTEM$SEND_EMAIL('pkg_Send_Alert', 'oncall@example.com', 'Load failed', '...');

-- After
CALL SYSTEM$SEND_EMAIL('pkg_Send_Alert', 'oncall@example.com', '[HIGH] Load failed', '...');
```

If an alerting rule matched the importance header and must keep working, add a `-- NEEDS-USER: mail rules must match the [HIGH] subject tag` comment and mark as needs-user.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker. When it is chained with another marker on the same line, remove only this one.
- `SYSTEM$SEND_SNOWFLAKE_NOTIFICATION` has no priority setting either; switching procedures does not help.
- A Low priority needs no replacement.
- See [SSC-FDM-SSIS0007](SSC-FDM-SSIS0007.md) for the per-run integration DDL.
