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
`convert/SKILL.md` calls them "always append", but they are invalid alongside
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

The highest-severity failure mode, and completely invisible to `dbt parse`. When
SnowConvert emits `SSC-EWI-0001` (unrecognized token) it comments out the surrounding
lines — which can include the `FROM` clause and the `{{ ref() }}` inside it. The result is
a model that is `SELECT *` with no source. Because the `ref()` is inside a comment, dbt
never registers the dependency, so **the DAG is silently missing edges** and parse still
succeeds.

**Do not detect this by grepping for commented `ref()` in isolation.** SnowConvert also emits
large legitimate commented-out blocks, so a raw grep returns roughly six times more hits than
there are real defects (observed: 160 raw hits, 26 real). The only sound signal is a per-file
diff of **live** `ref()` count — comments stripped — against the `source/` original. `source/`
is the oracle: any drop is converter-introduced.

```bash
python3 - <<'PY'
import os, re
SRC, DST = 'source', 'snowflake'

def live_refs(c):
    c = re.sub(r'/\*.*?\*/', '', c, flags=re.S)          # block comments
    c = re.sub(r'^[^\S\n]*--.*$', '', c, flags=re.M)      # line comments
    return len(re.findall(r'\{\{\s*ref\s*\(', c))

lost = []
for root, dirs, files in os.walk(SRC):
    # skip a self-nested migration dir and build output
    dirs[:] = [d for d in dirs if d not in ('migration', 'target', 'dbt_packages', '.git')]
    for f in files:
        if not f.endswith('.sql'):
            continue
        rel = os.path.relpath(os.path.join(root, f), SRC)
        dst = os.path.join(DST, rel)
        if not os.path.exists(dst):
            continue
        rd = lambda p: open(p, encoding='utf-8', errors='replace').read()
        s, d = live_refs(rd(os.path.join(root, f))), live_refs(rd(dst))
        if d < s:
            lost.append((rel, s, d))

print('FILES WITH LOST ref():', len(lost),
      '| DAG EDGES LOST:', sum(s - d for _, s, d in lost))
for rel, s, d in sorted(lost, key=lambda x: x[2] - x[1]):
    print(f'  {rel}: {s} -> {d}')
PY
```

A file that drops to `0` is the worst case: dbt treats it as a root node and builds it before
its upstreams, against stale or nonexistent tables.

Every file this reports must be repaired. See 2.5.4 — most are restorable from source verbatim.
Re-run this script after repairing; it must print `0` before you leave Step 2.5.

Also check for models left with no live `FROM` at all:

```bash
for f in $(grep -rl 'SSC-EWI-0001' snowflake/models --include='*.sql'); do
  case "$f" in */macro_tests/*) continue ;; esac
  grep -qiE '(^|[[:space:]])FROM[[:space:]]' "$f" || echo "HEADLESS: $f"
done
```

**Match `FROM` anywhere on the line, not just at line start.** Anchoring to `^[[:space:]]*FROM`
misses every inline `SELECT a FROM b` and reports it as headless — on a real run that produced
**95 hits, all false positives**, which makes the check worse than useless because the agent has
to dismiss all 95 by hand.

Exclude `models/macro_tests/` — those are macro fixtures that legitimately have no `FROM`
clause and are not defects.

### 2.5.3 `SSC-EWI-0001` scan

```bash
grep -rl 'SSC-EWI-0001' snowflake/models snowflake/macros --include='*.sql'
```

`SSC-EWI-0001` means the converter's tokenizer failed on a block, not that the SQL is
wrong. **It is frequently a false negative on syntax Snowflake supports natively.**
Confirmed example: `SELECT * EXCLUDE <col> FROM ...` is valid Snowflake, and the converter
rejects it with `UNRECOGNIZED TOKEN ... STARTING AT 'EXCLUDE'`. Before attempting any
translation, check whether the original already runs on Snowflake.

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
- [ ] **Zero files with lost live `ref()`** — the 2.5.2 diff script prints
      `FILES WITH LOST ref(): 0`. This is a hard gate, and it is the one check that no
      other signal covers: Jinja balance, `dbt parse`, and the EWI scan all pass green on
      a project with missing DAG edges. Do not report Step 2.5 clean on the strength of
      the balance and EWI checks alone — re-run the diff and quote its output.
- [ ] Zero headless models — every model outside `models/macro_tests/` has a live `FROM`
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
  | xargs sed -i '' 's/dbt_utils\.surrogate_key(/dbt_utils.generate_surrogate_key(/g'
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
grep -rn 'sort=\|dist=\|sort_key=\|dist_key=\|bind=' snowflake/models --include='*.sql'
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
  | xargs sed -i '' '/{{[[:space:]]*config()[[:space:]]*}}/d'
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
`type: redshift` (or bigquery, databricks, ...) on every run. Look for it proactively, and
**replace the connection block entirely** rather than adding a Snowflake target alongside
the old one — leaving the source target in place means a stray `--target` or a stale
`target:` default silently points dbt back at the source platform.

Replace with:

```yaml
<project_name>:
  target: snowflake
  outputs:
    snowflake:
      type: snowflake
      account: "{{ env_var('DBT_SNOWFLAKE_ACCOUNT') }}"
      user: "{{ env_var('DBT_SNOWFLAKE_USER') }}"
      role: "{{ env_var('DBT_SNOWFLAKE_ROLE') }}"
      database: "<TARGET_DATABASE>"
      warehouse: "<TARGET_WAREHOUSE>"
      schema: "<TARGET_SCHEMA>"
      threads: 4
```

Fill placeholders from `configure()`. Use `env_var()` for credentials — never
hardcode.

Give `database`/`warehouse` an `env_var()` default (e.g.
`"{{ env_var('DBT_SNOWFLAKE_DATABASE', 'dwh') }}"`) so a missing variable degrades to a
sensible value instead of a hard parse failure — `dbt parse` evaluates these at parse time
(see Step 5.3).

### 3.4 CHECKPOINT — Configs

- [ ] `packages.yml` has no adapter-specific packages and lists `dbt_utils` explicitly
- [ ] All remaining package version ranges are compatible with the installed dbt version
- [ ] `dbt_project.yml` has no placeholder `name:` or `profile:` values
- [ ] All adapter-specific model configs removed from `dbt_project.yml`, including unprefixed `dist:`/`sort:` and `+bind:`
- [ ] No `sort=`/`dist=`/`bind=` arguments remain in model `{{ config(...) }}` calls
- [ ] `vars:` reviewed for source-behavioral assumptions; anything suspect flagged for manual review
- [ ] `sources.yml` has no placeholder `database:` or `schema:` values
- [ ] Column types translated to Snowflake equivalents
- [ ] `profiles.yml` connection block **replaced** — `type: snowflake`, no source adapter target left behind

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

Check `reports/SnowConvert/Issues.csv` for any issues in `snowflake/models/`
files. Common fixable patterns:

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

### 5.3 dbt parse / compile Gate

**Prerequisites — both are mandatory, and `dbt parse` fails immediately without them.**

1. **Install packages.** `dbt parse` refuses to run when `packages.yml` lists packages that
   are not installed (`found N package(s) specified in packages.yml, but only 0 package(s)
   installed`). Step 3.0 must be done first, then:
   ```bash
   dbt deps --project-dir <DBT_PROJECT_PATH> --profiles-dir <PROFILES_DIR>
   ```
2. **Supply env vars.** `dbt parse` evaluates `env_var()` in `profiles.yml` at parse time
   even though it never connects, so unset variables abort the parse. When Snowflake
   credentials are not configured locally, dummy values are sufficient:
   ```bash
   DBT_SNOWFLAKE_ACCOUNT=dummy DBT_SNOWFLAKE_USER=dummy \
   DBT_SNOWFLAKE_ROLE=dummy DBT_SNOWFLAKE_WAREHOUSE=dummy \
   dbt parse --project-dir <DBT_PROJECT_PATH> --profiles-dir <PROFILES_DIR> --no-partial-parse
   ```

**Always pass `--no-partial-parse` while iterating.** Without it dbt reuses a cached partial
parse and a stale cache masks newly introduced errors, which turns a handful of real problems
into many rounds of confusing failures.

`<PROFILES_DIR>` is the directory holding the converted `profiles.yml` — normally
`<project>/snowflake`, not `~/.dbt`.

If `dbt-snowflake` is installed **and** real credentials are configured, prefer `dbt compile`
for deeper validation, since it resolves `ref()`/`source()` against the catalog:
```bash
dbt compile --project-dir <DBT_PROJECT_PATH> --profiles-dir <PROFILES_DIR>
```

For each failing node: read the error, apply the minimum fix, verify with
`dbt compile --select <node>`. Up to 5 attempts per node; mark as `needs-user`
on persistent failure.

If `dbt` is not installed:
> "Note: `dbt` is not installed — install with `pip install dbt-snowflake` to
> validate the output."

**A clean `dbt parse` does not mean the project works.** Parse never executes SQL, so it
cannot detect a function that does not exist on Snowflake, an invalid rewritten expression,
or a `ref()` that was commented out (Step 2.5.2). Do not report success on the strength of
the exit code alone — Step 2.5's checks and the macro fix log are what tell you the real
state.

### 5.4 CHECKPOINT — Refined SQL

- [ ] No remaining fixable EWIs in `reports/SnowConvert/Issues.csv`
- [ ] No `SSC-EWI-0001` blocks remain in any model — each was restored from source or genuinely translated
- [ ] Every model has a live `FROM` clause; no `ref()` survives only inside a comment
- [ ] Every `{{ ref() }}` call resolves to an existing model
- [ ] No deprecated `dbt_utils` macro calls remain (Step 5.0)
- [ ] `dbt deps` run, and `dbt parse` exits 0 with `--no-partial-parse`
- [ ] `dbt compile` exits 0 (if dbt is installed and credentials configured)
- [ ] All `needs-user` items listed with file path + error + recommended action

---

## On Completion

Tell the user:

> **dbt repointing complete.**
>
> Repointed models: `snowflake/models/`
> Reports: `reports/SnowConvert/`
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
