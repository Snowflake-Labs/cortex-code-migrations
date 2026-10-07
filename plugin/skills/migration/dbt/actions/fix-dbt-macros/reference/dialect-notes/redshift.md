## Redshift → Snowflake macro fix patterns

**Status: known patterns, grounded in a real repointed project.** This is a dialect note under `macro-fix-approach.md` — use it as an accelerant when `SOURCE_DIALECT` is Redshift, not as the only source of fixes. Anything not listed here still gets fixed by applying the general checklist and your own knowledge of Redshift vs. Snowflake SQL; if you find and apply a new pattern that isn't below, add it here before finishing the run (see "Improving this file" at the end).

Each pattern names the Redshift-ism, why it breaks on Snowflake, and the exact rewrite. Patterns are ordered roughly by frequency observed in real repointed projects.

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

### 10. `getdate()` / `CURRENT_SETTING('timezone')` — Redshift/Postgres time functions

| Redshift/Postgres | Snowflake |
|---|---|
| `getdate()` | `CURRENT_TIMESTAMP()` |
| `CURRENT_SETTING('timezone')` | `CURRENT_TIMEZONE()` |

Both verified live: `getdate()` and `CURRENT_SETTING(...)` raise `Unknown function` on Snowflake.

When a macro chains two `AT TIME ZONE` uses to convert from the session zone to a target zone (e.g. `getdate() AT TIME ZONE CURRENT_SETTING('timezone') AT TIME ZONE {{ tz }}`), collapse it to a single `CONVERT_TIMEZONE`:

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

### What NOT to touch

- Pure formatting/indentation differences are not incompatibilities. Don't reformat a macro that already runs correctly just to match a style.
- Query-shape simplifications with no behavioral driver (e.g. rewriting a `COALESCE(MAX(x), '1900-01-01')` guard to a plain correlated `MAX(x)` subquery) are optional style choices, not fixes — only make them if the original truly fails on Snowflake (it usually doesn't; `MAX` over an empty relation returns `NULL` identically on both platforms). Don't spend a fix cycle on cosmetic parity with a reference implementation.
- `{{ ref(...) }}` / `{{ source(...) }}` calls inside macros — these are the responsibility of `scai code convert --dbt`'s Jinja repointing (Phase 1) and the model-SQL refinement sibling skill, not this one. Leave them as-is unless a macro is the one place they're malformed.
- **`CASCADE` / `RESTRICT` on `DROP VIEW`** — undocumented for views but accepted by Snowflake's parser, so it runs unchanged. See Pattern 17 for the evidence. Don't add object-type branching to strip it.
- **A function or view name that merely sounds Redshift-specific.** Snowflake ships several Redshift-compatibility aliases (`JSON_EXTRACT_PATH_TEXT` is a confirmed one). Before rewriting any function call, verify it actually fails — with a live query against Snowflake if a connection is available, or by checking Snowflake's SQL reference if not. Don't pattern-match on the name alone. **See Pattern 16 for the running list of confirmed-native functions** — check it before rewriting anything.

### Improving this file

If you fix a Redshift-sourced macro using a rewrite not covered by the patterns above, add it as a new numbered pattern before ending the run — same format (Redshift-ism, why it breaks, exact rewrite). Insert new patterns before the "What NOT to touch" section, not after it — that section documents things to leave alone and should stay last. This file only stays useful as an accelerant if it grows with real fixes instead of staying frozen at its first version.
