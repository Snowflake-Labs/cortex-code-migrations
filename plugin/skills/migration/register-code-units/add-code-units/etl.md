---
name: add-code-units-etl
description: Import ETL into the project during register. SSIS and Informatica PowerCenter go under source/_etl via scai code add. Every other platform goes under source/_etl_aifirst and is registered as kind=etl. Triggers from add-code-units Step 4.
parent_skill: add-code-units
license: Proprietary. See License-Skills for complete terms
---

# Add Local Source Code — ETL

Entered from `add-code-units/SKILL.md` Step 4. Rejoin that skill at Step 5.
This file is the only place the ETL import steps live.

**Skip this entire step for a dbt project.** If Step 1 found `dbt_project.yml`, do **not** ask the
ETL question — a dbt workload has no SSIS or Informatica packages, and asking it is a defect. Go
straight to Step 5 without calling `ask_user_question`.

ETL belongs in the project from register onward. SSIS and Informatica PowerCenter
land in `source/_etl/` via `scai code add`. Every other ETL platform — Talend, Alteryx,
Informatica Cloud / IICS, DataStage, Pentaho, Azure Data Factory, or anything else the
user names — lands in `source/_etl_aifirst/<platform>/`, and its units are registered
in the Code Unit Registry with `kind: etl` and `source.objectType: workflow` via the
MCP `create_registry_unit` tool. The two roots stay apart because the native
`EtlFileClassifier` owns `source/_etl/` and only understands SSIS `.dtsx` and
PowerCenter XML repo exports. Routing `.yxmd` / `.dsx` / `.ktr` through it would
mis-arrange them.

This file is entered only when `has_etl_code` is `true`: the user already said yes on the extras
card, so never ask a standalone ETL yes/no. Ask which platform via `ask_user_question`
(`multiSelect = false`):

> "Which ETL platform is it?"
>
> 1. **SSIS** — `.dtsx` packages (native SnowConvert)
> 2. **Informatica Power Center** — XML repo export (native SnowConvert)
> 3. **Another ETL platform** — Talend, Alteryx, Informatica Cloud / IICS, DataStage,
>    Pentaho, Azure Data Factory, or something else (routes through AI-First)

- **SSIS / Informatica Power Center:** ask for the folder path and
  compare it to `<INPUT_PATH>`:
  - If it is **the same as, or inside, `<INPUT_PATH>`**, Step 3 already imported it —
    `code add` classifies and promotes ETL anywhere under the input path, not just at
    its root. Proceed to Step 5 without running a second `code add`.
  - Otherwise (a genuinely separate folder) run:

    ```bash
    scai code add -i <ETL_PATH> --json
    ```

    Do **not** pass `--overwrite` here — the SQL is already in `source/` and would be
    wiped.

  Getting the containment check wrong is not silently destructive: re-adding files
  already in `source/` fails with `ADD0007` (a conflict listing the offending files)
  rather than creating duplicate registry entries. But it is a dead end for the user,
  so check containment rather than plain path equality.

  `code add` arranges the packages into `source/_etl/`. Confirm they landed there
  before continuing.

- **Another ETL platform:**
  1. Ask which platform. Accept a free-form name if it is not in the list. Store the
     lower-case slug (`talend`, `alteryx`, `iics`, `datastage`, `pentaho`, `adf`, …).
  2. Ask for the folder path containing the platform's source documents.
  3. Copy losslessly into `source/_etl_aifirst/<platform>/` by invoking the enumeration
     helper — do **not** hand-copy files and do **not** run `scai code add` for these
     files. The helper is a lossless copy plus a per-document enumeration; it does
     **not** write any parallel manifest. Registration goes through the MCP
     `create_registry_unit` tool in step 4 below.

     ```bash
     python3 "<PLUGIN_ROOT>/register-code-units/scripts/import_aifirst_etl.py" \
       --platform <PLATFORM_SLUG> \
       --source "<ETL_PATH>" \
       --json
     ```

     `<PLUGIN_ROOT>` is this skill's grandparent directory
     (`.../plugin/skills/migration`). Add `--overwrite` if the user is re-importing on
     purpose. The helper is stdlib-only and runs anywhere Python 3.10+ is on PATH.
  4. Read back the JSON envelope. Its `units` array holds one entry per source
     document, each with the fields `create_registry_unit` needs: `unit_id`, `name`,
     `platform`, `format`, `source_file` (project-relative). Query those deterministic
     IDs first. For an ID that already exists, verify that its platform, format, and
     `files.source.path` exactly match the envelope and do not recreate it. Stop on a
     mismatch. For each missing ID, call:

     ```
     create_registry_unit(
       unit_id="<UNIT_ID>",
       name="<NAME>",
       platform="<PLATFORM_SLUG>",
       format="<FORMAT>",
       source_file="<PROJECT_RELATIVE_SOURCE_PATH>"
     )
     ```

     The MCP tool stamps `kind: etl`, `source.objectType: workflow`, keeps unlisted
     platforms under `extensions.sourcePlatform` (never faked as SSIS or Informatica),
     and refuses to overwrite an existing id. The query-before-create rule makes an
     identical re-import idempotent while preserving that refusal for collisions.

     Do **not** call `register_units` for these units and do **not** pass
     `customKind`. `register_units` creates `kind: custom` units without
     `files.source.path`, which is the exact shape this register step must not write.

  5. Verify each unit reached the registry with the shape convert expects:

     ```
     query_registry(
       where="kind = 'etl' AND extensions.sourcePlatform = '<PLATFORM_SLUG>'",
       fields="id,kind,source,files,extensions"
     )
     ```

     Confirm the response lists every `unit_id` you just created, that each row has
     `kind: "etl"`, `source.objectType: "workflow"`, and a `files.source.path` equal
     to the vendored source file. If any of that is missing, stop and tell the user
    . There is no side manifest to fall back to.

  Repeat steps 3–5 once per platform if the migration has more than one AI-First ETL
  source. Do not mix `source/_etl/` and `source/_etl_aifirst/<platform>/` for the same
  platform — SSIS / Informatica PowerCenter files live only under `source/_etl/`, and
  everything else lives only under `source/_etl_aifirst/`.

