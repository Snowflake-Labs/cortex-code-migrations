---
name: midway-entry
description: Bring an existing migration project into scai when you already have both source SQL and pre-converted Snowflake SQL on disk. Skips registration and conversion. SQL Server and Redshift only. Triggers: midway entry, existing project, already converted, bring project to snowflake, import converted project, pre-converted code.
parent_skill: setup
license: Proprietary. See License-Skills for complete terms
---

# Midway Entry

## On Entry

Tell the user:
> **Midway Entry** — I'll bring your existing project into scai. This path is for projects that already have both source SQL and pre-converted Snowflake SQL on disk. We'll skip registration and conversion and jump straight to assessment.

## When To Use This Skill

Use midway entry when **all** of the following are true:
- You already have source SQL files on disk.
- You already have converted Snowflake SQL files on disk.
- Your source dialect is **SQL Server** or **Redshift**. Other dialects are not supported by this path.

If any of these is not true, use the normal setup flow (`../SKILL.md`) instead.

## Prerequisites

- **Target directory is empty** — midway entry initializes a new scai project in place.
- **Source dialect**: `sqlserver` or `redshift`.
- **Source files**: one `CREATE ___` per file.
- **Mirrored layout**: `source/` and `snowflake/` inputs must share the same relative paths and filenames (nested subdirectories are fine).

## Workflow

### Step 1: Collect Inputs

Ask the user (one prompt, four answers):

1. **Target project directory** — default to the current working directory. Must be empty. If not empty, offer to create a subdirectory (e.g. `<cwd>/<name>-migration`).
2. **Source dialect** —
   > 1. **SQL Server**
   > 2. **Redshift**
   >
   > (Oracle/Teradata are not supported for midway entry — fall back to the normal setup path.)
3. **Path to source SQL files** — a directory whose contents mirror the converted directory.
4. **Path to converted Snowflake SQL files** — a directory whose contents mirror the source directory.

### Step 2: Audit The Inputs

Before running sync, inspect the customer's directories and decide whether they already meet the requirements or need pre-processing.

Run a quick audit:

```bash
# 1. Count files and extensions
find <SOURCE_PATH> -type f | wc -l
find <SNOWFLAKE_PATH> -type f | wc -l
find <SOURCE_PATH> -type f -not -name "*.sql" | head
find <SNOWFLAKE_PATH> -type f -not -name "*.sql" | head

# 2. Check for multiple CREATEs per file (flag anything with >1 top-level CREATE)
#    Use grep -ciE to get a rough count per file; anything >1 needs splitting.
grep -ciE '^[[:space:]]*(CREATE|ALTER)[[:space:]]+(OR[[:space:]]+REPLACE[[:space:]]+)?(TABLE|VIEW|PROCEDURE|FUNCTION|TRIGGER|SEQUENCE|SCHEMA|TYPE|INDEX|DATABASE|SYNONYM|ROLE)' \
  <SOURCE_PATH>/**/*.sql 2>/dev/null | awk -F: '$2>1'

# 3. Check mirror: list relative paths from each and diff
(cd <SOURCE_PATH> && find . -type f -name "*.sql" | sort) > /tmp/src.lst
(cd <SNOWFLAKE_PATH> && find . -type f -name "*.sql" | sort) > /tmp/sf.lst
diff /tmp/src.lst /tmp/sf.lst | head -40
```

Based on the audit, pick one of two branches:

- **(A) Clean already** — every file has exactly one top-level `CREATE`, and relative paths match 1:1 between source and snowflake. Skip to Step 3 using the customer paths directly.
- **(B) Needs pre-processing** — any of: multiple CREATEs per file, non-SQL files mixed in, missing or extra files on one side, differing filenames for the same object, differing directory layouts. Go to Step 2b.

### Step 2b: Plan And Build Cleaned, Mirrored Inputs

**Goal:** produce two new directories — `<WORK_DIR>/source_processed/` and `<WORK_DIR>/snowflake_processed/` — that are (1) SQL-only, (2) split so each file contains a single `CREATE ___`, and (3) mirrored (same set of relative paths).

Do **not** modify the customer's original directories. Always write to new intermediate dirs under a work area.

> **Important:** the work dir must live **outside** `<TARGET_DIR>`. `scai code sync` requires the target to be completely empty, and a nested `.midway_work/` will trip the "Project directory is not empty" check (error `PRJ0001`). Default the work dir to temp directory, e.g. `tmp/.midway_work/` or something else the user prefers. Never use `<TARGET_DIR>/.midway_work/`.

**Plan first, then act.** Before touching files, present the user with a short plan that includes:

1. **Inventory** — for each side: total files, file types, sample nested layout (depth and top-level groupings).
2. **Split candidates** — count of files containing multiple top-level CREATEs on each side.
3. **Mismatch summary** — files in source but not in snowflake (and vice versa), and any naming drift (e.g. `mytable.sql` vs `MyTable.sql`).
4. **Naming convention for outputs** — recommend one of:
   - `<database_if_exists>/<schema>/<object_type>/<object_name>.sql` (good for SnowConvert-style inputs),
   - `<schema>/<object_name>.sql` (flatter),
   - flat `<object_name>.sql` (only if no schema collisions).
   Pick the scheme that best preserves existing grouping while guaranteeing uniqueness. Qualify filenames with schema to avoid collisions.
5. **Proposed actions per file** — for each customer file, state: keep / drop (not-SQL) / split into N files / rename to `<new relative path>` / pair with snowflake counterpart at `<new relative path>`.

Ask the user to confirm the plan before proceeding.

**Execution rules:**

- Walk each input tree; for every `.sql` file, detect top-level `CREATE ___` statements. Split on those boundaries, preserving comments and a leading `USE DATABASE/SCHEMA` or `SET` statements that apply to each block. Write each piece to its own file named `<object_name>.sql` (lowercase) under the chosen relative path.
- When a source file and a snowflake file both split into multiple objects, produce matching relative paths on both sides. If counts don't line up, surface the object-name mismatch to the user and ask how to pair them.
- Drop non-SQL files (and note them to the user). Never silently discard a file that has a `CREATE` in it.
- After building the two dirs, re-run the audit from Step 2 to confirm counts and `diff` is empty. If not, iterate before calling sync.
- Record what you did in a manifest (e.g. `<WORK_DIR>/split_manifest.json` mapping original → produced paths) so the operation is reviewable.

**Tooling:** for non-trivial splits, prefer a small scripted pass (python/awk) over ad-hoc sed. Do not write to the customer's original paths.

After pre-processing succeeds, pass the cleaned directories (`source_processed/`, `snowflake_processed/`) as the `--input` / `--snowflake` arguments in Step 3.

### Step 3: Run `scai code sync`

```bash
scai code sync <TARGET_DIR> -l <sqlserver|redshift> \
  --input <SOURCE_PATH> \
  --snowflake <SNOWFLAKE_PATH>
```

Example:

```bash
scai code sync . -l redshift \
  --input ../source_processed \
  --snowflake ../snowflake_processed
```

This creates the scai project in `<TARGET_DIR>`, populates `source/` and `snowflake/` from the two input paths, and records the source dialect. Any source/snowflake mismatches are surfaced by `scai code sync` itself — read its output before proceeding.

### Step 4: Verify

```bash
# Project scaffolding exists
ls -la .scai source snowflake artifacts

# File counts
find source -name "*.sql" | wc -l
find snowflake -name "*.sql" | wc -l
```

Then call `migration_status`. Expect:
- `routing.project_exists = true`
- `routing.registered = true`
- `routing.converted = true`
- `routing.assessed = false`

### Step 5: Checkpoint

Confirm with the user:
- [ ] `scai code sync` completed without errors
- [ ] `source/` and `snowflake/` both contain the expected files
- [ ] `migration_status` reports registered + converted + not assessed

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Target directory not empty | Pick (or create) an empty target, or move existing files out first. Make sure `.midway_work/` lives **outside** the target. |
| Unsupported source dialect | Oracle/Teradata are not supported — use the standard setup flow (`../SKILL.md`). |
| `scai code sync` reports source/snowflake mismatch | Review its diff output, reconcile the two input directories, re-run. |
| Files have multiple `CREATE` statements per file | Split each file so it contains a single `CREATE ___` before re-running sync. |

## On Completion

After the CHECKPOINT passes, tell the user:
> **Midway entry complete** — Your project is initialized with <N> source files and <M> converted files. Skipping registration and conversion. Next up: assessment.

Then load `../../assessment/SKILL.md`.
