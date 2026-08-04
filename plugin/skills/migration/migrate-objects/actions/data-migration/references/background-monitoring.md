# Background monitoring (data migration)

Passive completion + periodic progress for long-running `migrate_data(mode="run")` jobs. Uses Claude Code **Monitor** for done/failed and **`/loop`** for progress. Falls back to active polling when Monitor or `/loop` is unavailable.

For data validation, see [validation background monitoring](../../../../validate-objects/actions/references/background-monitoring.md) (`validate_data_status` / `scai data validate status`).

---

## Goals

| Channel | Mechanism | Role |
|---------|-----------|------|
| **Completion** | Ad-hoc **Monitor** tool on `scai data migrate status <name> --json --watch` | Notify when the workflow finishes or fails |
| **Progress** | **`/loop`** (default every **30 minutes**) calling `migrate_data_status()` | Report tables/partitions/issues without blocking the user |
| **Fallback** | Existing active poll (every 30–60s) | Older CoCo, non-interactive sessions, Monitor/`/loop` missing or disabled |

**Do not** use plugin `monitors/monitors.json` — the workflow name is runtime-only; start Monitor from the skill after the name is known.

---

## Capability check (choose path)

Use the **background path** when all of the following hold:

1. Interactive Claude Code session (not a headless/non-interactive SDK run).
2. The **Monitor** tool is available (appears in the tool list / can be invoked).
3. **`/loop`** or session cron scheduling is available (not disabled via `CLAUDE_CODE_DISABLE_CRON`, and not a host where Monitor is documented as unavailable: Bedrock / Google Agent Platform / Foundry, or when `DISABLE_TELEMETRY` / `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` is set).

Otherwise use the **fallback path** (active poll). If unsure, use fallback.

**Single completion owner:** only one path may present Step 6. Never run Monitor completion and an active poll that both race to report.

---

## Background path

### Phase A — Wait for `workflow_name`

`migrate_data(mode="run")` returns `job_id` before `create-workflow` finishes. `workflow_name` is absent until then.

1. Call `migrate_data_status()` (or `migration_status(mode="data_migration")`) every **5–15 seconds**.
2. Stop Phase A when either:
   - `progress.output.workflowName` is set (non-empty), or top-level / job fields expose a workflow name the status tool can use, **or**
   - Job is already terminal (`status` is `completed`/`failed`) — skip Monitor; go to final status + Step 5.C / Step 6.
3. Tell the user once that migration started and you will report progress periodically (and immediately when it finishes).

### Phase B — Start Monitor (completion)

Working directory: project root (same as `configure()` `project_dir`).

Build the watch command (include `--connection` when Snowflake connection is set):

```bash
scai data migrate status <WORKFLOW_NAME> --json --watch --connection <SNOWFLAKE_CONNECTION>
```

Omit `--connection …` only when no Snowflake connection name is configured.

Invoke the **Monitor** tool:

- `command`: the string above
- `persistent`: `true`
- Do **not** combine with a WebSocket `ws` source

Optional: tell the user monitoring is attached (one short line).

**Watch target rules:**

- **Do** watch `scai data migrate status <name> --json --watch`.
- **Do not** watch `create-workflow` (exits when the workflow is created, not when load finishes).
- **Do not** use a plugin-declared monitor.

### Phase C — Start `/loop` (progress)

After Monitor is running, start a fixed-interval loop:

```text
/loop 30m Call migrate_data_status(). If the job is still running, give the user a short progress update (tables/partitions from progress.output; mention failures from reports if present). Run health checks per Step 5.B (30m cadence). If status is terminal (completed/failed and isFinished when progress present), cancel this loop and do not present Step 6 here — wait for Monitor or treat as crash fallback only if Monitor never fired.
```

Equivalent: `CronCreate` with a ~30-minute recurring prompt that does the same.

On each tick while still running:

1. `migrate_data_status()`
2. One-line (or short) progress for the user
3. Health checks (Step 5.B thresholds for the 30m cadence)
4. Do **not** present the full Step 6 report on a loop tick

### Phase D — On Monitor fire

1. Cancel the progress `/loop` / cron job (`CronDelete` or ask to cancel; self-paced loops: `ScheduleWakeup` with `stop: true` if applicable).
2. Call `migrate_data_status()` **once** (source of truth for the report — do not rely only on Monitor stdout).
3. Apply Step 5.C (finished-but-incomplete) if needed.
4. Proceed to **Step 6** (error-first summary). Only this path (or fallback terminal poll) owns Step 6.

Parse Monitor stdout JSON if useful as a hint; MCP status still wins for reporting.

### Phase E — Loop terminal without Monitor (crash fallback)

If the `/loop` ends or a tick sees a **terminal** job while Monitor has not fired (Monitor crash, session quirk):

1. Cancel Monitor if it is still listed/running.
2. Call `migrate_data_status()` once more.
3. Proceed to Step 5.C / Step 6.

Do not leave the user without a report.

---

## Fallback path (active poll)

Same as the classic Step 5 poll:

- `migrate_data_status()` every **30–60 seconds** (or when the user asks).
- Health every 2nd/3rd poll with **10m / 20m** stall/stuck thresholds (see SKILL Step 5.B fallback column).
- Stop when `status` is `completed`/`failed` and `progress.output.isFinished` is true when `progress` is present.
- Then Step 5.C → Step 6.

---

## Health thresholds

| Signal | Background path (`/loop` ~30m) | Fallback (30–60s poll) |
|--------|--------------------------------|-------------------------|
| Stall | `loadedPartitions` unchanged across **≥1** progress tick (~30–40 min) while running | unchanged **≥10 minutes** |
| Stuck | unchanged across **≥2** ticks | unchanged **≥20 minutes** |
| Partition failures / reports / partial table | Immediate warning (same) | Immediate warning (same) |
| Preprocessing lag | `preprocessedTables < totalTables` and running **≥30 minutes** | running **≥15 minutes** |

Stall/stuck warnings do **not** end monitoring — only terminal status + `isFinished` (or Monitor fire + confirmed terminal status) does.
