---
name: register-code-units
description: Register source code into the migration project — either by extracting from a live database or importing local SQL files.
license: Proprietary. See License-Skills for complete terms
---

# Register Source Code

## On Entry

Tell the user:
> **Register Source Code** — We need to get your source database objects into the project so they can be converted. You can extract them directly from your database or import local SQL files.

## Step 1: Ask How to Register

Ask the user:
> "How would you like to add source code?"
> 1. **Extract from database** - Pull DDL/code from a connected source database
> 2. **Add local files** - Import SQL files from a local directory

## Step 2: Route

- If **Extract from database** → Load `extract-code-units/SKILL.md`
- If **Add local files** → Load `add-code-units/SKILL.md`

## Sub-Skills

| Sub-skill | Location |
|-----------|----------|
| extract-code-units | `extract-code-units/SKILL.md` |
| add-code-units | `add-code-units/SKILL.md` |
