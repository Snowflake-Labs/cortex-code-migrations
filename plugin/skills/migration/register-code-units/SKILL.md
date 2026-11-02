---
name: register-code-units
description: Register source code into the migration project — either by extracting from a live database or importing local SQL files.
license: Proprietary. See License-Skills for complete terms
---

# Register Source Code

## On Entry

Tell the user:
> **Register Source Code** — We need to get your source database objects into the project so they can be converted. You can extract them directly from your database or import local SQL files.

Open with that and nothing before it. **Do not recap** what setup already
settled — the user answered those questions and does not need them read back,
and "extras are already recorded" reads as the opposite of `migration_extras=none`
(which means there is no ETL, Power BI, or Tableau to include). Read the values
you need and act; mention one only when it changes what you are about to do.

## Step 0: Extras belong to setup's prompt

Read `migration_extras` (or `has_etl_code` / `has_power_bi` / `has_tableau`)
from `configure()`. If extras are **already set**, skip to Step 1.

If they are **not set**, do **not** ask here. Do not invent a yes/no for ETL,
Power BI, or Tableau, and do not ask about conversion settings. Those are
setup's prompt. Call `progress_setup()` with no answers. If the reply has
`shown_on_card: true`, AIM shows that prompt on its card: end the turn.
Otherwise ask it as setup/SKILL.md step 3 says (one `ask_user_question`
call) and submit the answers with `progress_setup(answers={...})`.
Continue only after a later `progress_setup` shows this step has moved on.

## Step 1: Ask How to Register

The setup machine asks this at `chooseCodeSource` and persists the answer, so
read `code_source` from the session first and do not ask twice. Only when it is
unset — this skill can be entered outside setup — ask:

> "How would you like to add source code?"
> 1. **Extract from database** - Pull DDL/code from a connected source database
> 2. **I already have my code locally** - Import SQL files from a local directory

## Step 2: Route

- `code_source=extract`, or **Extract from database** → Load `extract-code-units/SKILL.md`
- `code_source=local`, or **I already have my code locally** → Load `add-code-units/SKILL.md`

Extracting needs a source connection; importing local files does not. Don't
offer to set one up here — the machine routes through
`../setup/configure-source-connection.md` before this task on the extract path,
and testing and data migration ask for it themselves when they need it.

## Step 3: When the Sub-Skill Returns

Keep going in the same turn. If setup sent you here, call `progress_setup()`
and start the step it names (normally conversion). Do not end the turn after
the "Extraction complete" / "Import complete" summary: that step needs no
answer from the user, so nothing would ever restart it.

## Sub-Skills

| Sub-skill | Location |
|-----------|----------|
| extract-code-units | `extract-code-units/SKILL.md` |
| add-code-units | `add-code-units/SKILL.md` |
