---
name: fix-dbt-macros
parent_skill: dbt
description: >
  Fix macro files in a dbt project for Snowflake incompatibilities after
  `scai code convert --dbt` has repointed the project's model SQL and
  ref()/source() calls from its original source dialect (Redshift,
  BigQuery, Databricks, PostgreSQL, Teradata, Oracle, SqlServer, or any
  other dialect scai's dbt repointing supports) to Snowflake. Scoped
  strictly to files under macro-paths (default `macros/`) — does not touch
  model SQL or dbt_project.yml/profiles.yml. Use when the user says "fix
  dbt macros", "macros aren't Snowflake compatible", "fix macro files
  after dbt repointing", or after scai's dbt repointing conversion leaves
  macro-level source-dialect syntax unconverted. Normally spawned by
  `migration/dbt/SKILL.md` Step 4 in task mode, but also runnable
  standalone. Do NOT use for fixing model SQL or validating dbt config
  files — those are Steps 5 and 3 of the dbt repointing orchestrator.
  Distinct from `migrate-objects/actions/etl-stabilization/dbt-fixer`,
  which fixes SnowConvert-generated dbt projects during ETL
  stabilization and keys off `session_status.json`.
license: Proprietary. See License-Skills for complete terms
---

# Fix dbt Macros for Snowflake

## On Entry

Tell the user:
> **Fix dbt Macros** — I'll scan `macros/` in your dbt project for source-dialect SQL that doesn't run on Snowflake, fix what has a known or inferable equivalent, and flag anything that needs a human decision instead of a guess.

This skill assumes `scai code convert --dbt` has already repointed the project's models and `ref()`/`source()` calls. It fixes what that conversion doesn't reach: SQL and Jinja logic living inside macro bodies. It is **not dialect-specific** — it works for any source language `scai`'s dbt repointing supports, using documented patterns where they exist and improvising from first principles (source dialect vs. Snowflake SQL semantics) where they don't.

## Prerequisites

- A dbt project already run through `scai code convert --dbt` (or otherwise already pointed at a Snowflake profile) — `dbt_project.yml`'s `profile` must resolve to a Snowflake target in the profiles directory identified in Step 2
- `dbt-snowflake` installed and available on PATH
- `dbt parse` must be runnable without a live warehouse connection; a real Snowflake connection is only needed if the user opts into full-compile verification (Step 5)

## Step 1: Locate the Project and Macro Files

Ask the user for the dbt project path if not already known from context. Read `dbt_project.yml` from that path:
- `macro-paths` (default `["macros"]`) — the directories this skill operates on
- `profile` — the profile name, for later `dbt parse`/`dbt compile` calls

List every `.sql` file under each macro path. **Do not descend into `macros/_archived/`** if it already exists — those files were already triaged as non-portable by a previous run; skip them.

If there are zero macro files, tell the user there is nothing to fix and stop.

**Write the list to a worklist file and record its length as `MACRO_COUNT`:**

```bash
find <DBT_PROJECT_PATH>/<macro-path> -name '*.sql' -not -path '*/_archived/*' \
  | sort > <DBT_PROJECT_PATH>/.fix-dbt-macros/worklist.txt
wc -l < <DBT_PROJECT_PATH>/.fix-dbt-macros/worklist.txt
```

Every file in this worklist gets a fix-log record in Step 6 — including files you conclude are already Snowflake-clean. `MACRO_COUNT` is the denominator for the Step 5.5 coverage gate, which is a hard gate: you cannot report completion having visited a subset. Macro paths are typically nested several levels deep (`macros/<vendor>/<thing>.sql`), so enumerate with `find`, not by reading the top-level directory.

## Step 1b: Detect Source Dialect

Read `SOURCE_DIALECT` from `.scai/config/project.yml`'s `source_language` field (or equivalent scai project config) in the parent scai project, if the dbt project sits inside one. If it's not discoverable from config, ask the user which platform the dbt project originally targeted (e.g. Redshift, BigQuery, Databricks, PostgreSQL, Teradata).

`SOURCE_DIALECT` is context for Steps 3–4, not a hard gate — proceed even if the user isn't sure, using general reasoning instead of dialect notes for that run.

## Step 2: Baseline Parse

Resolve `PROFILES_DIR` before any dbt call. Check whether the project bundles its own `profiles.yml` (common — many projects keep one in the project root or point `DBT_PROFILES_DIR` at a repo-local directory rather than `~/.dbt`). Resolution order:

1. `PROFILES_DIR`, if a parent orchestrator supplied it (task mode).
2. `<DBT_PROJECT_PATH>/profiles.yml` if it exists — a project repointed by `scai code convert --dbt` keeps its own, so this is the normal case here.
3. `$DBT_PROFILES_DIR`, if set.
4. `~/.dbt` as the last resort.

Use the resolved value for **every** `dbt parse`/`dbt compile` call in this skill. Do not fall back to `~/.dbt` when the project ships its own profile — that silently parses against the wrong target.

Run:

```bash
dbt parse --project-dir <DBT_PROJECT_PATH> --profiles-dir <PROFILES_DIR>
```

Record the result. A parse failure here almost always names the offending macro and line directly — use it to prioritize Step 3 rather than reading every macro cold.

**`dbt parse` success does not mean the macros are Snowflake-valid, and it must never shorten the Step 3 worklist.** Parse resolves Jinja and confirms the macros exist; it does not compile their SQL. A macro body is a Jinja-wrapped SQL *fragment* — `{{ col }}::TIMESTAMP AT TIME ZONE '{{ tz }}'` is not a standalone statement — so source-dialect syntax inside one passes parse cleanly and only fails once a calling model is compiled. This is exactly how a real run reported "7 macros fixed" while leaving 48 untouched and byte-identical to the source: parse was green, no error named them, and they were never read. Step 3 runs over **every** file in the worklist, error-named or not.

### Step 2b: Mechanical Construct Pre-Scan

Before reading macros one at a time, grep the whole macro tree for the source dialect's known-broken constructs. This seeds a candidate list you can prioritize, and — more importantly — it is re-run as the Step 5.5 residual check, so a construct that survives the pass is caught mechanically rather than depending on you having noticed it.

Build the pattern list from `reference/dialect-notes/<SOURCE_DIALECT>.md` (read in Step 3), not from memory. For Redshift that is at minimum:

```bash
grep -rniE 'AT TIME ZONE|JSON_PARSE|SPLIT_TO_ARRAY|IS_VALID_JSON|CURRENT_SETTING|getdate\(|APPROXIMATE COUNT|DATE_CMP|DIFFERENCE\(|svv_|stv_|pg_' \
  <DBT_PROJECT_PATH>/<macro-path> --include='*.sql'
```

Quote every `--include` glob — unquoted, zsh glob-expands it and the grep returns nothing, which reads identically to "no matches" and silently hides the whole problem. Note that a hit is a candidate, not a verdict (some source-dialect-looking names are Snowflake-native — Pattern 16), and a miss is not a clean bill of health, which is why Step 3 still reads every file.

## Step 3: Fix Each Macro File

Load `reference/macro-fix-approach.md` — it defines how to fix a macro for any source dialect, including when to defer to `reference/dialect-notes/<SOURCE_DIALECT>.md` (if that file exists) versus improvising from general SQL-dialect knowledge. Read it in full before fixing the first macro.

**Also read `reference/dialect-notes/<SOURCE_DIALECT>.md` in full now, before the first macro — not lazily when you think a pattern might apply.** You cannot know whether a pattern exists for a construct without having read the file, so deferring the read means re-deriving mappings that are already documented. This is not hypothetical: a real run re-derived the `svv_*` → `INFORMATION_SCHEMA` mappings, the `schema_owner <> 1` substitution and `TO GROUP` → `TO ROLE` "from first principles", then reported them as gaps in the reference — all three were already written up in `redshift.md`, one of them with more nuance than the re-derivation produced. If no file exists for `SOURCE_DIALECT`, that's fine, proceed on improvisation.

Work the worklist from Step 1 top to bottom, **every file, no sampling**. For each macro file:

1. Read the file in full.
2. Check `<PROJECT>/.fix-dbt-macros/fix_log.md` (if it exists from a prior run) for a prior fix on this same macro or the same error signature — reuse it rather than re-deriving from scratch.
3. Work through the checklist in `macro-fix-approach.md`: identify every construct in the macro that is specific to `SOURCE_DIALECT` and doesn't have identical behavior on Snowflake. Use the matching `dialect-notes/<SOURCE_DIALECT>.md` pattern when one exists; otherwise reason from first principles about the Snowflake-native equivalent. You are expected to improvise here — the dialect notes are an accelerant, not a boundary on what you're allowed to fix. Before rewriting a function or view name, confirm it actually fails on Snowflake rather than pattern-matching on the name (`macro-fix-approach.md` category c) — some source-dialect-named functions already work unmodified.
4. **If every incompatibility found has a fix with a real Snowflake-native equivalent**: apply the fix directly to the file. Preserve the macro's parameter names, argument order, comments, and formatting outside the fixed lines — this is a targeted fix, not a rewrite.
5. **If a Snowflake connection is available, verify the fix with the smallest possible live query** before moving to the next macro — isolate just the changed expression, not the whole macro (`macro-fix-approach.md`, "Verify before finalizing"). `dbt parse`/`dbt compile` in Step 4 won't catch a syntactically-wrong-but-parseable rewrite (e.g. malformed VARIANT field access); a live query is the only thing that does. If no connection is available, note that verification was skipped in the fix log.
6. **If the macro's core logic depends on a source-platform feature with no Snowflake equivalent** (bulk export commands, platform-specific sharing/introspection, superuser-only DDL, or any system catalog with no `INFORMATION_SCHEMA`/`ACCOUNT_USAGE` mapping — `macro-fix-approach.md` category f): do not edit it. Move it to `macros/_archived/<same filename>.sql` unchanged, and record it as `needs-user` in the fix log (Step 6) with the specific blocking feature named. Note that dbt still recurses into `_archived/` as part of `macro-paths` — moving a file signals "needs human redesign," it does not remove the macro from dbt's build graph or stop other macros/hooks from calling it. If `dbt_project.yml` has an `on-run-start`/`on-run-end` hook or another macro that calls something in an archived file, that caller will still fail at runtime until a human addresses it — record that dependency in the fix log too, it's a real blocker for whoever picks up the `needs-user` item.
7. **If a fix has a real Snowflake-native equivalent but correctly translating it requires knowing the live data shape** (e.g. structural unnesting where a wrong guess silently changes row counts — `macro-fix-approach.md` category g): prefer `needs-user` over a low-confidence rewrite.
8. **If a macro references a source-platform-only `dbt_project.yml` config key** (e.g. Redshift's `dist:`/`+bind:`) rather than SQL syntax: leave the macro alone and note the config key in the fix log as an item for config validation — that is out of scope for this skill.
9. Log an outcome for this file immediately (Step 6 format) — don't batch until the end; if you get interrupted, the log should reflect everything done so far. **Log a record even when you change nothing**, with outcome `CLEAN` and a one-line reason naming what you checked. This is what makes the Step 5.5 gate meaningful: without a record, "already Snowflake-compatible" and "never opened" are indistinguishable afterwards, and the latter is the failure mode this step exists to prevent.
10. If the fix you applied in step 4 generalizes beyond this one project, append it to `reference/dialect-notes/<SOURCE_DIALECT>.md` as a new pattern (create the file, modeled on `dialect-notes/redshift.md`'s format, if none exists yet for this dialect) — this is how the catalog grows to cover dialects that start with zero documented patterns. Add new patterns before that file's "What NOT to touch" section, not after it.
11. **Whenever you archive a macro, find and fix its callers in the same pass.** Recording the dependency in the fix log is not enough — the caller still fails at runtime. Search for every call site by macro name, not just by file:

    ```bash
    # for each macro defined in the file you archived
    grep -rn '<macro_name>' <DBT_PROJECT_PATH>/dbt_project.yml <DBT_PROJECT_PATH>/<macro-path> --include='*.sql' --include='*.yml'
    ```

    Check both places callers hide:
    - **`on-run-start` / `on-run-end` in `dbt_project.yml`.** These run on *every* `dbt run` and fail the whole invocation. A real case: archiving `redshift_udfs.sql` left three hooks calling `python_grant_usage()`, `create_udf_library()` and `create_clean_html()`. Remove the offending entries (delete the whole `on-run-start:` key if it empties out) and log each removal.
    - **Other macros.** A macro-calling-macro chain breaks just as hard and is easier to miss.

    Note that one archived *file* can define several macros — grep each macro name, not the filename.

## Step 4: Iterative Verify Loop

After processing all macro files in one pass, re-run:

```bash
dbt parse --project-dir <DBT_PROJECT_PATH> --profiles-dir <PROFILES_DIR>
```

- **Parse succeeds** → proceed to Step 5.
- **Parse fails and the error names a macro you already touched** → re-read that macro's current content and the specific error, apply a corrected fix, retry. Up to 5 attempts per macro.
- **Parse fails and the error names a macro you have not touched** → it wasn't in your macro-paths scan (e.g. a package macro) or it's a model file — read the error carefully; if it's genuinely a macro file within scope that Step 3 missed, fix it now. If it points at model SQL, stop touching macros for that error and record it in the fix log as out-of-scope, with the model file name — a sibling skill fixes model SQL.
- **A macro hits 5 failed attempts** → revert it to its pre-fix content (keep a copy before your first edit in this run so you can restore it), mark it `needs-user` in the fix log with the last error, and move on to the next macro. Do not leave a macro half-edited.

## Step 5: Optional Full-Compile Verification

**Skip this entire step when a parent orchestrator owns compile-and-refine.** If
`RUN_FULL_COMPILE` is false or absent, or you were spawned by
`migration/dbt/SKILL.md` (whose Step 5 runs the compile-and-refine loop over the
whole project), stop after Step 4 and go to Step 6. Running `dbt compile` here
would duplicate the parent's work and split ownership of the same errors across
two skills.

Otherwise, if the user has an active Snowflake connection configured in their dbt profile and wants a deeper check (not required for this skill's core job):

```bash
dbt compile --project-dir <DBT_PROJECT_PATH> --profiles-dir <PROFILES_DIR>
```

This exercises macros in the context of real models, which can surface incompatibilities `dbt parse` alone misses (e.g. a macro that only breaks when its SQL is actually assembled into a `run_query` call). Apply the same per-error triage as Step 4: fix if the error is clearly inside a macro you own, hand off if it's model SQL.

Do not run `dbt run` from this skill — executing models is the model-refinement/verification skill's responsibility, not this one's.

## Step 5.5: Coverage Gate (hard gate — do not skip)

Two mechanical checks must both pass before you report anything in Step 6. Neither is satisfiable by reasoning; run them.

**1. Every worklist file has a fix-log record.** Compare the worklist against the log:

```bash
comm -23 <DBT_PROJECT_PATH>/.fix-dbt-macros/worklist.txt \
  <(grep -oE '\*\*Macro file\*\*: .*' <DBT_PROJECT_PATH>/.fix-dbt-macros/fix_log.md \
    | sed 's/.*: //' | sort -u)
```

Any path printed is a file you never processed. Go back to Step 3 for exactly those files. Empty output is the only pass.

**2. The Step 2b construct scan comes back clean.** Re-run the same grep. Every remaining hit must be justifiable in one of two ways, and you must say which in the report:

- the construct is confirmed Snowflake-native (dialect-notes Pattern 16 or a live query), or
- the file is `ARCHIVED` / `NEEDS-USER` in the fix log, i.e. deliberately left for a human.

A hit in a file logged `FIXED` or `CLEAN` is a bug in this run, not an acceptable residual — reopen that file.

**If either check fails, you have not finished.** Report the failure rather than a success summary: a count of "N macros fixed" alongside an unvisited remainder is worse than no report, because it reads as coverage. The pass-through failure mode is silent by construction — an unconverted macro carries no EWI or FDM marker and is textually indistinguishable from a correctly-converted one — so these two greps are the only thing standing between a partial run and a project where ~37% of models fail `dbt compile` with a green status message.

## Step 6: Fix Log and Report

Maintain `<DBT_PROJECT_PATH>/.fix-dbt-macros/fix_log.md`, appending one record per fix attempt:

```markdown
### Fix Record
- **Macro file**: <path relative to project root>
- **Pattern(s) applied**: <names from reference file, e.g. "Pattern 2 (AT TIME ZONE), Pattern 5 (GROUP->ROLE)">
- **Outcome**: FIXED | CLEAN | ARCHIVED | NEEDS-USER | OUT-OF-SCOPE
- **Reason** (for CLEAN/ARCHIVED/NEEDS-USER/OUT-OF-SCOPE): <specific blocker, or for CLEAN what was checked>
- **Timestamp**: <ISO timestamp>

---
```

After all macros are processed, present a summary to the user:

```
dbt macro fixing complete for <project_name>:
  Macro files in worklist: MACRO_COUNT
  Fix-log records: R          (must equal MACRO_COUNT — Step 5.5 gate)
  Fixed: F
  Already Snowflake-compatible: C
  Archived (no Snowflake equivalent): A
  Needs user input: U
  Out of scope (model SQL / config, not macros): O
  Residual construct scan: clean | <n hits, each justified below>

Archived/needs-user details:
  - <macro_name>: <reason>

Fix log: <DBT_PROJECT_PATH>/.fix-dbt-macros/fix_log.md
```

Report `MACRO_COUNT` and the record count explicitly, even when they match. `Fixed: 7` on its own is the shape of the failure this skill's gate exists to catch — `7 fixed / 48 clean / 55 records / 55 files` is a coverage claim, `7 fixed` is not.

If any macro was archived or flagged `needs-user`, list each one with its specific reason so the user can act on it — don't just report a count.

## Reference Files

- [reference/macro-fix-approach.md](reference/macro-fix-approach.md) — the dialect-agnostic checklist and reasoning method used in Step 3. Load once per run, not once per macro file.
- `reference/dialect-notes/<SOURCE_DIALECT>.md` (e.g. [reference/dialect-notes/redshift.md](reference/dialect-notes/redshift.md)) — known patterns for a specific source dialect, loaded when `SOURCE_DIALECT` matches an existing file. Not every dialect has one yet; absence of a file is not a blocker, it just means Step 3 runs on improvisation alone for that dialect.

---

## Task Mode (spawned by a parent orchestrator)

This skill's parent orchestrator is [`migration/dbt/SKILL.md`](../../SKILL.md), which spawns it
from **Step 4: Fix Macro Files**. That orchestrator owns dbt config validation (its Step 3)
and model-SQL compile-and-refine (its Step 5) as sibling steps, so this skill stays scoped to
macro bodies. It remains runnable standalone — invoke it directly by name — in which case
Steps 1/1b do their own interactive path and dialect resolution.

### Expected Input

- `DBT_PROJECT_PATH` — absolute path to the repointed dbt project. When spawned by the dbt
  repointing orchestrator this is the **converted output** directory (`<project>/snowflake`),
  not the migration project root and not `source/`.
- Optional `SOURCE_DIALECT` — the project's original source platform (Redshift, BigQuery, Databricks, PostgreSQL, Teradata, Oracle, SqlServer, etc.). If omitted, this skill attempts Step 1b's own detection before falling back to improvisation-only.
- Optional `PROFILES_DIR` — directory containing the `profiles.yml` to parse against. Supply this
  whenever the project bundles its own profile; if omitted, Step 2 resolves it.
- Optional `ORIGINAL_PROJECT_PATH` — pre-repointing copy of the project in its original dialect, for reference when a macro's original intent is unclear from the Snowflake-side code alone
- Optional `SNOWFLAKE_CONNECTION_CONFIGURED` (bool) — if true, verify individual fixes with small live queries (Step 3.5); if false or absent, note skipped verification in the fix log
- Optional `RUN_FULL_COMPILE` (bool) — if true, run Step 5's full-compile verification. Leave
  false or absent when the parent orchestrator runs its own compile loop, which is the default
  for `migration/dbt/SKILL.md`.

### Behavioral Overrides in Task Mode

- Skip Step 1's interactive path-asking and Step 1b's interactive dialect-asking — the orchestrator supplies `DBT_PROJECT_PATH` and `SOURCE_DIALECT` directly
- Skip all other stopping points — proceed autonomously through Steps 2–6
- Skip Step 5 unless `RUN_FULL_COMPILE` is true
- Document any assumption made (e.g. guessing a timezone default) in the fix log's `Reason` field rather than asking

### Output (for the orchestrator to read)

- Fixed macro files in `<DBT_PROJECT_PATH>/<macro-path>/`
- Archived macro files in `<DBT_PROJECT_PATH>/<macro-path>/_archived/`
- `<DBT_PROJECT_PATH>/.fix-dbt-macros/fix_log.md` — full fix history for this run
- Any new patterns appended to `reference/dialect-notes/<SOURCE_DIALECT>.md` — the orchestrator doesn't need to do anything with these, but should know this skill writes back into its own reference tree as a side effect
- A final summary message (same shape as Step 6's user-facing summary) — the orchestrator should treat any `NEEDS-USER` or `OUT-OF-SCOPE` entries as blockers to surface, not silently-resolved work
- **Counts for the orchestrator's manual-review total**: `ARCHIVED + NEEDS-USER + OUT-OF-SCOPE`
  from the fix log. The parent must add these to any EWI-derived count rather than reporting the
  EWI count alone — hand-written source-dialect constructs (system catalogs, platform UDFs)
  produce no EWI, so an EWI-only total under-reports and can read as a false zero.
- **Step 5.5 coverage result** — `MACRO_COUNT`, the fix-log record count, and whether the residual
  construct scan was clean. The parent must treat a coverage-gate failure as a failed run, not a
  partial success: unconverted macro bodies carry no marker, so the parent has no independent way
  to detect them and will otherwise report a green summary over a project that won't compile.

### Team Protocol

If spawned as a team agent: send a `send_message` to `main` on completion summarizing macros fixed/archived/needs-user, and respond to any `shutdown_request` with `send_message` using `type: "shutdown_response"` and `approve: true`.
