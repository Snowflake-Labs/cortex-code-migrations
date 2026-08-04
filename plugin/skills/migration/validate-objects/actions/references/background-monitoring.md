# Background monitoring (data validation)

Passive completion + periodic progress for long-running `validate_data(mode="run")` and `validate_data(mode="revalidate")` jobs. Uses Claude Code **Monitor** for done/failed and **`/loop`** for progress. Falls back to active polling when Monitor or `/loop` is unavailable.

Same pattern as [data migration background monitoring](../../../migrate-objects/actions/data-migration/references/background-monitoring.md); this doc is the DV-specific command and status-field mapping.

---

## Goals

| Channel | Mechanism | Role |
|---------|-----------|------|
| **Completion** | Ad-hoc **Monitor** tool on `scai data validate status <name> --json --watch` | Notify when the workflow finishes or fails |
| **Progress** | **`/loop`** (default every **30 minutes**) calling `validate_data_status()` | Report tables validated/failed/issues without blocking the user |
| **Fallback** | Existing active poll (every 30–60s) | Older CoCo, non-interactive sessions, Monitor/`/loop` missing or disabled |

**Do not** use plugin `monitors/monitors.json` — the workflow name is runtime-only; start Monitor from the skill after the name is known.

---

## Capability check (choose path)

Use the **background path** when all of the following hold:

1. Interactive Claude Code session (not a headless/non-interactive SDK run).
2. The **Monitor** tool is available (appears in the tool list / can be invoked).
3. **`/loop`** or session cron scheduling is available (not disabled via `CLAUDE_CODE_DISABLE_CRON`, and not a host where Monitor is documented as unavailable: Bedrock / Google Agent Platform / Foundry, or when `DISABLE_TELEMETRY` / `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` is set).

Otherwise use the **fallback path** (active poll). If unsure, use fallback.

**Single completion owner:** only one path may present Step 5 (error-first validation report). Never run Monitor completion and an active poll that both race to report.

---

## Per-table progress narration (all paths)

`validate_data_status()` returns `progress.output.tableStates` — one entry **per table**, each carrying its table name plus per-level status (`schemaValidated`, `metricsValidated`, `rowsValidated`, `status`). Repeated status calls that surface only counts (or nothing) read to the user as "a long list of identical calls" with no sense of what is being worked on.

Whenever you surface a progress update — Phase A once `tableStates` first appears, each `/loop` tick, or each fallback poll — **name the tables**, don't stop at counts:

- tables **currently validating** (entries whose `status` is not yet terminal), and
- tables that **finished since your last update** (moved to a terminal `status`), noting pass/fail.

Keep it to one short line, e.g. `Validating dbo.Orders, dbo.Customers · done dbo.Regions ✓ (4/12 tables)`. When the in-flight list is long, name a few and summarise the rest as a count. Only skip naming while `progress.output` is still absent (early startup) — there, say what you're waiting for rather than emitting a silent repeat call.

---

## Background path

### Phase A — Wait for `workflow_name`

`validate_data(mode="run")` / `mode="revalidate"` return `job_id` before `create-workflow` / revalidate finishes. `workflow_name` is absent until then (revalidate may expose a child workflow name).

1. Call `validate_data_status()` every **5–15 seconds**.
2. Stop Phase A when either:
   - `progress.output.workflowName` is set (non-empty), or top-level / job fields expose a workflow name the status tool can use, **or**
   - Job is already terminal (`status` is `completed`/`failed`) — skip Monitor; go to final status + Step 4.B / Step 5.
3. Tell the user once that validation started and you will report progress periodically (and immediately when it finishes). Prefer plain language — do not require the user to understand Monitor/`/loop` tool chrome. The Phase A calls poll before `progress.output` exists, so they are necessarily quiet; the moment `tableStates` appears, switch to naming tables (see [Per-table progress narration](#per-table-progress-narration-all-paths)) instead of silent repeats.

### Phase B — Start Monitor (completion)

Working directory: project root (same as `configure()` `project_dir`).

Build the watch command (include `--connection` when Snowflake connection is set):

```bash
scai data validate status <WORKFLOW_NAME> --json --watch --connection <SNOWFLAKE_CONNECTION>
```

Omit `--connection …` only when no Snowflake connection name is configured.

Invoke the **Monitor** tool:

- `command`: the string above
- `persistent`: `true`
- Do **not** combine with a WebSocket `ws` source

Optional: tell the user monitoring is attached (one short user-facing line, e.g. “I’ll notify you when validation finishes”).

**Watch target rules:**

- **Do** watch `scai data validate status <name> --json --watch`.
- **Do not** watch `create-workflow` / revalidate create (exits when the workflow is created, not when validation finishes).
- **Do not** use a plugin-declared monitor.

### Phase C — Start `/loop` (progress)

After Monitor is running, start a fixed-interval loop:

```text
/loop 30m Call validate_data_status(). If the job is still running, give the user a short progress update: counts (validatedTables/totalTables/failedTables from progress.output) plus the tables currently validating and any that finished since the last tick (from progress.output.tableStates — see Per-table progress narration); mention reports errors if present. Run health checks per validate_tables Step 4 health section (30m cadence). If status is terminal (completed/failed and isFinished when progress present), cancel this loop and do not present Step 5 here — wait for Monitor or treat as crash fallback only if Monitor never fired.
```

Equivalent: `CronCreate` with a ~30-minute recurring prompt that does the same.

On each tick while still running:

1. `validate_data_status()`
2. One-line (or short) progress for the user — name the tables in progress / just finished, not just counts ([Per-table progress narration](#per-table-progress-narration-all-paths))
3. Health checks (Step 4 health thresholds for the 30m cadence)
4. Do **not** present the full Step 5 report on a loop tick

### Phase D — On Monitor fire

1. Cancel the progress `/loop` / cron job (`CronDelete` or ask to cancel; self-paced loops: `ScheduleWakeup` with `stop: true` if applicable).
2. Call `validate_data_status()` **once** (source of truth for the report — do not rely only on Monitor stdout).
3. Apply Step 4.B (finished-but-pending) if needed.
4. Proceed to **Step 5** (error-first summary). Only this path (or fallback terminal poll) owns Step 5.

Parse Monitor stdout JSON if useful as a hint; MCP status still wins for reporting.

### Phase E — Loop terminal without Monitor (crash fallback)

If the `/loop` ends or a tick sees a **terminal** job while Monitor has not fired (Monitor crash, session quirk):

1. Cancel Monitor if it is still listed/running.
2. Call `validate_data_status()` once more.
3. Proceed to Step 4.B / Step 5.

Do not leave the user without a report.

---

## Fallback path (active poll)

Same as the classic Step 4 poll:

- `validate_data_status()` every **30–60 seconds** (or when the user asks). When `progress.output` is present, surface a short per-table update ([Per-table progress narration](#per-table-progress-narration-all-paths)) rather than a silent repeat call.
- Health every 2nd/3rd poll with **10m / 20m** stall/stuck thresholds (see `validate_tables.md` Step 4 health fallback column).
- Stop when `status` is `completed`/`failed` and `progress.output.isFinished` is true when `progress` is present.
- Then Step 4.B → Step 5.

---

## Health thresholds

**Progress key:** `validatedTables + failedTables` from `progress.output` (how many tables have left the pending set). Record the poll/tick time when this key last increased.

| Signal | Background path (`/loop` ~30m) | Fallback (30–60s poll) |
|--------|--------------------------------|-------------------------|
| Stall | Progress key unchanged across **≥1** progress tick (~30–40 min) while running and `isFinished` is false | unchanged **≥10 minutes** |
| Stuck | unchanged across **≥2** ticks | unchanged **≥20 minutes** |
| Table failures | `failedTables > 0` or `reports.files.data_validation_errors` / failed `tableStates` | Immediate warning (same) |
| Slow start | `validatedTables + failedTables == 0` and running **≥30 minutes** | running **≥15 minutes** |

Stall/stuck warnings do **not** end monitoring — only terminal status + `isFinished` (or Monitor fire + confirmed terminal status) does.
