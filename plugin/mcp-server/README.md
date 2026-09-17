# snowflake-migration MCP Server

Rust MCP server that exposes Snowflake database migration tools — registry status, rule engine, testing orchestrator, deployment, and direct SQL execution — to any MCP-compatible client.

Snowflake connectivity runs through the `scai` CLI: the server spawns `scai mcp worker` as a persistent JSON-over-stdio subprocess and reuses it for all rule-engine, registry, and schema SQL. Builds with `--features universal-driver` use in-process `sf_core` instead, with a bounded session pool (`MIGRATION_SQL_POOL_SIZE`, default 8, `1` = serial). No Python runtime is required.

## Tools

### Configuration

| Tool | Description |
|------|-------------|
| `configure` | Set session defaults: `project_dir`, `source_connection`, `snowflake_connection`, `snowflake_database`, `dashboard_port`. Call once at session start. Also `subagent_mode` (process latch) and `require_independent_override_accept` (persisted to plugin.yml) — see below. |

### Per-agent identity (`subagent_mode`)

One MCP session serves an orchestrator and every subagent under it, so the transport cannot tell two callers apart (measured on stdio and streamable HTTP alike — the session tracks the client process, not the caller). Cortex stamps identity on Pre/PostToolUse (`agent_id` = child conversation session id; absent on the parent — the same payload still has `session_id`). A PreToolUse hook copies that onto every MCP `tool_input.agent_id` (always override caller-supplied values). Parent + `subagent_mode` latch → the PreToolUse `session_id` (persisted at `.scai/config/orchestrator_agent_id`). Interactive (no latch, no hook `agent_id`) → leave the call alone. Do not pass `agent_id` yourself — it is a system field.

An orchestrator that dispatches subagents calls `configure(subagent_mode=true)` once; from then on `transition_status`, `update_registry`, `deploy`, `migrate_data`, and `validate_data` require a stamped `agent_id`. The parent session id is refused on those object-mutating tools. Interactive sessions that never set the latch still omit `agent_id`.

- Any non-empty string that is not the parent session id is a walker (typically a Cortex child session UUID).
- `transition_status(status="begin")` records the stamped id on the object's claim, and every later write for that object must carry the same one. A write aimed at an object another agent holds is refused, naming both agents. A leftover first-send is a new child; `begin` reclaims a dead conversation's hold.
- `override_accept_case` is refused for the claim holder (the runTests walker) unless `.scai/config/plugin.yml` has `require_independent_override_accept: false`. After the fix loop, spawn one `test_case_verifier` with fresh context for the remaining failing cases on that object. Do not set `subagent_mode` for that — the latch is the autonomous orchestrator's, before dispatching walkers. Omitting `agent_id` is refused only after that latch is already on; Cortex stamps the verifier. On by default (key absent or `true`).
- `update_registry(patch={"dotted.path": <json>}, reason=..., objects|where=...)` is reserved for a hook-stamped `cur_reconciler`. It bypasses the normal field and object-binding allowlists and records the actor, reason, and exact patch in `TASK_EVENTS`.
- The parent session id is the orchestrator's, for `reset`, `escalate`, and `review`. It cannot `begin`, `finish`, stamp, `bypass`, `note`, `mark_done`, `skip`, `answer`, `deploy`, or dispatch `migrate_data` / `validate_data`. `status='answer'` is interactive only so that row cannot look like a person when a parent or walker writes it. A `test_case_verifier` honors override-accept from an `answered` row with `human: true`.
- The mode lasts the life of the server: omitting the parameter leaves it as it is, and `false` does not switch it off. Sessions that never set it are unaffected — `agent_id` stays optional.
- After the latch is on, a later `configure` is attach-only: it names the caller (hook-stamped `agent_id`), `source_connection`, the Snowflake connection, and `active_bindings` (the YAML whose `source:` / `snow:` maps are the catalogs to qualify against), and announces any live job to that id. It does not bind a dashboard, persist plugin.yml, or rewrite session defaults. Walkers, a `test_case_verifier`, and a `sandbox_specialist` omit `agent_id`.
- `ORCHESTRATION.AGENTS` has one row per Cortex child (and the parent session id) keyed with the MCP run as `SESSION_ID`, so `TASK_EVENTS` joins. `ORCHESTRATION.AGENT_ACTIONS` records `subagent_start`, `subagent_stop`, and MCP `tool_call` (tool name / agent_type / object_id — not prompts). Non-MCP tools such as Bash are not logged. The hub spool (`.scai/monitor`) is the live view; Snowflake is the durable log. Cortex `SubagentStart` does not carry the child prompt, so the parent's `PostToolUse` on `task` is what joins returned `agentId` to `objectId` in the prompt (and `resume` on a later send) while the walker is still `running`.

### Local dashboard (opt-in)

The server can host a small read-only HTML dashboard on `127.0.0.1` (no data leaves the host). It is **off by default** — enable it one of three ways:

- **Per project (persisted):** call `configure(dashboard_port=-1)` for the default port `7878`, or `configure(dashboard_port=<port>)` for an explicit port. The chosen port is saved to `.scai/config/plugin.yml` and the dashboard auto-starts on every future MCP session for that project. To opt out later, remove `dashboard_port` from `plugin.yml`.
- **One-shot, no persistence:** set `MIGRATION_DASHBOARD_ADDR=127.0.0.1:7878` (or any `host:port`) before launching the server. The env var is checked once at startup and never written to disk.
- **Idempotent:** repeat `configure(dashboard_port=...)` calls report the existing URL instead of re-binding. Bind failures (e.g. port already in use) are surfaced in the `configure` response, so the agent can offer a different port.

### Local (no Snowflake connection needed)

| Tool | Description |
|------|-------------|
| `migration_status` | Project status. `mode="summary"` (default) returns by-type counts, stage totals, routing flags. `mode="next_objects"` pulls main and returns the next ready objects in the current wave plus leftover open claims (`object_id`, `name` — no `agentId` to copy). `mode="next_task"` walks one object's machine; a walker's stamped `agent_id` registers a `wait` on a `blockedOn` migrate/validate so the entry can return `waiting`. `mode="collaborators"` returns objects other Snowflake users are currently working on (latest open claim per object, where the claimant isn't the current user). |
| `transition_status` | Drive the per-object git+claim lifecycle. `status="start"` checks out a feature branch, fetches and rebases onto `<git_remote_name>/<git_main_branch>`, and claims the object. `status="done"` commits, fast-forward-merges into main, pushes, and marks the claim completed. Returns structured JSON errors on dirty tree, missing config, or merge conflict. |
| `update_registry` | Scope flags, tags, and machine name. Not task status. |
| `query_registry` | Query the project registry with SQL-like filters |
| `register_units` | Register custom (`kind=custom`) units: one unit (`custom_kind`+`name`), a list (`entries`), or investigation findings (`expected_slugs`) |
| `app_info` | Report the desktop app's installed version and last app-update-check time. **App-only** — hidden from non-app callers (`SCAI_CALLER != aim-app`), so it doesn't ship to the standalone CLI. No Snowflake connection or project needed. |

### Rule engine (need Snowflake connection)

| Tool | Description |
|------|-------------|
| `search_rules` | Find migration rules matching a SQL file (regex + Cortex semantic search + EWI scan) |
| `find_similar_rules` | Search rules by text description (Cortex semantic) |
| `reverse_search_rules` | Find code units affected by a rule |
| `sync_sql_files` | Bulk sync SQL files to CODE_UNITS_SQL for rule search |
| `create_rule` | Create a new migration rule |
| `list_rules` | List migration rules with optional filters |
| `record_rule_application` | Record a rule application outcome |

### Deployment & data

| Tool | Description |
|------|-------------|
| `deploy` | Deploy converted objects via `scai code deploy`. Three walker calls: (1) `sandbox=true` omit `mode` = transitive closure into the sandbox (creates `AIMSBX_*` unless leftover yaml already names the pair — then no DROP/CLONE, but still deploys tables, functions, views, and this object); (2) `sandbox=true` `mode=redeploy_object` = this object only into a live pair; (3) omit `sandbox` = this object only onto the common catalogs. Procedures take (1) as the `deploySandbox` task and (3) after tests. `mode=reload_tables` reloads closure CSVs (wipes AIMSBX DML). |
| `setup_sandbox` | Shared source catalog: source DDL (CREATE skipped when the object already exists) plus testbed load for tables. `mode=load_only` reloads this object's CSV. Failure JSON carries `failure_class` (SQL 547 is `fixture_fk`; unmapped is `other`), `sample_rows`, and `next_invocation`. |
| `run_tests` | `mode="validate"` (default) runs `scai test validate`; `mode="capture"` runs `scai test capture`. Injects `--profile` / `--database-bindings` from the session pair; bound isolation only on validate when restore is set. |
| `query_source` | Run a SQL query against the source database via `scai query` (TEMP: writes allowed — CREATE / ALTER / EXEC) |
| `testbed` | Drive one Synthetic Testbed Generator phase (`phase` = mine \| validate \| enrich \| compile \| generate) via `scai testbed`. Each phase is idempotent (its view file is the completion predicate) and resumes from on-disk state; returns `{phase, rc, message}`. The deterministic critics, envelope assembly, ledger, and quarantine loop are native Rust (`src/testbed/`) — the LLM boundary stays the on-disk `fragments/` + `verdict.json` handoff. Replaces the former Python `run_pipeline.py` orchestration. |
| `migrate_data` | Two-mode tool. `mode="setup"` requires `where` and generates a per-`where` workflow YAML at `artifacts/data_migration/workflows/<hash>.yaml` (forwarding `where` to scai's `--where`); `where` is **not** stored on the session. Wave-level knobs persist under `data_migration:` in `plugin.yml`. The agent reviews/edits before running. `mode="run"` takes the `workflow_path` and binds objects from that file's `tables:` list (pure dispatch against the shared orchestrator + worker). |
| `validate_data` | Validate migrated data between source and Snowflake. `mode="setup"` generates workflow YAML; `mode="run"` executes it; `mode="revalidate"` retries failed partitions from a finished parent workflow. Uses cloud validation (SPCS) when configured. |
| `job_status` | Report long-running job state. A per-job Monitor terminal event already carries the authoritative compact result in `detail.completion`; use `job_status` for on-demand status, recovery, or deeper diagnostics. Live migrate/validate polling uses the same StatusSource `TABLE_PROGRESS` probes as the object-status knowledge base (one batched Snowflake query per job type per tick). `monitor=true` starts the background relay and returns `orchestrator_watch` (wake instructions for the parent) plus a per-job `watch_command`; `wait=true` blocks until the next wake line (the parent / omitted `agent_id` also needs `confirm=true`, otherwise a reminder is returned and the call does not block); `wake=true` re-attaches a walker to a job it already dispatched (dependents do not use this — `next_task` registers that wait); `details=true` is the only path that still shells `scai data … status` (full payload plus parsed CSV failure reports in `details.reports.files`). |
| `hub` | Orchestrator view of Cortex children **and** jobs. `mode="status"` (default) drains the agent spool and returns `agents` (`running` / `idle` / `walker_running` / `walker_idle` / `by_object`), `pending_wakes`, `jobs`, reminder intervals, and `orchestrator_watch`. `by_object` joins each claimed object to the live walker `agent_id` (the Task resume id). Live dispatcher slots are `walker_running`. Stop settles a yielded walker: a parked waiter is `harvested` (not `walker_idle`) and `completed` leaves the roster. Do not call `agent_output`. `mode="wait"` is the same blocking wait as `job_status(wait=true)` (the parent needs `confirm=true`). Walkers do not call this. |

## Building

```bash
crates/mcp-server/build-plugin.sh
```

This builds the Rust binary to `plugin/mcp-server/bin/`.

## Running

```bash
# Directly
plugin/mcp-server/bin/migration-mcp-server

# Or hosted by scai (what an MCP client launches)
scai mcp run
```

`scai mcp run` locates the binary next to the `scai` executable (or via `MIGRATION_MCP_SERVER_BIN`) and runs it with inherited stdio. Cortex plugin hooks are the same binary as one-shots (`migration-mcp-server hook <name>`); `hooks/mcp-hook.cmd` finds that sibling and execs it so PreToolUse does not start the .NET apphost. The resolved path is cached at `<cwd>/.scai/tmp/mcp-server-bin` so later hooks skip the locate. SessionStart stays a plugin shell script because it installs `scai`.

## Dependencies

- Rust toolchain (for building)
- `scai` CLI on PATH — all Snowflake connectivity (`scai mcp worker`) plus `deploy`, `query_source`, `migrate_data`
- Snowflake connection configured in `~/.snowflake/connections.toml`

## License

Copyright (c) Snowflake Inc. All rights reserved.

Licensed under the [Apache 2.0 license](https://www.apache.org/licenses/LICENSE-2.0).
