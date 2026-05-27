---
name: configure-project
description: Configure the migration project directory and confirm with the user before initializing.
license: Proprietary. See License-Skills for complete terms
---

# Configure project directory

This skill is invoked by the **setup state machine** as the first step of
project initialization. It corresponds to "Step A.1" of the legacy
`setup/SKILL.md`.

## When invoked

The setup machine returns this task when `config.projectInitialized` is
not yet truthy in the project view. In practice this means the user
hasn't run `configure(project_dir=...)` against an empty project
directory yet.

## What to do

Use `directory_empty` from the most recent `migration_status` response
(or call it again if you don't have it):

- If `directory_empty` is **false**, tell the user:
  > This directory isn't empty, so we can't initialize a project here.
  > Would you like to create one in a new subdirectory?

  Suggest `<current_dir>/<database>-migration` or let the user pick.
  Once confirmed, call `configure(project_dir=<new_path>)`.

- If `directory_empty` is **true**, confirm the location with the user:
  > I'll use `<project_dir>` for the migration project. Can you confirm?

  If the user wants a different location, call
  `configure(project_dir=<new_path>)`.

## On completion

Return to the parent setup skill — the resolver will pick the next task
on the next `progress_setup()` call.
