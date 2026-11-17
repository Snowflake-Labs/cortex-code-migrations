---
name: dbt-standards
description: "Choose which dbt standards dbt-quality enforces on a dbt project or estate, rule by rule, from the project's own audit findings, and record the choices in .dbt-quality.yml. Works for SnowConvert/AIM output and hand-written dbt projects. Writes only .dbt-quality.yml, after the user approves a diff; never edits models. Triggers: tune dbt-quality rules, choose dbt standards, set up .dbt-quality.yml, too many dbt-quality findings, waive or disable a dbt-quality rule, dbt-quality thresholds, migration mode lift_and_shift / native."
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# dbt standards

## On Entry

Tell the user:
> I'll audit the project, then go through the rules with the most findings, using examples from your
> own code. For each rule you choose to keep it, waive it for some paths, tune its threshold or
> disable it. I'll show you the `.dbt-quality.yml` change as a diff and write it only after you
> approve it. Then I'll audit again to show what changed. I won't edit any model.

This skill uses the `scai dbt-quality` CLI (see `../dbt-quality/SKILL.md`): `audit` for findings
and the report's `rules` map (or `scai dbt-quality rules --code <rule_id>`) for what a rule checks. Use
`scai dbt-quality audit` for this workflow. The migration audit flow writes markers into the models;
`scai dbt-quality audit` writes only the report files you name. The tool
decides what a finding is. Show what it returned. Do not judge a rule from your own reading of the
code.

**Hard limits**

- Write nothing but `.dbt-quality.yml`. Never edit models, schema YAML, `dbt_project.yml`, or add
  inline `-- dbt-quality: ignore` comments. For a finding with `repair` metadata, offer the reviewed
  repair in addition to keep, waive and disable, then route to `../dbt-quality/SKILL.md`. This skill
  does not apply repairs itself; findings with no repair use that skill's marker loop.
- Never write the config until the user has seen the exact diff and approved it.
- Every rule in the config is a full, upper-case rule ID, such as `SSC-EWI-DBTARC0001`. Take it
  from the finding's `rule_id` or the rule record's title. Never use a short code (`ARC0001`) or a pack.

## Properties standard

dbt-quality checks every project against one layout: each model's properties in `<model>.yml` beside
`<model>.sql`, one entry per file; each source in `_<source>__sources.yml` in the folder of the models
that read it (their closest common parent; a source no model reads stays in its folder). One place
to look, small reviews, no merge conflicts between models, `git mv` follows a model and its file,
and every entry has one expected file, so `DBTARC0008`-`DBTARC0012` name the exact target. Every
project declares `dbt_constraints` and `dbt_semantic_view`, so `DBTTST0003` and `DBTTST0004` ask
for dbt_constraints keys on every model and key-shaped column. `scai dbt-quality repair metadata`
moves existing entries to the standard, writes the missing files and sets `+persist_docs`. Do not
waive the layout rules to keep a per-folder `schema.yml`; propose the repair instead.

## Where the config lives

The analyzer reads **one** config for the whole audit: the nearest `.dbt-quality.yml` (or
`.dbt-quality.yaml`) in the audit root or a parent directory. It searches up to 8 parent levels,
and the last directory it searches is the one that contains `.git`. In a migration project, the
audit root is the migration root, so the config is the nearest one at or above the migration root.

- A config inside one project of an estate is **not** read when the audit root is the estate. Write
  the file the audit root will find: update the existing one if there is one, else create
  `<audit root>/.dbt-quality.yml`.
- If the nearest config is in a parent of the audit root, say which file it is before changing it.
  Other audits under that parent read it too.
- The loader does not report problems. If the YAML is invalid, it uses the defaults for everything.
  It skips unknown keys, `ignore` entries that are missing `paths` or `rules`, and thresholds of
  the wrong type. Step 6 is the only check that the file took effect.

## Workflow

### Step 1: Scope and existing settings

Ask for the dbt project or estate root if it is not clear. To compare projects, use the common
root. Find the config the audit will load (above) and read it. List the settings it already has,
so the user does not decide a rule twice.

### Step 2: Baseline audit

Run `scai dbt-quality audit <root> --no-group --quiet -o <scratch>/baseline.json`, with `<scratch>`
a temporary folder outside the project, and read that JSON file. `--no-group` gives one entry per
finding, so findings match across audits. Keep these as the baseline:

- `summary.counts`: active findings by `error`, `warning` and `information`, plus `suppressed`
- `summary.categories`: per pack (`category`), with `error`, `warning`, `information`, `total`
- `skipped_checks` (`rule_id`, `reason`) and `suppressed` (`by_rule`, `by_reason`)
- `projects[].provenance`: `is_migration`, `confidence`, `signals`

A finding in `suggestions` with `"suppressed": true` is inactive; `suppressed_reason` says why. All
other findings are active.

### Step 3: Migration mode

Get the mode from `migration.mode` in the config, or `auto` if it is not set. Show each project's
`provenance` result. Explain the three modes in terms of this project:

| `migration.mode` | Effect |
| --- | --- |
| `auto` (default) | Detects converted code per project from signals (conversion markers, `stg_raw__` models, ETL instance names, converter placeholders, `migration.paths`). With `confidence: high`, every architecture-tier finding in the project is suppressed. With `medium`, only those in the files it detected or that match `migration.paths`. With `low` or `none`, the project is native: nothing is suppressed and the conversion rules below do not run |
| `native` | Skips detection: no project counts as converted. Nothing is suppressed, **and** the conversion rules `DBTMIG0001` to `DBTMIG0008` stop running: unresolved EWI/FDM markers (`SSC-EWI-DBTMIG0002`, `SSC-FDM-DBTMIG0003`), placeholders, ETL control columns and names, scaffolding |
| `lift_and_shift` | Every project counts as converted. Every architecture-tier finding is suppressed, and the conversion rules run in every project |

Suppression hides only `architecture`-tier findings. `universal` and `migration` findings are never
suppressed, and disabled rules and waivers apply in every mode. Before the user picks, count what
each choice would change: the architecture-tier findings (`tier` in the findings) it would show or
hide, and, for `native`, the active `DBTMIG0001`–`DBTMIG0008` findings it would stop reporting.
Do not recommend `native` for converted code that still has unresolved conversion markers.
Ask the user to pick a mode, or to keep the current one.

**Wait for the user's choice before Step 4.**
`migration.paths` is a list of globs over project-relative model paths (`*` also matches `/`).
It only applies in `auto` mode.

### Step 4: Walk the rules, noisiest first

Group the active findings by `rule_id`. Rank by count. Break ties by level (error, then warning,
then information) and then `severity`. Present the rules pack by pack (`category`), starting with
the pack that has the most findings. Start with the top 10–15 rules. Then ask whether to go on or
to keep the rest unchanged; do not make the user walk all of the rules.

For each rule:

1. Read the rule's record from the report's `rules` map, or run `scai dbt-quality rules --code <rule_id>`. Give the name, the short description, the
   tier, the scope (`model`, `project` or `portfolio`) and the remediation in a few lines.
2. Show 2–3 real findings: `file:line`, `message` and `evidence`, from the baseline `suggestions`
   with that `rule_id`. Choose examples from different projects or folders when you can.
   Read the lines in the files to check that the examples are accurate.
3. Ask for one choice, and a short reason for any choice except keep. **Wait for the user's
   answer before the next rule.**

| Choice | Writes | When |
| --- | --- | --- |
| **Keep** | nothing (remove the rule from `disabled_rules` if it is there) | The rule matters here; fix the findings |
| **Waive for paths** | an `ignore` entry for the rule and the named paths | The rule is right in general, but some paths are an accepted exception (legacy, generated, vendored) |
| **Tune a threshold** | a key under `thresholds` | The rule is right, but the limit does not fit this project. Only for the rules in the table below |
| **Disable** | the rule ID in `disabled_rules` | The rule does not apply to this project |

For an error-level rule, recommend keep or a narrow waiver. If the user still disables it, say
that the rule's findings will no longer be reported. For a waiver, show which of the rule's
findings the paths cover and which they do not. Waive in `.dbt-quality.yml` and not inline: a
`project` or `portfolio` finding can only be waived in the config.

Thresholds (other keys under `thresholds` are ignored):

| Key | Default | Type | Rules it changes |
| --- | --- | --- | --- |
| `micro_project_threshold` | 5 | integer | `SSC-EWI-DBTPRJ0001` (project below model threshold) |
| `ephemeral_fanout_threshold` | 3 | integer | `SSC-PRF-DBTMAT0001` (ephemeral or view model with many consumers) |
| `max_cluster_columns` | 4 | integer | `SSC-PRF-DBTMAT0004` (clustering key over the column limit) |
| `column_doc_coverage` | 0.8 | number 0–1 | `SSC-EWI-DBTDOC0002` (column documentation below threshold) |
| `macro_model_ratio` | 0.5 | number | `SSC-EWI-DBTMAC0001` (high macro-to-model ratio) |
| `duplicate_block_threshold` | 3 | integer | `SSC-EWI-DBTMAC0010`, `SSC-EWI-DBTSQL0002` (repeated SQL block) |
| `duplicate_block_min_lines` | 4 | integer | `SSC-EWI-DBTMAC0010`, `SSC-EWI-DBTSQL0002` |

Write integer thresholds as whole numbers (`6`, not `6.0`); a non-integer is ignored.
`passthrough_chain_threshold` is read, but no rule uses it, so do not offer it.

### Step 5: Write `.dbt-quality.yml`, after approval

Build the change from the decisions:

```yaml
# .dbt-quality.yml: dbt-quality settings for this estate (chosen with the dbt-standards skill)
migration:
  mode: native              # auto | native | lift_and_shift
  # paths: ["models/converted/**"]   # auto mode only
thresholds:
  max_cluster_columns: 6    # integer
  column_doc_coverage: 0.6  # 0-1
disabled_rules:
  - SSC-EWI-DBTARC0001      # reason the user gave
ignore:
  - paths: ["models/legacy/**"]
    rules: [SSC-EWI-DBTSQL0006]  # reason the user gave
```

- Edit the existing file in place. Keep every key, value and comment the user did not change, and
  keep their order. Add the new settings. Put the user's reason in a comment next to each one.
- Remove a rule from `disabled_rules` when the user chose keep for it, and tell them.
- An `ignore` entry needs both `paths` and `rules`. Paths are globs matched against the file's
  project-relative path (`models/legacy/**`, which applies in every project) or its path from the
  audit root (`<project dir>/models/legacy/**`, which applies in one project).
- Leave keys this skill does not manage unchanged: `ddl_paths`, `ddl_bindings`, `type_compare`,
  `exclude_dirs`.

**⚠️ Stop:** show the change as a unified diff of the file (the whole new file if it is new), with
the file's path. Write it only after the user approves that diff. If they ask for changes, show the
new diff and wait for approval again.

### Step 6: Audit again and verify

Run the same `scai dbt-quality audit` again, into `<scratch>/after.json`, and read it. Match each finding to the
baseline by `rule_id`, `file`, `line` and `message`. Check each decision on its own, and expect a
mode change to move architecture-tier findings for every rule. The config took effect only if all
of these hold:

- **Disabled:** each rule you disabled is in `skipped_checks` with reason
  `disabled in .dbt-quality.yml`, and has no findings.
- **Re-enabled:** each rule you removed from `disabled_rules` (keep on a disabled rule) is no
  longer in `skipped_checks` with that reason. It can now have findings that the baseline did not
  have. List them as new findings; they are not a failed check.
- **Waived:** each waived rule's findings under the waived paths have `"suppressed": true` with
  `suppressed_reason` `` waived by `ignore:` in .dbt-quality.yml ``. Its findings outside those
  paths must not have that reason. They keep the state they would have without the waiver, as in
  the last check below.
- **Mode:** with `native` or `lift_and_shift`, each project's `provenance.signals` starts with
  `migration.mode set to …`.
- **Threshold:** a tuned threshold changes only the findings of its rules in the table above, and
  only in the way below. Each count can stay the same when every finding is past both limits.
  - `micro_project_threshold`: each `SSC-EWI-DBTPRJ0001` message names the new limit
    (`at or below the local 3-model consolidation threshold`). It reports only estates of 2 or more
    projects.
  - `ephemeral_fanout_threshold`: the message has no limit. Each `SSC-PRF-DBTMAT0001` message says
    `has N detected downstream consumers`, and every N must be at least the new limit.
  - `max_cluster_columns`: each `SSC-PRF-DBTMAT0004` message names the new limit
    (`above the local review threshold of 6`).
  - `column_doc_coverage`: each `SSC-EWI-DBTDOC0002` message names it (`below the 60% threshold`).
  - `macro_model_ratio`: the `SSC-EWI-DBTMAC0001` message names it
    (`the local 0.40 review threshold`).
  - `duplicate_block_threshold`: `SSC-EWI-DBTSQL0002` keeps the same findings and messages; only
    its `remediation` changes. A CTE shared by at least the limit's number of models (the other
    models its message lists, plus its own) `suggests a macro`; one shared by fewer
    `suggests an ephemeral model`. For `SSC-EWI-DBTMAC0010`, a block repeated within one project
    is reported only when it `repeats in N models` (or `repeat in`) with N at least the limit. A
    block repeated across projects is reported at any limit.
  - `duplicate_block_min_lines`: these two rules stop reporting blocks shorter than the new
    minimum, or start reporting them, so the line ranges in their findings move.

  A threshold has **no observable effect** on this audit when none of its rules' findings sits
  between the old and the new limit, before or after, such as a fanout limit raised from 3 to 4
  where every model has 6 consumers. That is not a failed check, and it does not show that the
  file was ignored. Check that the key is spelled as in the table and that an integer key has a
  whole number. Then report the setting as having no observable effect on this project. If
  nothing else in the file took effect either, report it as unconfirmed.
- **Everything else** (unchanged kept rules, and a waived rule's findings outside its paths): the
  same findings as the baseline, each with the same `suppressed` state and reason, except where the
  mode decision moves it:
  - Only findings with `"tier": "architecture"` can be suppressed by the mode. `lift_and_shift`
    suppresses all of them, with `suppressed_reason` `migration mode forced via .dbt-quality.yml`.
    `auto` suppresses those in the projects or files it detects as converted, with a reason
    starting `lift-and-shift provenance detected:`. `native` suppresses none.
  - Moving to `lift_and_shift` (or `migration.paths`) can add `SSC-EWI-DBTMIG*` findings, and
    moving to `native` removes them.
  - A finding waived inline (`-- noqa`, `-- dbt-quality: ignore`) keeps its inline reason.

If a check fails (other than a threshold with no observable effect), the file was not read, or
part of it was skipped. The usual causes are the wrong location, invalid YAML, a misspelled key, a
short or lower-case rule ID, or a decimal integer threshold. Fix the file, show the diff again, get
approval, and audit again. Do not report success until every check passes.

## Output

Report:

- the config file's path, and whether it is new or was updated
- each decision: the full rule ID, the choice, the paths or value, and the reason
- before and after: findings by level and by pack, the number suppressed, and the number of skipped
  checks
- every error-level finding that is still active, by rule and file
- any threshold with no observable effect on this audit, and why

Say that suppressed and disabled findings were hidden by choice, not fixed. To fix kept findings,
use `../dbt-quality/SKILL.md`.
