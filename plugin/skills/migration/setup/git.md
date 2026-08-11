---
name: git-setup
description: Set up git for a migration project
license: Proprietary. See License-Skills for complete terms
---

# Git Setup

## On Entry

Tell the user:

> **Git is required for this migration.** Every object is converted on its
> own branch and merged back into a main branch — that is how progress is
> tracked and, if something goes wrong, how work is recovered. So the project
> needs to live in a git repository.
>
> A **remote is optional.** A purely local repository is fully supported. You
> only need a remote (GitHub, GitLab, …) if you want an off-machine backup or
> to let teammates clone the project and work in parallel. I will never push
> anywhere on my own — set a remote and progress is pushed to it; leave it and
> everything simply stays local.
>
> To continue I need this folder to be a git repository.

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
to inspect state — `configure(needs_git=true)` is the source of truth. An
empty `remote_url` is expected and needs no action.

## Step 2: Ensure the folder is a git repository

**If `git_status.is_git_repo` is `true`:**

Confirm the detected `current_branch` with the user:

> "This folder is a git repository (current branch: `<current_branch>`). Is
> this the repo you want to use for the migration project?"
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
> 2. **Help me set it up** — initialize a fresh local repo on the user's
>    behalf:
>    ```bash
>    git init
>    git add -A
>    git commit -m "Initial migration project"
>    ```
>    That local repository is all the migration needs. A remote is optional —
>    if the user wants one they can add it themselves later; don't set one up
>    or push on their behalf.
>
> If any of these commands fails, attempt to diagnose and fix the issue (e.g.
> remove a stale `.git/index.lock`, resolve a conflicting worktree state, or
> re-run with corrected options). Surface the raw stderr to the user only if
> you cannot resolve the problem after one attempt.

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

## Step 4: Explain the git workflow

After the main branch is confirmed, briefly explain how git works in this migration so the user knows what to expect:

> "Here's how git works during the migration:
>
> - When you **finish** objects, I push them directly to `<main_branch>` — no pull requests needed.
> - I regularly **fetch and rebase** your working branch onto `<main_branch>` to keep you in sync with any teammate activity.
> - If multiple people are working in parallel, each person works on their own branch and the plugin handles merging automatically.
>
> You don't need to manage branches or create PRs — the plugin handles all of that behind the scenes, and I'll tell you what happened after each operation."

Keep this concise — don't elaborate further unless the user asks questions. If they want details, point them to the [collaboration model reference](../migrate-objects/references/collaboration-model.md).

Git setup is required (`configureGit` is locked). Do not offer permanent opt-out via `tasks.configureGit.enabled=false`.
