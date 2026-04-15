# snowflake-migration MCP Server

Rust MCP server that exposes Snowflake database migration tools — registry status, rule engine, testing orchestrator, deployment, and direct SQL execution — to any MCP-compatible client.

Uses an embedded Python interpreter (via PyO3) for Snowflake connectivity through `snowflake-snowpark-python`.

## Tools

### Configuration

| Tool | Description |
|------|-------------|
| `configure` | Set session defaults: `project_dir`, `source_connection`, `snowflake_connection`, `snowflake_database`. Call once at session start. |

### Local (no Snowflake connection needed)

| Tool | Description |
|------|-------------|
| `migration_status` | Full project status from registry (by-type counts, stage totals, routing flags) |
| `update_registry` | Update registry fields |
| `update_testing` | Update testing status from test results |
| `query_registry` | Query the project registry with SQL-like filters |
| `next_object` | Get next procedure/function to migrate (dependency-aware) |
| `testing_progress` | Testing progress summary (passed, failed, ready, blocked) |

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
| `migrate_data` | Migrate data from source to Snowflake (async, background job). Uses SPCS orchestrator + worker when `configure(compute_pool=...)` is set and a workflow config exists. |
| `migrate_data_status` | Check status of a data migration job. Includes per-table progress in `progress`. |

## Building

```bash
# Build binary + install Python deps
crates/mcp-server/build-plugin.sh
```

This builds the Rust binary to `plugin/mcp-server/bin/` and runs `uv sync` to install `snowflake-snowpark-python` in a local venv.

## Running

```bash
# Via wrapper (sets up PYTHONPATH automatically)
plugin/mcp-server/run.sh
```

The wrapper finds the venv's `site-packages`, sets `PYTHONPATH`, and execs the binary.

## Dependencies

- Rust toolchain (for building)
- Python 3.11+ (runtime, for Snowpark)
- [uv](https://github.com/astral-sh/uv) (for managing the Python venv)
- `scai` CLI on PATH (for `deploy`, `query_source`, `migrate_data`)
- Snowflake connection configured in `~/.snowflake/connections.toml`

## License

Copyright (c) Snowflake Inc. All rights reserved.

Licensed under the [Apache 2.0 license](https://www.apache.org/licenses/LICENSE-2.0).
