# Background monitoring (data migration)

Passive completion and trouble reporting for long-running `migrate_data(mode="run")` jobs. The MCP relay polls the workflow and appends state changes to a log; Claude Code **Monitor** tails that log for you.

---

## Goals

| Channel | Mechanism | Role |
|---------|-----------|------|
| **Completion / trouble** | **Monitor** on the `monitor.watch_command` the run response returned | Wake when the workflow finishes, fails, or goes quiet |
| **Fallback** (last resort) | Active poll of `job_status(job_id)` (every 30–60s) | Only when Monitor cannot be invoked |

The relay polls once per job no matter how many agents are watching, so a second agent attaches rather than starting its own watcher.

**There is no progress loop.** The relay reports a `stalled` event when a job has gone **30 minutes** without changing — and sooner, at **2 minutes**, when its `WORKFLOW` row is still `pending` (no orchestrator has claimed it yet) — so you learn about a quiet job by being told, not by waking on a timer to check. During a healthy run there is nothing to report and nothing wakes you — progress still lands in the log, and `job_status` reads it on demand when the user asks.

---

## Choosing a path

**Always prefer Monitor.** If the **Monitor** tool can be invoked, use the background path. There is no case where repeated polling is the better choice when Monitor is available:

- One relay poller serves every watcher, however many agents are attached.
- It wakes you on **trouble** (first failure, stall, relay error), not only on completion.
- It costs no tool call per check, so it does not spend context re-reading the same status.

Fall back to active polling **only** when Monitor is genuinely unavailable — absent from the tool list, or invoking it fails. A headless / non-interactive run is the usual reason.

**If you are unsure whether Monitor is available, try it.** A failed invocation tells you immediately and costs one call. Do not default to polling out of caution.

**On-demand reads are not the polling path.** Calling `job_status(job_id)` because the user asked how it's going is always fine and does not conflict with Monitor. The fallback path means using *repeated* polls as your completion signal.

**Single completion owner:** only one path may present Step 6. Never run Monitor completion and an active poll that both race to report.

---

## Background path

### Phase A — Start Monitor

`migrate_data(mode="run")` returns a `monitor` block immediately — before the workflow even has a name:

```json
{"monitor": {"job_id": "j-7f2a", "log": ".scai/monitor/relay.jsonl", "cursor": 4021, "watch_command": "…"}}
```

Invoke the **Monitor** tool with `command` set to `monitor.watch_command` verbatim and `persistent: true`. Run it from the project root. Do not rebuild the command by hand — the cursor in it is what keeps you from replaying old records or missing new ones.

There is no wait for a workflow name: the relay stamps it on when `create-workflow` reports it, and the watch is already armed. Until then `job_status(..., details=true)` may report `details_unavailable`; that is normal.

**A job can already be running when your session begins.** A workflow keeps going in Snowflake across an MCP restart, so `configure` reports any jobs still live and hands you a `watch_command` for each. When it does, arm Monitor from those commands before anything else — that job has been unwatched since the previous session ended.

Tell the user once, in plain language, that migration started and that you will report back when it finishes or if it runs into trouble.

**Then stop.** Arming Monitor ends your turn: no `sleep`, no status call, no
Bash of any kind until the event fires. The wait is the relay's job.

**The watch only fires on events worth acting on** — terminal, first failure, a stall (2 minutes unclaimed, or 30 minutes with no change), or relay error. It deliberately does *not* fire on ordinary progress, which changes on nearly every poll. Progress is still in the log, and `job_status` reports it on demand.

### Phase B — On Monitor fire

Read the event line's `phase` to decide what happened:

| `phase` | Meaning | Action |
|---------|---------|--------|
| `terminal` | Job finished (check `failed`) | Phase C |
| `failure` | First partition failure, job still running | Warn the user; keep watching |
| `stalled`, `detail.stall_reason: "infrastructure_down"` | The orchestrator or worker the job needs is down, local or SPCS; `detail.infrastructure` names it, with `exit_status` and `log_tail` for a local process this session started | Tell the user which process is down, with its last log line when there is one, and offer `detail.remediation` (see [Health monitoring](#health-monitoring)). Do not cancel or re-dispatch: keep watching, the job carries on once the process is back |
| `stalled`, `detail.stall_reason: "unclaimed"` | 2 minutes with the `WORKFLOW` row still `pending` — no orchestrator has claimed it | Run the stall diagnosis in [Health monitoring](#health-monitoring): a stopped or still-starting orchestrator, one bound to another affinity, or one busy initializing another workflow. Report what it finds; keep watching. A 30-minute `stalled` still follows, keeping `unclaimed` while the row stays `pending` |
| `stalled`, `detail.stall_reason: "no_change"` | 30 minutes with no change | Warn the user, run the stall diagnosis in [Health monitoring](#health-monitoring), keep watching. If `summary` names a workflow status (e.g. `(workflow status Unknown)`), the workflow may be paused or cancelled — see below |
| `relay_error` | The relay's own status query failed | Note it; the relay retries |

A paused or cancelled workflow produces no terminal record. Neither state is a member of
the CLI's workflow-status enum, so the status call reports `Unknown` and the relay keeps the
job `inProgress` rather than guessing. A stall whose `summary` carries an unclassifiable
workflow status is therefore the only signal you get: confirm with
`scai data migrate list` before continuing to wait, and tell the user rather than watching a
job that has already stopped.

### Phase C — On `terminal`

1. Read `detail.completion` from the terminal event — its verdict, status,
   counts, failures, and stale-report warning are the source of truth.
2. If `completion.failed` is true and deeper per-table diagnostics are needed,
   call `job_status(job_id, details=true)` once, then apply Step 5.C.
3. Proceed to **Step 6** (error-first summary).

The watch command exits by itself on its job's terminal record, so there is nothing to cancel.

### If the watch goes silent

Losing the watch is the one failure this design does not self-report: there is no second timer cross-checking it, and a lost watch looks exactly like a healthy quiet run.

So do not wait until you suspect it. **Whenever you call `job_status` for a live job, pass `monitor=true`.** It is idempotent and costs nothing extra: it returns a fresh `cursor` and `watch_command`, and re-arms the relay's poller if this process lost it. That turns every incidental status check — the user asking how it's going, a check after a compaction — into a repair. Re-arm your Monitor from the returned command whenever you are unsure the old one survived. Nothing is missed: the log is on disk and the new cursor resumes from where you are.

---

## Fallback path (last resort — only when Monitor cannot be invoked)

- Call `job_status(job_id)` repeatedly until `terminal` is true (or when the user asks). Do **not** pace yourself with `bash sleep` / wall-clock delays / worker-log tails / `.scai/monitor/relay.jsonl` tails — those skip the status tool and waste minutes. Short sleeps after killing a process (1–3s) are fine, and nothing else earns a longer one.
- Health every 2nd/3rd poll with **10m / 20m** stall/stuck thresholds (see [Health thresholds](#health-thresholds)).
- Stop when `terminal` is true.
- Then Step 5.C → Step 6.

---

## Health thresholds

On the **background path the relay computes stalls for you** — a `stalled` event means no orchestrator claimed the workflow within 2 minutes (`unclaimed`) or its counters have not moved for 30 minutes (`no_change`). Diagnose it with `data_infrastructure(mode="status")` ([Health monitoring](#health-monitoring)) and keep watching; a stall does not end monitoring.

For the **fallback path**, derive health yourself from consecutive `job_status(job_id, details=true)` responses.

**Progress key:** `loadedPartitions` from `details.progress.output.aggregatedCounts` (fallback: sum of `tablePartitions[].loadedPartitions`). Record the poll time when this key last increased.

| Signal | Background path | Fallback (30–60s poll) |
|--------|-----------------|-------------------------|
| Stall / stuck | `stalled` event from the relay | `loadedPartitions` unchanged **≥10 min** / **≥20 min** |
| Partition failures | `failure` event, or `failed: true` on any event | `aggregatedCounts.failedPartitions > 0` |
| Partial table failure | same `failure` event | Any `tablePartitions[]` with `failedPartitions > 0` or `hasBeenPreprocessed == false` while running |
| Preprocessing lag | `preprocessedTables < totalTables` and running ≥30 minutes | running **≥15 minutes** |

Only a `terminal` event (or a fallback poll seeing `terminal: true`) ends monitoring.

---

## Health monitoring

Monitor emits `stalled` and `failure` events. On either event, call
`job_status(job_id, details=true)` once to inspect the current state, surface
the warning, and keep the Monitor armed.

| Signal | Severity |
|--------|----------|
| `stalled` event | Per the diagnosis below (**Warning** or **Critical**) |
| A second `stalled` event with the same `detail.stall_reason` | **Critical** |
| `failure` event, or `failed: true` on any event | **Warning** (immediate) |
| Any `tablePartitions[]` with failed partitions or incomplete preprocessing | **Warning** |

**On a `stalled` event, diagnose before you keep watching.** Call `data_infrastructure(mode="status")` once, alongside the `job_status` read, and act on the first match:

| `detail.stall_reason` | Status shows | Meaning | Do |
|---|---|---|---|
| `infrastructure_down` | any | The orchestrator or worker the job needs is down, by the same check that refuses a dispatch. Sent at once, not after a deadline; `detail.infrastructure` names its `process` and `placement`, and for a local process this session started, its `exit_status`, `log_tail` and `log_path`. `detail.remediation` is the call that restarts it, absent when `up` would not (an SPCS worker, another metadata database) | **Critical.** Tell the user which process is down, with its last log line when there is one, and offer `detail.remediation` (else follow the `summary`: `scai data worker start` for an SPCS worker). Do not cancel or re-dispatch the job: keep watching, since it carries on once the process is back. If a local process exits again, read `log_path` and fix the cause before another `up` |
| any | `spcs_orchestrator.state` / `spcs_worker.state` is `suspended` or `not_running`, or `local_orchestrator` / `local_worker` is `false` for a recorded `local` placement (`spcs_worker` is read only when the project runs one) | The service that must run the workflow is down | **Critical.** Tell the user which one; offer `data_infrastructure(mode="up")` (orchestrator) or `scai data worker start` (SPCS worker). Do not cancel or re-dispatch the job: keep watching, since the workflow resumes once it is claimed |
| `unclaimed` | `spcs_orchestrator.state` is `starting` | The orchestrator is still coming up (a cold compute pool can take minutes) | **Warning.** Say so and keep watching; a second `unclaimed` stall is **Critical** |
| `unclaimed` | every recorded service running | The workflow row is still `pending`: no orchestrator has claimed it yet | Any `spcs_orchestrator.deployed_affinity` is **Critical**: the orchestrator must carry none, or it only claims workflows with that label (see [Affinity reference](../../../../data-infrastructure/references/affinity-reference.md#when-affinity-is-the-cause-of-a-stall)). Otherwise the orchestrator initializes claimed workflows one at a time, so if another of this project's data jobs was launched shortly before and has not started a table yet, say this one is likely queued behind it (**Warning**). With neither, say the orchestrator is up but not claiming; it is **Critical** on the second `unclaimed` stall |
| `no_change` | every recorded service running | Work is claimed but stopped moving | **Warning.** If no table has started, compare the workflow YAML's top-level `affinity` with the worker's — `spcs_worker.deployed_affinity` (each service's in `spcs_worker.services` when several run), or `[application].affinity` in `.scai/config/dew_configuration.toml` for a local worker (status does not report it); a mismatch is **Critical**. Otherwise read the stall `summary` for a workflow status, then [Troubleshooting Reference](./troubleshooting-reference.md) |
| any | `state: "unavailable"` | Status could not be read | **Warning.** Say so; keep watching |

A `stalled` event is a diagnosis trigger, not a progress report: never answer it with "still running" alone.

When **`reports`** is present, also scan `details.reports.files.errors` — any rows mean at least one task/partition has failed even if aggregate counters look healthy.

**What to tell the user** (short; do not block waiting unless they ask to stop):

```markdown
**Migration health** — `<workflowName or "starting…">`
- Loaded partitions: <loaded>/<total> (<pct>%)
- **Warning:** No partition progress in <N> minutes.  <!-- stall -->
- **Critical:** No partition progress in <N> minutes.  <!-- stuck -->
- <N> table(s) with failed partitions: `t1`, `t2`
- Preprocessing incomplete: <preprocessed>/<total> tables
```

On **Warning** or **Critical**, point to [Troubleshooting Reference](./troubleshooting-reference.md) (stale `TASK_QUEUE` tasks, worker DB mismatch, affinity). Do **not** auto-cancel the workflow — offer: keep waiting, open troubleshooting, or pause/teardown if the user wants to stop cost.

Fold the worst severity seen while waiting into the SKILL.md Step 6 report's **Infrastructure** or **Load** only if it was never surfaced to the user.

A stall or stuck warning does **not** end monitoring — only a `terminal` event does.

When a job fails before a workflow exists, the failure text is in the job's `summary` — surface it under **Infrastructure** in `### Errors`.

## Stalled after a session restart

`job_status` reports a live job `status: "stalled"` with `stalled_because` when the local worker or orchestrator recorded for this project is not running (`polled_status` keeps what the last poll read). Nothing will move it until one is back. Tell the user, then offer `data_infrastructure(mode="up")`, which starts them again so the job resumes, or `data_infrastructure(mode="down", force=true)`, which cancels the job so the next run starts a new one. Do not stamp the task or edit the relay files.
