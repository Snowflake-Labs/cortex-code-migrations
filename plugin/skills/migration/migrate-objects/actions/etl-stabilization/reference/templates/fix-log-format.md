# Fix Log Format

Defines the format for `artifacts/tracking/fix_log.md` — the append-only cross-phase learning record.

The orchestrator merges per-batch `learnings_batch_{B}.md` files into this file after each phase completes.

## Structure

### Index (rebuilt after each phase merge)

| EWI Code | Pattern Count | Phases |
|----------|--------------|--------|
| {code} | {N} | P1, P3 |

### Patterns (one section per unique fix pattern)

#### {pattern_name} ({EWI_CODE})

- **Applicability:** {which element types/contexts this applies to}
- **Preconditions:** {what must be true — e.g., "element has control variables", "pure SQL element"}
- **Before:**
```sql
{original code snippet}
```
- **After:**
```sql
{fixed code snippet}
```
- **Tested in:** Phase {N}, Batch {B}
- **Failure modes:** {what to check if this fix doesn't work for a similar element}

## Merge Protocol

When merging `learnings_batch_*.md` into fix_log.md:
1. Read all learnings files from the phase
2. For each learning entry: check if a pattern with the same EWI code already exists
3. If new pattern: add new section
4. If existing pattern with new variant: add as sub-pattern
5. Rebuild the Index table at the top
