---
name: setup
description: Set up a migration project — connect to source, initialize, extract objects, convert, and assess. Covers steps 1-5 of the migration lifecycle.
license: Proprietary. See License-Skills for complete terms
---

# Migration Setup

## On Entry

Tell the user:
> **Phase 1: Setup** — I'll walk you through connecting to your source database, initializing the project, registering your objects, converting them to Snowflake SQL, and generating an assessment report.

## Flow

Setup is driven by the **`setup` state machine** — the resolver picks
the next step automatically. The flow:

1. Call `progress_setup()`. The response carries the following keys
   when relevant — fields that would otherwise be the no-op default
   (`completed: false`, `blocked: false`, etc.) are omitted to keep
   responses small:
   - `next_task` — id of the task the resolver landed on
   - `next_skill` — sub-skill path to load (omitted when the task is
     handled inline via `next_prompt`)
   - `next_skill_md` — when present, the **full body** of the skill at
     `next_skill`. Execute it directly without calling Read. Only
     emitted for skills small enough to inline; for larger ones (or
     any skill not in the inline set), `next_skill` is the path and
     you Read it normally.
   - `next_prompt` — present when the task is an inline question (see
     step 3 below)
   - `planned_steps` — remaining task ids in order
   - `completed: true` — only when the machine reached its terminal
     state; absence means "not done, keep looping"
   - `blocked: true` (+ `blocked_on`), `errored: true` (+
     `error_reason`), `committed: [...]`, `project_initialized: false`
     — emitted only when actionable
2. If `completed` is `true`, jump to **On Completion** below.
3. If `next_prompt` is non-null, the engine wants you to ask the user a
   question directly — no sub-skill load required. Surface the prompt
   exactly as the engine returned it via `ask_user_question` (`multiSelect = false`):
   - `next_prompt.question` is the question text.
   - `next_prompt.options` is the list of `{label, value, description?}`
     entries to render. Use `label` as the user-facing choice; **never**
     show `value` to the user.
   - When the user answers, call
     `configure(<next_prompt.write_to>=<chosen option's value>)` to
     persist the answer. Then go back to step 1.
4. Otherwise (no prompt): if `next_skill_md` is set, **execute its
   instructions directly in this same turn** — no Read needed.
   Otherwise **load the skill at `next_skill` immediately** (Read it,
   then execute in the same turn). The sub-skill is responsible for
   asking the user any question it needs. Do not surface "Next step
   pending: X — let me know" prose and wait — that's a wasted
   round-trip; the user already said "continue" upstream. When the
   sub-skill returns, go back to step 1.

Note: `progress_setup()` also handles git commits automatically — when a
task with `commitOnComplete` completes, the tool commits and pushes
project files. You do not need to run git commands manually.

Tasks the machine routes through, in order:

| Task id                          | How the agent handles it                                          |
|----------------------------------|-------------------------------------------------------------------|
| `configureProjectDir`            | sub-skill: `setup/configure-project.md`                           |
| `enableDashboard`                | inline prompt (`next_prompt`) — no sub-skill load                 |
| `recommendSafeTools`             | inline prompt (`next_prompt`) — no sub-skill load                 |
| `chooseSourceDialect`            | inline prompt (`next_prompt`) — no sub-skill load                 |
| `chooseEntryMode`                | inline prompt (`next_prompt`) — no sub-skill load                 |
| `midwayEntry`                    | sub-skill: `setup/midway-entry.md`                                |
| `configureSnowflakeConnection`   | sub-skill: `setup/configure-snowflake-connection.md`              |
| `configureSourceConnection`      | sub-skill: `setup/configure-source-connection.md`                 |
| `configureGit`                   | sub-skill: `setup/git.md`                                         |
| `registerCode`                   | sub-skill: `register-code-units/SKILL.md`                         |
| `convertCode`                    | sub-skill: `convert/SKILL.md`                                     |
| `runAssessment`                  | sub-skill: `assessment/SKILL.md`                                  |

If `progress_setup()` returns an unexpected `next_task` not listed above,
surface the raw response to the user and stop — do not invent a skill
path.

## Sub-Skills Reference

| Stage | Sub-skill | Location |
|-------|-----------|----------|
| 1 | sql-server-connection | `../connection/sql-server-connection/SKILL.md` |
| 1 | redshift-connection | `../connection/redshift-connection/SKILL.md` |
| 1 | oracle-connection | `../connection/oracle-connection/SKILL.md` |
| 1 | teradata-connection | `../connection/teradata-connection/SKILL.md` |
| 1 | postgresql-connection | `../connection/postgresql-connection/SKILL.md` |
| — | midway-entry (existing project with pre-converted code; SQL Server/Redshift only) | `./midway-entry.md` |
| 3 | register-code-units | `../register-code-units/SKILL.md` |
| 4 | convert | `../convert/SKILL.md` |
| 4 | code-conversion-only | `../code-conversion-only/SKILL.md` |
| 5 | snowconvert-assessment | `../assessment/SKILL.md` |
| — | data-infrastructure-setup | `../data-infrastructure/SKILL.md` |
| — | data-migration-setup | `../migrate-objects/actions/data-migration/SKILL.md` |
| — | data-validation-setup | `./data-validation/SKILL.md` |
| — | data-infrastructure-teardown | `../data-infrastructure/teardown/SKILL.md` |

## Rules

1. **Follow sub-skill instructions** — Complete each sub-skill fully before returning
2. **Confirm transitions** — Ask user before moving to next stage

## On Completion

When the setup machine reaches `setupComplete`, tell the user:
> **Setup complete** — Your migration project is configured: connected to <source_type>, <N> objects registered, code converted, and assessment generated. Ready to start migrating objects to Snowflake.
>
> Every step along the way was committed to git. This is a good time
> to share the project with your team — the next phase (object
> migration) is designed to be multi-user, with multiple engineers
> working through waves in parallel.

Then return to the parent migration skill.
