## Batch Output Format

Each orchestration batch agent writes a structured artifact at `{UNIT}/stabilization/phases/phase_{N}/batch_{B}.md`. This is the **only** output channel for batch results — the orchestrator reads these artifacts to update tracking and apply fixes.

> **Placeholder:** `{B}` is the full phase-qualified batch ID (e.g., `B1.1`, `B1.2`). Schema names use the flat format `ETL_FIX_P{N}_B{M}` (e.g., `ETL_FIX_P1_B1`) where `{M}` is the batch number without phase prefix.

```markdown
# Batch {B} — Phase {N}

## Elements

### {element_name}

- **Status**: test-passed | test-failed | skipped | needs-user | auto-fixed-needs-review | failed
- **Reason**: (required for skipped, needs-user, auto-fixed-needs-review, failed)
- **Test file**: `{UNIT}/stabilization/tests/orchestration/{task_procedure_name}/{element_name}.sql`
- **Replacement tag**: `---- Start block: {exact_tag_from_orch_sql}`
- **Replacement SQL**:
\```sql
-- Production-ready SQL body (original DB/schema references, NOT test-env references)
-- This replaces everything between the Start and End tags in the orch SQL
{production_sql}
\```

### {next_element_name}
...
```

**Incremental write model:** Batch artifacts are written one element section at a time — the agent appends each `###` section immediately after completing that element. **Partial artifacts are valid** — if a batch agent stops early due to context pressure, the orchestrator reads whatever elements are present and treats missing elements as unprocessed (available for retry). Do not assume a batch artifact is complete just because it exists.

**Rules for batch artifacts:**
- One `###` section per element assigned to this batch
- Every assigned element MUST appear in a fully-completed artifact — but partial artifacts (missing elements) are expected during recovery flows
- `Replacement SQL` is required for `test-passed`, `auto-fixed-needs-review`, and `skipped:disabled-in-source` statuses, and conditionally for `no-fix-needed` when the element still has EWI markers that must be cleared
- `Replacement SQL` must use the **original** database/schema references from the orch SQL file, not the test schema (`ETL_FIX_P{N}_B{M}`)
- **Replacement tag**: The EXACT tag line from the orch SQL — either `---- Start block '<name>'` for containers or `---- Start '<name>'` for non-containers. Must match verbatim.
- `Test file` path is required for all statuses except `skipped` and `failed`

## Learning Artifact Format

Each batch agent writes a per-batch learning file at `{UNIT}/stabilization/phases/phase_{N}/learnings_batch_{B}.md`. These are merged into `{UNIT}/stabilization/tracking/fix_log.md` at phase end by the orchestrator (single-writer).

```markdown
# Learnings — Batch {B}, Phase {N}

## {element_name}: {one-line summary of fix}

- **EWI/FDM**: {code} — {title}
- **Root cause**: {what the converter did wrong or couldn't handle}
- **Fix pattern**: {the SQL transformation applied}
- **Before** (abbreviated):
\```sql
{original snippet}
\```
- **After** (abbreviated):
\```sql
{fixed snippet}
\```
- **Reusable**: yes | no — {why}

## {next_element_name}: ...
```

**Rules:**
- Only include entries for elements where a fix was actually applied (`test-passed` or `auto-fixed-needs-review`)
- `Reusable: yes` means this pattern can be applied to similar EWI/FDM codes in future phases
- Keep snippets abbreviated (relevant lines only, not full procedure bodies)
- If no fixes were applied (all elements skipped or passed without changes), write an empty learnings file with a note: `No fixes applied in this batch.`
