---
name: setup
description: Set up a migration project — connect to source, initialize, extract objects, convert, and assess. Covers steps 1-5 of the migration lifecycle.
license: Proprietary. See License-Skills for complete terms
---

# Migration Setup

## On Entry

Tell the user:
> **Phase 1: Setup** — I'll walk you through connecting to your source database, initializing the project, registering your objects, converting them to Snowflake SQL, and generating an assessment report. Once you've seen the assessment I'll ask whether you want to go on to migrating objects.

For a Snowflake source, use this instead:
> **Snowflake Validation Setup** — I'll initialize a Snowflake-source project,
> configure the Snowflake target and orchestrator, and capture your validation
> strategy. Snowflake-source projects skip code conversion, assessment,
> deployment, data migration, testing setup, and the Data Exchange Worker.

## Install check

Before `progress_setup()` or any other tool in this flow, run `scai doctor`. Exit 0: continue. Any other exit: stop, show the output, and do not advance the state machine. If the `doctor` command is missing, this scai predates the check — continue; SessionStart already gated the install. Skip the command when this session already ran it and it exited 0.

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
   - `then_ask` — further questions to ask in the **same turn**, in
     order (see step 3)
   - `planned_steps` — remaining task ids in order
   - `completed: true` — only when the machine reached its terminal
     state; absence means "not done, keep looping"
   - `memory_warning` — this machine likely has too little RAM for the
     long step ahead, or for the autonomous run setup is about to launch
     (see step 4 and **On Completion**)
   - `privilege_warning` — with autonomous on, the project's Snowflake role
     can change account-wide settings an autonomous run could use (see
     step 4 and **On Completion**)
   - `blocked: true` (+ `blocked_on`), `errored: true` (+
     `error_reason`), `committed: [...]`, `project_initialized: false`
     — emitted only when actionable
2. If `completed` is `true`, jump to **On Completion** below.
3. If `next_prompt` is non-null:
   - **`shown_on_card: true`** — AIM already shows it, with every
     `then_ask` entry, on a card that submits the answers itself. Do not
     ask or reword it; end the turn, then call `progress_setup()` next turn.
   - **Otherwise** (e.g. Cortex Code CLI) — ask `next_prompt`, then each
     `then_ask` entry in order, in **one** `ask_user_question` call, never
     as prose. Show each option's `label`, never its `value`. Then submit
     the answers as below.

   When the user has **already** said the answer in conversation, record it
   instead of waiting or asking. Do not ask them to say it again.
   - Submit the option's `value`, never its label. If they picked
     **Something else**, submit what they typed — not `other`.
   - If they picked **Snowflake** for the dialect, omit `code_source`.
   - Use each prompt's `multi_select` value (default `false` when omitted).
     The user can pick several values when it is true. If they pick
     **None of these**
     along with any other option, drop **None of these** and submit the
     rest. If they pick only **None of these**, submit `none`. Join
     multiple values as a comma-separated string (`etl,powerbi`). The
     queued conversion-settings question stays `multiSelect = false`.
   - A prompt with `text_input` is a plain text field, not an option list.
     Show `text_input.placeholder`; if the user leaves it blank, submit
     `text_input.default_value`.
   - Send every answer you collected in **one** call:
     `progress_setup(answers={"<write_to>": "<chosen value>", ...})` —
     keys are each prompt's `write_to`, values the chosen option's
     `value` verbatim (a string, even for a number or a boolean). If they
     pick **Something else** (or type an answer that is not one of the
     listed option values), submit what they typed — not the option's
     `value`. If what they typed is a question or a request, not an
     answer ("what does each one do?"), answer it and ask that prompt
     again before you submit anything. The engine accepts any answer
     `configure` would take for that `write_to` (`autonomous_max_subagents` is any integer from 1 to
     50). That records the answers *and* returns the next step, so for
     **questions** it replaces both the separate `configure(...)` call and
     the follow-up `progress_setup()`. Go to step 2 with its response.
   - A prompt whose chosen option carries `then` is the other case —
     that answer leads somewhere specific, so you can start on it in the
     same turn (such a prompt never has `then_ask`):
     - `then.completed` → setup is done; jump to **On Completion**.
     - `then.skill` → that is the step the answer leads to. Send the
       answer with `progress_setup(answers={...})`; its response carries
       `next_skill_md` for that very step, so execute it from there
       rather than Reading the file. `then` gives you the route early —
       what to tell the user, and what's coming — while the body arrives
       once, for the branch actually taken.
     - a `then` with only `task` → that step is already satisfied; send
       the answer and act on whatever the response names.
     If that response names the same `next_task` you just acted on, the
     step did not complete — do **not** run its skill again. Re-running it
     re-asks questions the user just answered; instead do what that skill
     says to do when it can't finish (e.g.
     `progress_setup(skip="<task>")`).

   If the user has **already** answered one of these questions in
   conversation — "move on to migration", "I'll use SQL Server" — don't
   ask it again. Put it straight in `answers` on your next call. An
   answer for a step that is already settled is harmless: the walk still
   decides what runs next, so a premature or unnecessary answer costs
   nothing.

   `answers` is for **questions the engine asked you**. Values a
   *sub-skill* tells you to set — `project_dir_confirmed`,
   `source_connection`, `git_main_branch`, `snowflake_database` — go
   through `configure(...)` as that skill instructs; that is what it is
   for, and those steps are not prompts. Folding one into `answers`
   anyway is tolerated rather than an error, but it is not the path.
4. Otherwise (no prompt): if `next_skill_md` is set, **execute its
   instructions directly in this same turn** — no Read needed.
   Otherwise **load the skill at `next_skill` immediately** (Read it,
   then execute in the same turn). When `memory_warning` or
   `privilege_warning` is set, tell the user its text in one sentence
   first, then start the sub-skill; skip it when you already told them
   that same text. The sub-skill is responsible for
   asking the user any question it needs. Do not surface "Next step
   pending: X — let me know" prose and wait — that's a wasted
   round-trip; the user already said "continue" upstream. When the
   sub-skill returns, go back to step 1.

   **Do not recap what the machine already settled.** `completed_tasks`
   names questions that were answered, not things the project has, and the
   user watched themselves answer them. `migration_extras=none` means the
   user said there is no ETL, Power BI, or Tableau to include — telling
   them "extras are recorded" states the opposite of their answer. Say what
   you are about to do instead. When a settled value genuinely matters to
   the step, name the value ("no extras", "SQL Server via
   `tastybytes-src`"), never the fact that it is on file.

Note: `progress_setup()` also handles git commits automatically — when a
task with `commitOnComplete` completes, the tool commits and pushes
project files. You do not need to run git commands manually.

Tasks the machine routes through, in order. Sub-skill paths below are relative
to the `migration/` skill root, **not** to this file's directory — `dbt/setup.md`
means `migration/dbt/setup.md`, a sibling of `setup/`.

| Task id                          | How the agent handles it                                          |
|----------------------------------|-------------------------------------------------------------------|
| `validateEmptyDir`               | sub-skill: `setup/validate-empty-dir.md`                          |
| `confirmProjectDir`              | sub-skill: `setup/confirm-project-dir.md`                         |
| `detectDbt`                      | router — auto-routes a detected dbt workload to `dbtSetup`, else the normal flow |
| `dbtSetup`                       | sub-skill: `dbt/setup.md` (dbt path only — resolves dialect from profiles.yml, inits) |
| `recommendSafeTools`             | inline prompt — arrives with the next two queued in `then_ask`     |
| `chooseSourceDialect`            | inline prompt — first card; `then_ask` queues extract, extras, and conversion settings (`askWith`). Snowflake omits `code_source`. In AIM (`shown_on_card`), the app renders this card from `progress_setup` without waiting for the model. |
| Snowflake branch                 | after dialect: `configureSnowflakeTarget` → `setupDataInfrastructure` → `dataStrategy` (validation-only; skips conversion) |
| `chooseEntryMode`                | inline prompt (queued; nothing queues after it — it routes by dialect) |
| `midwayEntry`                    | sub-skill: `setup/midway-entry.md`                                |
| `chooseCodeSource`               | inline prompt — extract vs. local files; asked on the same card as `chooseSourceDialect` when that is the current prompt. Each answer carries its `then` |
| `configureExtractionSource`      | inline `next_prompt` listing existing connections when scai has any (extract all objects from the picked database). Otherwise sub-skill: `setup/configure-source-connection.md` |
| `chooseMigrationExtras`          | inline prompt — **multi-select** extras (ETL / Power BI / Tableau / None). Arrives with `chooseConversionSettings` queued in `then_ask`. Both are asked as in step 3, never as yes/no questions. Stores `migration_extras` (and derived `has_etl_code` / `has_power_bi` / `has_tableau`). |
| `chooseConversionSettings`       | inline prompt (queued in `then_ask` from `chooseMigrationExtras`). Stores `tailor_conversion_settings` for the `convert` skill. |
| `registerCode`                   | sub-skill: `register-code-units/SKILL.md`                         |
| `convertCode`                    | sub-skill: `convert/SKILL.md`                                     |
| `dbtRepoint`                     | sub-skill: `dbt/SKILL.md` (dbt path only — agentic YAML/macro refinement after `--dbt`) |
| `runAssessment`                  | sub-skill: `assessment/SKILL.md`                                  |
| `chooseEtlFlow`                  | inline prompt (`next_prompt`) — recommended stabilize-first vs. validate-first ETL routing; writes `etl_flow=stabilize|validate`, then continues to `continueToMigration` |
| `continueToMigration`            | inline prompt (`next_prompt`) — continue into migration setup or stop at the assessment report; autonomous only |
| `chooseRunMode`                  | inline prompt (`next_prompt`) — pick manual vs autonomous run mode; each answer carries its `then` |
| `chooseAutonomousSubagentCount`  | inline prompt (`next_prompt`) — autonomous only; persist the project-wide concurrent sub-agent limit |
| `configureGit`                   | sub-skill: `setup/git.md`                                         |
| Default (non-Snowflake) branch   | `configureGit` → `configureSandboxProfile` → `chooseTestingPath`  |
| Snowflake-source branch          | `configureSnowflakeTarget` → `setupDataInfrastructure` → `dataStrategy` (skips sandbox profile) |
| `configureSandboxProfile`        | sub-skill: `setup/configure-sandbox-profile.md` — authoritative source + Snowflake connections and database bindings for migration execution |
| `configureSnowflakeTarget`       | sub-skill: `setup/configure-snowflake-target.md` (Snowflake-source path only) |
| `configureTesting`               | sub-skill: `setup/configure-testing.md`                           |
| `generateTestbed`                | sub-skill: `migrate-objects/baseline-capture/testbed-generator/SKILL.md` (bootstrap coupling state; table walkers generate/load CSVs later) |
| `setupDataInfrastructure`        | sub-skill: `data-infrastructure/SKILL.md`                         |
| `dataStrategy`                   | sub-skill: `setup/data-strategy/SKILL.md`                         |

Conversion and assessment come first on purpose: neither needs a Snowflake
target, so a user reaches their assessment report before opting into
migration setup. The ETL flow choice follows assessment; the continue gate
follows that, then run mode. Everything else — git included — follows the
`chooseRunMode` prompt.

The milestone commits (`registerCode`, `convertCode`, `runAssessment`) need git,
which is configured after that prompt, so they land together on the first
`progress_setup()` after `configureGit`.

The `assessment` skill's closing menu asks whether to move on, not how to run,
so on "Move on to migration" it submits
`progress_setup(answers={"continue_to_migration": "true"})`. Never answer
`run_mode` on the user's behalf there or anywhere else: manual vs autonomous is
the `chooseRunMode` prompt's question, and submitting a value for it marks the
question answered (`run_mode_confirmed`) so the user is never shown it.

The testing choice also decides the last step: **testbed** (and legacy
**synthetic**) walks into `generateTestbed` to bootstrap non-table coupling
state, while **source-data** ends setup right after `configureTesting`. In the
testbed path, each dependency-ready table walker later generates and loads its
own CSV before per-object tests use `generateTestCases`; they do not use
`seedSynthetic`.

If `progress_setup()` returns an unexpected `next_task` not listed above,
surface the raw response to the user and stop — do not invent a skill
path.

## Skipping an optional step

To skip an optional setup step for this run, call
`progress_setup(mode="setup", skip="runAssessment")`. The response
resolves the next step exactly as a normal call would (for the last step,
`completed: true`) — act on it directly. Nothing is persisted, so the step
is offered again later; for a permanent opt-out use
`configure(tasks={"runAssessment": {"enabled": false}})`.

Trust `progress_setup()` / related MCP return values for what is done vs
pending — do not invent completion from chat history.

## Sub-Skills Reference

| Stage | Sub-skill | Location |
|-------|-----------|----------|
| 1 | sql-server-connection | `../connection/sql-server-connection/SKILL.md` |
| 1 | redshift-connection | `../connection/redshift-connection/SKILL.md` |
| 1 | oracle-connection | `../connection/oracle-connection/SKILL.md` |
| 1 | teradata-connection | `../connection/teradata-connection/SKILL.md` |
| 1 | postgresql-connection | `../connection/postgresql-connection/SKILL.md` |
| 1 | azure-synapse-connection | `../connection/azure-synapse-connection/SKILL.md` |
| 1 | db2-connection | `../connection/db2-connection/SKILL.md` |
| 1 | bigquery-connection | `../connection/bigquery-connection/SKILL.md` |
| 1 | snowflake-connection (source and target for validation-only projects) | `../connection/snowflake-connection/SKILL.md` |
| — | midway-entry (existing project with pre-converted code; SQL Server/Redshift only) | `./midway-entry.md` |
| 3 | register-code-units | `../register-code-units/SKILL.md` |
| 4 | convert | `../convert/SKILL.md` |
| 4 | code-conversion-only | `../code-conversion-only/SKILL.md` |
| 5 | snowconvert-assessment | `../assessment/SKILL.md` |
| — | configure-snowflake-target (post-assessment: connection + database) | `./configure-snowflake-target.md` |
| — | configure-testing (post-assessment: source-data vs synthetic) | `./configure-testing.md` |
| — | data-infrastructure-setup | `../data-infrastructure/SKILL.md` |
| — | data-strategy | `./data-strategy/SKILL.md` |
| — | data-migration-setup | `../migrate-objects/actions/data-migration/SKILL.md` |
| — | data-validation-setup | `./data-validation/SKILL.md` |
| — | l3-pushdown-setup | `./data-validation/l3-pushdown/SKILL.md` |
| — | data-infrastructure-teardown | `../data-infrastructure/teardown/SKILL.md` |
| — | discover-extras (custom assets the engine doesn't generate — FiveTran, SSAS, Oracle PACKAGE, scripts) | `./discover-extras/SKILL.md` |

## Rules

1. **Follow sub-skill instructions** — Complete each sub-skill fully before returning
2. **Confirm transitions through the machine** — stage gates arrive as `progress_setup` prompts (`continueToMigration`, `chooseRunMode`); ask those when they come, and otherwise continue into the next sub-skill in the same turn (step 4)
3. **A requested stop is the end of this run** — If the user asked to stop after conversion, stop when conversion is done. Do not load `../assessment/SKILL.md` and do not run `scai assessment`, even when `progress_setup` names assessment as the next task. Tell the user assessment is the next stage and wait.
4. **Turn the local dashboard on once `plugin.yml` exists** — It does not start by itself. Call `configure(dashboard_port=-1)` so `.scai/config/plugin.yml` records the default port. Skip only when the user opts out.

## On Completion

When the setup machine reaches `setupComplete`, close out in the
interactive migration path. Do not mention autonomous mode or a sub-agent
limit, except that when the payload carries `memory_warning` or
`privilege_warning`, tell the user its text in one sentence before the
close-out, even if you said it before: the autonomous run starts right after.

**If setup ended early** (e.g. `chooseRunMode` permanently excluded via
`configure(tasks=…)`) — close without nudging toward migration.

**If they completed migration setup** and the Snowflake target and testing path are set:
> **Setup complete** — Your migration project is configured: connected to <source_type>, <N> objects registered, code converted, assessment generated, and your Snowflake target (`<snowflake_database>`) and testing path are set. Ready to start migrating objects.
>
> Every step along the way was committed to git. This is a good time
> to share the project with your team — the next phase (object
> migration) is designed to be multi-user, with multiple engineers
> working through waves in parallel.

Then return to the parent migration skill.
