# Fix Log Format

Defines the format for `{UNIT}/stabilization/tracking/fix-log.md` — the append-only cross-phase learning record.

The orchestrator merges per-batch `learnings_batch_{B}.md` files into this file after each phase completes.

## Structure

### Index (rebuilt after each phase merge)

| EWI Code | Pattern Count | Instances | Classification | Phases |
|----------|--------------|-----------|----------------|--------|
| {code} | {N} | {M fix instances} | engine-defect / conversion-improvement / intentional-decline / context-dependent | P1, P3 |

### Patterns (one section per unique fix pattern)

#### {pattern_name} ({EWI_CODE})

- **Applicability:** {which element types/contexts this applies to}
- **Preconditions:** {what must be true — e.g., "element has control variables", "pure SQL element"}
- **Classification:** engine-defect | conversion-improvement | intentional-decline | context-dependent — {one-line why; an `intentional-decline` (`!!!RESOLVE EWI!!!` / supported EWI/FDM) is NOT an engine bug}
- **Fix instances:** (carried from batch learnings — one row per file touched; anchors let a consumer expand context on demand)

| Element | File (repo-relative) | Anchor (fixed) | Original ref | Marker status | Source XML |
|---|---|---|---|---|---|
| {element} | {models/.../foo.sql} | {block tag / macro / model + line hint} | {stabilization/original/.../foo.sql + line hint, or `new-file`} | {NO_MARKER / MARKER_BROKEN / MARKER_PLUS_BUG / EWI_MARKED / FDM_MARKED / EWI_CRASH} | {source.XML :: TRANSFORMATION NAME} |

<!-- fix-log-entry: element={element} file={models/.../foo.sql} classification={engine-defect|conversion-improvement|intentional-decline|context-dependent} assertions={N} -->

Every row in the table above MUST be followed by one `fix-log-entry` HTML comment —
the markdown table is for human review; this comment is what `track_status.py`
(final validation and `close-unit`) actually parses, since it does not carry a
markdown-table parser. `element`/`file` are the same values as the table row.
`classification` is this row's own classification (not necessarily the pattern's —
see the "mixed" rule below). `assertions` is the number of assertions this fix
instance's test run exercised, as a bare integer. A row with no comment, an
unrecognized `classification`, or a non-numeric `assertions` fails final validation
for any element whose status reflects an applied fix (`fixed`, `test-passed`,
`auto-fixed-needs-review`).

- **Before** (representative, short — full context via `Original ref`):
```sql
{original code snippet}
```
- **After** (representative, short — full context via `Anchor (fixed)`):
```sql
{fixed code snippet}
```
- **Tested in:** Phase {N}, Batch {B}
- **Failure modes:** {what to check if this fix doesn't work for a similar element}

## Merge Protocol

When merging `learnings_batch_*.md` into fix-log.md:
1. Read all learnings files from the phase
2. For each learning entry: check if a pattern with the same EWI code already exists
3. If new pattern: add new section (copy its `Classification` and all `Fix instances` rows, each with its `fix-log-entry` comment, verbatim)
4. If existing pattern with new variant: add as sub-pattern, and **append** its `Fix instances` rows (and their `fix-log-entry` comments) to the pattern's instance table (never collapse instances away — per-instance anchors are the whole point)
5. Rebuild the Index table at the top, updating `Instances` (total fix-instance rows) and `Classification` for each code
6. If two instances of the same code disagree on `Classification`, keep them as separate rows (each with its own `fix-log-entry` comment stating its own classification) and flag the pattern `Classification` as `mixed — see instances` rather than silently picking one
7. Never merge a row without its `fix-log-entry` comment — a learnings file that omits one is incomplete; fix the source rather than inventing values at merge time
