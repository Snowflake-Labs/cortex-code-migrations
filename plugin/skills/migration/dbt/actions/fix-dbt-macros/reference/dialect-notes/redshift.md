## Redshift → Snowflake macro fix patterns

**Status: known patterns, grounded in a real repointed project.** This is a dialect note reached from both `macro-fix-approach.md` and the model-SQL refinement step — the patterns below apply to **any** Redshift SQL this skill rewrites, model or macro, because the dialect truth is the same in both places. Use it as an accelerant when `SOURCE_DIALECT` is Redshift, not as the only source of fixes. Anything not listed here still gets fixed by applying the general checklist and your own knowledge of Redshift vs. Snowflake SQL; if you find and apply a new pattern that isn't below, add it here before finishing the run (see "Improving this file" at the end).

Each pattern names the Redshift-ism, why it breaks on Snowflake, and the exact rewrite. Patterns are ordered roughly by frequency observed in real repointed projects.

> **The counts come from one project, and they are not a forecast.** Almost every site count
> below was measured on a single 2,180-model Redshift repointing. A recall audit against that
> project's shipped code found roughly 90% of its defect sites — but that figure is close to
> tautological, because these patterns were authored *from* that repo, and its counts reproduce
> to the digit. On a fresh project expect materially lower coverage, expect classes that are not
> here at all, and treat a count as "this existed once at this scale" rather than "expect this
> many." Thirteen detectors below found **zero** hits on that project and are kept because they
> are real dialect differences, not because they were exercised. When you hit a class that is
> missing, add it — see "Improving this file."

> **Detector scope, once for the whole file.** Every `grep` below is scoped to `artifacts/models artifacts/tests` deliberately. A converted project's `artifacts/` holds three trees (including `source_raw/`) plus a duplicate copy, so a bare `grep -r artifacts/` triple-counts every hit. Counts quoted in the patterns below were measured with that scope. Detectors that must read dbt `config()` blocks are the exception and are scoped to the dbt project tree instead — Pattern 24 explains why.

### 1. Redshift/Postgres system catalogs → INFORMATION_SCHEMA

Redshift-specific catalogs don't exist on Snowflake:

| Redshift | Snowflake |
|---|---|
| `svv_redshift_tables`, `svv_redshift_columns`, `SVV_COLUMNS`, `svv_all_columns` | `{{ database }}.INFORMATION_SCHEMA.TABLES` / `.COLUMNS` (verified live: `SVV_COLUMNS` raises "does not exist" on Snowflake; the others are the same class of Redshift-only view) |
| `pg_catalog.pg_tables` | `INFORMATION_SCHEMA.TABLES WHERE table_type = 'BASE TABLE'` |
| `pg_catalog.pg_views` | `INFORMATION_SCHEMA.TABLES WHERE table_type = 'VIEW'` |
| `pg_catalog.svv_all_schemas` | `INFORMATION_SCHEMA.SCHEMATA` |
| `svv_datashare_objects` | No 1:1 equivalent — see Pattern 7 (non-portable) |

`svv_all_columns`'s columns are `database_name`/`schema_name`/`table_name`/`column_name` — rename to `table_catalog`/`table_schema`/`table_name`/`column_name` when switching to `INFORMATION_SCHEMA.COLUMNS`, plus the `UPPER()` wrapping below. `svv_all_schemas` has a numeric `schema_owner` column (e.g. filtering `schema_owner <> 1` to exclude superuser-owned schemas) with no Snowflake equivalent — there is no owner-id column on `INFORMATION_SCHEMA.SCHEMATA`. Don't invent one; replace the filter with the closest semantic equivalent for what the query is actually trying to exclude (e.g. `schema_name <> 'INFORMATION_SCHEMA'` to skip the system schema) and note the substitution in the fix log — it is an approximation, not an exact translation.

Column renames that go with the catalog swap: `schemaname` → `table_schema`, `tablename`/`viewname` → `table_name`, `database_name` → unchanged but now scoped as `<db>.INFORMATION_SCHEMA...` rather than a global catalog row.

**Identifier casing**: Snowflake stores unquoted identifiers uppercase. Any comparison against a schema/table/column name coming from a macro argument must be wrapped in `UPPER(...)`:

```sql
-- Redshift
WHERE schema_name = '{{ schema_name }}'
  AND table_name = '{{ table_name }}'

-- Snowflake
WHERE table_schema = UPPER('{{ schema_name }}')
  AND table_name   = UPPER('{{ table_name }}')
```

Prefer a `{% set query %}...{% endset %}` block over Jinja string concatenation (`"..." + var + "..."`) when rewriting — it's the standard dbt idiom and avoids quoting bugs.

### 2. `AT TIME ZONE` — reserved-word collision

Snowflake's `AT (...)` / `BEFORE (...)` clauses are time-travel syntax, so `col AT TIME ZONE 'tz'` does not parse the way it does on Redshift/Postgres.

```sql
-- Redshift
{{ col }}::TIMESTAMP AT TIME ZONE '{{ tz }}'

-- Snowflake
CONVERT_TIMEZONE('UTC', '{{ tz }}', {{ col }}::TIMESTAMP_NTZ)
```

Assume the source column is UTC unless the macro's docstring says otherwise; make the source zone the first `CONVERT_TIMEZONE` argument and the target zone the second.

### 3. `TRIM(<char> FROM <expr>)` — SQL-standard form unsupported

Snowflake's `TRIM` only accepts the positional form `TRIM(expr [, chars_to_remove])`, not the SQL-standard `FROM` syntax.

```sql
-- Redshift
TRIM(' ' FROM {{ col }})

-- Snowflake
TRIM({{ col }})
```

If the trimmed character isn't a plain space, keep it as the second positional argument: `TRIM({{ col }}, '{{ char }}')`.

### 4. Semi-structured function renames

| Redshift | Snowflake |
|---|---|
| `JSON_PARSE(expr)` | `PARSE_JSON(expr)` |
| `SPLIT_TO_ARRAY(expr, delim)` | `SPLIT(expr, delim)` |
| `regexp_replace(..., x -> upper(x[1]) || lower(x[2]))` (Trino/Athena lambda-based title-case, sometimes vendored into Redshift projects for cross-engine macros) | `INITCAP(expr)` |

Both `JSON_PARSE`/`SPLIT_TO_ARRAY` return a variant/array-typed value; no argument reordering needed. Snowflake's `INITCAP` is a native title-case function — if a macro implements title-casing via a lambda-based `regexp_replace` (common in macros shared with Athena/Trino), replace the whole expression with `INITCAP(expr)` rather than trying to port the lambda syntax, which Snowflake doesn't support at all.

Verified live: `SPLIT_TO_ARRAY` and `JSON_PARSE` raise "Unknown function"; `PARSE_JSON` and `SPLIT` both run correctly.

### 5. RBAC: `GROUP` → `ROLE`

Redshift's `GROUP` grant target doesn't exist on Snowflake — everything is a `ROLE`.

```sql
-- Redshift
grant usage on schema {{ schema }} to group {{ role_name }};

-- Snowflake
grant usage on schema {{ schema }} to role {{ role_name }};
```

Apply this to every `grant ... to group X` occurrence in the macro, including nested ones inside loops/conditionals. Update `log(...)` messages that say "granting ... to group" to say "role" too, so log output matches what actually ran.

**Bare grant targets with no `GROUP` keyword** (e.g. `grant usage on schema x to looker;` or `grant usage on schema x to some_person;`) are ambiguous — Redshift lets you grant directly to a user or group name with no qualifier. Default to `TO ROLE <name>` (dbt grant macros overwhelmingly target roles, and tool-account names like `looker` almost always are one), but record the assumption in the fix log — if the name looks like a person's name rather than a service/role name, it may actually need `TO USER <name>` instead, and that's a judgment call worth a human's confirmation.

**Environment gating**: grant-management macros are commonly wrapped so they only run in real deployment targets, not local/sandbox dev:

```sql
{% if env_var('ENVIRONMENT', 'local') not in ['local', 'sandbox'] %}
  grant select on {{ this }} to role {{ role_name }}
{% else %}
  SELECT 1  -- skip role grants in local/sandbox environment
{% endif %}
```

If the macro has no such guard and its only purpose is issuing grants, add one — unguarded grant macros are a common source of local-dev failures once the underlying roles don't exist outside prod.

### 6. Platform-specific env var and config key renames

| Redshift-era | Snowflake |
|---|---|
| `env_var('REDSHIFT_DBNAME')` | `env_var('SNOWFLAKE_DB', '<default>')` |
| `env_var('REDSHIFT_USERNAME')` | `env_var('SNOWFLAKE_USERNAME', target.user \| lower)` |

Always add a default as the second `env_var()` argument when converting — Redshift projects often assumed the var was always set; Snowflake profiles frequently derive the same value from `target.user`/`target.database`, so a fallback avoids a hard failure when the var is absent.

Two Redshift-only `dbt_project.yml` config keys sometimes leak into macros as string literals or comments — flag but don't try to "fix" them in a macro body, they belong in config validation (a sibling skill's scope): `dist: <col>` (distribution style) and `+bind: false` (late-binding views). If you see a macro that *sets* one of these via `run-operation`, treat it as non-portable (Pattern 7).

### 7. Non-portable macros — archive, don't rewrite

Some Redshift macros have no Snowflake equivalent because the underlying feature doesn't exist on Snowflake at all:

- `UNLOAD ... TO 's3://...'` — Redshift's bulk export command. Snowflake's equivalent (`COPY INTO <location>`) has a different security model (storage integration vs. IAM role) and isn't a mechanical rewrite.
- `SHOW DATASHARES` / `svv_datashare_objects` — Redshift datashare introspection. Snowflake sharing is a different object model (`SHOW SHARES`, `INFORMATION_SCHEMA` doesn't cover shares) and needs a human to redesign the check, not translate it.
- Superuser-only DDL (e.g. granting a PL/Python or other language extension) — Snowflake has no equivalent superuser/language-grant concept.

**Do not guess a rewrite for these.** Move the macro file to `macros/_archived/<original_name>.sql`, unchanged, and record it in the report (Step 6) as `needs-user` with the specific reason. This mirrors the real precedent in `dwh/transforms-snow/macros/_archived/` (`redshift_udfs.sql`, `refresh_datashare.sql`, `unload_to_s3.sql`) — a human redesigned the equivalent behavior separately rather than the fixer inventing one.

Detect a candidate for this pattern when a macro body's core logic (not an incidental reference) depends on one of the identifiers above, or on any Redshift system view starting with `sv_`/`svv_`/`svl_`/`stl_` that isn't covered by Pattern 1's INFORMATION_SCHEMA mapping.

### 8. `APPROXIMATE COUNT(DISTINCT ...)` — modifier syntax vs. function

Redshift supports `APPROXIMATE` as a query modifier keyword directly in front of an aggregate. Snowflake has no such modifier — approximate distinct counting is a separate function.

```sql
-- Redshift
SELECT APPROXIMATE COUNT(DISTINCT {{ col }})

-- Snowflake
SELECT APPROX_COUNT_DISTINCT({{ col }})
```

Verified live: the Redshift form raises `SQL compilation error: syntax error ... unexpected '('` on Snowflake; `APPROX_COUNT_DISTINCT(...)` runs and returns the same approximate cardinality.

### 9. `IS_VALID_JSON` — Redshift JSON validity check

Redshift's `IS_VALID_JSON(expr)` boolean check doesn't exist on Snowflake:

```sql
-- Redshift
WHEN IS_VALID_JSON({{ url_params }})

-- Snowflake
WHEN TRY_PARSE_JSON({{ url_params }}) IS NOT NULL
```

`TRY_PARSE_JSON` returns `NULL` on invalid JSON and a VARIANT on success — `IS NOT NULL` replicates the boolean test.

**Do not also rewrite `JSON_EXTRACT_PATH_TEXT` in the same macro just because it looks Redshift-specific.** Verified live: `JSON_EXTRACT_PATH_TEXT(col, 'key')` already runs correctly on Snowflake, unchanged — Snowflake ships it as a compatibility alias. Fix only the part of the macro that actually fails (`IS_VALID_JSON` here); leave `JSON_EXTRACT_PATH_TEXT` calls exactly as they are. This is the general lesson of Pattern 12/"What NOT to touch" below: a name looking Redshift-specific is not proof it's broken.

### 10. `CURRENT_SETTING('timezone')` — Redshift/Postgres time functions

| Redshift/Postgres | Snowflake |
|---|---|
| `CURRENT_SETTING('timezone')` | `CURRENT_TIMEZONE()` |

`CURRENT_SETTING(...)` raises `Unknown function` on Snowflake.

**`getdate()` is NOT in this table — it is native to Snowflake.** `GETDATE()` is a documented
Snowflake function, an alias for `CURRENT_TIMESTAMP` ([docs](https://docs.snowflake.com/en/sql-reference/functions/getdate)).
An earlier revision of this file claimed `getdate()` raises `Unknown function` and mapped it
to `CURRENT_TIMESTAMP()`; that claim was wrong. Rewriting it is harmless but churns the diff
and costs reviewer attention — leave it alone. See Pattern 16.

When a macro chains two `AT TIME ZONE` uses to convert from the session zone to a target zone (e.g. `getdate() AT TIME ZONE CURRENT_SETTING('timezone') AT TIME ZONE {{ tz }}`), collapse it to a single `CONVERT_TIMEZONE`. Here the rewrite is driven by `CURRENT_SETTING` and the `AT TIME ZONE` chain, not by `getdate()`:

```sql
-- Redshift
getdate() AT TIME ZONE CURRENT_SETTING('timezone') AT TIME ZONE {{ tz }}

-- Snowflake
CONVERT_TIMEZONE('{{ tz }}', CURRENT_TIMESTAMP()::TIMESTAMP_NTZ)
```

### 11. Redshift SUPER field access → Snowflake VARIANT colon notation

Redshift's SUPER type uses dot notation to access nested JSON fields. Snowflake's VARIANT uses colon (`:`) notation:

```sql
-- Redshift SUPER
json_col.nested_field

-- Snowflake VARIANT
json_col:nested_field
```

**The field name after `:` must be a bareword, never a quoted string — `col:'field'` is a syntax error, `col:field` is correct.** This matters most when the field name comes from a Jinja variable: write `col:{{ field_var }}` (renders to a bareword like `col:utm_source`), not `col:'{{ field_var }}'` (renders to `col:'utm_source'`, which fails to parse). Verified live — the quoted form raises a syntax error, the bareword form returns the value correctly.

```sql
-- Redshift
json_parse(pages) pages,
...
pages.data as response

-- Snowflake
PARSE_JSON(pages) AS pages,
...
pages:data AS response
```

The implicit lateral unnesting form `FROM table t, t.super_col AS alias, alias.nested AS alias2` (used to iterate arrays inside SUPER columns) has no mechanical Snowflake equivalent — that requires `LATERAL FLATTEN` and depends on the live JSON shape to get right. Flag it NEEDS-USER rather than guessing; only fix the simple field-access cases shown above.

### 12. `DIFFERENCE()` — no Snowflake equivalent, prefer NEEDS-USER

`DIFFERENCE(a, b)` returns a 0–4 SOUNDEX-based similarity score on Redshift. **Verified
live: Snowflake raises `Unknown function DIFFERENCE`.** `SOUNDEX` itself does exist. See Pattern 16 for the confirmed-native list.

It is tempting to approximate it with a prefix-match CASE:

```sql
-- APPROXIMATION ONLY - NOT equivalent, do not apply silently
CASE WHEN SOUNDEX(a) = SOUNDEX(b) THEN 4
     WHEN LEFT(SOUNDEX(a),3) = LEFT(SOUNDEX(b),3) THEN 3
     WHEN LEFT(SOUNDEX(a),2) = LEFT(SOUNDEX(b),2) THEN 2
     WHEN LEFT(SOUNDEX(a),1) = LEFT(SOUNDEX(b),1) THEN 1
     ELSE 0 END
```

**This is not a faithful translation.** Redshift's `DIFFERENCE` scores how many SOUNDEX
character *positions* agree, not how long a shared prefix is, so the two disagree on real
inputs. `DIFFERENCE` is overwhelmingly used for fuzzy identity matching (patient, customer,
address dedupe), where a changed score silently changes match rates with no error raised —
category **g** in `macro-fix-approach.md`.

Flag it **NEEDS-USER** and offer the CASE above as a starting point for the human to
calibrate against their own data. Do not apply it as an automatic fix.

### 13. `EXTRACT` on a timestamp difference — type change, not a rename

Redshift: `TIMESTAMP - TIMESTAMP` yields an INTERVAL, so `EXTRACT(DAYS FROM diff)` works.
Snowflake: the same subtraction yields a **number of days as a FLOAT**, and `EXTRACT`
fails on it. This needs two coordinated edits, not a function swap:

```sql
-- Redshift
(ts2 - ts1) AS diff,
EXTRACT(MICROSECOND FROM diff),
EXTRACT(DAYS FROM diff)

-- Snowflake
DATEDIFF(MICROSECOND, ts1, ts2) AS diff,   -- integer microseconds
diff,                                      -- already in microseconds
FLOOR(diff / 86400000000.0)                -- microseconds -> whole days
```

Redefine the difference column with an explicit `DATEDIFF` unit first, then rewrite each
`EXTRACT` against that unit. Watch the argument order: `DATEDIFF(unit, start, end)` is the
reverse of the `end - start` it replaces, so getting it backwards silently flips the sign.

**Scope note.** `EXTRACT(x FROM (` is a narrow detector — 10 hits in the measured corpus, and
`master` rewrote **none** of them. The high-volume form of this same type change is a *bare*
`a - b` with no `EXTRACT` wrapper, 270 sites of which the repair did rewrite. See
**Pattern 31**, which owns the detector; this pattern only covers the `EXTRACT`-wrapped shape.

### 14. `DATE_CMP(a, b)` — comparison helper

**Verified live: Snowflake raises `Unknown function DATE_CMP`.** Redshift returns -1/0/1.
Translate by the comparison it feeds, not mechanically:

| Redshift | Snowflake |
|---|---|
| `DATE_CMP(a, b) = 0` | `a = b` |
| `DATE_CMP(a, b) < 0` | `a < b` |
| `DATE_CMP(a, b) > 0` | `a > b` |

Only rewrite to a bare `a = b` when the call really is compared against `0`. If the result
is stored, returned, or passed onward as -1/0/1, preserve the three-way semantics with
`SIGN(DATEDIFF(day, b, a))` instead of collapsing it to a boolean.

### 15. `~*` and `~` regex operators → `RLIKE`

Redshift's `~*` (case-insensitive) and `~` (case-sensitive) regex match operators do not
exist on Snowflake. `RLIKE` replaces both — but **`RLIKE` is case-sensitive**, so `~*` does
not map to it directly:

```sql
-- Safe: the left side is already lowercased, so case-insensitivity is preserved
LOWER(col) ~* 'pattern'   ->   LOWER(col) RLIKE 'pattern'

-- NOT safe: this silently becomes case-sensitive
col ~* 'pattern'          ->   col RLIKE 'pattern'          -- WRONG
col ~* 'pattern'          ->   LOWER(col) RLIKE LOWER('pattern')   -- correct
```

Check what is on the left of the operator before replacing. If it is not already wrapped in
`LOWER()`, add the wrapping on both sides, or the match set changes with no error. `~` maps
to `RLIKE` unchanged.

### 16. Verified to exist on Snowflake — do NOT rewrite

Every function below **runs unmodified on Snowflake** despite a Redshift/Postgres-sounding
name. Each has been confirmed with a live query. Rewriting them is a regression: it adds
noise, and hand-rolled replacements are usually worse than the native function.

| Function | Evidence |
|---|---|
| `LEAST_IGNORE_NULLS(...)` | `SELECT LEAST_IGNORE_NULLS(1, NULL, 3)` → `1` |
| `GREATEST_IGNORE_NULLS(...)` | `SELECT GREATEST_IGNORE_NULLS(1, NULL, 3)` → `3` |
| `JSON_EXTRACT_PATH_TEXT(...)` | Snowflake compatibility alias |
| `SOUNDEX(...)` | native (unlike `DIFFERENCE` — see Pattern 13) |
| `SELECT * EXCLUDE (<col>)` | native Snowflake syntax; SnowConvert may still emit `SSC-EWI-0001` on it, which is a converter false negative, not an incompatibility |
| `LISTAGG(DISTINCT <col>, <sep>) WITHIN GROUP (ORDER BY ...)` | `SELECT LISTAGG(DISTINCT c, '\|') WITHIN GROUP (ORDER BY c)` over `'b','a','b'` → `a\|b`. `DISTINCT` **and** `WITHIN GROUP` are both native. SnowConvert flags it as an FDM anyway — another false positive |

**`LISTAGG` is the costliest trap in this table, because the plausible rewrite silently loses
ordering.** Translating it to `ARRAY_TO_STRING(ARRAY_AGG(DISTINCT col), sep)` drops the
`WITHIN GROUP (ORDER BY ...)` clause, and `ARRAY_AGG` without an explicit `ORDER BY` has no
ordering guarantee in Snowflake — so the concatenated string becomes non-deterministic across
runs. This happened on a real run in four models. Leave `LISTAGG` exactly as it is, FDM or not.

**Redshift/Postgres type aliases are accepted as cast targets** and must not be rewritten.
All verified live on a real run (`select 1::double precision, current_timestamp::timestamptz,
''::character varying, ''::text, current_timestamp::datetime` — all succeed):

| Cast target | Snowflake result |
|---|---|
| `::double precision` | native (→ FLOAT) |
| `::timestamptz` | native (→ TIMESTAMP_TZ) |
| `::character varying` | native (→ VARCHAR) |
| `::text` | native (→ VARCHAR) |
| `::datetime` | native (→ TIMESTAMP_NTZ) |

SnowConvert *does* normalise several of these (`character varying` → `VARCHAR`,
`timestamp without time zone` → `TIMESTAMP_NTZ`), which is cosmetic — a source file using the
alias form already runs. **Consequence for verification tooling:** do not use a
source-vs-converted token diff to hunt for conversion damage. Those legitimate normalisations
all register as token loss — on one real run that was 472 files / 5,651 tokens of noise against
13 genuinely damaged files.

Two more verified-native forms:

| Construct | Evidence |
|---|---|
| `POSITION(x IN y)` | `SELECT POSITION('d' IN 'abcd')` → `4`. The SQL-standard `IN` form works, not just `POSITION(x, y)` |
| `GETDATE()` | returned a live timestamp (`2026-09-28T14:58:46`), and is [documented](https://docs.snowflake.com/en/sql-reference/functions/getdate) as an alias for `CURRENT_TIMESTAMP` |

> **Formerly conflicted with Pattern 10; resolved.** An earlier revision of Pattern 10 listed
> `getdate()` as raising `Unknown function` and mapped it to `CURRENT_TIMESTAMP()`, which
> contradicted the live result above. Snowflake's documentation settles it — `GETDATE()` is
> native — so Pattern 10's row was wrong and has been removed. `GETDATE()` is native: leave
> it alone.

`*_IGNORE_NULLS` is the trap worth naming explicitly: the name reads like a custom Redshift
UDF, and a plausible-looking `IFF(a IS NULL, b, IFF(b IS NULL, a, LEAST(a, b)))` rewrite is
both unnecessary **and wrong for more than two arguments**. Leave these alone.

When you confirm another such function during a run, add it to this table with its evidence
rather than only noting it in the fix log — that is what keeps the next run from repeating
the mistake.

### 17. `DROP VIEW ... CASCADE` — accepted by Snowflake, do NOT rewrite

Redshift/Postgres allow `CASCADE`/`RESTRICT` on both `DROP TABLE` and `DROP VIEW`. Snowflake
**documents** the clause only for `DROP TABLE`/`DROP SCHEMA`/`DROP DATABASE` — but its parser
accepts it on `DROP VIEW` as well, so the Redshift form runs unchanged.

Verified live, three statements distinguishing "accepted" from "tolerated by luck":

```sql
DROP VIEW IF EXISTS nodb.s.v CASCADE;   -- Database 'NODB' does not exist  <- parsed OK
DROP VIEW IF EXISTS nodb.s.v RESTRICT;  -- Database 'NODB' does not exist  <- parsed OK
DROP VIEW IF EXISTS nodb.s.v BANANA;    -- syntax error ... unexpected 'BANANA'
```

A genuinely invalid trailing clause fails at parse, before name resolution; `CASCADE` and
`RESTRICT` get past parse to name resolution. So the grammar accepts them on views.

**Do not branch a generic `DROP {{ object_type }} ... CASCADE` cleanup macro on object type
to strip `CASCADE` for views.** That rewrite is unnecessary churn on a working macro — the
exact failure mode Pattern 16 and "What NOT to touch" exist to prevent. The documentation gap
is not a compatibility gap.

One open edge, if it ever matters for a specific macro: this was confirmed at parse time only.
Whether `CASCADE` also has no *effect* on a real view drop (rather than being silently ignored)
was not testable on the connection used — it lacked privileges to create a view. Since
Snowflake has no view-level FK dependency for the clause to act on, ignoring it is the
expected behavior, and the pre-existing Redshift semantics were the same no-op in practice.

### 18. Grant macro targets with no `GROUP` keyword can still need `TO ROLE`, not `TO USER`

Extending Pattern 5's bare-target guidance: on real Redshift projects, an unqualified grant
target (`grant usage on schema x to some_name;`) is actually a Redshift **user**, since
Redshift's grant grammar defaults an unqualified name to a user, not a group. That does not
mean it should become `TO USER` on Snowflake — Snowflake privilege management is
role-centric, and even a name that reads as a person (e.g. `jane_doe`) is very often
backed by a personal role, not direct user grants. Default to `TO ROLE <name>` here too, and
still flag the specific name in the fix log for human confirmation — the judgment call is
about *whether that role exists*, not about picking `USER` over `ROLE`.

### 19. Timezone name literals — Redshift's vocabulary is wider than Snowflake's

**47 fatal sites in one real project.** Snowflake accepts only IANA zone names (and a small
set of offsets); Redshift additionally accepts POSIX-style `GMT±HH:MM` strings and
abbreviations. The converter passes the literal through verbatim, so every one of these
raises `100094 (22000) Unknown timezone` — **per row**, which means they pass
`dbt run --empty` and fail on the first real row. This was the largest block of
falsely-green models in the project.

| Redshift literal | Sites / files | Snowflake |
|---|---|---|
| `CONVERT_TIMEZONE('GMT-06:00', …)` | 28 / 24 | `100094` — `'-06:00'` and `'GMT-6'` are also rejected |
| `CONVERT_TIMEZONE('CST', …)` | 18 / 6 | `100094` — abbreviations are not zone names |
| `CONVERT_TIMEZONE('america/chicago', …)` | 1 / 1 | `100094` — **zone names are case-sensitive** |

**Case-sensitivity is the non-obvious half:** `'America/Chicago'` works and
`'america/chicago'` does not, and nothing in the error hints that casing is the cause.
Normalise casing before assuming a zone name is invalid.

#### Choosing the replacement zone — do not infer it from the offset

This is the part that matters. `GMT-06:00` does **not** determine the target zone, because
POSIX inverts the sign in the `Etc/GMT±N` names. The plausible candidates disagree by about
eleven hours:

| Candidate | `2024-03-15 00:00 UTC` becomes |
|---|---|
| `Etc/GMT-6` (POSIX: actually UTC**+**6) | `2024-03-14 18:00` |
| `America/Chicago` (UTC−6, with DST) | `2024-03-15 05:00` |

So `Etc/GMT-6` is UTC **+6** and `Etc/GMT+6` is UTC **−6** — the opposite of how the name
reads. Picking by offset arithmetic silently shifts every timestamp in the model.

Resolve it by **evidence from the project**, in this order:

1. **A matched sibling model.** In the real run, `other_writeoffs/savings_writeoff_receiver.sql`
   built the same `event_time` column the same way using
   `CONVERT_TIMEZONE('America/Chicago','UTC', …)`. A sibling in the same directory writing the
   same column settles it outright.
2. **The project's dominant convention.** Measured over the converted corpus,
   `America/Chicago` appears **249** times against **28** for `GMT-06:00`.
3. **Otherwise flag NEEDS-USER** and state the magnitude of the candidate disagreement (here,
   either one hour or twelve depending on how Redshift read the original) so the human knows
   what they are deciding.

Leaving the invalid literal in place is never the safe default — it is the one option
guaranteed to fail. "Escalate" must not become "ship it broken".

#### Detector for the literal half — census the zone, then judge against IANA

Do not hard-code the bad strings. `grep -ro "'CST'"` returns **19 hits with 1 false positive**
(a commented `-- at time zone 'CST'`) and tells you nothing about the next project's
vocabulary. Instead extract every `CONVERT_TIMEZONE` **first-argument** literal and compare
the census against valid IANA zone names — "any zone literal not in the allow-list" rather
than three remembered strings:

```bash
grep -rhoiE "CONVERT_TIMEZONE\([[:space:]]*'[^']*'" artifacts/models artifacts/tests --include=*.sql \
  | sed -E "s/.*'([^']*)'.*/\1/" | sort | uniq -c | sort -rn
```

Measured output on the real project — it reproduces the table above exactly and separates
valid from invalid in one read:

```
 214 America/Chicago     <- valid IANA
  28 GMT-06:00           <- invalid: POSIX offset string
  27 UTC                 <- valid
  18 CST                 <- invalid: abbreviation
   1 america/chicago     <- invalid: casing
```

28 + 18 + 1 = the **47 fatal sites** quoted at the top of this pattern, and the detector
adjudicates that figure rather than asserting it. Judge each distinct literal once — the
census collapses thousands of lines into a handful of decisions.

**The census is the point, not a suspicion list.** 241 of the 288 first-argument literals here
are valid. Consistent with the three-argument caution below, the detector must not be read
as flagging `CONVERT_TIMEZONE` itself; the function is right far more often than it is wrong.

#### The nested-call defect — a separate, invisible bug

**22 sites / 6 models.** Where the Redshift source chained `AT TIME ZONE` twice, the converter
collapsed it into a nested call with the timezone literals fed in as *data*:

```sql
-- emitted: the inner call gets 'UTC' in the timestamp position
CONVERT_TIMEZONE(CONVERT_TIMEZONE('America/Chicago','UTC','UTC'),'UTC', x)

-- correct
CONVERT_TIMEZONE('UTC','America/Chicago', x)
```

It raises `100035 (22007) Timestamp 'UTC' is not recognized` — again per row, so all 6 models
reported PASS under `--empty`. Reconstruct from the source's `AT TIME ZONE` order rather than
swapping arguments in place:

| Source | Snowflake |
|---|---|
| `x at time zone 'UTC' at time zone 'America/Chicago'` | `CONVERT_TIMEZONE('UTC','America/Chicago', x)` |
| `x at time zone 'America/Chicago' at time zone 'UTC'` | `CONVERT_TIMEZONE('America/Chicago','UTC', x)` |

A nested `CONVERT_TIMEZONE` whose inner call has a string literal in the timestamp position is
always a defect — no human writes that. Detector (verified: 22 hits, 0 false positives):

```bash
grep -rn "CONVERT_TIMEZONE([^)]*CONVERT_TIMEZONE" artifacts/models artifacts/tests --include=*.sql
```

**Do not blind-swap three-argument calls.** Only 12 of 208 three-arg calls in that project
were wrong; the correct arity depends on whether the operand is `TIMESTAMP_NTZ` (3-arg) or
`TIMESTAMP_TZ` (2-arg).

### 20. `TO_CHAR` / `TO_NUMBER` format models — silent wrong output, no error

**Silent wrong output, with no error anywhere to triage by.** Snowflake accepts
several Postgres/Redshift format-model tokens and **mis-parses** them, returning a
plausible-looking string. No error, no FDM, no failed test.

Snowflake reads `Month` as `Mon` + `t` + `h`, and `Day` as `D` + `a` + `y`, filling in from
its own token set:

| Pattern | Redshift | Snowflake | Sites |
|---|---|---|---|
| `TO_CHAR(ts,'Month')` | `July` | **`Jult13`** | 3 |
| `TO_CHAR(ts,'YYYY-Month')` | `2024-July` | **`2024-Jult13`** | 2 |
| `TO_CHAR(ts,'Day')` | `Monday` | **`15a24`** | 2 |
| `cast(TO_CHAR(d,'Q') as smallint)` | `3` | returns the literal `'Q'`, then `100038 Numeric value 'Q' is not recognized` | 2 |

In the real run two of these sat in `date_table` and `calendar_table` — dimension tables whose
`month_name`/`day_name` feed dashboards project-wide, so the garbage propagated silently to
every consumer. Worst possible placement.

Correct equivalents (verified live):

| Redshift | Snowflake |
|---|---|
| `TO_CHAR(ts,'Month')` | `TO_CHAR(ts,'MMMM')` |
| `TO_CHAR(ts,'YYYY-Month')` | `TO_CHAR(ts,'YYYY-MMMM')` |
| `TO_CHAR(d,'Q')` | `QUARTER(d)` — a function, not a format token |
| `TO_CHAR(ts,'Day')` | `decode(dayname(ts), …)` — all seven arms, see below |

Full day names have no Snowflake format token at all, hence the `decode`. Enumerate all seven
days — a partial mapping returns `NULL` for the days it omits, which is a silent wrong result,
not an error:

```sql
decode(dayname(ts),
       'Mon','Monday',   'Tue','Tuesday', 'Wed','Wednesday',
       'Thu','Thursday', 'Fri','Friday',  'Sat','Saturday',
       'Sun','Sunday')
```

Use `DAYNAME` rather than `DAYOFWEEK` as the input — `DAYOFWEEK` is `WEEK_START`-dependent (Pattern 21).

**`TO_NUMBER` with a format model — 7 sites / 3 files**, all
`to_number(<numeric>, '999999999999999D99')`. Two independent problems: Snowflake's two-argument
`TO_NUMBER(expr, format)` requires a **string** first argument (`001045 (22023) argument needs
to be a string`), and it rejects Redshift's `D` decimal-separator token outright
(`100140 (22007)`), so even a string input would not port. Use the precision/scale form —
`'999999999999999D99'` is 15 integer digits, `D`, then 2 decimals:

```sql
to_number(aum, '999999999999999D99')   -- Redshift
to_number(aum, 17, 2)                  -- Snowflake: NUMBER(17,2)
```

**Do not generalise this to every `TO_CHAR` format model.** Currency-style models are portable:
`to_char(numeric, 'FMMI$999,999,999,990.00')` runs **unchanged** on Snowflake and returns
`$1,234.50`. In the real run that macro was the prime suspect and was innocent — it is
byte-identical to source and has ~40 callers. A blanket "translate all format models" rule
would have broken 40 call sites of working code. Fix the specific tokens in the tables above;
leave the rest alone.

Because these are *accepted*, execution is not a sufficient check: any format model carried
over verbatim should be round-tripped against a known input and compared to the Redshift
output.

### 21. `WEEK_START` — a session-parameter dependency, not a code defect

**Widespread** in one real project — `dow` extractions and `date_trunc('week', …)` across the
corpus. Nothing is wrong with the SQL; its *meaning* depends on a Snowflake session parameter
that Redshift has no equivalent of.

> **No site count is quoted here deliberately.** A `'dow'` or `'week'` literal is only
> `WEEK_START`-dependent in some positions, and no grep distinguishes the dependent uses from
> the inert ones — so any number would be an assertion rather than a measurement. Count the
> dependent sites in your own corpus before deciding between the two options below; the choice
> turns on the magnitude, and that is the one input worth establishing first-hand.

| `WEEK_START` | `dow` for Sunday | Matches Redshift? |
|---|---|---|
| `0` (Snowflake default) | `0` | yes |
| `1` | `7` | **no — silently shifts every site** |

At the default the behaviour matches Redshift, so a project is correct by luck until someone
changes the parameter. There is no error either way.

**Critical and non-obvious: this cannot be pinned from the dbt project.** `profiles.yml` has
no `session_parameters` field for this — dbt-snowflake builds its `session_parameters` payload
internally, from `query_tag` only. So the usual instinct (pin it next to the connection) does
not work. The remaining options are:

1. **Set it outside the project**, as a deployment prerequisite — one statement, and the
   reason this is the recommended route whenever the site count is non-trivial:
   ```sql
   ALTER USER <dbt_user> SET WEEK_START = 0;   -- or at account level
   ```
2. **Rewrite to a parameter-independent form** where a model must be self-contained —
   `DAYOFWEEKISO()` (always Monday=1…Sunday=7, immune to `WEEK_START`) plus arithmetic to map
   onto Redshift's Sunday=0. Correct but churn: rewriting every dependent site to avoid a
   one-statement setting is rarely the right trade.

Record the chosen option in the fix log either way — an account-level parameter is invisible
to every code-level gate, so a reader of the repo alone cannot tell the project depends on it.
`TIMESTAMP_TYPE_MAPPING` and `TIMEZONE` are the obvious neighbours worth the same treatment.

> Snowflake's documented defaults are `WEEK_START = 0` and `WEEK_OF_YEAR_POLICY = 0`. **Not
> re-verified live for this note** (no connection available); confirm with
> `SHOW PARAMETERS LIKE 'WEEK%' IN ACCOUNT` before relying on "it matches by default" for a
> specific account, since either can be set account-wide.

### 22. `listaggdistinct(expr, sep)` — a customer UDF, *not* a Snowflake function

**18 fatal call sites / 5 files.** `listaggdistinct` is a **customer-defined Redshift UDF**. It is
present in the Redshift source, so the converter did not invent it — it correctly left the
unknown user function unchanged and tagged it `SSC-EWI-0073`, which means the EWI is the only
signal that anything needs doing.

> **Count the call sites, not the name.** A bare `grep -c listaggdistinct` over this corpus
> returns **36**, exactly double the truth: the `SSC-EWI-0073` comment the converter appends
> to each call *names the node it flagged*, so every call is matched twice — once as code and
> once inside its own marker. Match `listaggdistinct\s*\(` to count calls. This applies to
> any EWI-tagged construct, not just this one.

```sql
-- Redshift (customer UDF)
listaggdistinct(m1_account_number, ', ') as account_numbers

-- Snowflake (native aggregate)
LISTAGG(DISTINCT m1_account_number, ', ') as account_numbers
```

It fails at name resolution — `Unknown function LISTAGGDISTINCT` — so `dbt run --empty`
catches it, but `dbt parse` and `dbt compile` do not. That is how all 18 sites survived to the
execution gate.

Add `WITHIN GROUP (ORDER BY …)` **only where the source shows ordering intent.** In the real
run no source site supplied an ordering, so adding one would invent a guarantee the Redshift
code never made.

> **Do not confuse this with Pattern 16's rule.** They point in opposite directions and are
> easy to conflate:
>
> | Construct | Action |
> |---|---|
> | `LISTAGG(DISTINCT col, sep) WITHIN GROUP (ORDER BY …)` — the **native aggregate** | **Do not rewrite.** Pattern 16. An FDM on it is a false positive, and the plausible `ARRAY_TO_STRING(ARRAY_AGG(...))` rewrite silently loses ordering |
> | `listaggdistinct(expr, sep)` — a **UDF whose name resembles it** | **Must be rewritten.** Leaving it is fatal |
>
> The distinction is between "the construct is native" and "this token is a user function that
> merely looks like the construct". Pattern 16's list is about constructs; a single-token
> function name is not covered by it.

If the UDF's exact semantics matter (NULL handling, dedup before or after casting, truncation),
the safe path is to obtain its Redshift definition from the customer and port it, rather than
assuming the one-line equivalence. Flag NEEDS-USER if any caller depends on those edges.

**A related genuine restriction on the native form:** Snowflake will not order a `DISTINCT`
aggregation by a column outside the distinct list, where Redshift allows it.

```sql
-- Redshift: allowed
LISTAGG(DISTINCT account_opening_reason, ', ') WITHIN GROUP (ORDER BY account_id)
-- Snowflake: 002024 (42601) [ACCOUNT_ID] is not a valid order by expression
```

Order by the distinct expression itself. **This changes the output ordering** of the
concatenated string, so it is a semantic change rather than a translation — surface it to the
user instead of applying it silently.

### 23. Zeroed interval literals — magnitude destroyed; and why the day-form is *not* safe

**11 zeroed sites / 11 files, all silent wrong answers.** Snowflake accepts
`current_date - interval '2 years'` **unchanged** — the correct conversion is *no* conversion.
SnowConvert nevertheless replaced month and year interval literals with a zeroed ANSI
day-to-second interval, discarding both magnitude and unit:

```sql
-- source (Redshift)
where funded_at >= current_date - interval '2 years'

-- converted: valid Snowflake, evaluates to zero
where funded_at >= current_date - INTERVAL '0 00:00:00' DAY TO SECOND
```

`INTERVAL '0 00:00:00' DAY TO SECOND` is zero, so the subtraction collapses to `current_date`
and the predicate silently narrows from "last two years" to "today". The model builds, the
tests pass, the number is wrong.

The zeroing is **unit-dependent**, which is what makes that half predictable — units
representable in a `DAY TO SECOND` interval keep their magnitude, month and year units do not:

| Source literal | Emitted | Magnitude kept? | Safe to leave? |
|---|---|---|---|
| `interval '2 days'` | `INTERVAL '2 00:00:00' DAY TO SECOND` | yes | **no — see below** |
| `interval '2 years'` | `INTERVAL '0 00:00:00' DAY TO SECOND` | **no — zeroed** | no |
| `interval'11 months'` | `INTERVAL '0 00:00:00' DAY TO SECOND` | **no — zeroed** | no |

In the measured corpus the failure rate for month/year units was 100% — 11 source month/year
literals (`interval '1 year'`, `interval '2 years'`, `interval '3 months'`, and
`interval'11 months'` ×8), 11 zeroed sites — and no `YEAR TO MONTH` interval was emitted
anywhere. The worst shape is a single predicate carrying both behaviours, where the
magnitude-preserving conversion sits beside the broken one and makes it look deliberate:

```sql
-- converted: first bound destroyed, second bound kept its magnitude
where d.day between CURRENT_DATE() - INTERVAL '0 00:00:00' DAY TO SECOND
                and DATE_TRUNC('week', CURRENT_DATE())::date - INTERVAL '1 00:00:00' DAY TO SECOND
```

**Fix the zeroed form by restoring the source literal verbatim**, not by computing a
replacement interval. Detector — any hit is a dropped interval, since a zeroed interval literal
is never something a human wrote:

```bash
grep -rn "INTERVAL '0 00:00:00'" artifacts/models artifacts/tests --include=*.sql
```

Pair it with the inverse check against the source: every `interval'<n> month|year'` in the
source must still carry its magnitude after conversion. Note the source spells these **without
a space** (`interval'11 months'`), so a source-side detector must not assume one.

#### The non-zero day-form is **not** automatically safe — do not green-light it

`INTERVAL 'N 00:00:00' DAY TO SECOND` is valid Snowflake *in isolation* and keeps its
magnitude, so it is tempting to leave alone. **In this corpus most of it was wrong anyway**,
because it usually appears as an operand of a converted timestamp subtraction (Pattern 31).
Measured across `artifacts/models artifacts/tests` → `master`:

| Emitted form | artifacts | master | verdict |
|---|---|---|---|
| `INTERVAL '2 00:00:00' DAY TO SECOND` | 90 | **0** | all 90 rewritten to `- 172800` |
| `INTERVAL '1.5 00:00:00' DAY TO SECOND` | 18 | **0** | all 18 → `- 129600` |
| `INTERVAL '0.5 00:00:00' DAY TO SECOND` | 18 | **0** | all 18 → `- 43200` |
| `INTERVAL '1 00:00:00' DAY TO SECOND` | 33 | 27 | 6 rewritten, **27 kept** |
| `INTERVAL '30 00:00:00' DAY TO SECOND` | 2 | 2 | **both kept** |
| `INTERVAL '0 00:00:00' DAY TO SECOND` | 11 | **0** | zeroed — restore from source |

143 of 172 day-to-second intervals were removed; 29 survive. The survivors are the ones doing
plain date arithmetic against a `DATE`/`TIMESTAMP`. The casualties are the ones sitting next to
a `ts - ts` subtraction:

```sql
-- converted
then (first_contact - created_at) - INTERVAL '2 00:00:00' DAY TO SECOND
-- master (ground truth)
then DATEDIFF(second, created_at, first_contact) - 172800
```

The interval change is a **consequence of the subtraction fix, not an independent defect**.
Redshift's `ts - ts` yields an interval/number; the repair rewrote it to
`DATEDIFF(second, …)`, which returns an **integer**. You cannot subtract an interval from an
integer, so once the subtraction is corrected the interval operand has to become a count of
seconds (`2 days → 172800`).

**Order of operations: fix the subtraction first (Pattern 31), then make the interval operand
match the type the other operand ended up with.** Deciding the interval's fate on its own —
in either direction — is how you get non-compiling code or a silently wrong unit. Verify by
reading the full expression, not the literal:

```bash
# day-form intervals, with surrounding context so you can see the other operand
grep -rn -B2 "INTERVAL '[0-9.]* 00:00:00' DAY TO SECOND" artifacts/models artifacts/tests --include=*.sql
```

The general rule this is the clearest instance of: **a converted numeric or temporal literal
that differs from the source literal is a defect, not a translation.**

### 24. Expression-valued `unique_key` on an incremental model

**5 models.** Not Redshift-vs-Snowflake syntax, but a repointing consequence that only
surfaces on Snowflake, so it belongs with the dialect gaps. dbt builds each merge predicate as
`DBT_INTERNAL_SOURCE.{{ key }} = DBT_INTERNAL_DEST.{{ key }}`, substituting the `unique_key`
entry **as a bare identifier**. An expression therefore becomes:

```sql
-- config: unique_key=["coalesce(m1_expected_email_address, '')", 'm1_expected_document_date']
DBT_INTERNAL_SOURCE.coalesce(m1_expected_email_address, '')
  = DBT_INTERNAL_DEST.coalesce(m1_expected_email_address, '')
-- 002028 (42601): ambiguous column name
```

It worked on Redshift only because dbt-redshift used `delete+insert` rather than `merge`, so
the repointing is what exposes it. An expression `unique_key` is unsupported on every adapter.

**Fix:** materialize the expression as a named column in the model body and point `unique_key`
at the column name.

```sql
select coalesce(m1_expected_email_address, '') as m1_expected_email_key, ...
-- then: unique_key=['m1_expected_email_key', 'm1_expected_document_date']
```

**The detection trap is the valuable part of this pattern.** On a first build the relation does
not exist, so dbt emits `CREATE TABLE AS` and the `MERGE` is **never compiled** — a one-pass
`dbt run --empty` says nothing about the incremental path. In the real run **4 of the 5 models
falsely reported PASS** on the first pass and all 5 failed on the second. Run the execution
gate **twice** and treat the second pass as the gate for incremental models.

Static detector — a `unique_key` entry containing `(` is always wrong:

```bash
grep -rl 'unique_key' <dbt_project>/models --include=*.sql | xargs \
  perl -0777 -ne 'print "$ARGV\n" if /unique_key\s*=\s*(\[[^\]]*\]|[^\n,]*)/s && $1 =~ /\(/' | sort -u
```

**Scope the test to the assignment, not to a line window.** The `unique_key` list is
frequently written multi-line (`unique_key=[` then one entry per line), so the obvious
`-A4 | grep "("` form sweeps up whatever follows the `config()` block — typically a
`with <cte> as (` opener four lines below. Measured on the real project it returned **17 hits
for 5 true models: 29% precision.** The form above captures the assignment's value — the
bracketed list or the bare scalar — and tests for `(` inside *that*, returning **5 files / 5
true positives, 100% precision.**

Run this against the **dbt project tree**, not the converted `artifacts/` tree: converted
artifacts carry no `config()` blocks, so the same search there returns 0 and reads as a clean
result. Verified — 5 files match in the project tree, 0 in `artifacts/models artifacts/tests`.
Grepping the wrong tree is this detector's most likely failure mode.

### 25. Which segment of a dotted reference is the VARIANT column

**~270 replacements across ~50 files** in one project. Pattern 11 covers the rewrite
(`.` → `:` for the first VARIANT hop) and the NEEDS-USER boundary for the implicit lateral
unnesting form — that guidance stands and is not repeated here. What Pattern 11 lacks is the
rule for deciding **where** the `:` goes:

> **If segment 1 of a dotted reference is a declared CTE or table alias in the same file, the
> VARIANT column is segment 2. Otherwise segment 1 is the VARIANT column.**

```sql
-- 'e' is an alias bound in the FROM  -> VARIANT column is segment 2
SELECT e.payload.user_id FROM events e        -- -> e.payload:user_id

-- no alias named 'payload'           -> VARIANT column is segment 1
SELECT payload.user_id FROM events            -- -> payload:user_id
```

This rule resolved every site in the real run. Its evidence: in `ste.jdata.context.library.name`
the column is `jdata` (`ste` is an alias), but in `ste.context.library.name` it is `context` —
same shape, different split point. And 4 of 24 candidates in one pass turned out not to be
VARIANT at all; they were `alias.column` where the *producer* model emitted no alias, so the fix
belonged upstream. A rewrite assuming segment 1 is always the column would have corrupted all
four.

**This is parse-level, not grep-level — and that is a hard limit, not a detector that needs
refining.** `a.b.c` is a VARIANT path or a qualified column reference depending entirely on
whether `a` is bound as an alias *somewhere else in the file* — in a `FROM`, a `JOIN`, or a
`WITH`. A regex matches one line at a time and cannot supply that set, so no pattern can decide
the question. What a detector can honestly do is enumerate a **review queue**:

```bash
grep -rnE '\b[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*\.[a-z_]' artifacts/models artifacts/tests --include=*.sql
```

Resolving each hit needs the file's alias set *and* the base column's declared type — confirm
the base column is `VARIANT` in `information_schema` before changing anything, and flag
NEEDS-USER where you cannot. Three-segment names are the higher-signal shape in dbt models,
which use `ref()`/`source()` rather than `db.schema.table`.

Key casing is a **separate** fix and does not disambiguate: double-quoting preserves
case-sensitive keys (`col:"lastPublishedDate"`), but `"journey"."activity"` is still parsed as
table-dot-column. Apply the alias rule to place the `:` first, then quote keys to preserve
casing. Neither substitutes for the other.

### 26. A null test followed by `::` — Redshift binds the cast to the NULL literal

**8 sites in one model**, all summed into a single reported metric.

```sql
-- Redshift: '::' binds to the NULL literal, so this stays a null test
nvl(borrow_users.acquisition_date is not null::integer, 0) + …

-- Snowflake: syntax error unexpected '::'
nvl((borrow_users.acquisition_date is not null)::integer, 0) + …   -- correct
```

Redshift/Postgres bind `::` to the `NULL` **literal**, leaving a boolean-returning null test
that Redshift then coerces inside `nvl`. Snowflake rejects the form outright. Not a converter
defect — the expression is identical in the source; it is a genuine precedence difference.

Parenthesise the predicate, which is also what the surrounding alias implies. Both the
parentheses **and** the explicit cast are required: Snowflake will not implicitly coerce the
boolean to an integer for the arithmetic sum either. Detector, scoped as above:

```bash
grep -rniE 'is[[:space:]]+(not[[:space:]]+)?null[[:space:]]*::' artifacts/models artifacts/tests
```

> **Only this order is broken.** The mirror image, `x::date is not null`, is **valid
> Snowflake** and must be left alone — there, `::` binding tighter is exactly the intended
> reading. That form is common: 73 sites across 23 files in this corpus, all correct. A
> detector written as "`::` near `IS NULL`" therefore has roughly 10% precision and would
> send a fixer through 73 working sites. Match on null-test-then-cast, not on proximity.

> **All 8 hits were commented out in the converter's output** — and all 8 are **live** in the
> Redshift source (`stg_users.sql`). The converter commented live code, which silently dropped
> the product-count metric those lines summed. So this pattern never actually reached
> execution on that project; the precedence difference is real, but the *observed* defect was
> the commenting. Check whether a hit is inside a comment before editing it, and treat
> commented-out source as its own finding — see Step 2.5's commented-code checks.
>
> **Re-run this detector after the commented-code restore in Step 2.5.** Measured on the raw
> tree, **8 of 8 hits sit on `--` lines**, so a reader who checks liveness first will conclude
> the pattern is inert and skip it. It is not — these become live defects the moment the
> restore puts the source lines back. The restore is what *creates* the work here.

### 27. `BOOL_OR` / `BOOL_AND` → `BOOLOR_AGG` / `BOOLAND_AGG`

**2 residual sites / 1 file.** Straight rename.

| Redshift | Snowflake |
|---|---|
| `bool_or(is_eligible)` | `BOOLOR_AGG(is_eligible)` |
| `bool_and(x)` | `BOOLAND_AGG(x)` |

Fails at name resolution: `002141: Unknown function BOOL_OR`.

**The converter handles this one correctly — the residue is a commented-code artifact, not a
converter gap.** Measured: the raw tree carries **129 `BOOLOR_AGG` + 22 `BOOLAND_AGG`**
already renamed, against just **2 surviving `bool_or`**. The two survivors are the two that
sat inside converter-commented blocks, which the rewriter does not touch. The shipped tree has
**131 + 22** — exactly those 2 more, renamed after the restore put them back.

```bash
grep -rniE '\bbool_(or|and)[[:space:]]*\(' artifacts/models artifacts/tests --include=*.sql
```

> **Re-run this detector after the commented-code restore in Step 2.5.** Both raw-tree hits
> sit on `--` lines (`wealth_index_metrics.sql`), so a liveness check made before the restore
> reads them as inert and the pattern looks like nothing to do. They are live in the Redshift
> source and become live defects once the restore returns them. Expect this pattern to have
> **zero** work before the restore and non-zero after — on this project that was its entire
> footprint.

### 28. Redshift epoch arithmetic → `DATEADD`, never `TO_TIMESTAMP_NTZ`

**9 sites.** Left unconverted by the converter.

```sql
-- Redshift
TIMESTAMP 'epoch' + generated_timestamp * INTERVAL '1' SECOND

-- Snowflake
DATEADD(second, generated_timestamp, '1970-01-01'::timestamp_ntz)
```

**Do not use `TO_TIMESTAMP_NTZ(n)`** as the shortcut: it infers seconds / ms / µs / ns from the
*magnitude* of the argument, so it silently shifts units for some rows and not others.

Its visibility is **position-dependent**, which is worth knowing before trusting a green run —
the same expression was proven to behave differently by projection vs. predicate:

| Position | Snowflake error | Caught by `dbt run --empty`? |
|---|---|---|
| `SELECT` projection | `000603 (XX000) cannot_find_signature Expr_map_intervalDayTimeMultiply` | **yes** |
| `WHERE` predicate | `260022 (2200W)` | **no** — 0 rows returns a clean result |

So "this construct is covered by the execution gate" can be true in one model and false in the
next for identical SQL. Treat the converter's `SSC-EWI-0073 'EPOCH ARITHMETIC'` tag as the
authority rather than the run result.

**Detector — match the construct, not the word.** A loose `epoch|1970` search returns 293 hits
across 214 files, of which 9 are this defect: **97% false positive.** The noise is almost
entirely `EXTRACT(epoch FROM …)` (262 sites), which is **native Snowflake and must be left
alone** — `master` keeps 247 of those untouched. Match the literal-plus-arithmetic shape
instead:

```bash
# 9 hits / 3 files in the measured corpus; master rewrote all 9, so precision is 100%
grep -rniE "timestamp[[:space:]]*'epoch'" artifacts/models artifacts/tests --include=*.sql
```

`TIMESTAMP 'epoch'` is absent from `master` entirely (0 sites), which is what makes this a
clean detector: the pseudo-literal has no legitimate use on Snowflake. Do **not** widen it to
bare `epoch` — and do not "fix" `EXTRACT(epoch FROM x)` or `DATE_PART('epoch', x)`; both are
supported and rewriting them is a regression.

### 29. Unaliased bare casts — `col::type` loses its output column name

**The largest single defect class measured on a real project: 4,513 sites across 412 files,
and 59% of all runtime errors.** Redshift/Postgres derive an output column name from a bare
cast — `generated_date::varchar` yields a column named `generated_date`. **Snowflake derives
no name at all.** The converter emits nothing here: `col::type` is already valid Snowflake
*syntax*, so there is no EWI and no FDM to triage by.

Two failure shapes, and the second is the one that misdirects:

| Context | Symptom |
|---|---|
| `CREATE VIEW` / `CREATE TABLE AS` | hard error `002022 (42601) Missing column specification` |
| inside a CTE or subquery | the relation builds, then a downstream `SELECT generated_date` fails `000904 invalid identifier 'GENERATED_DATE'` |

In the CTE case the error surfaces in a **different model** from the one carrying the defect,
so the reported failure points away from the cause.

**Invisible to every static gate.** `dbt parse` passes, and `dbt compile` passes with exit 0
— compile renders SQL, it never submits it. On the measured project compile produced 4,516
artifacts cleanly while 289 models could not execute. Verbatim restore (Step 2.5) also
preserves the defect, correctly: the source is portable by every listed criterion — no
`DISTKEY`, no `SUPER`, no `svv_*`, no `UNLOAD` — and the restored file still cannot run.
**Only `dbt run --empty` exposes this class.** It is the clearest argument in this file for
treating execution as a required gate rather than optional deeper validation.

**Fix: alias to the base column name, not to the expression.** This reproduces the Redshift
name exactly, which is what downstream models already reference.

```sql
-- converted (raw)
       user_id::bigint,
       subscriber_key::varchar(65000),
       days_since_user_acquisition::bigint,

-- shipped
       user_id::bigint AS user_id,
       subscriber_key::varchar(65000) AS subscriber_key,
       days_since_user_acquisition::bigint AS days_since_user_acquisition,
```

#### Only a projection needs a name — this is the whole precision problem

A cast is a defect **only where it sits in a projection that needs a name.** The identical
`::` in a `WHERE`, `GROUP BY`, `ORDER BY`, `JOIN ... ON`, or as a function argument needs no
alias and **adding one there is a syntax error.** So the defect is not the `::` token, it is
the `::` token in one specific position.

Tell them apart by the **nearest preceding clause keyword**: walk back from the cast line to
the first line beginning `select` / `where` / `group by` / `order by` / `partition by` /
`having` / `qualify` / `on`, and rewrite only when that keyword is `select`. Measured over
whole-line bare casts in the corpus, that walk-back splits **4,207 in a `SELECT` against 52
under a `GROUP BY`** plus 6 in other predicate positions — about 1.4% of hits are
leave-alone, and each one of them would be a new syntax error if aliased.

This is also why **a naive `grep '::'` is useless here**: it returns **24,930** hits in the
same two trees, a 5.5× over-report against the 4,513 the positional detector finds. Most
casts in a converted Redshift project are perfectly fine.

Detector — casts that end a line with a comma, the dominant shape of the generated staging
layer (scope as stated at the top of this file):

```bash
grep -rnoiE "[a-z0-9_.\"]+::[a-z0-9_]+(\([0-9, ]*\))?,$" artifacts/models artifacts/tests --include=*.sql
```

Measured: **4,513 sites / 412 files.** That is specifically *bare casts terminating a line
with a comma* — it does not attempt clause awareness, and it misses casts that end a
projection without a trailing comma. A clause-aware walk-back over the same project reports
**3,827 sites / 295 files** because it additionally discards non-`SELECT` positions. The two
numbers measure different things and are both correct for what they count; pick the shape you
are about to rewrite and quote that one.

Concentrated in generated `models/sources/**` staging layers, where the
`transform AS (SELECT col::type, …)` idiom is applied uniformly — the worst single file
carried 186 unaliased columns.

**~112 bare casts remain in the shipped tree and that is correct**, not unfinished work: the
repair aliased what needed a name and left the rest. A representative survivor is a cast used
as a function argument, where no name is possible:

```sql
nullif(REGEXP_SUBSTR(
    transunion_raw_response::text,          -- correct as-is: function argument
    '(?<=militaryLendingActSearch searchStatus=")[a-zA-Z]+(?=")', …
```

A fixer that drives the count to zero has broken working SQL.

### 30. `GET(arr, -1)` — array subscript shifted by one, silently

**146 sites / 25 files, zero errors, wrong data.** The highest severity-per-site of anything
in this file: there is no error anywhere, in any gate, at any point.

Converting a Redshift array subscript, SnowConvert rewrites `arr[n]` as `GET(arr, n-1)` —
preserving the call but **shifting the index down by one**:

```sql
-- source (Redshift)
when credit_pulls.raw_response.data[0].code::text = 'pre-check' then credit_pulls.raw_response.data[0]

-- converted (raw): index shifted to -1
when GET( credit_pulls.raw_response.data, -1).code::text = 'pre-check' then GET( credit_pulls.raw_response.data, -1)

-- shipped: native subscript, original index, ':' for the VARIANT hop
when credit_pulls.raw_response:data[0]:code::text = 'pre-check' then credit_pulls.raw_response:data[0]
```

**The off-by-one is uniform, so every index is wrong — not only the negative ones.** This is
the part that is easy to miss. `GET(arr, -1)` returns `NULL` on Snowflake, so those columns
null out outright; but a shifted `GET(arr, 0)` corresponds to source `[1]` and returns a
**neighbouring element**, which is a plausible-looking wrong value. Measured index census over
the two trees:

| Emitted index | Sites | Source index it came from | Result on Snowflake |
|---|---|---|---|
| `-1` | 62 | `[0]` | **`NULL`** — silently empty column |
| `0` | 26 | `[1]` | **wrong element** |
| `1` | 25 | `[2]` | **wrong element** |
| `2` | 15 | `[3]` | **wrong element** |
| `3` | 10 | `[4]` | **wrong element** |

Verified on `stg_entities_risk_tags.sql`, where source `[0] [1] [2] [3]` became
`-1 0 1 2`, and on `credit_pulls_cleaned.sql`, where source `[0]…[4]` became `-1…3`.

**No gate catches any of it.** `dbt parse`, `dbt compile` and `dbt run --empty` all pass —
`GET()` is a real Snowflake function with a valid signature and a negative index is a legal
argument, so execution succeeds. It is a wrong *value*, not a failure to execute. Only a
row-level or per-column non-NULL comparison against the source system finds it.

**Fix: Snowflake native subscript plus `:` for the VARIANT field**, which is also what the
shipped tree uses throughout — `GET(` appears **0 times** in it, against 146 in the raw tree:

```sql
GET(credit_pulls.raw_response.data, -1).code::text   -- raw
credit_pulls.raw_response:data[0]:code::text          -- shipped
```

**Recover the index from the Redshift source — do not assume every `-1` was a `[0]`.** The
shift happened to be exactly −1 everywhere in this corpus, but that is an observation about
one converter run, not a guarantee, and the non-negative indices need the same treatment.
Read the corresponding source line and use its literal subscript. Where the source file is
unavailable, **flag NEEDS-USER**: the index cannot be inferred from the converted output,
because every value in it is self-consistent and none of them errors.

Nesting is common and both levels shift independently —
`GET(GET(cdd, -1).answers, -1)` came from `cdd[0].answers[0]`, so fix inner and outer
together.

Detector — any `GET(` in a converted Redshift tree is converter-emitted and suspect, and a
negative index is unambiguously a defect:

```bash
grep -rnoE "GET[[:space:]]*\(" artifacts/models artifacts/tests --include=*.sql | wc -l   # 146 / 25 files
grep -rniE "GET[[:space:]]*\([^()]*,[[:space:]]*-[0-9]+\)" artifacts/models artifacts/tests --include=*.sql
```

> **Pair this with Pattern 25.** They are adjacent and usually both needed on the same line:
> Pattern 25 decides **where the `:` goes** in a dotted VARIANT reference, this one fixes
> **the subscript**. `GET(x.raw_response.data, -1).code` needs the colon placement *and* the
> index restored — fixing one and not the other still returns the wrong answer.

### 31. Bare `TIMESTAMP - TIMESTAMP` → `DATEDIFF(second, …)` — the high-volume form

**271 sites across 7 files — the second-largest class measured, and the converter emits
nothing for it.** Pattern 13 states the semantics correctly but only detects the
`EXTRACT`-wrapped shape (10 hits, **none** of which the repair touched). The construct that
actually matters is a bare subtraction between two timestamp columns:

```sql
-- converted (left as-is by the converter; valid syntax, wrong type)
then (first_contact - created_at) - INTERVAL '2 00:00:00' DAY TO SECOND
-- master (ground truth)
then DATEDIFF(second, created_at, first_contact) - 172800
```

Redshift's `ts - ts` yields an interval; Snowflake's yields a **number of days as a FLOAT**, so
every downstream unit assumption is silently off by a factor of 86,400 — and any interval
arithmetic on the result fails outright.

**The argument order inverts.** `later - earlier` becomes
`DATEDIFF(second, earlier, later)` — the subtrahend moves to the *second* position. Getting
this backwards compiles cleanly and silently flips the sign of every row.

**The result type changes from interval/float to integer seconds**, which is what forces the
companion interval edit in Pattern 23: once the left operand is an integer, an
`INTERVAL 'N 00:00:00' DAY TO SECOND` on the right no longer type-checks and must become a
count of seconds (`2 days → 172800`, `1.5 days → 129600`, `0.5 days → 43200` — all three
verified in `master`). Fix the subtraction first, then the interval.

#### Detector — a triage queue, not a precise matcher. Be honest about this.

`-` between two identifiers is one of the most common things in SQL, so there is no
high-precision grep. The least-bad version restricts to a *parenthesised* subtraction of two
bare identifiers:

```bash
grep -rnE "\(\s*[A-Za-z_][A-Za-z0-9_.]*\s*-\s*[A-Za-z_][A-Za-z0-9_.]*\s*\)" \
  artifacts/models artifacts/tests --include=*.sql
```

Measured behaviour — read this before trusting it:

| | value |
|---|---|
| hits | 138 occurrences on 137 lines, across 16 distinct models |
| hits inside the 6 high-volume files the repair edited | 126 (91% of hits) |
| of the 271 real sites, how many this finds | ~126 → **recall under 50%** |
| files flagged that needed no change | 10 of 16 |

So it is **good at pointing you at the busy files** (the 6 high-volume files are among the 16) and
**bad at enumerating the sites** — more than half the real subtractions are unparenthesised and
it misses them. Treat a hit as "open this file and read every `-` in it", not as a work item.

**It also misses the sparse tail entirely.** On that project the 271 sites were 45 each in six
files plus **one lone site in a seventh**, and the locator found the six and not the seventh. A
file with a single subtraction looks like every other file, so expect to find the long tail only
when the execution gate fails on it or a reviewer reads the model.

The unrestricted form (`ident - ident` anywhere) returns 4,898 hits across all 2,228 files and
is useless. Once a file is flagged, confirm each candidate by resolving both operand types from
the model's column definitions — the subtraction of two numeric columns is correct and must be
left alone.

### 32. `+` as string concatenation → `||`

**85 sites across 16 files; a hard runtime error, not a silent one.** Redshift overloads `+`
for string concatenation. Snowflake does not: it coerces both operands to numbers and fails
with `Numeric value 'John' is not recognized`. The converter leaves it untouched because
`a + b` is valid syntax.

```sql
-- converted (artifacts/models/.../314_wire_lookup.sql)
on jpm_wires.ULT_BENE2 ilike '%%' + LEFT(entity_lookup.business_name,8) + '%%' ESCAPE '\\'
-- master (ground truth)
on jpm_wires.ULT_BENE2 ilike '%%' || LEFT(entity_lookup.business_name,8) || '%%' ESCAPE '\\'
```

The repair added 85 `||` operators net (2,103 → 2,188). Note the shape above: `+` and `||`
routinely appear **in the same expression**, so a file already containing `||` is not evidence
that it was converted.

**`+` between numeric operands is correct and must be left alone.** That is what makes this a
judgment call rather than a rename — there is no syntactic difference between the two uses, only
a type difference, and the corpus contains 1,079 bare `+` operators of which 85 were defects
(~8%). Resolve the operand types before touching one.

Detector — anchor on a `+` adjacent to a quoted literal, which is the only cheap signal:

```bash
grep -rnE "'[^']*'[[:space:]]*\+|\+[[:space:]]*'[^']*'" \
  artifacts/models artifacts/tests --include=*.sql
```

136 occurrences on 74 lines across 25 distinct models, against 85 real sites in 16 files —
**~63% occurrence-level precision, and 15 of the 16 real files are among the 25.** (Add `-o` to
the grep if you want the occurrence count rather than the line count; several lines carry two
`+` operators.) The residual noise is `+` inside quoted regex literals (`'\\s+'`,
`'[^0-9]+'`) where the `+` is a quantifier, not an operator; those are instantly dismissible on
sight. One real file is missed (its `+` has no adjacent literal), so pair the grep with a read
of any model that concatenates strings.

### 33. Converter-inserted `ANY_VALUE()` wrappers — remove them

**43 sites across 9 files. The converter *inserts* this — the defect shape does not exist in
the source at all** (`source` contains exactly one hand-written `any_value(statement_date)`,
and it wraps a plain column, not an aggregate). SnowConvert wraps some expressions in
`ANY_VALUE(...)` that do not need it — 42 of the 43 removed sites wrap an already-deterministic
aggregate:

```sql
-- converted
ANY_VALUE(MIN(trs.created_timestamp)::timestamp)
-- master (ground truth): the inner expression alone
MIN(trs.created_timestamp)::timestamp
```

Why it is wrong: `MIN(...)` already returns exactly one value per group, so `ANY_VALUE` around
it is redundant. It is also not inert — it is itself an aggregate, so the extra nesting changes
how the expression participates in `GROUP BY` resolution and can mask a genuinely ambiguous
column. Unwrap to the inner expression; do not substitute `MIN`/`MAX`.

Detector — **anchor on `ANY_VALUE` wrapping an aggregate**, which is the defect shape:

```bash
grep -rniE "ANY_VALUE[[:space:]]*\([[:space:]]*(MIN|MAX|SUM|AVG|COUNT|LISTAGG)[[:space:]]*\(" \
  artifacts/models artifacts/tests --include=*.sql
```

42 hits / 8 files, **0 in `master` and 0 in `source` — 100% precision.** The one remaining site
is an `ANY_VALUE(date…)` the repair also dropped, so expect the grep to under-count by about
one.

Do **not** detect on bare `ANY_VALUE(` and delete everything it finds. That returns 64 hits
across 27 files, and `master` deliberately **keeps 21 of them** — the ones wrapping a plain
column reference (`ANY_VALUE(zsa.score)`, `ANY_VALUE(cc.created_at)`), where "pick any row in
the group" is the intended semantics. `source` contains one hand-written `any_value(...)` too.
Bare-name detection is 67% precise and will delete working code.

### What NOT to touch

- Pure formatting/indentation differences are not incompatibilities. Don't reformat a macro that already runs correctly just to match a style.
- Query-shape simplifications with no behavioral driver (e.g. rewriting a `COALESCE(MAX(x), '1900-01-01')` guard to a plain correlated `MAX(x)` subquery) are optional style choices, not fixes — only make them if the original truly fails on Snowflake (it usually doesn't; `MAX` over an empty relation returns `NULL` identically on both platforms). Don't spend a fix cycle on cosmetic parity with a reference implementation.
- `{{ ref(...) }}` / `{{ source(...) }}` calls inside macros — these are the responsibility of `scai code convert --dbt`'s Jinja repointing (Phase 1) and the model-SQL refinement sibling skill, not this one. Leave them as-is unless a macro is the one place they're malformed.
- **`CASCADE` / `RESTRICT` on `DROP VIEW`** — undocumented for views but accepted by Snowflake's parser, so it runs unchanged. See Pattern 17 for the evidence. Don't add object-type branching to strip it.
- **A function or view name that merely sounds Redshift-specific.** Snowflake ships several Redshift-compatibility aliases (`JSON_EXTRACT_PATH_TEXT` is a confirmed one). Before rewriting any function call, verify it actually fails — with a live query against Snowflake if a connection is available, or by checking Snowflake's SQL reference if not. Don't pattern-match on the name alone. **See Pattern 16 for the running list of confirmed-native functions** — check it before rewriting anything.
- **Trailing semicolons.** The shipped repair stripped the trailing `;` from 2,182 sites across 2,168 files — effectively every model — which is a mechanical pass over the whole corpus, not a dialect fix. Treat it as the repointing tool's job and don't burn a fix cycle on it; if models are arriving with trailing `;` still attached, that's a `scai code convert --dbt` finding to report, not something to edit file-by-file.
- **The long tail below ~10 sites.** The same repair also made a handful of one-off changes — `SELECT * EXCLUDE` (1 site added), `= ANY (...)` → `IN (...)` (8 sites, 1 file), `TRUNC(x)` → `CAST(x AS DATE)` (5 sites, 4 files), `timestamp_tz` → `timestamptz` (11 sites, 1 file), ~25 sites combined. Each is a legitimate edit when you hit it, but none recurs often enough to be worth a detector or a pattern of its own. Fix in passing; don't go looking.

### Improving this file

If you fix a Redshift-sourced macro using a rewrite not covered by the patterns above, add it as a new numbered pattern before ending the run — same format (Redshift-ism, why it breaks, exact rewrite). Insert new patterns before the "What NOT to touch" section, not after it — that section documents things to leave alone and should stay last. This file only stays useful as an accelerant if it grows with real fixes instead of staying frozen at its first version.
