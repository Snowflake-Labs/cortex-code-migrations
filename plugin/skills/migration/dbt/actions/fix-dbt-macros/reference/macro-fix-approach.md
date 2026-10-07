## General approach: fixing dbt macros for any source dialect on Snowflake

There is no complete, fixed catalog of every source-dialect incompatibility — `scai`'s dbt repointing (`code convert --dbt`) supports multiple source languages, and new ones get added over time. This file is a **checklist and reasoning method**, not a lookup table. Use it on every macro, for every dialect, whether or not a `dialect-notes/<dialect>.md` file exists for the project's source.

### Order of operations for each macro

1. **Check for a dialect note first.** If `dialect-notes/<SOURCE_DIALECT>.md` exists (lowercased, e.g. `dialect-notes/redshift.md`), read it and check whether it already documents this macro's incompatibility. If so, apply that exact fix — it's a known-good pattern from a real prior fix, not a guess.
2. **If no dialect note exists, or the note doesn't cover what's wrong with this macro, improvise using the checklist below plus your own knowledge of `<SOURCE_DIALECT>` SQL vs. Snowflake SQL.** You are not limited to documented patterns. Reason about what the macro is trying to do, identify the specific `<SOURCE_DIALECT>` construct that doesn't exist or behaves differently on Snowflake, and write the Snowflake-native equivalent.
3. **After fixing, if the fix generalizes** (i.e., another macro in another project with the same source dialect would hit the same issue), append it to `dialect-notes/<SOURCE_DIALECT>.md` as a new pattern before finishing the run. Create the file (using `dialect-notes/redshift.md` as a formatting template) if this is the first fix ever recorded for that dialect. This is how the catalog grows to cover dialects it doesn't yet have notes for.

### Checklist — categories of incompatibility to look for, regardless of source dialect

**a. System catalogs and metadata views.** Every warehouse exposes its own catalog surface (Redshift's `svv_*`/`pg_catalog.*`, BigQuery's `INFORMATION_SCHEMA` with dataset-scoped quirks like `_TABLE_SUFFIX`/`_PARTITIONTIME`, Databricks' Unity Catalog three-level namespace and `information_schema` differences, Postgres' `pg_catalog`, Teradata's `dbc.*` views, Oracle's `ALL_*`/`DBA_*` views). If a macro queries one of these to introspect tables/columns/schemas, map it to Snowflake's `INFORMATION_SCHEMA.TABLES`/`.COLUMNS` or `ACCOUNT_USAGE` equivalent, adjusting column names and remembering Snowflake stores unquoted identifiers uppercase (wrap comparisons in `UPPER(...)`).

**b. Reserved-word or clause collisions.** A construct that's valid SQL on the source dialect may collide with a Snowflake keyword that means something else (e.g. Redshift's `AT TIME ZONE` colliding with Snowflake's time-travel `AT (...)` clause). Read the Snowflake SQL reference behavior for the exact clause before assuming a straight port works.

**c. Function name, argument order, or return-type differences.** Every dialect has small function-surface differences from Snowflake: string trimming syntax (`TRIM(x FROM y)` vs `TRIM(y, x)`), date arithmetic argument order (`DATEADD`/`DATEDIFF` unit-first vs unit-last), semi-structured data functions (`JSON_PARSE`/`PARSE_JSON`, `SPLIT_TO_ARRAY`/`SPLIT`, BigQuery `STRUCT`/`ARRAY_AGG` vs Snowflake `OBJECT_CONSTRUCT`/`ARRAY_AGG`, Databricks `explode()` vs Snowflake `FLATTEN`), string aggregation (`LISTAGG` vs `STRING_AGG` vs `GROUP_CONCAT`), current-timestamp spelling (`GETDATE()`/`NOW()`/`CURRENT_TIMESTAMP()`). Translate to the closest Snowflake-native function rather than trying to reimplement the source function's exact signature.

**A function name that looks source-dialect-specific is not proof it's actually broken.** Snowflake ships compatibility aliases for a number of Redshift/Postgres functions (`JSON_EXTRACT_PATH_TEXT` is a confirmed one — it runs unmodified on Snowflake despite the name). Don't rewrite a function call just because you don't recognize it as native Snowflake syntax; confirm it actually fails first (see "Verify before finalizing" below).

**Nested-field access syntax differs by dialect and is easy to get subtly wrong.** Redshift's SUPER type uses dot notation (`col.field`); Snowflake's VARIANT uses colon notation (`col:field`) — but the part after the colon must be a bareword, never a quoted string (`col:'field'` is a syntax error). This bites hardest when the field name comes from a Jinja variable: render it as `col:{{ field_var }}`, not `col:'{{ field_var }}'`. This exact mistake has shipped from following this checklist too literally without the verification step below — treat it as a standing warning, not a hypothetical.

**d. RBAC / DCL syntax.** Grant statement targets differ (Redshift `GROUP`, BigQuery IAM roles/bindings, Databricks Unity Catalog principals) — Snowflake grants always target a `ROLE`. If the macro issues grants, also check whether it should be environment-gated (skip in local/sandbox targets where the roles may not exist) — see `dialect-notes/redshift.md` Pattern 5 for the guard idiom, which is dialect-agnostic. Bare grant targets with no group/role qualifier are ambiguous between a role and a user — default to `ROLE` and record the assumption in the fix log rather than silently picking one.

**e. Environment variables and config keys tied to the old platform's naming.** `env_var('<PLATFORM>_DBNAME')`-style names, or `dbt_project.yml` config keys that only make sense for the source warehouse (Redshift's `dist:`/`+bind:`, BigQuery's `partition_by:`/`cluster_by:` syntax differences, Databricks' `file_format:`). Renaming an env var used inside a macro is in scope; renaming a `dbt_project.yml` config key is not (that's config validation's job) — if you spot one, note it in the fix log as out-of-scope rather than editing `dbt_project.yml`.

**f. Platform-exclusive features with no Snowflake equivalent.** Bulk export commands (Redshift `UNLOAD`, BigQuery `EXPORT DATA`), platform-specific sharing/introspection (Redshift datashares, BigQuery Analytics Hub), superuser-only DDL, external UDF/language extensions tied to the source platform's runtime. **Do not invent a Snowflake equivalent for these** — archive the macro (move to `macros/_archived/<name>.sql` unchanged) and flag it `needs-user` with the specific blocking feature named. A human needs to redesign the behavior, not receive a guessed translation. See `dialect-notes/redshift.md` Pattern 7 for the precedent (`UNLOAD`, `SHOW DATASHARES`).

**g. Structural rewrites that need live data-shape knowledge you don't have.** Some incompatibilities *do* have a real Snowflake equivalent (e.g. Redshift SUPER's implicit lateral-unnest `FROM t, t.col AS a, a.nested AS b` really does map to `LATERAL FLATTEN`) but only a correct translation if you know the actual JSON structure being unnested — guessing risks silently changing row counts or dropping data with no error to catch it. This is different from category f (no equivalent at all): here an equivalent exists, but a wrong guess is worse than no fix. Prefer `needs-user` over a low-confidence structural rewrite; reserve improvisation for fixes you can state with certainty from the dialect's documented semantics.

### Cross-dialect quick translations

Frequently-hit cases under categories c and e. This is a shortcut for common cases, not a
substitute for the checklist — and every entry is still subject to the "verify before
finalizing" rule below.

| Source | Construct | Snowflake replacement |
|---|---|---|
| Redshift | `GETDATE()` | `CURRENT_TIMESTAMP()` |
| BigQuery | `DATE_DIFF(d1, d2, part)` | `DATEDIFF(part, d2, d1)` |
| BigQuery | `DATE_FORMAT(date, fmt)` | `TO_CHAR(date, fmt)` |
| Databricks | `DATE_FORMAT(date, fmt)` | `TO_CHAR(date, fmt)` |
| Databricks | `DATEDIFF(d1, d2)` | `DATEDIFF('day', d2, d1)` |
| SqlServer | `ISNULL(a, b)` | `NVL(a, b)` |
| SqlServer | `CONVERT(type, expr)` | `TRY_CAST(expr AS type)` |
| SqlServer | `WITH (NOLOCK)` | *(remove — no Snowflake equivalent, and none needed)* |

**Platform DDL clauses inside DDL-emitting macros.** Redshift `DISTKEY`/`SORTKEY` have no
Snowflake equivalent — Snowflake handles distribution automatically; strip them and leave a
comment recording what was removed, so a reader doesn't think the clause was lost by accident.
For BigQuery DDL partitioning, use Snowflake `CLUSTER BY` where the intent maps, or strip it
when it doesn't. Note that `dist:`/`+bind:` appearing as `dbt_project.yml` *config keys* is
category e and out of scope — only DDL emitted from macro bodies is yours to fix.

### What NOT to touch (applies to every dialect)

- Pure formatting/indentation differences — not an incompatibility.
- Style-only query reshaping with no functional driver — only change something if it actually fails on Snowflake, not to match a reference implementation's shape.
- `{{ ref(...) }}` / `{{ source(...) }}` calls — owned by `scai`'s Jinja repointing and the model-SQL refinement sibling skill, not this one.
- A function/view name you merely recognize as "sounds like `<SOURCE_DIALECT>`" — verify it actually fails before touching it (category c above).

### Verify before finalizing

`dbt parse`/`dbt compile` (Step 4/5 of `SKILL.md`) never execute SQL against the warehouse — they catch Jinja/macro-dispatch errors, not "does this function exist" or "is this syntax valid." That means most of the fixes in this checklist can pass the parse loop while still being wrong. **If a Snowflake connection is available, verify each nontrivial fix with the smallest possible live query** — isolate just the changed expression (e.g. `SELECT <rewritten_expr>` with representative literal inputs), not the whole macro or model. This is cheap, it's the only signal that actually proves correctness, and it is how the bareword-vs-quoted-string VARIANT bug above was caught — the fix looked plausible, passed every parse check, and was still a syntax error. If no connection is available, say so in the fix log rather than silently skipping verification.

### When you're genuinely unsure

If you can't determine whether a construct is a real incompatibility or just unfamiliar syntax, don't rely on `dbt parse`/`dbt compile` to settle it — per "Verify before finalizing" above, they don't execute SQL and won't tell you. Use a live query (if a connection is available) or your knowledge of the Snowflake SQL reference instead. An unnecessary "fix" to correct-but-unfamiliar SQL is itself a bug — if you can't confirm the construct actually fails, leave it alone and say so in the fix log rather than guessing either way.
