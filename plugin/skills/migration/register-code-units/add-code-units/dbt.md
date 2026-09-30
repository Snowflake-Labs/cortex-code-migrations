---
name: add-code-units-dbt
description: Register a dbt project as code units. The dbt variant of add-code-units — the project root is the source path, sc-tag splitting and ETL import do not apply. Triggers: add dbt code, register dbt project, dbt code add.
parent_skill: add-code-units
license: Proprietary. See License-Skills for complete terms
---

# Add Local Source Code — dbt

Entered from `add-code-units/SKILL.md` when the workload is dbt. Replaces Steps 1
through 4 of the common path; rejoin it at Step 5.

## Step 1: Locate the Project Root

**Do NOT ask where the source files are.** The directory containing `dbt_project.yml`
*is* the source path. Announce it and proceed:

> **dbt project detected** at `<DBT_PROJECT_ROOT>` — registering the whole project
> (`models/`, `macros/`, `tests/`, `seed/`). No path needed.

Use the dbt project **root**, never a subdirectory. Passing `models/` silently drops
`macros/`, which is where dialect-specific SQL that most needs repointing lives.

## Step 2: Register

dbt models are already one-object-per-file, so the common path's sc-tag splitting and
ETL import steps do not apply. Never ask the ETL or source-connection questions for a
dbt workload.

Run exactly this command, then jump to Step 5 of `add-code-units/SKILL.md`:

```bash
scai code add -i <DBT_PROJECT_ROOT> --code-already-split --json
```

`--code-already-split` is **required and unconditional** here, not something to discover
by trial. Because the splitting step is skipped, the source files carry no
`/* <sc-...> */` boundary tags; for Redshift, Teradata, Postgres, and SQL Server the
arrange engine demands them and fails with `ADD0010: Source files must contain SC tags`.
dbt input is structurally one-model-per-file and never tagged, so the flag is always
correct on this path — same reasoning as `code conversion-only` hardcoding `--skip-split`.
Never issue the bare `code add` for a dbt project first.

`scai code add` classifies the dbt files and the `DbtProjectRegistrar` records a
`kind = "custom"` entry marked `source.customKind = "dbt"` (the registry's `kind` enum
has no `dbt` variant; `customKind` is its extension point).
