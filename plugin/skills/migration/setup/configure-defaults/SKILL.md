---
name: configure-defaults
description: Prompt the user after project creation to choose shared vs local project defaults, explain the difference, and apply project-scoped defaults with scai commands.
license: Proprietary. See License-Skills for complete terms
---

# Configure Defaults After Project Creation

Use this skill immediately after:

1. Source connections have been created or selected, and
2. The migration project has been initialized with `scai init`.

This step helps the user choose how to store project defaults:

- **Shared project defaults** in `.scai/config/project.yml`
- **Workspace-local defaults** in `.scai/config/project.local.yml`

## What these files mean

- **`.scai/config/project.yml` (shared):**
  - Intended to be committed and shared with the team.
  - Use for stable project-wide defaults everyone should use.
- **`.scai/config/project.local.yml` (local):**
  - Machine/workspace-specific overrides.
  - Typically gitignored and not shared.
  - Use when each developer needs different default values.

## Step 1: Prompt for preference

Ask the user:

> "Project created and connections registered. How would you like to configure defaults now?"
>
> 1. **Shared project defaults** — save to `.scai/config/project.yml`
> 2. **Local project defaults** — save to `.scai/config/project.local.yml` (`--local`)
> 3. **Skip for now** — continue setup without changing defaults

If the user chooses **Skip for now**, return to the parent setup flow.

## Step 2A: Shared project defaults path

Run `scai project defaults set` without `--local` using the values the user wants to share.

Example (shared):

```bash
scai project defaults set \
  -s <SOURCE_CONNECTION_NAME> \
  -c <SNOWFLAKE_CONNECTION_NAME> \
  --warehouse <WAREHOUSE> \
  --database <DATABASE> \
  --schema <SCHEMA> \
  --role <ROLE>
```

## Step 2B: Local project defaults path

Run `scai project defaults set --local` using values intended only for this workspace.

Example (local):

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

Notes:

- Include only options the user wants to set now.
- `defaults set` requires at least one option.
- Without `--local`, values are written to `.scai/config/project.yml` (shared).
- With `--local`, values are written to `.scai/config/project.local.yml` (typically gitignored).
- For detailed flags, unset behavior, and precedence, see [REFERENCE.md](references/REFERENCE.md).

## Step 3: Confirm and return

Confirm with the user:

- [ ] Preferred defaults strategy selected
- [ ] Commands completed without errors
- [ ] Setup should continue to next parent step

Return control to `../SKILL.md`.
