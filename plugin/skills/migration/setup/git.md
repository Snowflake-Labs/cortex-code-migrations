---
name: git-setup
description: Set up git for a migration project
license: Proprietary. See License-Skills for complete terms
---

# Git Setup

## On Entry

Tell the user:

> **Git setup for collaboration.** This project will be shared via git
> so that multiple people (or agents) can work on the migration in
> parallel.
>
> **How collaboration works:**
> - **One person** creates the migration project and runs through setup
>   (that's you, right now).
> - After setup, the project is pushed to a shared git remote (e.g.
>   GitHub, GitLab, Bitbucket).
> - **Teammates** clone the repo and run `configure()` to join the
>   project. From there, each person claims objects and works on their
>   own feature branches.
> - The plugin commits and pushes progress automatically at key
>   milestones (after extraction, conversion, and assessment).
>
> To set this up I need this folder to be a git repository with a remote.

## Step 1: Inspect current git state

Call:

```
configure(needs_git=true)
```

The response includes a `git_status` block:

```yaml
git_status:
  is_git_repo: <true|false>
  current_branch: <branch or empty>
  remote_url: <origin url or empty>
  configured_main_branch: <branch or empty>
```

Use this to drive the next step. **Do not run any `git` commands yourself**
to inspect state — `configure(needs_git=true)` is the source of truth.

## Step 2: Ensure the folder is a git repository

**If `git_status.is_git_repo` is `true`:**

Show the user the detected `current_branch` and `remote_url` and ask:

> "This folder is a git repository (current branch: `<current_branch>`, remote:
> `<remote_url or 'none'>`). Is this the repo you want to use for the migration
> project?"
>
> 1. **Yes** — continue to Step 3.
> 2. **No** — ask the user to switch into the correct repository (or
>    re-clone) and let you know when it's ready. Then re-run
>    `configure(needs_git=true)` and continue.

**If `git_status.is_git_repo` is `false`:**

Tell the user:

> "This folder isn't a git repository yet. Migrations need a repo so I can
> branch per object and merge work back to main. Can you set one up for this
> folder and let me know when it's ready?"
>
> 1. **I'll set it up myself** — wait for the user to confirm, then re-run
>    `configure(needs_git=true)` and continue.
> 2. **Help me set it up** — initialize a fresh repo on the user's behalf:
>    ```bash
>    git init
>    git add -A
>    git commit -m "Initial migration project"
>    ```
>    Then tell the user they will need to push it to a remote (e.g. GitHub).
>    Once the user creates the remote repository themselves and tells you
>    the URL, run:
>    ```bash
>    git remote add origin <url>
>    git push -u origin <current-branch>
>    ```
>
> If any of these commands fails, surface the raw stderr to the user and wait
> for them to resolve it. **Do not run any other `git` commands to "clean up"
> state on your own** — limit yourself to the four commands above.

After the repo is in place, re-run `configure(needs_git=true)` so you have a
fresh `git_status` snapshot before continuing.

## Step 3: Pick the main branch

Use `git_status.current_branch` as the suggested default.

Ask the user:

> "Which branch should I treat as the main migration branch?" (default:
> `<current_branch>`)
>
> This is the long-lived branch that per-object feature branches will rebase
> onto and fast-forward-merge back into.

If `git_status.configured_main_branch` is already set and matches what the
user wants, you can skip the persist call. Otherwise, persist with:

```
configure(git_main_branch="<branch>")
```
