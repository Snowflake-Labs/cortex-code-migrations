# Cortex Code Migrations

Cortex plugin for AI-assisted database migration to Snowflake.

## Overview

This plugin provides migration skills, hooks, and an MCP server for use with Snowflake's Cortex platform. It supports end-to-end database migration including assessment, conversion, validation, and deployment.

## Installation

Follow the [official documentation](https://docs.snowflake.com/en/migrations/snowconvert-docs/general/user-guide/snowconvert/migration-skill/skill) to install and configure the plugin.

## Structure

```
plugin/
├── .cortex-plugin/   — Plugin manifest (plugin.json)
├── hooks/            — Session start hooks (auto-install dependencies)
├── mcp-server/       — MCP server configuration and binaries
├── skills/           — Migration skills and prompts
├── .mcp.json         — MCP server definition
└── VERSION           — Current plugin version
```

## Branches

| Branch    | Purpose                        |
|-----------|--------------------------------|
| `main`    | Stable production release      |
| `preview` | Pre-release for beta testing   |

## License

License
Copyright (c) Snowflake Inc. All rights reserved.

The skills in this project are licensed under the [Snowflake Skills License](./License-Skills).

All other content is licensed under the Apache 2.0 license.
