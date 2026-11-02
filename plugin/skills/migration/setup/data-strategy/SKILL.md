---
name: data-strategy
description: Capture the data migration + validation strategy (migration type, sync strategy, extraction strategy, target table type; validation type + sync strategy) by driving the data-migration-setup and data-validation-setup wizards to completion.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# Capture Data Strategy

Capture the project's **data migration and validation strategy** by driving the existing
`data-migration-setup` and `data-validation-setup` wizards to completion. This skill only **drives**
those two wizards — it asks no new questions of its own (the questions live in those machines) and makes
no assumptions about who invoked it. Deciding *whether* to capture the strategy is the caller's job; when
this skill runs, it runs the wizards.

For a Snowflake-source validation-only project, skip Step 1 and run only the
validation wizard in Step 2. Snowflake is already the source and target, so
data migration is not available.

## Step 1 — Migration strategy (non-Snowflake sources only)

Drive the `data-migration-setup` machine to completion: call `progress_setup(mode="data_migration")` in a
loop until the response's `completed` is `true` — ask each response's `next_prompt` (plus any `then_ask`,
in the same turn) and send the answers back with `progress_setup(mode="data_migration", answers={...})`.

**Ask the whole strategy on one card.** Before the first question, also call
`progress_setup(mode="data_validation")` (read only — no answers). Put the migration
`next_prompt`, its `then_ask` (the extraction method), and the validation `next_prompt` in **one**
`ask_user_question` call, up to four questions, each with its options in the order the machine gives
(recommended first). Then send each machine its own answers: the migration ones with
`mode="data_migration"` and the validation one with `mode="data_validation"`. Ask a follow-up card only
for what the answers newly opened (Redshift target table type, an incremental validation sync strategy).

The migration wizard does **not** ask for an incremental sync strategy (checksum / watermark). That
choice needs each table's columns, so it is made per table when the workflow is generated
(`migrate_data(mode="setup")`); see the data-migration action's Step 2a. Do not ask it here unless
the user volunteers one, in which case pass it as `sync_strategy=` to `migrate_data(mode="setup")`.

For a full or preliminary load into native tables the wizard then asks what a re-run does to the rows
already in the target: `full-replace` (delete them before loading) or `none` (append). Neither is
right for every user, so present both as the machine gives them and let the user pick; Iceberg targets
take `none` only and skip the question.

If the strategy was already chosen (e.g. a prior migration set it lazily), the first call returns
`completed: true` immediately — do not re-prompt.

### Target table type before extraction

For Redshift, Teradata, and SQL Server the wizard asks the **target table type** (native vs Iceberg)
**before** the extraction strategy, because Iceberg narrows which extraction mechanisms are valid: an
Iceberg target loads from external cloud storage, so only cloud strategies that unload Parquet there are
offered (SQL Server → `cet_as` / `cloud_direct`, Redshift → `unload` / `cloud_direct`, Teradata →
`write_nos` / `cloud_direct`) — worker internal-stage reads (`odbc`, `bcp`) are not. Iceberg is valid
only when the source object is fully relational; if the source is itself an Iceberg (or
external / catalog-backed) table, do not continue. Other dialects skip the table-type question and go
straight to their extraction ladder.

Make the Iceberg support boundary explicit when presenting the choice: the supported Iceberg target is a
**Snowflake-managed Iceberg table (spec v2 or v3) on an external volume** with `storageMode: compatible`
(or `native` on v3) — external / AWS-Glue / other catalogs are not supported. If that is not what the user wants, they should
pick **native** tables. When the user picks Iceberg the wizard then asks the **spec** (v2 default, or v3)
and, after the extraction strategy, the **load mode** (`ADD_FILES_COPY` default, or `FULL_INGEST`); both
persist to `plugin.yml` (`data_migration_iceberg_spec` / `data_migration_load_mode`).

### Extraction prerequisite contract

Extraction options are ordered best-first for each dialect. Present each option's full description:
selecting it is the user's explicit confirmation that its listed source/cloud/worker prerequisites can
be met. Do not infer readiness from table size and do not silently choose the first option. If the user
cannot confirm the preferred method, walk down to the next option.

This selection is an **attestation**, not a live probe. For a server/cloud method (`unload`,
`write_nos`, `dbms_cloud`, `cet_as`, `export_data`, `cloud_direct`), the later
`migrate_data(mode="setup")` call needs the fully-qualified Snowflake `external_stage` the first time
and writes it with the strategy; re-runs inherit whatever the workflow already records. Setup then runs
Data Doctor for evidence; `migrate_data(mode="run")` validates the workflow again and fails closed
before dispatch. Worker methods (`odbc`, `bcp`, `pg_copy`, `tpt`) persist as the method but write
workflow strategy `regular`; `data_infrastructure(mode="up")` applies their TOML flag.

`odbc` and `regular` are **not** interchangeable. `odbc` is the explicit driver-read rung and turns the
dialect's worker bulk flag off. Bare `regular` is the legacy value from before this ladder and means
"leave the worker config as it is" — it is what projects configured earlier already hold, and setup
deliberately does not reinterpret it as a driver read. Record `odbc` when the user picks that rung.

## Step 2 — Validation strategy

Then drive the `data-validation-setup` machine the same way: `progress_setup(mode="data_validation")` in
a loop until `completed`. An already-chosen strategy returns `completed: true` at once.

The choices persist to `plugin.yml` as `data_migration_type`,
`data_migration_extraction_strategy` (the user-facing method, including worker methods),
`data_migration_target_table_type` (asked only for Redshift, Teradata, and SQL Server),
`data_validation_type`, and
`data_validation_sync_strategy`. `data_migration_sync_strategy` is set by the re-run question or an
explicit `migrate_data(mode="setup", sync_strategy=...)`.

## Changing an existing choice

Only the main/setup agent changes persisted strategy. A per-object
`migrateData` / `validateData` subagent must return the request to its parent
instead of re-running setup or changing infrastructure.

When the user explicitly asks for a different strategy, confirm the new choice
once and apply it through the corresponding setup tool. For example, changing
an existing full load to incremental watermark means calling
`migrate_data(mode="setup", migration_type="incremental",
sync_strategy="watermark", force_regenerate=true, where=...)`, then reviewing
the regenerated workflow and setting its real `watermarkColumn` (plus
`primaryKeyColumns` / `trackModifications` when required for an already
populated target). Explicit setup arguments persist the new defaults in
`plugin.yml`; subsequent object dispatches reuse them without asking again.
Only these strategy knobs persist: `target_schema` and the validation toggles
apply to their own call, and a `subagent_mode` call persists nothing.

If the change also affects placement or worker prerequisites, return through
[`../../data-infrastructure/SKILL.md`](../../data-infrastructure/SKILL.md)
before resuming dispatch.

> Infrastructure readiness (compute pool / orchestrator service) is **not** covered here — that is the
> shared `../../data-infrastructure/SKILL.md`. This skill only captures the data strategy.

Return control to the caller.
