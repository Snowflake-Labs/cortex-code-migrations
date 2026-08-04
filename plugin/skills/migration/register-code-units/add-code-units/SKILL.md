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

Ask the user for the path to their source SQL files:

> "Where are your SQL source files located? Please provide the full path to the directory."

### Step 2: Add Code to Project

```bash
scai code add -i <INPUT_PATH> --json
```

This will:
- Copy all files from the input path to `artifacts/source_raw/`
- Arrange and process the source code
- Merge processed output into `source/`

**If files already exist** and you need to overwrite:
```bash
scai code add -i <INPUT_PATH> --overwrite --json
```

### Step 3: Verify Files Were Added

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
source/                  Arranged source files ready for conversion
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "conflicting files" error | Use `--overwrite` flag to replace existing files |
| No `.sql` files found after add | Verify input path contains valid SQL files |
| Unexpected file arrangement | Check `artifacts/source_raw/` for the original copies |

## CHECKPOINT

Confirm with user:
- [ ] `scai code add` completed without errors
- [ ] Expected number of files appear in `source/`
- [ ] File structure looks correct

## On Completion

After the CHECKPOINT passes, tell the user. Fill placeholders from the JSON envelope returned by `scai code add --json`.

> **Import complete.** `<filesCopied>` SQL files imported as `<codeUnitsAdded>` code units, broken down by type (filled from `byType`). Files in `source/`.
> *If `etlFilesAdded > 0`:* ETL: `<etlFilesAdded>` files added.
> *If `etlFilesSkippedInvalidSchema > 0`:* `<etlFilesSkippedInvalidSchema>` ETL files skipped due to invalid schema.
> Next, we'll convert these to Snowflake SQL.

Then return to the calling skill.
