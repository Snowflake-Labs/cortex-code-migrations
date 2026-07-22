# snowflake-migration MCP Server

Rust MCP server that exposes Snowflake database migration tools — registry status, rule engine, testing orchestrator, deployment, and direct SQL execution — to any MCP-compatible client.

Snowflake connectivity runs through the `scai` CLI: the server spawns `scai mcp worker` as a persistent JSON-over-stdio subprocess and reuses it for all rule-engine, registry, and schema SQL. No Python runtime is required.

## Tools

### Configuration

| Tool | Description |
|------|-------------|
| `configure` | Set session defaults: `project_dir`, `source_connection`, `snowflake_connection`, `snowflake_database`, `dashboard_port`. Call once at session start. |

### Local dashboard (opt-in)

The server can host a small read-only HTML dashboard on `127.0.0.1` (no data leaves the host). It is **off by default** — enable it one of three ways:

- **Per project (persisted):** call `configure(dashboard_port=-1)` for the default port `7878`, or `configure(dashboard_port=<port>)` for an explicit port. The chosen port is saved to `.scai/config/plugin.yml` and the dashboard auto-starts on every future MCP session for that project. To opt out later, remove `dashboard_port` from `plugin.yml`.
- **One-shot, no persistence:** set `MIGRATION_DASHBOARD_ADDR=127.0.0.1:7878` (or any `host:port`) before launching the server. The env var is checked once at startup and never written to disk.
- **Idempotent:** repeat `configure(dashboard_port=...)` calls report the existing URL instead of re-binding. Bind failures (e.g. port already in use) are surfaced in the `configure` response, so the agent can offer a different port.

### Local (no Snowflake connection needed)

| Tool | Description |
|------|-------------|
| `migration_status` | Project status. `mode="summary"` (default) returns by-type counts, stage totals, routing flags. `mode="next_objects"` pulls main and returns the next ready objects in the current wave plus any of the current user's open claims. `mode="collaborators"` returns objects other Snowflake users are currently working on (latest open claim per object, where the claimant isn't the current user). |
| `transition_status` | Drive the per-object git+claim lifecycle. `status="start"` checks out a feature branch, fetches and rebases onto `<git_remote_name>/<git_main_branch>`, and claims the object. `status="done"` commits, fast-forward-merges into main, pushes, and marks the claim completed. Returns structured JSON errors on dirty tree, missing config, or merge conflict. |
| `update_registry` | Update registry fields |
| `query_registry` | Query the project registry with SQL-like filters |

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
| `migrate_data` | Two-mode tool. `mode="setup"` generates a per-`where` workflow YAML at `artifacts/data_migration/workflows/<hash>.yaml` (forwarding `where` to scai's `--where`) and persists the other params under `data_migration:` in `plugin.yml` as defaults; the agent reviews/edits before running. `mode="run"` takes the `workflow_path` and starts the migration (`scai data orchestrator setup`, `scai data worker start`, then `scai data migrate create-workflow`) in the background. |
| `validate_data` | Validate migrated data between source and Snowflake. `mode="setup"` generates workflow YAML; `mode="run"` executes it; `mode="revalidate"` retries failed partitions from a finished parent workflow. Uses cloud validation (SPCS) when configured. |
| `migrate_data_status` | Check status of a data migration job. Includes per-table progress and parsed CSV failure reports (`reports.files.progress` / `errors`). |
| `validate_data_status` | Check status of a data validation job. Includes per-table progress and parsed CSV reports (`reports.files`) for schema/metrics/row detail. |

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
