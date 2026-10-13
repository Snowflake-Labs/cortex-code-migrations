# The validation ladder: parse, compile, execute

Three gates, each strictly stronger than the last. Step 5.3 names which one you owe; this
file is how to run them and what the evidence behind them is.

| Gate | Submits SQL to Snowflake? | Catches |
|---|---|---|
| `dbt parse` | no | Jinja and YAML errors, unresolvable `ref()` |
| `dbt compile` | no | the above, plus `ref()`/`source()` against the catalog |
| `dbt run --empty` ×2 | yes, with 0-row inputs | names, syntax, types, function resolution |

## Prerequisites for parse

Both are mandatory, and `dbt parse` fails immediately without them.

**1. Install packages.** `dbt parse` refuses to run when `packages.yml` lists packages that
are not installed (`found N package(s) specified in packages.yml, but only 0 package(s)
installed`). Step 3.0 must be done first, then:

```bash
dbt deps --project-dir <DBT_PROJECT_PATH> --profiles-dir <PROFILES_DIR>
```

**2. Supply env vars.** `dbt parse` evaluates `env_var()` in `profiles.yml` at parse time even
though it never connects, so unset variables abort the parse. When Snowflake credentials are
not configured locally, dummy values are sufficient:

```bash
DBT_SNOWFLAKE_ACCOUNT=dummy DBT_SNOWFLAKE_USER=dummy \
DBT_SNOWFLAKE_ROLE=dummy DBT_SNOWFLAKE_WAREHOUSE=dummy \
dbt parse --project-dir <DBT_PROJECT_PATH> --profiles-dir <PROFILES_DIR> --no-partial-parse
```

**Dummy values are for `dbt parse` only.** They must not carry into the execution gate: a
dummy account produces an authentication failure that looks exactly like a conversion defect,
and chasing it wastes a full gate run. Before `dbt seed` or `dbt run --empty`, supply real
credentials and confirm them with

```bash
dbt debug --project-dir <DBT_PROJECT_PATH> --profiles-dir <PROFILES_DIR>
```

which tests the connection specifically. If `dbt debug` fails, fix that before reading any
model error — every node will fail for the same reason.

**Always pass `--no-partial-parse` while iterating.** Without it dbt reuses a cached partial
parse and a stale cache masks newly introduced errors, which turns a handful of real problems
into many rounds of confusing failures.

`<PROFILES_DIR>` is the directory holding the converted `profiles.yml` — normally
`<project>/snowflake`, not `~/.dbt`.

If `dbt` is not installed, report:

> "Note: `dbt` is not installed — install with `pip install dbt-snowflake` to validate the
> output."

## Compile

If `dbt-snowflake` is installed **and** real credentials are configured, prefer `dbt compile`
over parse: it resolves `ref()`/`source()` against the catalog.

```bash
dbt compile --project-dir <DBT_PROJECT_PATH> --profiles-dir <PROFILES_DIR>
```

For each failing node: read the error, apply the minimum fix, verify with
`dbt compile --select <node>`. Up to 5 attempts per node; mark as `needs-user` on persistent
failure.

**Compile never submits a statement to the warehouse.** It renders Jinja and resolves
relations, but a missing function or an invalid rewritten expression passes it exactly as it
passes parse. On one project `dbt compile` exited 0 and wrote 4,516 artifacts while **289
models could not execute**. Keep it as the cheaper prior gate, then run the execution gate.

## Execution gate

`--empty` (dbt 1.8+) runs every model with its inputs limited to 0 rows. It submits the real
compiled SQL, so Snowflake's query compiler checks names, syntax, types, and function
resolution — but it reads no data and costs almost nothing. It needs the upstream *relations*
to exist, not their contents, which is the usual situation here: the source system is
unreachable but the DDL migration has already deployed the tables.

```bash
dbt seed --project-dir <DBT_PROJECT_PATH> --profiles-dir <PROFILES_DIR>
dbt run --empty --project-dir <DBT_PROJECT_PATH> --profiles-dir <PROFILES_DIR>
dbt run --empty --project-dir <DBT_PROJECT_PATH> --profiles-dir <PROFILES_DIR>
```

`dbt seed` first: `--empty` does not build seeds, and without them the error list is dominated
by unloaded-seed noise that hides the real defects.

### Run it twice

Treat the second pass as the gate for incremental models. On a first build the relation does
not exist, so dbt emits `CREATE TABLE AS` and the `MERGE` that every later run uses is **never
compiled**. On one project 4 of the 5 models configuring an expression-valued `unique_key`
reported PASS on pass 1 purely because their tables did not yet exist; all 5 failed on pass 2.
A single pass left **86 incremental models untested**.

### Limits — state these whenever you report the gate

A green run is evidence about the query compiler only.

- **It cannot see wrong results**, only failures to execute. Correctness needs a row-count or
  checksum diff against the source system.
- **Its visibility is position-dependent.** Redshift epoch arithmetic
  (`TIMESTAMP 'epoch' + n * INTERVAL '1' SECOND`) fails as `000603` in a `SELECT` projection
  and is caught; as a `WHERE` predicate it raises `260022` only per row, so 0 rows returns
  cleanly and it is not caught. Identical SQL, opposite verdicts.
- **The complement is a one-row smoke test** on a few representative models — worth targeting
  at expressions with literal arguments (casts, timezone names, format models, `GET`/path
  access), which is where converter defects concentrate.

### Calibration

From one project of 1,179 nodes, across repair waves: PASS 898 → 1166 (98.9%), ERROR 173 → 12,
SKIP 108 → 1. A full `--empty` run over those nodes took about 11 minutes. **These are that
project's numbers, not thresholds.**
