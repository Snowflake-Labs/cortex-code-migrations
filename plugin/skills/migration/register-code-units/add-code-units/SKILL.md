---
name: add-code-units
description: Add local source code files to a migration project using scai code add. Use when source SQL files are already available on disk instead of extracting from a live database. Triggers: add code, import files, local files, add source, scai code add.
parent_skill: register-code-units
---

# Add Local Source Code

Add existing SQL source files from a local directory to the migration project.

## Prerequisites

- Migration project initialized (`scai init`)
- Local directory containing SQL source files

## Workflow

### Step 1: Get Source Path

Ask the user for the path to their source SQL files:

> "Where are your SQL source files located? Please provide the full path to the directory."

### Step 2: Add Code to Project

```bash
scai code add -i <INPUT_PATH>
```

This will:
- Copy all files from the input path to `artifacts/source_raw/`
- Arrange and process the source code
- Merge processed output into `source/`

**If files already exist** and you need to overwrite:
```bash
scai code add -i <INPUT_PATH> --overwrite
```

### Step 3: Verify Files Were Added

```bash
# Check source files were processed
find source/ -name "*.sql" | head -20

# Count total files
find source/ -name "*.sql" | wc -l
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

## Next Steps

After successfully adding source code:

```bash
# Convert source code to Snowflake
scai code convert
```
