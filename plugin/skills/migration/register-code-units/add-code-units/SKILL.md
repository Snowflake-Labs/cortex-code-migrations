---
name: add-code-units
description: Add local source code files to a migration project using scai code add. Use when source SQL files are already available on disk instead of extracting from a live database. Triggers: add code, import files, local files, add source, scai code add.
parent_skill: register-code-units
license: Proprietary. See License-Skills for complete terms
---

# Add Local Source Code

## On Entry

Tell the user:
> **Importing local SQL files.**
>
> I'll handle this for you — importing your local SQL files and organizing them by type into `source/`, ready for conversion. It's a single automated step; you won't need to copy, arrange, or move anything yourself.

## Prerequisites

- Migration project initialized (`scai init`)
- Local directory containing SQL source files

## Workflow

### Step 1: Get Source Path

If the session's `workload` is `dbt`, load `dbt.md` instead of Steps 1–4, then rejoin at Step 5.

Otherwise, ask the user for the path to their source SQL files:

> "Where are your SQL source files located? Please provide the full path to the directory."

### Step 2: Annotate Multi-Object Files with sc-tags

`scai code add` uses the arrange engine to split files into one object per code unit. For non-T-SQL dialects the engine splits on `/* <sc-...> */` boundary tags. Before importing, call the `split_code` MCP tool to detect files that need tags (more than one top-level object, or one object and no SC tag yet) and inject those tags automatically.

```
split_code(input_path="<INPUT_PATH>")
```

- If no file needs tags, the tool says so and you can skip ahead to Step 3 using `<INPUT_PATH>` directly.
- Otherwise the tool copies all files to `artifacts/source_split/` (leaving out macOS `__MACOSX/` / `._*` metadata), injects the sc-tags, verifies the result, and tells you to use `artifacts/source_split` as the input for Step 3.
- If it lists files that still have no SC tag, apply the fix it gives for each before Step 3 — do not fall back to `--code-already-split`.

The tool handles the full detect → inject → verify cycle in one call. It is OS-agnostic and does not require Python.

**Example** — what the tool injects before each object in a multi-object file:

```sql
/* <sc-table>sales.public.customers</sc-table> */
CREATE TABLE sales.public.customers (
  id INT,
  name VARCHAR(100)
);

/* <sc-view>sales.public.v_active_customers</sc-view> */
CREATE VIEW sales.public.v_active_customers AS
SELECT * FROM sales.public.customers WHERE active = 1;
```

> **T-SQL note:** T-SQL files do not need this step — the engine has a native T-SQL splitter. Skip Step 2 for T-SQL source files.

### Step 3: Add Code to Project

Use the path returned by `split_code` (or `<INPUT_PATH>` directly if no file needed tags):

```bash
scai code add -i <INPUT_PATH> --json
```

**dbt projects use this form instead** — always, with no exceptions:

```bash
scai code add -i <DBT_PROJECT_PATH> --code-already-split --json
```

Step 2 is skipped for dbt, so the files have no SC tags; `--code-already-split` tells the arrange
engine the input is already one object per file. Without it the command fails with `ADD0010`.

This will:
- Copy all files from the input path to `artifacts/source_raw/`
- Arrange and process the source code
- Merge processed output into `source/`

**If files already exist** and you need to overwrite:
```bash
scai code add -i <INPUT_PATH> --overwrite --json
```

### Step 4: Import ETL

**Skip this entire step for a dbt project.** If Step 1 found `dbt_project.yml`, do **not** ask the
ETL question — a dbt workload has no SSIS or Informatica packages, and asking it is a defect. Go
straight to Step 5 without calling `ask_user_question`.

ETL belongs in the project from register onward. Read `has_etl_code` from `configure()` (set by
`chooseMigrationExtras` or by the parent register skill's extras card). Never ask a standalone ETL
yes/no — that question lives only on the extras multi-select.

- If `has_etl_code` is **`false`** (explicitly): the user already said no ETL — proceed to Step 5 without asking.
- If `has_etl_code` is **not set**: return to the parent register skill and collect the extras card there, then re-read `has_etl_code`. Do not invent a yes/no.
- If `has_etl_code` is **`true`** (explicitly): open [etl.md](etl.md) and follow it. That file holds the ETL import
  steps: which directory each platform uses, and how each unit is registered as `kind: etl`. Come
  back here at Step 5 when it finishes. Do not register ETL as `customKind`.

### Step 5: Import Power BI templates

Power BI template (`.pbit`) files are inventory only: `code add` copies them to
`source/BI/PowerBI/` and `artifacts/BI/PowerBI/` and never sends them to the conversion engine.
Read `has_power_bi` from `configure()`:

- If `has_power_bi` is **`false`**, proceed to Step 6 without asking.
- If `has_power_bi` is not set, return to the parent register skill and collect
  the extras card, then re-read it.
- If `has_power_bi` is **`true`**, first check whether Step 3 already imported
  `.pbit` files. If it did, proceed to Step 6. Otherwise ask only for the folder
  path and compare it to `<INPUT_PATH>`:
  - If it is **the same as, or inside, `<INPUT_PATH>`**, Step 3 already imported it — `code add` claims `.pbit` files anywhere under the input path. Proceed to Step 6 without running a second `code add`.
  - Otherwise (a genuinely separate folder) run:

```bash
scai code add -i <POWER_BI_PATH> --json
```

Do **not** pass `--overwrite` here — existing SQL/ETL in `source/` would be wiped.

Confirm files landed in both `source/BI/PowerBI/` and `artifacts/BI/PowerBI/` before continuing.

### Step 6: Verify Files Were Added

Check that `source/` contains the expected `.sql` files and report a count. Use whichever portable form fits the host:

```bash
# macOS / Linux
find source/ -name "*.sql" | head -20
find source/ -name "*.sql" | wc -l
```

```powershell
# Windows PowerShell
Get-ChildItem -Recurse -Filter *.sql source/ | Select-Object -First 20
(Get-ChildItem -Recurse -Filter *.sql source/).Count
```

## Output Structure

```
artifacts/source_raw/    Original files copied from input path
artifacts/source_split/  sc-tag annotated copies (only created when some file needed tags)
source/                  Arranged source files ready for conversion
source/_etl/             ETL packages (when present)
source/BI/PowerBI/       Power BI `.pbit` templates (inventory only, not converted)
artifacts/BI/PowerBI/    Same relative layout as `source/BI/PowerBI/`
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "conflicting files" error | Use `--overwrite` flag to replace existing files |
| `ADD0010: Source files must contain SC tags` | The arrange engine found no `/* <sc-...> */` boundary tags. For a **dbt project**, re-run with `--code-already-split` (required on every dbt add). For a non-dbt source, run Step 2 (`split_code`) first and pass the returned `artifacts/source_split/` path. |
| No `.sql` files found after add | Verify input path contains valid SQL files |
| Unexpected file arrangement | Check `artifacts/source_raw/` for the original copies |
| `split_code` reports verification errors | Manually inspect flagged files; the tool lists each with its boundary and tag counts |

## CHECKPOINT

Check these yourself against the `--json` envelope. Do **not** turn them into a
question — the envelope already says what was imported, and the user cannot
verify a count you just computed for them:

- [ ] `scai code add` exited without errors
- [ ] `filesCopied` matches the SQL files in the input path
- [ ] `.sql` files are present under `source/`
- [ ] If Power BI was imported: files exist in both `source/BI/PowerBI/` and `artifacts/BI/PowerBI/`

Stop and ask only when a check fails: say which one, and what you propose to do
about it.

## On Completion

After the CHECKPOINT passes, tell the user — a statement, not a question. Fill placeholders from the JSON envelope returned by `scai code add --json`.

> **Import complete.** `<filesCopied>` SQL files imported as `<codeUnitsAdded>` code units, broken down by type (filled from `byType`). Files in `source/`.
> *If `etlFilesAdded > 0`:* ETL: `<etlFilesAdded>` files added.
> *If `etlFilesSkippedInvalidSchema > 0`:* `<etlFilesSkippedInvalidSchema>` ETL files skipped due to invalid schema.
> *If Power BI files were added:* Power BI templates copied to `source/BI/PowerBI/` and `artifacts/BI/PowerBI/` (not converted).
> Next, we'll convert these to Snowflake SQL.

Then return to the calling skill **in this same turn**. That last line announces
the next step; it is not a stopping point. Under setup, call `progress_setup()`
now and start the step it names. Ending the turn on it leaves the user watching
an idle screen with nothing to click until they type "continue".
