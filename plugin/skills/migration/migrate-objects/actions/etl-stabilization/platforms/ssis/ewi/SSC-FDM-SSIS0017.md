# SSC-FDM-SSIS0017 — Bulk Insert Field Terminator Not Specified

The Bulk Insert task in the `.dtsx` has no `FieldTerminator`, so SnowConvert used `','` for `FIELD_DELIMITER`. That comma is the converter's fallback, **not** SSIS's: the Bulk Insert task's default column delimiter is **Tab**, and a missing `FieldTerminator` usually means it was left at that default. The FDM is informational, but the delimiter is often wrong.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | Inline FDM comment (not `!!!RESOLVE EWI!!!`) |
| Breaks compilation? | **No** |
| Frequency | Low (once per Bulk Insert task without a FieldTerminator) |
| Common action | Confirm the delimiter from a sample file; without one, use `'\t'` |

## Identification

Look for the marker, often with [SSC-FDM-SSIS0018](SSC-FDM-SSIS0018.md):
```
--** SSC-FDM-SSIS0017 - FIELD TERMINATOR NOT SPECIFIED IN DTSX. USING SSIS DEFAULT VALUE ','. VERIFY THIS MATCHES YOUR DATA FILE FORMAT. **
```

It sits above the task's `COPY INTO`, whose `FILE_FORMAT` has `FIELD_DELIMITER = ','`.

## Fix Patterns

### Pattern 1: A sample file or file spec is available

Look in the project's source tree for the file (or a test copy), a format file, or the Flat File connection manager that writes it, and set `FIELD_DELIMITER` to what the file uses. A Flat File connection's own delimiter is a good clue, though the Bulk Insert task itself ignores it.

### Pattern 2: No evidence

Use the SSIS default, Tab, and note it:

```sql
-- FieldTerminator not set in the package: SSIS Bulk Insert default (Tab)
FILE_FORMAT = (TYPE = 'CSV', FIELD_DELIMITER = '\t', RECORD_DELIMITER = '\r\n', SKIP_HEADER = 0, NULL_IF = ('', 'NULL', 'null'), ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE)
```

### Pattern 3: A format file or native file

With [SSC-EWI-SSIS0023](SSC-EWI-SSIS0023.md) the terminators come from the format file; with [SSC-EWI-SSIS0020](SSC-EWI-SSIS0020.md) from the new export. Follow that guide.

## Key Points

- Do **NOT** remove the FDM comment.
- A wrong delimiter does not fail loudly: with `ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE` each whole line goes into the first column and the rest are NULL (a numeric first column turns that into row errors that `SKIP_FILE_n` hides). Check the delimiter even when the load "works".
- SSIS stores some terminators by name; the converter maps `Tab`, `{TAB}` and `Comma {,}`-style values, but check any other word left as the delimiter (see [SSC-EWI-SSIS0023](SSC-EWI-SSIS0023.md)).
