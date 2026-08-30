# snowflake-migration MCP Server

Rust MCP server that exposes Snowflake database migration tools — registry status, rule engine, testing orchestrator, deployment, and direct SQL execution — to any MCP-compatible client.

Snowflake connectivity runs through the `scai` CLI: the server spawns `scai mcp worker` as a persistent JSON-over-stdio subprocess and reuses it for all rule-engine, registry, and schema SQL. Builds with `--features universal-driver` use in-process `sf_core` instead, with a bounded session pool (`MIGRATION_SQL_POOL_SIZE`, default 8, `1` = serial). No Python runtime is required.

## Tools

### Configuration

| Tool | Description |
|------|-------------|
| `configure` | Set session defaults: `project_dir`, `source_connection`, `snowflake_connection`, `snowflake_database`, `dashboard_port`. Call once at session start. Also `subagent_mode` (process latch) and `require_independent_override_accept` (persisted to plugin.yml) — see below. |

### Per-agent identity (`subagent_mode`)

One MCP session serves an orchestrator and every subagent under it, so the transport cannot tell two callers apart (measured on stdio and streamable HTTP alike — the session tracks the client process, not the caller). An orchestrator that dispatches subagents calls `configure(subagent_mode=true)` once; from then on `transition_status` and `update_registry` require an `agent_id`. `deploy`, `migrate_data` and `validate_data` do **not** yet — see the note below.

- Four lowercase hex digits. The **server** mints them and hands one out with each object in `migration_status(mode="next_objects")` and with each `answered` entry in `mode="escalations"`; an id the process never issued is refused.
- `transition_status(status="begin")` records the id on the object's claim, and every later write for that object must carry the same one. A write aimed at an object another agent holds is refused, naming both agents.
- `override_accept_case` is refused for the claim holder (the runTests walker) unless `.scai/config/plugin.yml` has `require_independent_override_accept: false`. After the fix loop, spawn one `test_case_verifier` with fresh context for the remaining failing cases on that object. Do not set `subagent_mode` for that — the latch is the autonomous orchestrator's, before dispatching walkers. Omitting `agent_id` is refused only after that latch is already on; a verifier that configures without an id is minted one. On by default (key absent or `true`).
- `0000` is the orchestrator's, for `reset`, `escalate`, `review`, and `answer` that is not an object-level outcome. It cannot `begin`, `finish`, stamp, `bypass`, `note`, `mark_done`, or `skip`.
- The mode lasts the life of the server: omitting the parameter leaves it as it is, and `false` does not switch it off. Sessions that never set it are unaffected — `agent_id` stays optional and no id is minted.
- After the latch is on, a later `configure` is attach-only: it names the caller (`agent_id`, or a mint when omitted), the Snowflake connection / target catalog, and `metadata_database` (ORCHESTRATION / RULE_ENGINE / `VALIDATION.RESULTS` — not the migration target), and announces any live job to that id. It does not bind a dashboard, persist plugin.yml, or rewrite session defaults. Walkers pass their minted id; a `test_case_verifier` omits it.
- **Not yet covered:** `deploy`, `migrate_data`, `validate_data`. They mutate one object's state and belong in a second pass. Their damage is at least visible — each stamps the registry, so a write to an object the agent never claimed shows up on the board as a stamp with no matching claim — and the skill text forbids it. `update_registry` is in scope precisely because it has no such tell: its wildcard field mapping reaches any `codeStatus.*` / `cloudStatus.*` path, so an unattributed call there advances an object while writing nothing to `TASK_EVENTS`.

### Local dashboard (opt-in)

The server can host a small read-only HTML dashboard on `127.0.0.1` (no data leaves the host). It is **off by default** — enable it one of three ways:

- **Per project (persisted):** call `configure(dashboard_port=-1)` for the default port `7878`, or `configure(dashboard_port=<port>)` for an explicit port. The chosen port is saved to `.scai/config/plugin.yml` and the dashboard auto-starts on every future MCP session for that project. To opt out later, remove `dashboard_port` from `plugin.yml`.
- **One-shot, no persistence:** set `MIGRATION_DASHBOARD_ADDR=127.0.0.1:7878` (or any `host:port`) before launching the server. The env var is checked once at startup and never written to disk.
- **Idempotent:** repeat `configure(dashboard_port=...)` calls report the existing URL instead of re-binding. Bind failures (e.g. port already in use) are surfaced in the `configure` response, so the agent can offer a different port.

### Local (no Snowflake connection needed)

| Tool | Description |
|------|-------------|
| `migration_status` | Project status. `mode="summary"` (default) returns by-type counts, stage totals, routing flags. `mode="next_objects"` pulls main and returns the next ready objects in the current wave plus any of the current user's open claims. `mode="next_task"` walks one object's machine; a walker passes `agent_id` so a `blockedOn` migrate/validate registers a `wait` and can return `waiting`. `mode="collaborators"` returns objects other Snowflake users are currently working on (latest open claim per object, where the claimant isn't the current user). |
| `transition_status` | Drive the per-object git+claim lifecycle. `status="start"` checks out a feature branch, fetches and rebases onto `<git_remote_name>/<git_main_branch>`, and claims the object. `status="done"` commits, fast-forward-merges into main, pushes, and marks the claim completed. Returns structured JSON errors on dirty tree, missing config, or merge conflict. |
| `update_registry` | Update registry fields |
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
| `deploy` | Deploy objects via `scai code deploy` (single `object_name` or `where` filter) |
| `query_source` | Run a SQL query against the source database via `scai query` |
| `migrate_data` | Two-mode tool. `mode="setup"` requires `where` and generates a per-`where` workflow YAML at `artifacts/data_migration/workflows/<hash>.yaml` (forwarding `where` to scai's `--where`); `where` is **not** stored on the session. Wave-level knobs persist under `data_migration:` in `plugin.yml`. The agent reviews/edits before running. `mode="run"` takes the `workflow_path` and binds objects from that file's `tables:` list (pure dispatch against the shared orchestrator + worker). |
| `validate_data` | Validate migrated data between source and Snowflake. `mode="setup"` generates workflow YAML; `mode="run"` executes it; `mode="revalidate"` retries failed partitions from a finished parent workflow. Uses cloud validation (SPCS) when configured. |
| `job_status` | Report long-running job state. `monitor=true` starts the background relay and returns `orchestrator_watch` (wake instructions for the parent) plus a per-job `watch_command`; `wait=true` blocks until the next wake line (`0000` / omitted `agent_id` also needs `confirm=true`, otherwise a reminder is returned and the call does not block); `wake=true` re-attaches a walker to a job it already dispatched (dependents do not use this — `next_task` registers that wait); `details=true` attaches the full status payload plus parsed CSV failure reports (`details.reports.files`). |

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

`scai mcp run` locates the binary next to the `scai` executable (or via `MIGRATION_MCP_SERVER_BIN`) and runs it with inherited stdio.

## Dependencies

- Rust toolchain (for building)
- `scai` CLI on PATH — all Snowflake connectivity (`scai mcp worker`) plus `deploy`, `query_source`, `migrate_data`
- Snowflake connection configured in `~/.snowflake/connections.toml`

## License

Copyright (c) Snowflake Inc. All rights reserved.

Licensed under the [Apache 2.0 license](https://www.apache.org/licenses/LICENSE-2.0).
