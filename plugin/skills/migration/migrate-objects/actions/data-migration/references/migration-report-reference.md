# Migration report: errors and next steps

Loaded from [SKILL.md](../SKILL.md) Step 6 when the run had failures. Step numbers below are that file's.

## 6.B — Headline

| Outcome | **Result** line |
|---------|-----------------|
| All tables loaded, no failures | `Success — <N>/<N> tables loaded` |
| Some failures | `<N_ok>/<N_total> tables OK — <F> failed` |
| **Finished but incomplete** (Step 5.C) | `<N_ok>/<N_total> tables OK — <F> never completed` |
| Job `failed` is true or no table progress | `Failed — no tables processed` (or partial counts if available) |

**Never** use the all-success **Result** when Step 5.C applies. **Workflow** line: `` `details.progress.output.workflowName` ``; if the job failed before a workflow existed, say so and put its `summary` under **Infrastructure**. **Header shows only `Result` and `Workflow`.**

## 6.C — Classify errors (fixed category order)

Assign each failed table to **one** category (first match wins). List categories **only when they have at least one error**, in this order:

| Order | Category | When |
|-------|----------|------|
| 1 | **Preprocessing** | `hasBeenPreprocessed` is false |
| 2 | **Extraction** | `TaskName` is `extract` (or extract-phase failure); source/read errors in `ExampleErrorMessage` / `LastErrorMessage` |
| 3 | **Load** | Load-phase failures, `failedPartitions` > 0 with load task, partial partition load (table-specific message) |
| 4 | **Infrastructure** | Top-level `error`, orchestrator/compute pool/worker failures before per-table progress |

**Message per table:** prefer `details.reports.files.progress[].ExampleErrorMessage`, else first `details.reports.files.errors[].LastErrorMessage` for that `TableName`. For load, you may add partition context (`loaded`/`total`, `PartitionNumber`) on the same bullet.

**Deduplicate:** when two or more tables share the same normalized message in a category, emit **one** bullet with the message and a line `- Affects: \`table1\`, \`table2\`, …`. Use a single table name in the bullet only when the failure is table-specific (e.g. one load timeout with partition detail).

## 6.D — Suggested fixes

Number fixes in the **same category order** as **Errors** (Preprocessing → Extraction → Load → Infrastructure). One numbered item per error group (not per table when deduped). Each item must be a **concrete prerequisite action** (edit worker TOML, fix workflow YAML, cancel stale tasks, grant privileges, etc.) — not “re-run and hope.” Tie actions to:

- [Troubleshooting Reference](./troubleshooting-reference.md) for worker/orchestrator/partition issues
- YAML / TOML edits: `whereClauseCriteria`, partitions, `source.databaseName`, extraction strategy, worker connection fields — as required by the error category
- **Re-run only as a follow-up:** mention `migrate_data(mode="run", workflow_path=...)` in `### Suggested fixes` only when prerequisites are clear, or label it “after the steps above” — do not list re-run as the first or only fix. Before suggesting re-run, confirm the workflow uses incremental sync (`watermark` / `checksum`) or that the user accepts a full reload; a non-incremental re-run against a populated target duplicates rows (see the duplicate-data callout in [SKILL.md](../SKILL.md) Step 2).

Do **not** include a per-table markdown table unless the user asks for a full audit.

## 6.E — Failure template

```markdown
## Data migration — completed with errors

**Result:** <N_ok>/<N_total> tables OK — <F> failed
**Workflow:** `<workflowName>`

### Errors

**Preprocessing**
- <message>
  - Affects: `<table>`, …

**Extraction**
- <shared message>
  - Affects: `<table>`, …

**Load**
- `<table>` — <message> (<loaded>/<total> partitions failed if relevant)

**Infrastructure**
- <job summary or orchestrator error>

### Suggested fixes

1. **Preprocessing (<tables>)** — …
2. **Extraction (<tables>)** — …
3. **Load (<table>)** — …
4. **Infrastructure** — …
```

Omit empty category subsections. If every table completed **and Step 5.C does not apply**, omit `### Errors` and `### Suggested fixes` failure content. If the job failed before `progress` existed, use the **failed** title, minimal **Result**, and a single **Infrastructure** error + fix.

## After the summary

- **All tables succeeded** — return control to the parent skill; its state machine chooses the next task.
- **Any failures** — do **not** jump to re-run. Summarize the prerequisite actions from `### Suggested fixes`, then **ask the user** how to proceed, for example:
  1. Apply fixes (YAML/TOML/config) — you or the user edits files; confirm when done
  2. Re-run the same workflow — only after prerequisites are done or the user explicitly accepts re-run without fixes (e.g. transient infra). **Warn:** if `sync_strategy=none` (or no `synchronization` block), re-run reloads all rows and **duplicates data** on the target; prefer adding `watermark`/`checksum`, and clear the target only as *Clearing a bad load* ([SKILL.md](../SKILL.md) Step 2) allows — never blind `TRUNCATE`/`DELETE`.
  3. Narrow scope — adjust `where` / workflow YAML and run setup + run for failed tables only
  4. Investigate further — troubleshooting reference, logs, health signals from Step 5.B
  5. Stop — proceed to Step 7 (teardown) without re-running

Then continue to Step 7 (teardown offer) when wave data work is done for this pass.
