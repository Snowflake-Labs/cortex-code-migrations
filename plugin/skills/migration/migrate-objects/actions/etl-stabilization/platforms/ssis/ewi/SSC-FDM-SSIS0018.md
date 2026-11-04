# SSC-FDM-SSIS0018 — Bulk Insert Row Terminator Not Specified

The Bulk Insert task in the `.dtsx` has no `RowTerminator`, so SnowConvert used `'\r\n'` (CR LF) for `RECORD_DELIMITER`. That matches the task's own default, `{CR}{LF}`, so it is usually right. The FDM is informational.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Low (once per Bulk Insert task without a RowTerminator) |
| Common action | No change, or drop `RECORD_DELIMITER` if the files may now arrive with LF line ends |

## Identification

Look for the marker, often with [SSC-FDM-SSIS0017](SSC-FDM-SSIS0017.md):
```
--** SSC-FDM-SSIS0018 - ROW TERMINATOR NOT SPECIFIED IN DTSX. USING SSIS DEFAULT VALUE '\r\n'. VERIFY THIS MATCHES YOUR DATA FILE FORMAT. **
```

It sits above the task's `COPY INTO`, whose `FILE_FORMAT` has `RECORD_DELIMITER = '\r\n'`.

## Fix Patterns

### Pattern 1: No change (most common)

The source loaded the files with CR LF line ends; Windows-produced files still have them. Leave the comment and the `COPY`.

### Pattern 2: Files may come with LF line ends

With an explicit `'\r\n'`, a file with LF-only line ends has no record delimiter, and the whole file reads as one record. That happens when the producer moves off Windows or a transfer converts line ends. Remove the `RECORD_DELIMITER` option: Snowflake's default newline accepts both `\n` and `\r\n`.

```sql
FILE_FORMAT = (TYPE = 'CSV', FIELD_DELIMITER = ',', SKIP_HEADER = 0, NULL_IF = ('', 'NULL', 'null'), ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE)
```

### Pattern 3: A format file or native file

With [SSC-EWI-SSIS0023](SSC-EWI-SSIS0023.md) the last field's terminator in the format file is the record delimiter; with [SSC-EWI-SSIS0020](SSC-EWI-SSIS0020.md) it is the new export's. Follow that guide.

## Key Points

- Do **NOT** remove the FDM comment.
- `'\r\n'` inside a Snowflake string literal is the two characters CR LF; keep it in single quotes.
- The field delimiter next to it is the riskier default: check [SSC-FDM-SSIS0017](SSC-FDM-SSIS0017.md).
