# dbt-quality

dbt-quality checks dbt projects for Snowflake readiness, including dbt projects that SnowConvert
produced. It reads the project files, reports findings against 139 rules, and writes a JSON report
and an HTML report. The rules cover project structure, vars and parameters, hooks, incremental
loads, macros, SQL, materialization, tests, documentation, column contracts against scai DDL, and
conversion debt. `scai dbt-quality rules` lists every rule.

dbt-quality ships with scai. In a migration project the agent runs it through the migration MCP's
`dbt_quality_audit` tool; everywhere else you run `scai dbt-quality`. Both use the same analyzer, so
they report the same findings.

## Limits

Read these before you rely on a result.

- **Static audit.** `audit`, `lint` and `validate` read files. They do not run dbt, compile models,
  run SQL, or connect to Snowflake or any other database. They do not read `target/manifest.json`.
- **Review every finding.** A finding can be a false positive, and a clean
  audit does not prove that a project is correct. A skipped check is a coverage gap, not a pass.
- **No correctness guarantee for suggested SQL.** Remediation text, examples, and repairs
  are suggestions. Snowflake does not guarantee that they compile, keep the original
  results, or perform well. Review each change, run your dbt build and tests, and compare results
  before you adopt it.
- **Local process, your file permissions.** dbt-quality runs on your machine as your user. It can
  read every file that your user can read, and the caller chooses which directory to audit and where
  to write reports. dbt-quality does not sandbox those choices.
- **Writes happen only when you ask.** `scai dbt-quality annotate`, `repair` and `fix-columns` preview a diff by
  default. `annotate --write` and `fix-columns --write` need a clean Git tree. In a migration project,
  the agent's `dbt_quality_audit` writes markers into the converted models, as SnowConvert
  writes its EWIs, and records every change in `.scai/dbt-quality/changes.diff`.
- **Marker syntax.** SQL annotations use Jinja comments; YAML and Python retain hash comments to
  keep those files valid. Annotation refreshes selected live findings, removes obsolete selected
  markers, and leaves unselected markers unchanged. Non-UTF-8 files are skipped for annotation;
  explicit marker removal preserves their remaining bytes, including a BOM.

## Install

dbt-quality is part of scai: install or update scai and `scai dbt-quality` is there. You need no
Rust, Python, or Node runtime for an audit. You need Git for `repair`, `annotate --write`,
`fix-columns --write`, and the Git-aware checks. Repair apply uses your separately installed dbt
for its default parse gate; a dry run and an explicitly chosen `--verify none` do not run dbt.
Run your dbt build and tests after changing models. Check the installation:

```bash
scai dbt-quality --version
```

The output is `dbt-quality <version> (<commit>)`.

## Run a first audit

### From Cortex Code or Claude Code

Install the `snowflake-migration` plugin as the
[Snowflake documentation](https://docs.snowflake.com/en/migrations/snowconvert-docs/general/user-guide/snowconvert/migration-skill/skill)
describes. Open a session in your dbt project (or in the folder that contains several projects) and
ask:

> Use dbt-quality to audit this project and show the highest-priority findings. Do not edit files.

The plugin's `dbt-quality` skill tells the agent how to run the audit, read the report, and stop for
your approval before it writes anything. See the [dbt-quality skill](SKILL.md). In a migration
project the agent uses the migration MCP's `dbt_quality_audit` tool; it needs no API key and no
Snowflake credentials.

### From the command line

```bash
# JSON on stdout; no report files and no project edits.
scai dbt-quality audit /path/to/dbt-project --stdout --quiet

# Save JSON and HTML outside the project. Create the folder first.
mkdir -p ./reports
scai dbt-quality audit /path/to/dbt-project --out ./reports/findings.json --html ./reports/report.html
```

To find collisions between projects (duplicate models and sources, copied macros, conflicting
vars), audit the **folder that contains all the projects**. An audit of one project cannot see the
others. Without `--out` or `--stdout`, `audit` writes `dbt-audit-suggestions.json` into the audited
folder (in a migration project, into the migration root); it writes HTML only with `--html`. The JSON is compact; add `--pretty` for indented JSON.

### Scope inside a migration project

A path inside a scai migration project (a `.scai/config/project.yml` at or above it) takes its DDL,
bindings, and config from the project. The config is the nearest `.dbt-quality.yml` at or above the
migration root. The audit covers only the dbt projects under the path you give.
With the migration root as the path, that is every project. `--estate` audits
the whole project registry from any path. Every run prints `Scope: <root> (N of M registry projects)`
on stderr. The JSON `inputs.scope` holds `root`, `estate`, `projects_in_scope`, `registry_projects`,
and `registry_in_scope`.

Cross-project rules (for example PRJ0020) see only the projects in scope. In a migration project,
`inputs.registry_check` in the JSON lists registry problems, each as `{count, items}`:

| Key                     | Meaning                                                                          |
| ----------------------- | -------------------------------------------------------------------------------- |
| `stale_targets`         | A registry target with no `dbt_project.yml`                                      |
| `unregistered_projects` | A project under `snowflake/` that no in-scope unit targets                       |
| `missing_models`        | A part's `modelName` with no model file in its project                           |
| `skipped_targets`       | Registered targets left out on purpose (see [Skipped folders](#skipped-folders)) |

The HTML report shows a Registry tile. Stderr prints a `Registry: ...` line when a count is not zero.

## The migration audit (`dbt_quality_audit`)

In a migration project, the migration MCP's `dbt_quality_audit` tool runs one audit over every dbt
project the registry lists and the converted table DDL. It takes its inputs from the project. It
audits, writes a marker above each warning, error and deploy-blocking finding, and writes to
`.scai/dbt-quality/`:

| File                         | Contents                                                     |
| ---------------------------- | ------------------------------------------------------------ |
| `dbt-audit-suggestions.json` | The full report, as `scai dbt-quality audit --out` writes it |
| `dbt-audit-report.html`      | The HTML report                                              |
| `findings.jsonl`             | One active finding per line, every location                  |
| `changes.diff`               | Every marker the run wrote, when it wrote any                |

An unchanged estate is not audited again. The migration workflow's `auditDbtQuality` task calls the
tool with its units and stamps them; the next run removes the markers of fixed findings.

## CLI quick start

| Command                                  | Use                                                                                                                                                                                                |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `scai dbt-quality audit <root>`          | Full audit: JSON report, and HTML with `--html <file>`. `--category`, `--min-level`, `--ddl`, `--fail-on-error`, `--quiet`, `--stdout`, `--out`, `--estate`, `--no-group`, `--pretty`, `--timings` |
| `scai dbt-quality lint <root>`           | One line per finding, for editors and CI. `--format text\|json`, `--min-level`, `--strict`, `--ddl`                                                                                                |
| `scai dbt-quality validate <file>`       | Model-scoped rules on one `.sql` or `.py` model. `--strict`                                                                                                                                        |
| `scai dbt-quality rules`                 | The rule list. `--code <code>` prints one rule; `--format json\|markdown`                                                                                                                          |
| `scai dbt-quality annotate <root>`       | Marker diff; `--write`, `--remove`, `--rule <code>`, `--allow-dirty`                                                                                                                               |
| `scai dbt-quality fix-columns <root>`     | Preview column casts against DDL. `--ddl`, `--select <glob>`, `--write`, `--allow-dirty`, `--format text\|json`                                                                                         |
| `scai dbt-quality setup-tasks [project]` | VS Code tasks for the Problems panel                                                                                                                                                               |

`audit --timings` prints the time of each phase to stderr. `--timings=rules` also prints the 10 slowest
rules. Use them to report a slow audit.

`validate` runs only the rules that need one model. Project- and estate-wide rules are listed as
skipped, so a clean `validate` result does not mean the project passes. `validate` also returns
success for a file that is not a discovered model, such as a missing path or a file outside the
project's model paths, so check the path when it reports nothing.

## Read the HTML report

Open the HTML file in a browser. It has seven sections:

1. **Overview**: tiles for projects, models, active findings, errors, warnings, information, and
   *Not reported*, the SnowConvert markers inside comments that the audit counts but does not list (see
   `converter_markers` in [Configure and waive](#configure-and-waive)); a list under the tiles shows
   each code, message, count, and the files and lines. A *Contract coverage* tile (for example "44 of
   1,912") shows how many models matched a DDL table. The tiles cover the whole audit, not only the
   findings that `--category` or `--min-level` returned.
2. **Categories**: findings per category and level.
3. **Findings**, grouped by rule, then by message, then by file. A message group puts `...` and `N`
   in place of the names and numbers in the message, and each file lists its lines with those
   values. A finding that fires in many projects is shown once, with its count and the first 50 sites
   (see `group_threshold`). The page opens each level only when you click it, so a report with tens of thousands of
   findings stays small. Search (rule, message, or file path) and the category and level filters
   apply to the groups.
4. **Column contract**: a summary of the COL findings. The full list is in `column_issues.csv` (see
   [Check columns against scai DDL](#check-columns-against-scai-ddl)).
5. **Suppressed** findings, grouped the same way.
6. **Skipped checks** and read errors. None of them count as passed.
7. **Rule reference**: the guidance for each rule that has a finding.

A rule, a message group, or a file takes one decision: *Will address*, *Ignore once*, or *Ignore
permanently* with a reason. A decision on a rule or a message group covers every finding in it
and replaces the decisions inside it; a later decision on a group or a file inside it overrides it
for that part. The browser keeps
decisions in local storage for that audit folder, so they survive a re-audit in the same browser.
*Export decisions* downloads `dbt-quality-decisions.json` with one entry per decided finding; an
*Ignore permanently* entry includes the waiver comment to add. The report never writes project
files. You or your agent apply the decisions, review the diff, run your dbt checks, and audit again.

The report is a fixed static viewer. It embeds its data and runs one local script, pinned by hash.
It loads nothing from the network, so it also opens where network access is blocked.
Every section, filter, decision, and the source viewer need JavaScript. With scripts blocked, the
page shows a notice only. A preview pane or a sandbox that blocks scripts may not show the report.

**Before you share a report, review it.** It contains file paths and finding evidence. By default it
does not contain whole model files. `--include-models` adds the text of
discovered SQL and Python models, up to 256 KiB a file, 4 MiB in total, and 100 files. It never
adds profiles or configuration files. Each file in the Findings section then has a **Source**
button that shows the model with the finding lines marked. Sharing such a report shares that source
code.

## Mark findings in the files, safely

`annotate` writes one marker comment above each finding, so you and your agent can fix the code
where the problem is:

```sql
{# SSC-EWI-DBTSQL0007 - <rule name>: <subject> #}
```

The marker is a Jinja comment on its own line and renders no SQL.
YAML files use plain `# SSC-EWI-... - <name>` markers, followed by owned commented syntax
that becomes valid YAML when uncommented. Python retains `# ** ... **`.
Markers carry only dbt-quality codes, and the analyzer ignores
them, so they do not change the findings. SnowConvert's own markers stay as they are, and a finding
that only reports a SnowConvert marker gets no second marker.

1. Audit, and read the evidence for the findings you plan to fix.
2. Preview: `scai dbt-quality annotate <root>`. Review the diff.
3. Commit or stash your changes, then write: `scai dbt-quality annotate <root> --write`. It refuses when the Git
   tree, or a nested repository, has uncommitted changes; the report files do not count.
   `--allow-dirty` skips that check; use it only on purpose.
4. Fix the code under each marker. `scai dbt-quality rules --code <code>` explains the rule and its
   remediation.
5. Run your dbt build and tests, audit again, and run `annotate` again: it removes the markers of
   fixed findings. `annotate --remove --write` removes all dbt-quality markers. With no edits in
   between, removal restores the original bytes; it does not undo your code changes.

`--rule <code>` limits annotation to some rules.

## Repair findings

`scai dbt-quality repair [<root>] --json` and the MCP's `dbt_quality_repair` with no `issue` list
the shipped repairs: `bom`, `comment-trim`, `collate`, `cast-placeholder`, `empty-config`, `columns`,
`sql-comments`, `alias`, `folder-config` and `metadata`. Every repair ends with an annotate pass over
the files it changes, in the same diff: they gain a marker for each remaining finding and lose the
markers of the findings the repair fixed. Standalone `collate` includes review and automatic
matches; `safe` includes predicate matches only and gates each applied step before the next writes.
`sql-comments` defaults to a case-sensitive `^Source:` pattern; change it with
CLI `--pattern` or MCP `options.pattern`. Its report names each changed line and every skip.
`cast-placeholder` expands a standalone `{# @@CASTS <ddl path> #}` SELECT-list line from
the resolved migration/configured DDL roots. It preserves DDL column order, quotes, BOM and
line endings, emits function-form `collate(cast(...), ...)`, and binds DDL hashes to the
reviewed plan. Missing/ambiguous DDL, unsupported types or uncertain SQL placement are skips;
other `@@WORD` tokens are audit findings without an automatic repair.
`columns` applies DDL-bound casts and function-form collations. `alias` and `folder-config` are
review-class repairs: preview their structured references or effective-setting moves, then obtain
approval. `repair safe` preplans `bom`, `comment-trim`, automatic `collate`, `cast-placeholder`,
`empty-config`, `columns` and `sql-comments`, in that order, before writing any model. The CLI also
resolves migration-wide projects and requires every project's baseline gate before the first write.

`metadata` (review) brings a project to the properties standard in one plan. Each model's
properties go in `<model>.yml` beside its SQL file, one entry per file, so they are found, reviewed
and renamed with the model and two people editing two models never edit one file. Each source goes
in `_<source>__sources.yml` in the folder of the models that read it. Entries move byte for byte,
single-entry files are renamed with `git mv` and emptied ones removed with `git rm`; a model with no
entry gets a new `<model>.yml` with its columns, types, contract and key tests, and one-line
`# SSC-EWI-...` markers above what it still needs (delete only the `#` of the commented lines below a
marker to use them). Models that load a scai DDL table get their DDL types, keys, `CHECK` tests and
source comments as descriptions. The plan also declares `dbt_constraints` and `dbt_semantic_view`
in `packages.yml` (ranges from dbt Hub, bundled versions offline) and sets `+persist_docs`.

Preview one repair with `scai dbt-quality repair bom <root>`, review its `report.json` and
`changes.diff`, obtain approval, then repeat with `--apply`. Repairs stage their changes but never
commit. In MCP, preview with `apply: false`, show the summary and diff, obtain approval, then apply
using the exact returned `plan_id` and unchanged scope/options. Changed inputs or evidence require
a new dry run and review.

Apply defaults to the offline `parse` gate, comparing baseline and repaired model relations.
`--verify compile` adds compilation of changed models and their dependants; an introspecting model
may need a warehouse connection. `--verify none` skips dbt, not repair self-checks: choose it only
explicitly, never as an automatic fallback. Missing dbt returns installation choices without
installing anything. Failed post-write gates retain staged edits, reports and a literal,
Git-root-anchored recovery command. No recovery command runs automatically. Passing gates trigger
an offline audit delta, which is not proof of full SQL or data correctness.

The legacy column fixer remains `scai dbt-quality fix-columns`: preview its diff, get approval,
then use `--write`. It neither stages files nor runs dbt verification. Test changes with your dbt
build and tests, then audit again. Other findings use the marker loop above.

## Check columns against scai DDL

The COL rules compare each model's outer `SELECT` with the Snowflake table that scai converted:
missing and extra columns, alias, type, and collation differences. Point them at a scai project
(they read `snowflake/<db>/<schema>/table/*.sql`), at a folder with `table/` subfolders, or at
`.sql` files:

```bash
scai dbt-quality lint /path/to/dbt-project --ddl /path/to/scai-project
```

A cast can fail or change values at run time, so run your dbt build and tests after a repair.

An audit with DDL and `--html` also writes `column_issues.csv` next to the HTML report, with one
row per column finding: `project, model, file, line, column, model_type, ddl_type, rule, kind, message`.
`model_type` is the cast type in the model, and is empty when the model has no cast. `kind` is
`missing_cast` (a column with no outer cast, rule COL0008) or `type_differs` (a cast to another type,
rule COL0005). `--column-csv <path>` writes it elsewhere, and writes it without `--html` too.
`dbt_quality_audit` writes it into `.scai/dbt-quality/`.

Without a catalog, dbt-quality knows a column type only from an outer `CAST`, `TRY_CAST`, or `::`.
COL0008 reports columns with no cast once per model, at information level; the JSON holds one entry
per model, and the CSV holds one row per column. A cast to another type is a COL0005 warning. The JSON
summary holds `contract_coverage: {models_matched, models_total}`.

## Configure and waive

Put `.dbt-quality.yml` (or `.dbt-quality.yaml`) in the folder you audit. dbt-quality reads one file
per audit: the first one it finds in the audited folder or up to eight folders above it, stopping
at the folder that contains `.git`. When you audit an estate, a `.dbt-quality.yml` inside one of its
projects is not read. A file that is not valid YAML is ignored without an error, so check your
settings with an audit after you edit the file.

```yaml
migration:
  mode: auto                 # auto, native, or lift_and_shift
  paths: ["models/legacy/*"] # optional: model paths that are converted code
disabled_rules: [SSC-EWI-DBTDOC0002]
exclude_dirs: [archive]        # folder names to skip, added to the defaults
exclude_paths: ["legacy/**"]   # gitignore-style globs, relative to this file
thresholds:
  micro_project_threshold: 5
  column_doc_coverage: 0.8
ddl_paths: [../scai-project]   # for the COL rules, relative to this file
type_compare: normalized       # or strict: TIMESTAMP_NTZ does not match TIMESTAMP_NTZ(3)
ddl_bindings: {E2E_DB: PROD}   # values for <%TOKEN%> and ${TOKEN} in DDL names
converter_markers: count       # count (default) or report
group_threshold: 25            # 0 turns portfolio grouping off
ignore:
  - paths: ["models/legacy/*"]
    rules: [SSC-EWI-DBTSQL0006]
```

Two keys keep the report readable on a large estate. With `converter_markers: count`, the markers
that SnowConvert wrote (`SSC-EWI-*`, `SSC-FDM-*`, `!!!RESOLVE EWI!!!`) that sit entirely inside a SQL
comment (`--`, `/* */`) or a Jinja comment (`{# #}`) are counted, not listed. Text outside a comment
is executable, so a marker there is always a finding: a `!!!RESOLVE EWI!!!` marker at the start of a
line is a MIG0001 error at its own file and line. The JSON gives each counted marker in
`summary.not_reported` as `{code, message, count, files: [{path, lines}]}`, and the HTML shows the
total in the *Not reported* tile. Set `report` to get one MIG0001, MIG0002, or MIG0003 finding per
marker again, in comments too.

When the same rule and message fire in more than `group_threshold` projects, the report shows them
once, as a `portfolio` finding that lists its projects. A grouped entry has `count` (the findings it
stands for) and `sites` (`{file, line}` for each one). `summary.counts` counts entries;
`summary.findings_total` counts the findings behind them. `--no-group` turns grouping off for one
run. `annotate`, `lint`, and `findings.jsonl` always see every location.

### Skipped folders

These keys control which folders the audit skips:

```yaml
exclude_dirs: [vendor]        # folder names to skip, added to the defaults
exclude_dirs_replace: false   # true: use only your exclude_dirs
exclude_paths: ["legacy/**"]  # gitignore-style globs, relative to this file's folder
include_backups: false        # true: also audit **/stabilization/original/**
```

- The default `exclude_dirs` are `target`, `dbt_packages`, `logs`, `node_modules`, `build`, `dist`,
  `bin`, `obj`, and similar. Your `exclude_dirs` adds to them. Set `exclude_dirs_replace: true` to
  replace them.
- `exclude_paths` defaults to `**/stabilization/original/**`, the backups that the ETL stabilization
  skill writes. Your globs add to it. `include_backups: true` removes that default.
- A `.dbtignore` file (`.gitignore` syntax) in any folder under the audit root skips what it matches.
- A registry target under a skipped folder (for example a Visual Studio `obj/` copy) is skipped, not
  a gap. Skipped folders appear on the `Scope:` line and in the JSON as `inputs.skipped`.
- Inside a project, only the folders that `dbt_project.yml` declares (`model-paths`, `macro-paths`,
  `seed-paths`, `snapshot-paths`, `test-paths`, `analysis-paths`, `docs-paths`) and a few standard
  ones are indexed. Other folders, such as an SSIS export beside `models/`, are not indexed.

Use full rule codes in `disabled_rules` and `ignore`; they are case-sensitive. A disabled rule does
not run and is listed as a skipped check. A **waiver** is narrower: it accepts one finding or one
rule in some files, and it is not a fix. A waived finding stays in the report as suppressed, with
the waiver as its reason, and does not count as active.

Waive in the file, at the reported line:

```sql
select id from analytics.public.orders  -- dbt-quality: ignore SSC-EWI-DBTSQL0006
-- dbt-quality: ignore-file SSC-EWI-DBTDOC0002
```

A directive after code covers that line. A directive on a line of its own covers its own line and
the next non-blank line. `ignore-file` covers the whole file. SQLFluff-style comments also work for
dbt-quality codes: `-- noqa`, `-- noqa: SQL0002`, `-- noqa-file`, and `-- noqa: disable=CODE` until
`-- noqa: enable=CODE`. A waiver that matches no finding, or names a code that is not a dbt-quality
rule (such as SQLFluff's `LT01`), is reported as `SSC-EWI-DBTMIG0010`. Findings for a whole project
or estate have no single line; waive them with `ignore` in `.dbt-quality.yml`.

For converted projects, dbt-quality detects SnowConvert output and can suppress architecture
findings that a lift-and-shift migration is expected to have. The report counts those separately.
If the detection is wrong for your project, set `migration.mode`. The
`scai dbt-quality rules` explains the tiers, codes, levels, and severities.

## Editor tasks

```bash
scai dbt-quality setup-tasks /path/to/dbt-project
```

This adds two tasks to `.vscode/tasks.json`, or updates them, and keeps your other tasks: **dbt: quality
suggestions**, and a watch task that runs every five minutes when the folder opens (if your editor's
task trust settings allow it). Findings appear in the Problems panel after a task runs, not as you
type. The tasks run `scai dbt-quality lint .`, so `scai` must be on the editor's PATH. The file
must be plain JSON; JSON with comments is not supported.

## Gate CI

Install scai on the CI runner, then run:

```bash
scai dbt-quality lint /path/to/dbt-project --strict
# Or keep a report and gate on errors:
scai dbt-quality audit /path/to/dbt-project --stdout --quiet --fail-on-error > findings.json
```

| Command                 | Exits 1 when                                                                                |
| ----------------------- | ------------------------------------------------------------------------------------------- |
| `lint --strict`         | an active error-level finding passes `--min-level`                                          |
| `audit --fail-on-error` | the audit has an active error-level finding (before `--category` and `--min-level` filters) |
| `validate --strict`     | the file has an error-level finding                                                         |
| `audit`, `lint`         | no `dbt_project.yml` is under the folder                                                    |
| `repair`                | a dry run proposes edits or renames                                                        |
| other commands          | the command fails, for example a missing folder or a write error                            |

`repair` exits **0** for listing, nothing to do, or a successful apply; **1** for a dry run with
edits or renames; and **2** for any error, including failed verification gates. `--allow-dirty`
permits unrelated changes only: apply refuses untracked targets and targets or rename sources
with existing staged or unstaged user changes, so recovery cannot discard those files or edits.

Warnings never fail these gates. Without `--strict` or `--fail-on-error`, a run with findings still
succeeds.

## Troubleshooting

| Symptom                                                | What to check                                                                                                                                          |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `could not run dbt-quality from ...`                   | scai could not start its bundled `migration-mcp-server`. Reinstall scai.                                                                               |
| `No dbt_project.yml found under ...`                   | Point at a folder that contains `dbt_project.yml`, or at the folder above several projects.                                                            |
| A check is skipped                                     | Read `skipped_checks` in the JSON. Each entry has a reason: the rule is disabled, or it needs more than one file.                                      |
| `annotate` or `fix-columns --write` refuses to write   | Commit or stash your changes, including in nested repositories, and preview the diff again. The folder must be in a Git repository.                    |
| A waived or disabled rule still appears                | Use the full code. Check which `.dbt-quality.yml` the audit read: only one, from the audited folder or above it.                                       |
| An expected finding is missing                         | Search for `dbt-quality: ignore` and `noqa`, and check `ignore` and `disabled_rules` in `.dbt-quality.yml`. Look in the Suppressed view of the report. |
| `scai dbt-quality --version` shows an unexpected build | The output is `dbt-quality <version> (<commit>)`. Update scai.                                                                                         |
| The report shows only a notice                         | The browser, preview pane, or sandbox blocks scripts. Open the HTML file directly in a browser.                                                        |

## More

- `scai dbt-quality rules`: every rule, its tier, and its level.
- [dbt-quality skill](SKILL.md): how the agent runs dbt-quality and when it stops for your approval.
- `scai dbt-quality rules --code <code>`: one
  rule's full description, remediation, and examples.
