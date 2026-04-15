# Configure Defaults Reference

This reference expands on `SKILL.md` for project defaults behavior.

## Scope

Project defaults are managed with:

- `scai project defaults set ...`
- `scai project defaults unset ...`

## Shared vs local files

- **Shared defaults** (no `--local`):
  - Write to `.scai/config/project.yml`
  - Intended to be committed and shared across the project
- **Local defaults** (`--local`):
  - Write to `.scai/config/project.local.yml`
  - Workspace/machine-specific and typically gitignored

`project.local.yml` is usually created when the first local default is saved; it may not exist in a fresh project.

## Supported fields

| Area | `defaults set` flags | `defaults unset` flags |
|------|----------------------|-------------------------|
| Snowflake profile (TOML connection name) | `-c` / `--connection <NAME>` | `--connection` |
| Source profile (TOML connection name) | `-s` / `--source-connection <NAME>` | `--source-connection` |
| Snowflake warehouse | `--warehouse <NAME>` | `--warehouse` |
| Snowflake database | `--database <NAME>` | `--database` |
| Snowflake schema | `--schema <NAME>` | `--schema` |
| Snowflake role | `--role <NAME>` | `--role` |

`defaults set` requires at least one option.  
`defaults unset` only clears fields whose flags are provided.

When connection/context values are provided (`-c/--connection`, `-s/--source-connection`, `--warehouse`, `--database`, `--schema`, `--role`), they are tested before saving so invalid defaults are not persisted.

## Example commands

Shared:

```bash
scai project defaults set \
  -s <SOURCE_CONNECTION_NAME> \
  -c <SNOWFLAKE_CONNECTION_NAME> \
  --warehouse <WAREHOUSE> \
  --database <DATABASE> \
  --schema <SCHEMA> \
  --role <ROLE>
```

Local:

```bash
scai project defaults set \
  --local \
  -s <SOURCE_CONNECTION_NAME> \
  -c <SNOWFLAKE_CONNECTION_NAME> \
  --warehouse <WAREHOUSE> \
  --database <DATABASE> \
  --schema <SCHEMA> \
  --role <ROLE>
```

Unset local source connection default:

```bash
scai project defaults unset --local --source-connection
```

## Precedence summary

Highest to lowest:

1. Per-command CLI flags
2. `.scai/config/project.local.yml` values (if set)
3. `.scai/config/project.yml` values (if set)
4. Saved connection profile values from TOML (when connection name resolves to a profile)

## Notes

- `scai project defaults` updates project config files; it does not rewrite connection profiles in TOML.
- `scai connection set-default` is separate behavior and not part of this defaults flow.
- For full CLI syntax, run:
  - `scai project defaults set --help`
  - `scai project defaults unset --help`
