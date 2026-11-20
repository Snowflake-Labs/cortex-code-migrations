---
name: dbt-quality
description: "Static quality checks for dbt projects with the migration MCP's dbt_quality_audit and reviewed dbt_quality_repair tools and scai dbt-quality repair. Use to audit, review, health-check, validate, mark, repair findings, fix SSC-EWI-DBT findings, repair converted dbt models, or check converted model columns against scai DDL. Repairs include bom, comment-trim, collate, cast-placeholder, empty-config, columns, sql-comments, alias, folder-config and metadata. Triggers: audit dbt, dbt quality, dbt anti-patterns, review dbt project, validate dbt model, lint dbt, SSC-EWI-DBT, fix dbt-quality findings, fix-columns."
---

# dbt quality

The Rust analyzer uses dbt's Jinja parser and local SQL analysis to produce JSON findings and an
HTML report. It can also write `SSC-EWI-DBT*` markers into dbt files and repair mechanical findings.
An audit does not execute models or connect to a warehouse.

Audit and repair are separate workflows. An audit reports findings. A repair changes files, and only
after the user approves its diff. Check the evidence before changing code, test each change, and
audit again.

Audit never runs `fix-columns` or rewrites column expressions. It returns `repairable` counts by
issue and `delta` against the previous completed audit, including removed-project rows. Use these
as repair-routing and comparison evidence, not approval to edit. Audit semantics revision 4
rejects revision-3 caches; core and CLI are paired at version 0.3.5.

The tool decides what a finding is. Report what the audit, `lint` or `validate` returned, and get a
rule's explanation and remediation from the report's `rules` map (key `rule_id`) or from
`scai dbt-quality rules --code <rule_id>`. Do not apply the
rules by reading the code yourself, and do not report a finding the tool did not return.

## Tools

dbt-quality ships with scai. Its audit and repair MCP tools share the same CLI core.

| Surface | Use |
| ------- | --- |
| `dbt_quality_audit` (migration MCP) | In a migration project, after `configure`. Omit `where`. One run over every dbt project of the migration and its converted table DDL: it audits, writes a marker above each warning, error and deploy-blocking finding, and writes to `.scai/dbt-quality/`: `dbt-audit-suggestions.json`, `dbt-audit-report.html`, `findings.jsonl`, and `changes.diff` when it changed a model. It returns those paths and the counts, including `markersSkipped`: the models that changed after the audit read them, which got no marker. A concurrent audit or repair stops with `another audit or repair of <root> is running`. An unchanged estate is not audited again. The state machine's `auditDbtQuality` task calls it with `where`, which also stamps the units. |
| `dbt_quality_repair` (migration MCP) | Lists repairs without creating the audit lock, previews a repair, or applies the exact reviewed `plan_id`. Dry runs write `preview-<combined_plan_id>.json`/`.diff` per project; apply validates these files and writes `report.json`/`changes.diff`, stages applied files, runs the chosen gate, and never commits. Use returned `report_json` and `changes_diff` paths. Repairs: `bom`, `comment-trim`, `collate`, `cast-placeholder`, `empty-config`, `columns`, `sql-comments`, `alias`, `folder-config` and `metadata`. `safe` preplans the seven automatic steps; it never includes review-class aliases, folder settings or metadata. |
| `scai dbt-quality <command>` | Outside a migration project, for a preview, and for people, CI and editor tasks: `audit`, `lint`, `validate`, `rules`, `annotate`, `repair`, `fix-columns`, `setup-tasks`. `scai dbt-quality <command> --help` lists the options. |
| `rules` map in the report JSON, `scai dbt-quality rules --code <code>` | One rule's record: description, remediation, examples and tier. Read the record for a finding's `rule_id` or a marker's code. |
| `findings.jsonl` | One active finding per line, with file, line, code, level and message. Grep it by code or file instead of loading the full JSON. |

## Stopping points

- **Before `dbt_quality_audit` in a migration project:** it writes markers into the
  converted models, as SnowConvert writes its EWIs. Tell the user, and get approval to write.
  If the user asked for no edits, or has not approved writes, do not call it. Run
  `scai dbt-quality audit <path> -o <json> --html <html>` instead, which does not edit models.
  After an approved run, point the user at `.scai/dbt-quality/changes.diff`.
- **Before `scai dbt-quality annotate --write`:** show the diff from the run without `--write` and get
  approval. It refuses to write when the git tree has uncommitted changes (the report files do not
  count) and writes only files inside the path. With `--rule`, it replaces only those rules' markers.
- **Before `scai dbt-quality fix-columns --write`:** show the preview diff and get approval.
  This compatibility alias is retained for one release with its existing flags. Prefer
  `scai dbt-quality repair columns`; COL0005 and COL0008 recommend that command. See [Repair findings](#repair-findings).
- Pass `--allow-dirty` only when the user explicitly asks; it bypasses the clean tree that makes a
  change reviewable and reversible.
- **Before writing reports:** `scai dbt-quality audit` writes `dbt-audit-suggestions.json` into the
  migration root in a migration project, and into the audited root in a standalone audit, unless
  `-o` names another file. Pass `-o` and `--html` paths the user approved, or
  `--stdout`. Confirm a durable destination before retaining or sharing the report. Do not write
  into the user's repo without asking.
- **Before including model text:** explain that sharing the report shares that source. Pass
  `--include-models` only when the user approves source inclusion; it requires `--html`.
- **Before reporting a suggestion:** spot-check two or three against the actual files.
- **Before `setup-tasks`:** ask before it writes `.vscode/tasks.json`, unless the user already
  asked for editor setup.
- **Before changing model code or adding a waiver:** get approval. A finding is evidence to review,
  not permission to rewrite the model.

## Routing

| User intent                                       | Surface                                                     |
| ------------------------------------------------- | ----------------------------------------------------------- |
| "Check this one model"                            | [Validate one file](#validate-one-file): model-scoped rules |
| "Populate the Problems panel" / CI gate           | `scai dbt-quality lint`; `--strict` exits 1 on errors; [editor tasks](#editor-tasks) |
| "Why did this fire?" / "What does this code mean?" | `scai dbt-quality rules --code <code>` |
| "Audit my project" / "assess this estate"         | The workflow below: the audit, then the HTML report         |
| "Fix these findings" / "repair converted dbt"      | [Repair findings](#repair-findings): list, dry run, approval; no repair uses the marker loop |
| "Consolidate these migrated projects"             | The marker loop below                                       |
| "Which rules should we enforce?" / tune `.dbt-quality.yml` | The `dbt-standards` skill of the `snowflake-migration` plugin |

---

## Workflow

### Step 1: Establish scope

Ask what to audit if it is not clear. Use the common estate root when the audit must compare
projects. Discovery looks for `dbt_project.yml` below that root and excludes generated/dependency
directories. A single-project root cannot reveal cross-project collisions. Estate checks include
fragmentation (PRJ0001-0003), conflicting var defaults (PRJ0012), macros copied across projects
(MAC0015/0016), and duplicated logic (MAC0010, SQL0002).

### Step 2: Run the audit

In a migration project (a `.scai/config/project.yml` at or above the path), call
`dbt_quality_audit` with no arguments, only after the user approved writes (see Stopping points). It audits every dbt project the registry lists, with the
converted table DDL the registry lists, the `snow:` bindings and the nearest `.dbt-quality.yml` at or above the migration root. The CLI
writes its default JSON to the migration root, whatever path the user gives.
To audit only the projects under one folder, or to add inputs, use the CLI:
`scai dbt-quality audit <path inside the project>` audits the dbt projects under that path (`--estate`
for the whole registry), and `--ddl`, `--project`, `--binding` and `--config` only add to the
project's inputs. Outside a migration project those options are the only inputs. Tell the user every
line in `inputs.gaps` of the report JSON: each one is a project, table or binding the run could not
use, so a check did not run.
Also tell the user what `inputs.skipped` lists (build output under `bin/` and `obj/`, stabilization
backups, `.dbtignore`, `exclude_paths`): those folders are skipped on purpose and are not gaps.
`exclude_paths`, `include_backups` and `.dbtignore` change that; `exclude_dirs` adds to the defaults.

A `missing_dbt_project` gap, an "unregistered project" gap, or a non-zero `inputs.registry_check` means the registry and the dbt folders disagree: a unit targets a folder that is gone, or a project exists that no unit targets (it is not audited). Do not treat these as audit noise. Follow [registry-consolidation](references/registry-consolidation.md).

Outside a migration project, run `scai dbt-quality audit <path> -o <json> --html <html>` with output
paths the user approved, outside the project unless they ask otherwise (`--stdout --quiet` writes
the JSON to stdout and no files). Graph checks use the `ref()` calls in the model files;
`target/manifest.json` is not read. Default HTML contains evidence, not complete model files. Opt in
to bounded SQL/Python model snapshots with `--include-models`, which needs `--html`. Normal findings
JSON remains unchanged.

### Step 3: Read before writing

Work from `summary`, `remediation` and `suppressed` in the JSON. `summary.counts` counts entries; a grouped portfolio entry stands for `count` findings at the `sites` it lists, so quote `summary.findings_total` and `summary.tally_findings` as the number of findings. `findings.jsonl`, or `scai dbt-quality audit --no-group`, has one entry per finding. `remediation` is already grouped
by rule and ranked by impact over effort. Read each finding on three independent axes:

| Axis       | Values                            | Meaning                                                                    |
| ---------- | --------------------------------- | -------------------------------------------------------------------------- |
| `kind`     | `EWI`, `FDM`, `PRF`               | Issue / possible functional difference / performance concern              |
| `level`    | `error`, `warning`, `information` | Diagnostic level; confirm the evidence and conditions before changing code |
| `severity` | `critical`, `high`, `medium`, `low` | Potential impact if the concern applies                                  |

Compare `per_model` across re-audits only when scope, settings, and coverage are comparable. No
grade is produced. HTML labels all-audit counts separately from returned or browser-filtered
findings. Skipped checks and read errors are coverage gaps, not passes.

### Step 4: Review or share the report

The audit writes standalone HTML: an overview, category bars, findings grouped by rule, then
message, then file, a column-contract summary, suppressed findings, skipped checks, and the rule
reference, with Auto/Light/Dark themes. It is a fixed static viewer: the report data is embedded, and
one local script, pinned by hash, builds the page. It loads nothing remote and makes no network
request. Every section, filter, decision, and the source viewer need JavaScript; with JavaScript
blocked, the page shows only a notice. A Snowflake
shared-report sandbox or editor preview may block the script. Do not promise full interactive
support there. Follow the `html-authoring` skill if adapting HTML for the shared-report sandbox.

The report keeps `snowflake-source` and `snowflake-report-metadata` provenance. Its CSP allows only
the embedded script (by hash) and inline styles and blocks data connections. Review paths and
evidence before sharing, even when complete model text is not included.

With `--include-models`, each file in a message group has a source viewer with the finding
lines marked; it marks them only when the snapshot matches the audited bytes, and otherwise says the
lines are unverified. A report without model text has no source viewer. Source snapshots have
limits of 256 KiB/file, 4 MiB total, and 100 files; they exclude profiles/configuration files,
unsafe paths, and unsupported content. These controls do not sandbox the audit reader.

Edits affect a copy in the report. The reader can preview changes, copy text, or download a new
file; the report never overwrites project files. Mixed or CR-only line endings are read-only.
Use downloads when exact bytes matter, and use manual text copy if clipboard access fails. Apply
changes separately, review the diff, test, then audit again. Do not mark a finding resolved from
a browser edit. There is no live linter, SQL execution, local write server, or WASM validator.

### Step 5: Use markers to fix and consolidate

In a migration project `dbt_quality_audit` writes the markers itself (warnings, errors and every
deploy-blocking finding), so start at step 4. Outside one:

1. `scai dbt-quality annotate <root>` prints the diff and writes nothing. **⚠️ Stop:** show the diff
   and get approval before writing.
2. `scai dbt-quality annotate <root> --write`.
3. Continue with step 4.
4. For each marker `{# SSC-EWI-DBT<PACK><NNNN> - <name>: <subject> #}` (YAML:
   `# SSC-EWI-DBT<PACK><NNNN> - <name>`, optionally followed by `. <what to do>`; Python:
   `# ** SSC-EWI-DBT<PACK><NNNN> - <name>: <subject> **`),
   run `scai dbt-quality rules --code <code>` for its remediation and examples. Fix the construct the marker
   sits above. Leave the marker in place: the next audit or `annotate` run removes the markers of
   fixed findings.
   YAML's directly following `#`-commented syntax lines belong to the marker and are removed with
   it; removing their `#` at the marker's indent yields valid YAML.
5. Test the code changes, then audit again. Outside a migration project, preview `annotate` again
   and approve any writes. With the same inputs, a second run changes nothing.
   `scai dbt-quality annotate <root> --remove --write` removes dbt-quality markers in scope. With no
   intervening edits, removal restores the pre-annotation bytes; it does not undo code changes.

Markers carry only dbt-quality codes (`SSC-{EWI|FDM|PRF}-DBT<three letters><four digits>`). The
engine ignores them when it scans, so findings do not change because markers are present.
SQL markers are Jinja comments and render no SQL; YAML and Python markers are hash comments.
SnowConvert's own markers, such as `SSC-EWI-DBT0001` or `SSC-EWI-INF0039`, are left alone. MIG0001,
MIG0002 and MIG0003 report them. By default (`converter_markers: count`), a marker inside a
comment is only counted, in `summary.not_reported` with its files and lines. A
`!!!RESOLVE EWI!!!` marker outside a comment is executable text. It is always a MIG0001 error.

Use this order as a starting point for migrated estates, then adjust it to the actual dependencies:

1. Hooks that write (INC0010, INC0001-0003, INC0016-0020). Fix these before any consolidation. A
   table that a hook writes is not a dbt node, so its readers (`context.readers` of INC0010) do not
   wait for the writer, and a merged or partial run can read it first. Move each write into a model:
   - The hook copies `{{ this }}` into the table (SnowConvert's SSIS `ole_dst_*` views): make this
     model the table with `alias`, `schema` and `table` or `incremental` materialization, then
     remove the hook.
   - The hook writes other rows: put its SELECT in a new model named for the table.
   - Change each reader's `source()` of the table to `ref()` of the model, and remove the source entry.
   - Keep a hook only for audit or control rows that no model reads.
2. Vars and parameters (PRJ0009-0018): verify sentinel defaults and required values before changing load behavior.
3. Macro duplication across projects (MAC0010, MAC0015-0017).
4. Review project consolidation (PRJ0001-0003, PRJ0006) after confirming ownership and deployment boundaries. In a migration project, a merge must also retarget the registry: follow [registry-consolidation](references/registry-consolidation.md). **⚠️ Stop:** show the user the affected units and get approval before any registry patch (the `cur_reconciler` retarget).

---

## Repair findings

List the shipped repairs rather than inferring availability from a rule ID. `bom`, `comment-trim`,
`collate`, `cast-placeholder`, `empty-config`, `sql-comments`, `columns`, `alias`, `folder-config`
and `metadata` are available. Every repair ends with an annotate pass over the files it changes, in
the same diff and `plan_id`: those files gain a marker for each remaining finding and lose the
markers of fixed ones. `sql-comments` defaults to the
case-sensitive `^Source:` pattern. Use CLI `--pattern` or MCP `options.pattern` to choose another
pattern; lines inside Jinja comments/raw blocks or containing Jinja delimiters are skipped when
the repair cannot prove rendering safety. Show these skips during review.

`comment-trim` removes only the next Jinja tag's left trim after an executable SQL line comment;
the right trim and source bytes otherwise stay unchanged. `collate` rewrites complete operands
into lower-case function form, with a parse check and COLLATE-normalized AST comparison when
the original SQL parses. Standalone `collate` includes automatic predicates and review-only
positions. CLI and MCP `safe` include only automatic matches, with reviewed plans and a separate
gate and offline audit for every step; a failure stops before any later step writes.
COLLATE spans that cross Jinja statement boundaries are skipped as `jinja_control_boundary`;
never expand their control flow by hand during a repair apply. Its offline parser uses stand-ins
for Jinja expressions and separators for complete alternative queries, not a runtime dbt context.
The chosen dbt gate remains responsible for actual expansion. Comment-trim similarly checks
template tokens and renders only a bounded context-free subset offline.

In a configured migration project, use this reviewed flow:

1. Call `dbt_quality_repair` with no `issue`, then show the repairs and match counts per project.
2. Call it with the selected `issue` and `apply: false`. Keep `project`, `select`, `options`,
   `allow_dirty` and `verify` explicit and unchanged through review. A dry run executes no dbt.
3. Read the returned `report_json` and `changes_diff` paths under each project's
   `.dbt-quality/repair/<issue>/`: `preview-<combined_plan_id>.json` and
   `preview-<combined_plan_id>.diff`. Show the summary and that preview diff, including every skip
   and warning. Stop and obtain the user's
   approval before changing model files or staging them.
4. Call it with `apply: true` and the returned `plan_id`. Do not substitute an old plan or change its
   options. A changed input, scope, option, report or diff requires a fresh dry run and review.
5. Show the gate results, staged paths and offline per-rule audit delta. A failed post-write gate
   retains edits and evidence; show the reported `git restore` command rather than running it.
   Obtain approval before another migration audit that writes markers.

MCP apply validates the exact persisted preview report and byte-exact diff. Initial, no-op and
changed-plan dry runs never create or replace applied `report.json`/`changes.diff`; identical
previews retain bytes and modification times. Project labels are session-relative (`.` for the
session project). Check `complete` and `evidence_write_errors`; if publication fails, use inline
reports to explain the failure and stop rather than treating unavailable artifacts as reviewed.

For the CLI, `scai dbt-quality repair [<root>] --json` lists shipped repairs, and
`scai dbt-quality repair bom <root>` previews one. Show its report and diff, obtain approval, then
repeat with `--apply`. `repair safe` plans every automatic step against the preceding in-memory
outputs before the first write, then applies the checked steps in order. A planning or baseline-gate
failure writes no model files; post-write failures retain staged edits and evidence. Unrelated dirty
files need explicit `--allow-dirty`; pre-existing changes to repair inputs are never owned by repair.
CLI preview evidence still uses `report.json` and `changes.diff`; the MCP preview filenames do not
change CLI behavior.

`metadata` is review-class and declares `requires: ["dbt"]`. A plan editing a package file runs
`dbt deps` before its post-repair parse; baseline dependencies must already be installed. It reads
both `tests:` and `data_tests:`. `dbt_constraints.primary_key` implies NOT NULL, so primary-key
columns need no separate generated `not_null` test. A plain `unique` test is not a primary key.

dbt calls have a 120-second timeout and process-tree cleanup. Each evidence stream is capped at
64 KiB; inspect `timed_out`, `process_tree_cleanup_attempted`, `stdout_truncated`,
`stderr_truncated` and `cleanup_errors`. Compile selects exact changed models with `path:<model>`,
without `+`; it does not certify descendants. The gate executes the PATH entry, preserving shim
behavior, and records its canonical executable path.

The default apply gate is `parse`: it compares the dirty worktree's baseline and repaired model
relation identities without a warehouse connection. `compile` adds compilation of changed models
and their dependants; introspecting models may need the user's warehouse connection. `none` still
runs repair self-checks but skips dbt. Never switch to `none` automatically when dbt is unavailable:
show the returned installation choices, or get explicit approval for that weaker gate. Never install
dbt automatically, make a repair commit, or automatically discard retained edits.

`metadata` (review, not in `safe`) brings properties to the standard in one plan: each model's
entry in `<model>.yml` beside its SQL, each source in `_<source>__sources.yml` beside the models that
read it (`git mv` for single-entry files, `git rm` for emptied ones, `git init` and `git add` first
when needed), a new `<model>.yml` for each model without one, Snowflake-Labs `dbt_constraints` and
`dbt_semantic_view` in `packages.yml`, contracts, `data_type` and DDL keys, `CHECK` tests and
source-comment descriptions for models with a scai DDL table, and `+persist_docs`. New files carry
one-line YAML markers with commented syntax: fill the description or key, or delete only the `#`
of the syntax lines and replace the placeholders. Show the diff's renames, removals and new files
during review. It reads dbt Hub for the package ranges; offline it uses bundled versions and warns.

On `needs_dbt`, show these choices and let the user install one:

```bash
uv tool install --python 3.12 dbt
uv tool install --python 3.12 dbt-oss
uv tool install --python 3.12 dbt-core --with dbt-snowflake
uv tool update-shell
dbt --version
```

The first is full dbt v2 ([license](https://www.getdbt.com/dbt-fusion-engine-license-agreement)),
the second is OSS v2, and the third is Core v1. Check `uv tool dir --bin` is on `PATH` before retrying.

For column type and collation fixes, preview `repair columns` (or MCP `issue: "columns"`) with the
same DDL inputs as the audit. Show the diff, stop for approval, then apply the reviewed plan. Use the
checked repair rather than legacy `fix-columns --write`: the repair stages changes and runs the
selected gate. Other findings follow the marker loop in Step 5.

---

## Write actionable remediation

- Use actual identifiers, such as `unique_key='order_line_id'`, once you have confirmed the key.
- Group findings that share a fix; several models missing a key test may be one piece of work.
- Sequence dependent fixes and explain those dependencies.
- State a supported consequence, such as duplicate rows on reprocessing, rather than "violates best practice".
- Record accepted trade-offs with narrow waivers and their reasons.

Keep the summary proportional to the findings and coverage. Do not inflate either the risks or
the confidence of a clean result.

## Lift-and-shift tiers

Migration detection does not suppress `universal` or `migration` rules. `architecture` findings
can be suppressed for detected converted code and are counted separately for later review.
Suppression is a scope policy, not proof that the code is correct. Disabled rules and waivers
still apply. If the user disputes the classification, show `projects[].provenance.signals` and
offer `.dbt-quality.yml` (`migration.mode: native | lift_and_shift`, `migration.paths`).

## Validate one file

Run the model-scoped rules against one file. The rules, codes, and remediation are the same as in
the project audit; only the scope differs. This does not build models, connect to a warehouse, or
prove that the SQL returns correct results.

```bash
scai dbt-quality validate path/to/models/gold/dim_customers.sql     # one file
scai dbt-quality validate --strict path/to/model.sql                # exit 1 on any error-level finding
scai dbt-quality lint <project> [--format json] [--min-level warning] [--strict]   # whole project, one line per finding
```

Replace example paths and optional arguments before running these commands.

`validate` exits 0 for a path that is not a discovered dbt model, including a missing path. Check
that the intended `.sql` or `.py` file is under the project's configured model paths. A literal
`$FILE_PATH` argument is read from the environment. If the validator reports nothing on a file with
known problems, check its path first: the engine must find an enclosing `dbt_project.yml` and
discover the file as a model.

Project- and portfolio-scoped rules are skipped for a single-file check; they did not pass. For
example, `SSC-EWI-DBTSQL0001` compares subquery fingerprints across models, and fragmentation checks
need the estate. Report "No active findings from the model-scoped checks that ran" when that is what
the output shows. Do not call a model fully validated on that basis. Use `lint` or the project audit
when the question needs broader coverage.

### Editor tasks

Run once per dbt project, when the user asks for editor setup:

```bash
scai dbt-quality setup-tasks [PATH]
```

It adds two tasks to `.vscode/tasks.json` at the dbt project root: `dbt: quality suggestions` and
`dbt: quality suggestions (watch, every 5 min)`. It keeps other tasks, adds missing
dbt-quality labels, and updates the command of existing ones. It exits 1 if `dbt_project.yml` is missing or `tasks.json` is not valid JSON
(JSON-with-comments is not supported). The tasks run `scai dbt-quality lint .` by process execution
(through PowerShell on Windows, where `scai` is a `.cmd` shim), and the watcher through the platform
shell, so `scai` must be on the editor's PATH.

The linter emits `path:line:col:endLine:endCol: level: [RULE-ID] message -> fix`. If the Problems
panel is empty or points at missing paths, check that the `pattern` block in `.vscode/tasks.json`
maps `file` (1), `line` (2), `column` (3), `endLine` (4), `endColumn` (5), `severity` (6), `code` (7)
and `message` (8).

Diagnostics appear after the task runs, not as you type. The watch task requests folder-open
startup, subject to editor trust and task-approval settings. Reload the window after setup.
Findings do not fail the task by default. Use `lint --strict` to fail CI on active error-level
findings; warnings do not fail that gate. Command errors can still return nonzero.

## Configuration and waivers

One `.dbt-quality.yml` (or `.yaml`) applies to the whole audit: the first one at the audit root or up
to eight folders above it, stopping at the Git root. A project's own file is not read when you audit
its estate. Keys: `thresholds`, `migration`, `disabled_rules`, `ignore`, `exclude_dirs`, `ddl_paths`,
`type_compare`, `ddl_bindings`. To choose these settings rule by rule from the project's findings,
use the `dbt-standards` skill of the `snowflake-migration` plugin. For a false positive or an
accepted trade-off, prefer a narrow waiver to disabling the rule:

```sql
select id from analytics.public.orders  -- dbt-quality: ignore SSC-EWI-DBTSQL0006
-- dbt-quality: ignore-file SSC-EWI-DBTDOC0002
```

```yaml
# .dbt-quality.yml — waives findings with no single line, such as project- and estate-wide ones
ignore:
  - paths: ["models/legacy/**"]
    rules: [SSC-EWI-DBTARC0001]
```

Waiver directives count only inside comments. A directive after code applies to that line; a
directive on its own line applies to its own line and the next non-blank line. Config-related findings often anchor at
`{{ config() }}`; other rules can have a precise read-site anchor. Use the reported location, not a
pack-wide assumption. Waived findings stay in the report as suppressed, with the waiver as the
reason, and do not count as active. Record why the waiver is acceptable.

If an expected finding is missing, search for `dbt-quality: ignore` directives and the `ignore:`
block in the nearest `.dbt-quality.yml`, which can be in an ancestor directory, and the report's
`suppressed` section. Also check `disabled_rules`, which produces skipped checks rather than findings.
To choose which rules a team enforces, see the rule tiers (`scai dbt-quality rules` lists each rule
with its tier).

## Limits

There is no general naming-convention validator. A migrated model may keep its original object
name; do not infer a naming defect without a reliable source-to-target mapping. MIG0007 can still
flag ETL-instance names for review.

Static rules do not provide complete SQL dialect validation or business-result validation. Run the
project's dbt build and tests after a change. A successful build does not prove all business logic
correct either.

## References

- [README.md](README.md): the user guide (install, first audit, configuration, CI gating, troubleshooting, limits). Point users to it.
- `scai dbt-quality rules`: every rule with its tier and level. Run it when a user disputes a finding or asks which rules exist.
- `scai dbt-quality rules --code <rule_id>`: one rule's description, remediation and examples. The report JSON `rules` map holds the same record for each rule the report names.

## Output

Return the report paths (or the checked file), scope, coverage gaps, and a short list of fixes
supported by the evidence. State whether complete model text was included and whether the output
is in a durable folder. Do not claim that edits are validated until the project's checks and a fresh audit
have run.
