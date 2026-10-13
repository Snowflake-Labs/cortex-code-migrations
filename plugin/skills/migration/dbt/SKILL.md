---
name: dbt-orchestrator
description: >
  Orchestrates the full dbt Jinja repointing workflow. Invoked automatically
  by main.json when `scai code add` detects a dbt project (dbt_project.yml).
  Resolves the source SQL dialect, runs `scai code convert --dbt`, validates
  and fixes YAML configs for Snowflake compatibility, fixes dialect-specific
  macro files, and refines converted SQL models until the project compiles clean.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# dbt Repointing Orchestrator

**This skill is invoked automatically** by `main.json`'s `dbtOrchestrator` task
when `scai code add` detects a `dbt_project.yml` in the source directory and
writes the corresponding `kind = "custom"` / `source.customKind = "dbt"` registry
entry. The user does not trigger this skill manually.

> **The `--dbt` flag is an internal engine detail.** This orchestrator calls
> `scai code convert --dbt` on behalf of the user — the flag is never exposed.

---

## Step 0: Orient

Call `configure(project_dir="<current directory>")` if not already configured.
Tell the user what is happening:

> **dbt Jinja Repointing** — I detected a dbt project in your source directory
> and I'll repoint it for Snowflake automatically. Here's what I'll do:
> 1. Detect your source SQL dialect.
> 2. Run `scai code convert --dbt` to rewrite Jinja macros.
> 3. Validate and fix YAML configs for Snowflake compatibility.
> 4. Fix dialect-specific macro files.
> 5. Compile and refine until the project is clean.

**Mark the status of every step in that list — do not leave any step
unannotated.** Before printing it, check what the Setup phase already did:

- A step already satisfied gets a trailing `— done` plus the evidence in
  parentheses, e.g. `1. Detect your source SQL dialect. — done (Redshift)` or
  `2. Run \`scai code convert --dbt\` to rewrite Jinja macros. — done (1502 files)`.
- The first step still outstanding gets `— next`.
- Remaining steps get `— pending`.

Then state where you are starting, e.g. *"Starting at step 3: config
validation."* Never report a step's completion only in prose below the list — a
user scanning the list must be able to tell, per line, what is done and what is
next.

---

## Step 1: Detect Source Platform

Resolve the source SQL dialect in this order — do **not** ask the user unless
the first two sources are both missing:

**1. Project config** — if `configure()` already has `source_language` set,
use it directly.

**2. `profiles.yml` inference** — resolve it in this order and **stop at the
first hit**: `source/profiles.yml`, then `$DBT_PROFILES_DIR/profiles.yml`, then
`~/.dbt/profiles.yml` as a **fallback only**. Never probe `~/.dbt` while
`source/` ships its own profile — a stale one there resolves the wrong source
platform. Read the `type:` field:

| `profiles.yml type:` | Source platform |
|---|---|
| `redshift` | Redshift |
| `bigquery` | BigQuery |
| `databricks` | Databricks |
| `spark` | Spark |
| `postgres` | PostgreSQL |
| `snowflake` | (already Snowflake — nothing to repoint; tell the user and stop) |

If found, confirm briefly: *"Detected source platform: Redshift."* No need to ask.

**3. Ask the user only if needed** — if `profiles.yml` is absent or type is
unrecognized:
> "What platform are you migrating from? (e.g. Redshift, BigQuery, Databricks)"

Persist with `configure(source_language="<platform>")`. Store as `SOURCE_PLATFORM`.

---

## Step 2: Run Phase 1 Conversion

Tell the user what is running, then execute:

```bash
scai code convert --dbt --json
```

**Exactly that command — no other flags.** In particular do not append
`--generate-source-bindable-format` / `--generate-snowflake-bindable-format`:
`convert/SKILL.md` appends them by default on SqlServer, but they are invalid alongside
`--dbt` and the engine rejects the whole command. Nothing from
`convert/SKILL.md`'s flag table applies on this path.

The engine tokenizes all Jinja calls, translates `SOURCE_PLATFORM` SQL to
Snowflake SQL, then restores all Jinja calls in the converted output.

Read the JSON envelope:
- `status != "success"` → surface errors verbatim and **stop**. Do not
  proceed to validation until conversion succeeds.
- `status = "success"` → repointed models are in `snowflake/models/`.

---

## Step 2.5: Post-Conversion Integrity Checks

**Run these before anything else in Step 3 or Step 5.** These are structural corruptions
introduced by the conversion itself, not dialect issues. Every one of them **passes
`dbt parse` with exit 0**, so if you skip this step you will not find them at all — you
will ship them.

> `dbt parse` validates Jinja and resolves refs. It does not execute SQL and it cannot see
> a `ref()` that has been commented out. A clean parse is not evidence of a working project.

### 2.5.1 Jinja block balance

SnowConvert reformats single-line expressions across multiple lines, and when it does that
inside an `{% if is_incremental() %}` block it can move the closing `{% endif %}` to the
wrong side of the block's `)`, dropping it. Same class of failure for `{% for %}`/`{% endfor %}`.

```bash
python3 - <<'PY'
import glob, re
TAGS = ('if', 'endif', 'for', 'endfor')
for p in glob.glob('snowflake/**/*.sql', recursive=True):
    c = open(p, encoding='utf-8', errors='replace').read()
    counts = {k: len(re.findall(r'\{%-?\s*' + k + r'\b', c)) for k in TAGS}
    if counts['if'] != counts['endif'] or counts['for'] != counts['endfor']:
        print('UNBALANCED', p, counts)
PY
```

For each imbalanced file, diff against its `source/` counterpart and restore the missing
closing tag. Do not guess at placement — the source shows where it belongs.

### 2.5.2 Headless models (commented-out `FROM` / `ref()`)

The highest-severity failure mode, and completely invisible to `dbt parse`. When SnowConvert
emits `SSC-EWI-0001` (unrecognized token) it comments out the surrounding lines — which can
include the `FROM` clause and the `{{ ref() }}` inside it. The result is a model that is
`SELECT *` with no source. Because the `ref()` sits inside a comment, dbt never registers the
dependency, so **the DAG is silently missing edges** and parse still succeeds.

Two checks, both in [Detecting headless models](references/headless-model-detection.md):

1. **Upstream-call diff** — compare the live `ref()`/`source()` targets per file against the
   `source/` original. `source/` is the oracle; any drop is converter-introduced.
2. **No live `FROM`** — a comment-stripped scan of every `SSC-EWI-0001` file.

What must hold, and why each is easy to get wrong:

- **Diff the set of targets, not a count**, and count `source()` alongside `ref()`. A
  `ref()`-only gate is blind to a `source()`-only staging layer, and a count comparison is
  fragile wherever a model calls the same `ref()` twice.
- **Strip comments before matching**, or the converter's own `--    FROM source` reads as live.
- **Run against the repointed tree, not the raw conversion output.** Jinja is re-injected in a
  later phase, so running one phase early reports the whole project as gutted.

A file that drops to `0` upstreams is the worst case: dbt treats it as a root node and builds
it before its upstreams. Every file either check reports must be repaired — see 2.5.4, most are
restorable from source verbatim — and both must come back clean before you leave Step 2.5.

### 2.5.3 `SSC-EWI-0001` scan

```bash
grep -rl 'SSC-EWI-0001' snowflake/models snowflake/macros --include='*.sql'
```

`SSC-EWI-0001` means the converter's tokenizer failed on a block, not that the SQL is
wrong. **It is frequently a false negative on syntax Snowflake supports natively.**
Confirmed example: `SELECT * EXCLUDE <col> FROM ...` is valid Snowflake, and the converter
rejects it with `UNRECOGNIZED TOKEN ... STARTING AT 'EXCLUDE'`. Before attempting any
translation, check whether the original already runs on Snowflake.

Also scan the **model** tree for leftover inline markers, not just macros:

```bash
grep -rn '!!!RESOLVE EWI!!!' snowflake/models --include='*.sql'
```

These are raw text in the SQL stream, so each one is a syntax error wherever it lands. Step
4.4's checklist covers macro files only; models need their own pass. One raw tree carried
**75** of them in models. Any hit is a defect — there is no false-positive case, because the
marker is never valid SQL.

A related counting trap: the marker names the node it flagged, so a bare grep for a flagged
construct counts every site twice — once as code and once inside its own marker. In one
project `grep -ro listaggdistinct` returned 36 for 18 real call sites. Match the call form
(`name\s*\(`) when counting, not the bare name.

### 2.5.4 Restore from source when no translation is needed

For any file flagged in 2.5.1–2.5.3, check the `source/` original for source-dialect
constructs (`DISTKEY`, `SORTKEY`, `SUPER`, `UNLOAD`, `~*`, `svv_*`). **If there are none, copy
the source file over the converted output verbatim** — the conversion was a false negative and
repairing the mangled output by hand only risks introducing new errors. This applies to a large
share of utility and passthrough models, which contain nothing but dbt Jinja and portable SQL.

**An FDM on a construct is not a reason to translate it, and not a reason to skip the verbatim
restore.** A large share of FDMs are false positives on syntax Snowflake supports natively.
Confirmed: `LISTAGG(DISTINCT col, sep) WITHIN GROUP (ORDER BY ...)` is fully native — verified
live, `LISTAGG(DISTINCT c, '|') WITHIN GROUP (ORDER BY c)` over `'b','a','b'` returns `a|b`.
Rewriting it to `ARRAY_TO_STRING(ARRAY_AGG(DISTINCT col), sep)` drops the `WITHIN GROUP`
ordering, and `ARRAY_AGG` without an explicit `ORDER BY` is unordered in Snowflake — so the
result becomes non-deterministic. A real run did this to four models. Before translating
anything on the strength of an FDM, verify the original actually fails on Snowflake; if a
connection is available, run it. See
`actions/fix-dbt-macros/reference/dialect-notes/<dialect>.md` for the running list of
confirmed-native constructs.

### 2.5.5 CHECKPOINT — Integrity

- [ ] Zero unbalanced Jinja files
- [ ] **Zero files with lost live `ref()` or `source()`** — the diff script in
      [Detecting headless models](references/headless-model-detection.md) prints BOTH
      `FILES COMPARED: n / n` and `FILES WITH LOST UPSTREAMS: 0`. Quote both lines. A clean
      second line with a low first line means the gate never ran, not that the project is
      healthy — the script skips any source file with no counterpart under `DST`, so a wrong
      path yields `FILES COMPARED: 0 / n` and an otherwise perfect report. This is a hard
      gate and the one check no other signal covers: Jinja balance, `dbt parse`, and the EWI
      scan all pass green on a project with missing DAG edges.
- [ ] Zero headless models — every model has a live `FROM`, excluding any `macro_tests/`
      fixture directory if the project has one (many do not)
- [ ] Every `SSC-EWI-0001` file either restored from source or genuinely translated
- [ ] Count of files touched here recorded, for the manual-review total in `On Completion`

---

## Step 3: Validate dbt Configs

Review and **fix** YAML configuration files for Snowflake compatibility.
Apply fixes directly to the files — do not just report issues.

### 3.0 packages.yml

**Do this first — it gates `dbt deps`, which gates every `dbt parse` in this skill.**
Locate `packages.yml` under `snowflake/`.

Remove adapter-specific packages:

| Remove | Why |
|---|---|
| `dbt-labs/redshift` | Redshift-only macros (`dist_key`, `sort_key`); fails on Snowflake |
| `dbt-labs/spark_utils` | Spark-only |
| `dbt-labs/bigquery` | BigQuery-only |

Add what the source project relied on implicitly:

| Add | Why |
|---|---|
| `dbt-labs/dbt_utils` with `[">=1.0.0", "<2.0.0"]` | Usually a *transitive* dep of the source adapter package, never listed explicitly. Removing the adapter package removes `dbt_utils` with it, breaking every `dbt_utils.*` call in the project. |

Then verify remaining version ranges are compatible with the installed dbt version — older
pins fail on modern dbt. Widen to a compatible range.

| Package | Known-bad pin | Use |
|---|---|---|
| `calogica/dbt_expectations` | `<0.9.0` (e.g. `0.5.x`) | `[">=0.10.0", "<1.0.0"]` |

That table is a starting point, not exhaustive. For every remaining package, check the pin
against the installed dbt version rather than assuming it is fine — `dbt deps` failing on a
stale pin is the single most common blocker at this step.

**Before touching `packages.yml`, scan for adapter-namespaced macro calls.** Removing
`dbt-labs/redshift` deletes the `redshift.*` macro namespace with it, and any caller then fails
with a confusing macro-not-found error at parse time — long after the edit that caused it:

```bash
grep -rn 'redshift\.\|spark_utils\.\|bigquery\.' snowflake/macros snowflake/models --include='*.sql'
```

Every hit is a caller of a package you are about to remove. Resolve each one — rewrite or archive
per Step 4 — **in the same pass as the package removal**, not later. A real case:
`unload_to_s3.sql` called `redshift.unload_table(...)`; it happened to be archived before the
first `dbt parse`, which is the only reason the error never surfaced.

**Fix `packages-install-path` if it references a source-platform env var.** A real source project
had:

```yaml
packages-install-path: "{{ env_var('DBT_PROFILES_DIR') }}/dbt_packages"
```

The converter passes this through unchanged, and `dbt deps` then fails immediately with
`Env var required but not provided: 'DBT_PROFILES_DIR'` — before any profile env vars exist.
Replace it with the default:

```yaml
packages-install-path: "dbt_packages"
```

**Migrate `dbt_utils.surrogate_key` now, not later.** In dbt_utils 1.x the old name is a
compilation **error**, not a deprecation warning. Treat this as expected rather than conditional:
the source adapter package transitively pinned an old `dbt_utils`, so any project that used
`dbt_utils` at all will have these calls, and they all break the moment you install `>=1.0.0`
above. Left until Step 5 it surfaces as a parse failure across a large share of the project (143
files in one real run):

```bash
grep -rl 'dbt_utils\.surrogate_key(' snowflake/models snowflake/macros --include='*.sql' | wc -l
# note: sed -i '' is macOS; on GNU sed use sed -i (no argument)
grep -rl 'dbt_utils\.surrogate_key(' snowflake/models snowflake/macros --include='*.sql' \
  | xargs -r sed -i '' 's/dbt_utils\.surrogate_key(/dbt_utils.generate_surrogate_key(/g'
```

Record the count — `generate_surrogate_key` hashes NULLs differently from the old
`surrogate_key`, so any model whose key is persisted or joined across incremental runs needs a
manual-review entry.

### 3.1 dbt_project.yml

Locate `dbt_project.yml` under `snowflake/`. Fix:

| Issue | Fix |
|---|---|
| `profile:` is a placeholder (`YOUR_PROFILE_NAME`, `default`) | Replace with a sensible Snowflake profile name (derive from project folder name, or ask once) |
| `name:` is a placeholder | Replace with the dbt project folder name |
| Adapter-specific model configs (`+sort:`, `+dist:` for Redshift; `+cluster_by:` for BigQuery; `+location:` for BigQuery) | Remove from `models:` block |
| `dist: <value>` / `sort: <value>` **without** the `+` prefix, as a top-level key under `models:` | Remove. dbt raises `MissingPlusPrefixDeprecation`, which some versions escalate to an error, and the setting is meaningless on Snowflake anyway |
| `+bind: false` | Remove — Redshift late-binding view config, no Snowflake meaning |
| `require-dbt-version:` incompatible range | Update to `[">=1.0.0", "<2.0.0"]` |

Also scan model SQL for the same keys passed through Jinja `config()`, which the converter
leaves alone:

```bash
grep -rnE '(^|[^[:alnum:]_])(sort|dist|sort_key|dist_key|bind)=' snowflake/models --include='*.sql'
```

Remove those arguments from `{{ config(...) }}` calls. Snowflake tolerates unknown config
keys with a warning, so this is cleanup rather than a hard break — but leaving them means
every future run re-emits the warnings.

**If removing the arguments empties the call, delete the whole line.** `{{ config(sort='date_minute') }}`
becomes `{{ config() }}`, which dbt 1.7+ rejects with `Invalid inline model config` — turning
cosmetic cleanup into a parse failure that costs another fix pass:

```bash
# after the argument removal, drop any now-empty config calls
# note: sed -i '' is macOS; on GNU sed use sed -i (no argument)
grep -rln '{{[[:space:]]*config()[[:space:]]*}}' snowflake/models --include='*.sql' \
  | xargs -r sed -i '' '/{{[[:space:]]*config()[[:space:]]*}}/d'
```

**Review the `vars:` block for source-behavioral assumptions.** Vars that exist to work
around source-platform semantics still parse fine on Snowflake but may produce different
results. A real example is a pair of `lowered_true_values`/`lowered_false_values` lists
carrying the comment *"Redshift duck typing will match integers"* — Snowflake's coercion
rules differ, so the values need a human's review. Do not silently rewrite them; flag them
as manual-review items with the specific var name.


### 3.2 sources.yml / schema.yml

Locate `sources.yml` and any `schema.yml` under `snowflake/models/`. Fix:

| Issue | Fix |
|---|---|
| `database:` is a placeholder | Replace with Snowflake target database from `configure()` |
| `schema:` is a placeholder | Replace with the appropriate Snowflake schema |
| Adapter-specific table configs (`sort_key:`, `dist_key:`, `partition_by:` in config blocks) | Remove |

**Column type translations:**

| Source | Type | Snowflake |
|---|---|---|
| BigQuery | `FLOAT64` | `FLOAT` |
| BigQuery | `INT64` | `NUMBER(38,0)` |
| BigQuery | `BOOL` | `BOOLEAN` |
| BigQuery | `DATETIME` | `TIMESTAMP_NTZ` |
| Redshift | `SUPER` | `VARIANT` |
| Databricks | `LONG` | `NUMBER(38,0)` |

### 3.3 profiles.yml (output)

**This file always exists and always has the source adapter.** SnowConvert copies
`source/profiles.yml` to `snowflake/profiles.yml` unmodified, so it will contain
`type: redshift` (or bigquery, databricks, ...) on every run. Look for it proactively and
replace the connection details of **every** target, leaving none still typed to the source
adapter — otherwise a stray `--target` or a stale `target:` default silently points dbt back
at the source platform.

Template, authentication options, and the `dbt debug` check:
[Rewriting profiles.yml](references/profiles-yml.md).

Three things that must hold:

- **Keep every existing target name.** `target.name` is frequently load-bearing program logic,
  not an environment label. Run
  `grep -rn 'target\.name' snowflake/models snowflake/macros snowflake/dbt_project.yml | wc -l`
  first; if it is nonzero, rename nothing. A target name missing from
  `generate_alias_name.sql`'s `in [...]` test silently renames every model in the project, and
  parse and compile both still pass.
- **Never write a credential into the file**, not even a dummy that looks real. Everything goes
  through `env_var()` with a default, as `account`/`user` already do.
- **Default to key-pair auth.** Snowflake ended single-access password login on 2026-08-31, and
  `externalbrowser` cannot run unattended.

`dbt parse` and `dbt compile` never authenticate, so a bad credential first surfaces inside
Step 5.3's execution gate, looking exactly like a conversion defect. Run `dbt debug` per target
before you get there.

### 3.4 CHECKPOINT — Configs

- [ ] `packages.yml` has no adapter-specific packages and lists `dbt_utils` explicitly
- [ ] All remaining package version ranges are compatible with the installed dbt version
- [ ] `dbt_project.yml` has no placeholder `name:` or `profile:` values
- [ ] All adapter-specific model configs removed from `dbt_project.yml`, including unprefixed `dist:`/`sort:` and `+bind:`
- [ ] No `sort=`/`dist=`/`bind=` arguments remain in model `{{ config(...) }}` calls
- [ ] `vars:` reviewed for source-behavioral assumptions; anything suspect flagged for manual review
- [ ] `sources.yml` has no placeholder `database:` or `schema:` values
- [ ] Column types translated to Snowflake equivalents
- [ ] `profiles.yml` connection details **replaced** on every target — `type: snowflake`, no source adapter target left behind
- [ ] Existing target **names** preserved wherever `target.name` is referenced — collapsing targets renames every model if `generate_alias_name` branches on it
- [ ] Exactly one authentication method configured, entirely via `env_var()` — no credential literal in the file
- [ ] `dbt debug` reports a passing connection for every target Step 5.3 will use

---

## Step 4: Fix Macro Files

Review `snowflake/macros/` for dialect-specific incompatibilities and fix them.

### 4.1 Inventory

List all `.sql` files under `snowflake/macros/`. Scan for:

| Pattern | Category |
|---|---|
| `!!!RESOLVE EWI!!!` | Unresolved conversion marker |
| Platform SQL functions (`GETDATE()`, `DATE_DIFF`, `DATE_FORMAT`) | Dialect SQL |
| Redshift `DISTKEY`/`SORTKEY`, BigQuery `PARTITION BY` in DDL macros | Platform DDL |
| `adapter.dispatch` overrides referencing source adapter only | Adapter dispatch |
| `generate_schema_name` logic hardcoded for source platform | Platform schema logic |
| Source system catalogs: `svv_*`, `pg_catalog.*`, `dbc.*`, `ALL_*`/`DBA_*`, `_TABLE_SUFFIX` | **System catalog** |
| `env_var('REDSHIFT_*')` / `env_var('<SOURCE_PLATFORM>_*')` | Source-platform env var |

The **system catalog** row is the highest-frequency real-world miss and the easiest to
overlook: a macro that introspects tables or columns through a source-platform catalog view
parses fine as Jinja and only fails when the SQL actually runs, so neither the EWI report nor
`dbt parse` will flag it. Map these to Snowflake `INFORMATION_SCHEMA`/`ACCOUNT_USAGE`
(`reference/dialect-notes/<dialect>.md` Pattern 1 for Redshift).

**Review `generate_schema_name.sql` first, before any other macro.** It is the most commonly
customized macro in source dbt projects, it almost always carries source-specific logic, and
it controls schema naming for *every* model — if it fails, the whole project fails. Typical
fixes are env var swaps:

| Source-platform env var | Snowflake replacement |
|---|---|
| `env_var('REDSHIFT_DBNAME')` | `target.database` |
| `env_var('REDSHIFT_USERNAME')` | `target.user` |

Prefer `target.*` over renaming the variable to `SNOWFLAKE_*`: the value is already available
from the resolved profile, so using `target.*` removes the environment dependency entirely
rather than moving it. When a literal env var must be kept, always give it a default as the
second argument — source projects commonly assumed the variable was always set.

### 4.2 Fixes

Delegate the macro-body fixing to the [`fix-dbt-macros`](actions/fix-dbt-macros/SKILL.md)
action rather than working from an inline table. Load
`actions/fix-dbt-macros/SKILL.md` and run it in **task mode** with:

| Input | Value |
|---|---|
| `DBT_PROJECT_PATH` | `<project>/snowflake` (the converted output, not `source/`) |
| `SOURCE_DIALECT` | the platform resolved in Step 1 |
| `PROFILES_DIR` | the directory holding the converted `profiles.yml` (normally `<project>/snowflake`) |
| `ORIGINAL_PROJECT_PATH` | `<project>/source` — for original intent when the converted macro is unclear |
| `SNOWFLAKE_CONNECTION_CONFIGURED` | true only if a live Snowflake connection is available |
| `RUN_FULL_COMPILE` | **false** — Step 5 of this skill owns `dbt compile` |

That action carries the dialect-agnostic incompatibility checklist
(`reference/macro-fix-approach.md`, categories a–g) and the per-dialect pattern catalog
(`reference/dialect-notes/<dialect>.md`), applies fixes, archives non-portable macros, and
writes a fix log. It also enforces two rules worth calling out, because getting them wrong
is worse than not fixing at all:

- **Do not rewrite a function because its name sounds source-specific.** Snowflake ships
  compatibility aliases (`JSON_EXTRACT_PATH_TEXT` is a confirmed one). Confirm it actually
  fails first.
- **Prefer `needs-user` over a low-confidence structural rewrite.** A wrong
  `LATERAL FLATTEN` guess silently changes row counts with no error to catch it.

Two things the action does **not** cover — handle them here, before or after invoking it:

**EWI markers** — Replace the entire block (marker + all commented-out source
code) with working Snowflake SQL/Jinja. Original is in `source/` for reference.
This is a SnowConvert artifact the action knows nothing about; if you skip it, the markers
survive into the delivered project.

**`adapter.dispatch`** — If a macro overrides only the source adapter
(e.g. `redshift__date_spine`), duplicate as `snowflake__<name>` and add to
the dispatch list.

### 4.3 Verify

The action runs its own `dbt parse` loop (up to 5 attempts per file, reverting any macro
that exhausts them) against the profiles directory you passed. Do not re-run it here.

Remember what `dbt parse` does **not** prove: it never executes SQL, so it cannot tell you
whether a function exists or a rewritten expression is valid. A clean parse is not evidence
the macros are correct — it only means the Jinja resolves. Treat the fix log, not the parse
exit code, as the record of what actually got fixed.

### 4.4 CHECKPOINT — Macros

- [ ] No `!!!RESOLVE EWI!!!` markers remain in any macro file
- [ ] No source-platform-only SQL functions or system catalog references remain unfixed
- [ ] `dbt parse` exits 0
- [ ] **Coverage gate passed**: the fix log has one record per file in `.fix-dbt-macros/worklist.txt` (counts equal), and the residual construct scan is clean or every hit is justified as Snowflake-native / `ARCHIVED` / `NEEDS-USER`
- [ ] Manual-review count recorded as `ARCHIVED + NEEDS-USER + OUT-OF-SCOPE` from the fix log

**A macro count is not coverage.** Verify the gate yourself rather than trusting the child's
summary — a partial macro pass is invisible from the outside: a macro copied through in its
source dialect carries no EWI and no FDM, parses fine, and is textually indistinguishable from a
correctly-converted one. A real run reported "7 macros fixed" over a 55-macro project and left 48
byte-identical to the source, breaking ~37% of models at `dbt compile` behind a green summary.
If the counts don't match, send the child back for the missing files; do not proceed to Step 5.

**The manual-review count reported to the user must come from the fix log, not from the EWI
count.** Hand-written source-dialect constructs — system catalog views, platform-specific
UDF installers — generate no EWI, so an EWI-derived total under-reports them and prints a
false `0` while real blockers remain in the project. Carry the fix log's
`ARCHIVED`/`NEEDS-USER`/`OUT-OF-SCOPE` entries into the final summary and list each one with
its reason.

---

## Step 5: Compile and Refine

### 5.0 dbt_utils API Migration

If the project uses `dbt_utils`, migrate deprecated macro calls **before** attempting any
parse. In `dbt_utils` 1.x — which dbt ≥ 1.7 requires — several macros were renamed, and
calling the old name raises a **compilation error, not a warning**, halting `dbt parse`
immediately. Setting `surrogate_key_treat_nulls_as_empty_strings` in `vars:` does **not**
suppress it; the call site must change.

| Old | New | Notes |
|---|---|---|
| `dbt_utils.surrogate_key(...)` | `dbt_utils.generate_surrogate_key(...)` | **NULL handling differs** — the new macro treats NULLs as empty strings by default, so generated keys can change value. Flag for review on any model where the key is persisted or joined across runs. |
| `dbt_utils.current_timestamp()` | `dbt_utils.current_timestamp_in_utc()` | |
| `dbt_utils.dateadd(...)` / `dbt_utils.datediff(...)` | native `DATEADD(...)` / `DATEDIFF(...)` | The cross-adapter shim is unnecessary on a single-target Snowflake project |

Count first, then replace project-wide:

```bash
grep -rl 'dbt_utils\.surrogate_key' snowflake/models snowflake/macros --include='*.sql' | wc -l
```

Use a word boundary when replacing so you do not double-rewrite an already-migrated call:
`dbt_utils.surrogate_key(` → `dbt_utils.generate_surrogate_key(`. Note that a plain
`grep 'dbt_utils.surrogate_key'` also matches comments — verify remaining hits are real call
sites, not prose like `-- TODO cannot use dbt_utils.surrogate_key here`.

### 5.1 Scan Remaining EWIs

Check the latest `Issues.*.csv` for issues in `snowflake/models/` files. Look in
`<project>/.scai/reports/SnowConvert/` first, then `<project>/reports/SnowConvert/`,
then `<project>/Reports/SnowConvert/`. Stop at the first hit. Do not use a leftover
older folder when `.scai` already has the file. The filename carries the conversion
timestamp, so glob rather than assuming it.

**This report is a one-shot artifact of the conversion run and never updates.** It keeps
listing issues for files you have since repaired, so it cannot be driven to zero and must not
be used as an exit condition — read it as a worklist, and take the live tree's own scans
(2.5.3, Step 5.3) as the state of the project. Common fixable patterns:

| Pattern | Fix |
|---|---|
| `CONVERT(VARCHAR, ...)` | → `CAST(... AS VARCHAR)` |
| `SELECT TOP N` | → `SELECT ... LIMIT N` |
| Unresolved type casts | → `::type` or `TRY_CAST` |

Apply fixes directly to the model `.sql` files. Preserve all `{{ ref() }}`,
`{{ source() }}`, and `{{ config() }}` Jinja calls exactly.

### 5.2 Validate ref() and source() Calls

For each model file, verify every `{{ ref('name') }}` matches an actual model
in `snowflake/models/`. Common mismatches after repointing:
- Model was renamed → update `ref()` to match actual filename
- `source()` database/schema wrong → fix `sources.yml`, not the `source()` call

**Check the same name against `source/` before "fixing" it.** A `ref()` that resolves to
nothing may be a pre-existing bug in the customer's project rather than something conversion
broke, and repointing is not the place to fix it. On one project all 3 unresolved targets were
unresolved identically in `source/`; treating them as conversion defects would have meant
editing working customer logic. Only a name that resolves in `source/` and not in the
converted tree is yours to repair — report the rest as pre-existing.

### 5.3 Validation gate

Throughout this step, `<DBT_PROJECT_PATH>` is the converted project root (normally
`<project>/snowflake`) and `<PROFILES_DIR>` is the directory holding its `profiles.yml` —
the same directory, not `~/.dbt`.

Three gates, each strictly stronger than the last. Run them in order; the deepest one you can
reach is the one you report.

1. `dbt parse` — no SQL leaves the machine.
2. `dbt compile` — resolves `ref()`/`source()` against the catalog. Still submits nothing.
3. `dbt run --empty`, **twice** — submits the real compiled SQL with 0-row inputs.

**A clean `dbt parse` does not mean the project works, and neither does a clean `dbt compile`.**
Parse never executes SQL. Compile does not either — it renders Jinja and resolves relations,
but a function that does not exist on Snowflake, an invalid rewritten expression, or a `ref()`
commented out in Step 2.5.2 passes both. On one project compile exited 0 with 4,516 artifacts
while 289 models could not execute. Never report success on an exit code or an artifact count.

Non-negotiables for the execution gate:

- **Run `dbt seed` first**, or unloaded-seed noise buries the real defects.
- **Run `--empty` twice.** A first build emits `CREATE TABLE AS`, so an incremental model's
  `MERGE` is never compiled. One project left 86 incremental models untested on a single pass.
- **Use real credentials**, not the dummy values parse accepts, and confirm with `dbt debug`
  first — otherwise every node fails for the same reason and it looks like a conversion defect.
- **Report tallies with limits**, never a boolean. The gate is evidence about the query
  compiler only: it cannot see wrong results, and its visibility is position-dependent.

Commands, prerequisites, the per-node fix loop, the full limits, and calibration figures:
[The validation ladder](references/execution-gate.md).

### 5.4 CHECKPOINT — Refined SQL

- [ ] Every fixable EWI the conversion report listed is either fixed in the live tree or
      recorded as `NEEDS-USER` — judged against the tree, not the report, which is a
      one-shot conversion artifact and never reaches zero (see 5.1)
- [ ] No `SSC-EWI-0001` blocks remain in any model — each was restored from source or genuinely translated
- [ ] Every model has a live `FROM` clause; no `ref()` survives only inside a comment
- [ ] Every `{{ ref() }}` call resolves to an existing model
- [ ] No deprecated `dbt_utils` macro calls remain (Step 5.0)
- [ ] `dbt deps` run, and `dbt parse` exits 0 with `--no-partial-parse`
- [ ] `dbt compile` exits 0 (if dbt is installed and credentials configured) — the cheaper
      prior gate, not the deepest one
- [ ] **`dbt seed` + two consecutive `dbt run --empty` passes clean**, or every remaining
      error triaged to a named `needs-user` item. The second pass is what covers the
      incremental `MERGE` path. This is the deepest gate: `dbt compile` exiting 0 does not
      discharge it, because compile never submits SQL (Step 5.3).
- [ ] All `needs-user` items listed with file path + error + recommended action

---

## On Completion

Tell the user:

> **dbt repointing complete.**
>
> Repointed models: `snowflake/models/`
> Conversion reports: AIM Assessment (HTML report or the conversion-reports zip). Do not send the user to browse conversion CSV folders.
> Items needing manual review: K *(list if K > 0)*

**K is a sum, not the EWI count.** Compute it as:

```
K = (ARCHIVED + NEEDS-USER + OUT-OF-SCOPE from snowflake/.fix-dbt-macros/fix_log.md)
  + (needs-user items from Step 5.4)
  + (unresolved config items from Step 3.4, including flagged `vars:`)
  + (files from Step 2.5 that could not be fully repaired)
```

Reporting the EWI count alone yields a false `0` whenever the only remaining problems are
hand-written source-dialect constructs — system catalog views, platform UDF installers,
source-only config keys — none of which produce an EWI. If you did not read the fix log,
you do not know K; read it before printing this block.

If `needs-user` items remain, present each with file path, error, and the
specific manual action needed.

**Do not report success on an exit code or an artifact count.** "`dbt compile` exits 0" and
"4,516 artifacts written" were both true on a project where 289 models could not execute.
Report the Step 5.3 execution gate as tallies — PASS / ERROR / SKIP, from the second
`--empty` pass — and state what the gate did *not* cover: no model's output has been compared
against the source system, and row-evaluated behaviour (bad casts, invalid timezone or format
literals, division by zero) is invisible to it. Anything the evaluator decides rather than the
query compiler is unverified.

Set `codeStatus.dbtRepointing = completed` in the registry to mark this task
done for the MCP server's state machine.

Also write the project-scope Setup completion marker so the Setup machine's
`dbtRepoint` task can advance (a per-object `registryField` is not readable at
project scope):

```bash
touch .scai/dbt-repoint-complete
```

> If the marker is not written, the Setup machine will keep presenting this task
> on the next `progress_setup()`.
