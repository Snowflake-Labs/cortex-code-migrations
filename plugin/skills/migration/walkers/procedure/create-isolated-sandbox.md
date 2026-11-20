# Set up the procedure sandbox

Run the step's `run` as given (op `sandbox`).

A `sourceDefects` entry in the reply is a source defect: escalate at once per
[general_task §3](../../../../agents/general_task.md#3-rules) (*Key without IDENTITY*). No helper, no repair.

## Deploy modes

| `walk_run` op | Does |
|---|---|
| `sandbox` | Transitive closure into the `AIMSBX_*` pair: tables (CSV reload), peer functions/views/procs on both sides, this object on **source only**. A live `ready` pair is reused (no DROP/CLONE); an unready one is DROPped first so the retry remints. Also fills tables missed on first setup (dynamic-SQL names, 42S02). |
| `sandbox_object` | This object only onto Snowflake AIMSBX (needs a live pair: the step has `sandbox`). The only Snowflake CREATE of this id in the sandbox — after a SQL fix and before `runTests`. |
| `sandbox_closure` | The closure's functions, views and peer procedures, then this object, onto Snowflake AIMSBX only (needs a live pair). No table DDL or CSV reload and no source side, so seeded rows stay. The `runTests` refresh after an `invalidation`. |
| `deploy` | This object onto the common catalogs — the later `deploy` task, not this one. |

- A `sandbox` compile failure is a **peer** body — setup never CREATEs this id on Snowflake; never fix this object for it. A `sandbox_object` compile failure **is** this object's body.
- After AIMSBX DML the tools did not see (`sql_execute`), pass `restore_from_sandbox=true` on op `sandbox_object` — `sandbox` reloads CSVs first, and on `test` it only clones when none is latched yet. A helper's `reload_tables` and a mutating `query_source` into AIMSBX latch it automatically.
- Converted-only procedures (no `source`) get a Snowflake-only pair.
- Pre-deploy file checks for `sandbox_object`: [deploy.md](deploy.md#pre-deploy-file-checks). Do not apply them, or fix this object's SQL, to make setup `ready`.

## Working in the sandbox

- Use the `sandbox` maps (`snowflake` / `source`, `bindingsPath`) a sandbox op returns for tests, `sql_execute`, `query_source` — the `AIMSBX_*` catalogs, not the common `snow:` values. Fully qualify; never substitute `source.database`, a `SNAP_USE_*` clone, or `SNOWCONVERT_AI*`.
- Pass `sql_execute` `connection` (`-c`) = the first-prompt `snowflakeConnection` on every call (Cortex does not inherit the attach).
- Never `SHOW DATABASES`, `SHOW … IN ACCOUNT`, or `CREATE SCHEMA` via `sql_execute`. Tool unavailable / denied / timed out / catalog missing → escalate; do not roam other databases.
- Mutating `query_source` naming a common catalog while a sandbox is live is refused — use the `AIMSBX_*` name.

## If the call fails

Do what `fix` says; act on a helper's `result` per [general_task §4](../../../../agents/general_task.md#4-helpers). Every source CREATE here comes from a bindable copy; a failure the customer's `files.source` would not hit is drift ([general_task §3](../../../../agents/general_task.md#3-rules)). Do not DROP shared WAVE_SRC or write `ready` by hand.
