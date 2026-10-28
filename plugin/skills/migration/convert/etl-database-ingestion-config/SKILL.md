---
name: etl-database-ingestion-config
description: Author, edit, or skip database-ingestion-config.json before an SSIS or Informatica conversion. Skip leaves conversion unchanged. An invalid file stops conversion and names the JSON path. Triggers: database ingestion config, which tables to land, landing database, configure change tracking, configure CDC.
parent_skill: convert
license: Proprietary. See License-Skills for complete terms
---

# Database ingestion config

## On Entry

Tell the user:
> **Database ingestion config** — this file is optional and it is read at conversion time. Skip it and relational objects keep their converted names. I'll write `source/_etl/database-ingestion-config.json` only after you choose the rules and the validator accepts them.

## Step 1: Ask

Ask via `ask_user_question` (`multiSelect = false`):

> "Relational sources can be selected for Snowflake landing before conversion. What should I do with `database-ingestion-config.json`?"
>
> 1. **Author** — write a new schema 1.0 file.
> 2. **Edit** — load the file that is already there.
> 3. **Skip** — leave conversion unchanged.

**Wait for the user's response — do not proceed until they choose.**

**Skip:** leave the directory untouched. Tell the user conversion will not classify relational objects as ingestion, then return to [../SKILL.md](../SKILL.md) Step 3.

**Edit when `source/_etl/database-ingestion-config.json` is absent:** say so and ask again with Author and Skip only.

The engine reads exactly one file of that name under `source/_etl/`. Write that path.

## Step 2: Collect the document

Load [references/schema.md](./references/schema.md) and collect only the fields the user names. Leave out a field they did not ask for, including engine defaults.

## Step 3: Validate, then write

From this skill's `scripts/` directory, validate before the file is written:

```
python3 database_ingestion_config.py validate -
```

Pass the JSON on stdin. On failure the script prints one message that includes the JSON path. Show that message, correct the document, and validate again. Conversion stays at this step while the on-disk file is invalid.

On an edit, confirm the rewrite kept the user's fields:

```
python3 database_ingestion_config.py round-trip source/_etl/database-ingestion-config.json
```

Keys that were present stay present. Keys they did not set stay absent. Write the file only after validate exits 0.

## Step 4: Return

Tell the user whether the file was written, edited, or skipped, and the path when one exists. Return to [../SKILL.md](../SKILL.md) Step 3. Conversion is that skill's next step.
