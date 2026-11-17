# Testing Framework Permissions — Reference

What Snowflake and source-DB privileges the testing framework needs, and what to do when `configure()` reports a `schema_status_validation: error(...)` or `prereq_status_clone_perms: failed(...)`, or `scai test validate` reports a refused clone, a procedure that needs cloning, or a recovery stop.

> **Not auto-loaded.** The agent surfaces the configure response message verbatim and stops. The user can read this reference to find the GRANTs needed, apply them out-of-band, then say "recheck" / "done" — the agent runs `configure(ensure_metadata_schema=true)` to re-verify.

## What the testing framework does on Snowflake

When the user opts into testing (answers Q1 in `migrate-objects/SKILL.md` Step 2), `configure(ensure_metadata_schema=true)` triggers two probes that may write to Snowflake:

1. **`scai test validate --create-schema`** — installs the `VALIDATION` schema in the database named by `testing_results_database` in `.scai/settings/test_config.yaml` (the SnowConvert metadata database, not the migration target; projects predating that setting still have it in the target). Creates a stage (`@VALIDATION.BASELINES`), a results table (`VALIDATION.RESULTS`), supporting views (`SUMMARY`, `LATEST`, `FAILURES`), and the validation stored procedures (`VALIDATE_SINGLE`, `VALIDATE_BATCH`). Idempotent on the scai side: it creates only the objects that are missing and never replaces one, so re-runs against an already-deployed schema, including one another role set up, are no-ops.
2. **The `clone_perms` probe** — under `clone` (the default) and `auto` it creates and drops a scratch database (`_SCAI_CLONE_PERM_CHECK_…`) to see whether the role can create databases, which clone-based isolation needs; under any other strategy it reports `not_applicable` without a probe. Under `auto` a refused probe reports `info`, not `failed`.

Later, during the deploy-test-fix loop, the framework also:

- Writes baseline JSON files to `@VALIDATION.BASELINES` (one per test case).
- Inserts results rows into `VALIDATION.RESULTS`.
- Under `clone` (the default), creates a clone of each target database for data-changing tests (`CREATE OR REPLACE DATABASE <clone> CLONE <user_db>`); its name is recorded in the project and later runs reuse it. Under the live-target strategies it writes recovery records to `<METADATA_DATABASE>.TESTING.ISOLATION_RECOVERY` instead.
- Reads from source procedures, captures result sets via `scai test capture`.

The Snowflake-side privileges below cover all of the above.

## Snowflake-side privileges

Have a `SECURITYADMIN`-equivalent user (or whoever owns role grants in your account) run this block. Substitute `<DATABASE>`, `<WAREHOUSE>`, and `<ROLE>` with your project values. `<ROLE>` is the role used by the connection in `~/.snowflake/config.toml`.

```sql
USE DATABASE <DATABASE>;

-- Database-level provisioning for the testing schema.
GRANT USAGE ON DATABASE <DATABASE> TO ROLE <ROLE>;
GRANT CREATE SCHEMA ON DATABASE <DATABASE> TO ROLE <ROLE>;

-- VALIDATION is shared by every role that records test results in
-- <DATABASE>. The role that created it owns it; every other role gets this
-- bundle from that owner. Never transfer OWNERSHIP of VALIDATION or anything
-- in it: that takes the schema away from the team that set it up.
GRANT USAGE ON SCHEMA <DATABASE>.VALIDATION TO ROLE <ROLE>;
GRANT CREATE TABLE, CREATE VIEW, CREATE STAGE, CREATE FILE FORMAT, CREATE PROCEDURE
    ON SCHEMA <DATABASE>.VALIDATION TO ROLE <ROLE>;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON ALL TABLES IN SCHEMA <DATABASE>.VALIDATION TO ROLE <ROLE>;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON FUTURE TABLES IN SCHEMA <DATABASE>.VALIDATION TO ROLE <ROLE>;
GRANT READ, WRITE
    ON ALL STAGES IN SCHEMA <DATABASE>.VALIDATION TO ROLE <ROLE>;
GRANT READ, WRITE
    ON FUTURE STAGES IN SCHEMA <DATABASE>.VALIDATION TO ROLE <ROLE>;
GRANT SELECT ON ALL VIEWS IN SCHEMA <DATABASE>.VALIDATION TO ROLE <ROLE>;
GRANT SELECT ON FUTURE VIEWS IN SCHEMA <DATABASE>.VALIDATION TO ROLE <ROLE>;
GRANT USAGE ON ALL FILE FORMATS IN SCHEMA <DATABASE>.VALIDATION TO ROLE <ROLE>;
GRANT USAGE ON FUTURE FILE FORMATS IN SCHEMA <DATABASE>.VALIDATION TO ROLE <ROLE>;

-- Read access to the schemas being tested. The validation procs run as the
-- caller and need to read the source rows the procedures under test touch.
GRANT USAGE ON ALL SCHEMAS IN DATABASE <DATABASE> TO ROLE <ROLE>;
GRANT USAGE ON FUTURE SCHEMAS IN DATABASE <DATABASE> TO ROLE <ROLE>;
GRANT SELECT ON ALL TABLES IN DATABASE <DATABASE> TO ROLE <ROLE>;
GRANT SELECT ON FUTURE TABLES IN DATABASE <DATABASE> TO ROLE <ROLE>;
GRANT USAGE ON ALL PROCEDURES IN DATABASE <DATABASE> TO ROLE <ROLE>;
GRANT USAGE ON FUTURE PROCEDURES IN DATABASE <DATABASE> TO ROLE <ROLE>;
GRANT USAGE ON ALL FUNCTIONS IN DATABASE <DATABASE> TO ROLE <ROLE>;
GRANT USAGE ON FUTURE FUNCTIONS IN DATABASE <DATABASE> TO ROLE <ROLE>;

-- Clone-based isolation: `isolation_strategy: clone` (the default) and
-- `auto`'s first choice. A data-changing test runs in a clone of <DATABASE>
-- that validate creates once and reuses. This is what
-- `prereq_status_clone_perms` checks. Without it, see "Testing without
-- CREATE DATABASE".
GRANT CREATE DATABASE ON ACCOUNT TO ROLE <ROLE>;

-- Warehouse to run validation procs.
GRANT USAGE, OPERATE ON WAREHOUSE <WAREHOUSE> TO ROLE <ROLE>;
```

`RAW_TEXT_FORMAT` is replaced by a versioned testing migration, not by validation runs: migration 3 (`migration_0003_raw_text_escape.py`) re-runs `CREATE OR REPLACE FILE FORMAT RAW_TEXT_FORMAT` with `ESCAPE_UNENCLOSED_FIELD = NONE` once per account. The existing owner, or an authorized maintenance role with the required ownership privileges, applies that upgrade; a runtime role needs `USAGE` on it and never takes ownership. If every case fails reading a baseline with a Windows path (`hex digit is expected in \U????????`), an outdated format may be the cause: ask its owner to check whether the migration has been applied and apply it if needed, without transferring ownership. An existing `JSON_FORMAT` also requires only `USAGE`; it is created with `IF NOT EXISTS`.

After applying, tell the agent "done" or "recheck" — it will run `configure(ensure_metadata_schema=true)` which clears the cached failure (including the `schema_version` stamp in `plugin.local.yml`) and re-probes.

### Why each grant

| Grant | Used for |
|---|---|
| `USAGE ON DATABASE` | Connecting to the database at all |
| `CREATE SCHEMA ON DATABASE` | `scai test validate --create-schema` installing `VALIDATION` |
| The bundle on `VALIDATION` | Creating whichever testing objects are missing, writing results and reading the views another role created |
| `READ, WRITE ON STAGE` | Uploading baseline JSON files to `@VALIDATION.BASELINES`, reading them during validation |
| `SELECT ON ALL/FUTURE TABLES` | Validation procs reading source rows the procedures under test touch |
| `USAGE ON ALL/FUTURE PROCEDURES, FUNCTIONS` | Invoking the migrated procs/functions during validation |
| `CREATE DATABASE ON ACCOUNT` | Clone-based isolation (`clone`, and `auto` when granted; not needed with `testing_sandbox_databases`, below) |
| `USAGE ON DATABASE <METADATA_DATABASE>` and one recovery-table ladder below | Live-target isolation (`rollback`, `time_travel`, and `auto` without the grant) keeping its recovery records |
| `USAGE ON PROCEDURE <METADATA_DATABASE>.ISOLATION.CREATE_TEST_CLONE(VARCHAR, VARCHAR)` | Cloning through an installed clone procedure instead of `CREATE DATABASE` |
| `USAGE, OPERATE ON WAREHOUSE` | Running validation queries |

### Without `CREATE DATABASE ON ACCOUNT`: `testing_sandbox_databases`

Some accounts grant `CREATE DATABASE` only through an admin procedure. Then have an admin create one empty database per converted database, used for nothing else, and grant the role on each:

```sql
CREATE DATABASE AIM_TEST_MDB;              -- one per converted database
GRANT USAGE, CREATE SCHEMA ON DATABASE AIM_TEST_MDB TO ROLE <ROLE>;
```

and name them in `.scai/settings/test_config.yaml`, keyed by converted database (one name alone serves every converted database, if their schema names do not collide):

```yaml
testing_sandbox_databases:
  mdb: AIM_TEST_MDB
  udm: AIM_TEST_UDM
```

Testing then creates no database. A procedure sandbox creates its schemas in the named database (so the database must not already hold schemas of those names), clones the tables into them, and drops only the schemas it marked at teardown; the database, its `PUBLIC` schema and anything else in it stay. Tables in `PUBLIC` cannot be sandboxed this way, and two converted databases with a same-named table need a named database each. A named database takes one sandbox at a time. `scai test validate` isolates cases with per-table backups (`--isolation-strategy backup_restore`) instead of database clones. `clone_perms` probes `CREATE SCHEMA` in each named database instead of `CREATE DATABASE`.

A `restore_from=sandbox` snapshot needs a second such database per converted database, named under `testing_sandbox_snapshot_databases` in the same shape; without it that request is refused.

### Shared lookup databases: `testing_reference_databases`

A procedure that only reads some converted databases (shared lookup data, too large to copy per object) can read them in place. List their converted database names in `.scai/settings/test_config.yaml`:

```yaml
testing_reference_databases: [adp, viewpoint]
```

Each one needs an entry on both sides of `.scai/bindings/database-bindings.yaml`, which names the shared database it reads. A procedure sandbox binds the token to that database instead of copying it: no database, schema or table is created, cloned, seeded, restored or dropped there, and the sandbox's write guards refuse SQL that changes it. Setup refuses an object that deploys into a reference database itself, or whose reference shares a database with one it copies. A test case whose procedure writes a reference database fails with `procedure writes reference catalog <X>; it needs private isolation`: leave that database out of the list for it.

## Testing without CREATE DATABASE

If the probe is refused, setup asks once (in autonomous mode the question goes to the Escalations tab when tests run); yes → `auto`, no → `clone`. You can change it any time by asking the agent.

On the live target a data-changing test runs against the real tables, and its changes are restored right after it — by rolling the statements back, or from Time Travel. Two limits: a procedure whose changes can't be restored that way is reported and not run (`Not run: needs cloning …`), and a run that cannot confirm a restore stops (`Recovery required …`) until its records are recovered. Those records need somewhere to live:

```sql
-- Recovery records live in the SnowConvert metadata database (<METADATA_DATABASE>, SNOWCONVERT_AI unless
-- your admin names another); it must not be the migration target.
GRANT USAGE ON DATABASE <METADATA_DATABASE> TO ROLE <ROLE>;
-- The first run creates <METADATA_DATABASE>.TESTING.ISOLATION_RECOVERY when the role can:
GRANT CREATE SCHEMA ON DATABASE <METADATA_DATABASE> TO ROLE <ROLE>;
-- ...or, when the TESTING schema already exists:
GRANT USAGE, CREATE TABLE ON SCHEMA <METADATA_DATABASE>.TESTING TO ROLE <ROLE>;
-- ...or have an admin create the table, and grant only:
GRANT USAGE ON SCHEMA <METADATA_DATABASE>.TESTING TO ROLE <ROLE>;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE <METADATA_DATABASE>.TESTING.ISOLATION_RECOVERY TO ROLE <ROLE>;
```

On the tables the procedures change, the role needs the table-level privileges the migration already uses (INSERT, UPDATE, DELETE, and, for a table a test drops or replaces, ownership of it and `CREATE TABLE` on its schema), and, for Time Travel, retention above 0.

### A clone procedure (optional)

An admin can install the reference clone procedure, [clone-procedure.sql](clone-procedure.sql), so the role never needs `CREATE DATABASE`. It must be installed as `<METADATA_DATABASE>.ISOLATION.CREATE_TEST_CLONE`: under `auto`, when `CREATE DATABASE` is refused, validate looks for it by that name and calls it to make each clone. `clone` never uses it. The installer's grants and steps are in the script's header. The runner role then needs `USAGE` on `<METADATA_DATABASE>`, on `<METADATA_DATABASE>.ISOLATION`, and on `PROCEDURE <METADATA_DATABASE>.ISOLATION.CREATE_TEST_CLONE(VARCHAR, VARCHAR)`.

### Check what this role can do

Run `scai test doctor` in the project (after tests are captured, for the clone and per-procedure parts). It reports:

- the strategy;
- whether the clone procedure is installed in the metadata database and visible to this role;
- which clones validate needs, and whether they exist;
- whether the role can create databases (the same scratch-database probe, run only when a validate run would create a database);
- where recovery records go;
- what `auto` would pick for each procedure. Under `rollback` and `time_travel` it also lists the tables each would rewrite, and states (without checking) the one precondition that the role can INSERT, UPDATE and DELETE them.

It changes nothing but that one probe.

## Source-side privileges by dialect

When `scai test capture` later fails with `permission denied on EXECUTE` or `SELECT permission denied` errors, the source role is missing privileges. The testing framework needs to (a) execute every procedure under test and (b) read every table those procedures touch.

### SQL Server

```sql
GRANT EXECUTE ON SCHEMA::<SCHEMA> TO <LOGIN>;
GRANT SELECT  ON SCHEMA::<SCHEMA> TO <LOGIN>;
-- Snapshot isolation is used to capture DML deltas atomically:
ALTER DATABASE <DB> SET ALLOW_SNAPSHOT_ISOLATION ON;
ALTER DATABASE <DB> SET READ_COMMITTED_SNAPSHOT ON WITH NO_WAIT;
```

### Redshift

```sql
GRANT USAGE ON SCHEMA <schema> TO <user>;
GRANT SELECT ON ALL TABLES IN SCHEMA <schema> TO <user>;
GRANT EXECUTE ON ALL PROCEDURES IN SCHEMA <schema> TO <user>;
-- Transaction-based isolation needs nothing extra: each test runs in its
-- own implicit transaction that gets rolled back after capture.
```

### Oracle

```sql
GRANT CONNECT, RESOURCE TO <USER>;
GRANT SELECT ON <SCHEMA>.<TABLE> TO <USER>;       -- per table
GRANT EXECUTE ON <SCHEMA>.<PROCEDURE> TO <USER>;  -- per proc / package
-- Or, less granular but more common in dev environments:
GRANT SELECT ANY TABLE, EXECUTE ANY PROCEDURE TO <USER>;
```

### Teradata

```sql
GRANT SELECT  ON <DATABASE> TO <USER>;
GRANT EXECUTE PROCEDURE ON <DATABASE> TO <USER>;
-- Backup/restore isolation creates short-lived database copies on Teradata;
-- the user needs CREATE DATABASE on the parent database:
GRANT CREATE DATABASE ON <PARENT_DATABASE> TO <USER>;
```

## Common errors → fix

| Error message (verbatim from configure response or scai) | Fix |
|---|---|
| `Insufficient privileges to operate on database '<DB>'` | `GRANT USAGE ON DATABASE`, then `configure(ensure_metadata_schema=true)` |
| `Insufficient privileges to operate on schema 'VALIDATION'` or `not authorized to perform: CREATE SCHEMA` | `GRANT CREATE SCHEMA ON DATABASE`, then `configure(ensure_metadata_schema=true)`. After the deploy succeeds, the schema-bundle grants above are still needed for ongoing test runs. |
| `prereq_status_clone_perms: failed("CREATE DATABASE on ACCOUNT is not granted ...")` | `GRANT CREATE DATABASE ON ACCOUNT`, or answer the setup's opt-in question. The probe really creates a database, so a grant inherited through a parent role counts. Where the account cannot grant it, pre-created databases named under `testing_sandbox_databases` (above) also work. |
| `prereq_status_clone_perms: failed("The current role cannot create schemas in ...")` | Create the named databases, then `GRANT USAGE, CREATE SCHEMA ON DATABASE` on each to the role. |
| `prereq_status_clone_perms: failed("… No isolation_strategy is set yet. Only after the user answers …")` | Answer the question setup asks: yes tests procedures on the live target, no keeps clones. Autonomous runs never answer it and carry on. |
| `Insufficient privileges to operate on account … If this role can't create databases, …` | The clone was refused mid-run. Grant `CREATE DATABASE`, or answer the setup's opt-in question. `scai test doctor` shows whether this role can create databases. |
| `Not run: needs cloning (…). To run it, …` | That procedure can't be restored on the live target; the message names what unlocks it. `scai test doctor` lists them before a run. |
| `<METADATA_DATABASE>.TESTING.ISOLATION_RECOVERY can't be created or read by this role …` | The grants in "Testing without CREATE DATABASE", or ask the agent to switch the project to `clone`. |
| `… keep their recovery records in the SnowConvert metadata database, and <DB> is the target …` | Ask the agent to switch the project to `clone`, or have an admin pick another metadata database; in CI, `CUSTOM_SNOWCONVERT_DATABASE` names it. |
| `Recovery required …` (any other) | A run stopped before it could confirm a restore, and neither recovery row above matches. Run the tests again: the next run recovers the records it left, or names them and stops. |
| `Object 'VALIDATION.BASELINES' is not owned by ... GRANT WRITE` | `GRANT READ, WRITE ON STAGE`, from the role that owns it. Never `GRANT OWNERSHIP` on an object another role created. |
| Source-side: `permission denied on EXECUTE` | Apply the dialect-specific EXECUTE grants above |
| Source-side: `SELECT permission denied on relation X` | Apply the dialect-specific SELECT grants above |
