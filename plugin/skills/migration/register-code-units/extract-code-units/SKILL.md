---
name: extract-code-units
description: Extract DDL and source code from a connected source database using scai CLI. Pulls tables, views, procedures, functions, and other objects. Triggers: extract, pull ddl, extract code, get source code.
parent_skill: register-code-units
license: Proprietary. See License-Skills for complete terms
---

# Code Extraction

## On Entry

Tell the user:
> **Extracting from source database.**
>
> Here's what I'll do:
> 1. Connect to your source database using the configured connection.
> 2. Run read-only queries to enumerate the objects in scope.
> 3. Extract the DDL and code for each one, and save them under `source/`.

## Prerequisites

- Migration project initialized (`scai init`)
- `configure()` called at session start — validates the source connection and, for Oracle/Teradata, seeds the driver cache via [`../../connection/references/driver-bootstrap.md`](../../connection/references/driver-bootstrap.md)
- Network access to source database

## Workflow

### Step 1: Extract all objects from the connection's database

Do **not** ask what to extract. The connection card already said we will
pull all objects from that connection's database. Run `scai code extract`
against the configured connection with no type / schema / name filter.

If the user later asks to narrow the catalog, then filter with `--schema`,
`-t`, `-n`, or `-d` as in Step 2. Do not invent that question up front.

> **Name matching:** `-n` / `--name` is an **exact** case-insensitive match unless the
> pattern contains `*`. Do **not** pass a bare prefix expecting substring match —
> that used to pull sibling objects (e.g. `FOO` matching `FOO_SWTCH`). For partial
> matches use wildcards: `FOO*`, `*Employee*`. When the user lists specific table
> names, pass each exact name or extract by schema/type and let them confirm the
> catalog count.

### Step 2: Run Extraction

Build the `scai code extract` command based on user selections:

```bash
# Base command
scai code extract -s <CONNECTION_NAME> --json

# Add flags based on user choices:
#   -d, --database <DATABASE> extract from a specific database on the server,
#                             overriding the connection's own database
#   --schema <SCHEMA>        filter by schema
#   -t TYPE1,TYPE2           filter by object type
#   -n "Name"                exact name (case-insensitive); use * for wildcards
#   --driver-path <PATH>     path to driver .nupkg (Oracle only, first use)
```

**Multiple databases on one server (SqlServer, AzureSynapse, Redshift, Postgresql, Teradata).**
A source connection points at one database, but its server may host several. To migrate more
than one, pass a comma-separated list with `-d` — the CLI loops internally, continues past a
single database's failure, and returns one JSON envelope with per-database counts plus the
aggregate. Do **not** re-run without `-d`; that only re-pulls the connection's own database.
(Oracle and BigQuery don't bind a swappable database in the connection, so `-d` is rejected there —
use the connection's own database / schemas.)

1. **List the databases** on the connection's server with `query_source` (dialect-specific):
   - **SqlServer / AzureSynapse:** `SELECT name FROM sys.databases WHERE database_id > 4` (excludes the
     `master`/`tempdb`/`model`/`msdb` system databases).
   - **Redshift / Postgresql:** `SELECT datname FROM pg_database WHERE datistemplate = false`.
   - **Teradata:** `SELECT DatabaseName FROM DBC.DatabasesV WHERE DBKind = 'D'`.
2. Do **not** ask which databases up front: extract the connection's own database (omit
   `-d`). Only when the user asks to include others, **ask which to extract** via
   `ask_user_question` (`multiSelect = true`), defaulting to the connection's own database.
   Show the databases you found and ask even when the list has only one database: one
   candidate on the server is not the user saying it is the one to migrate. Never skip this
   question once you are choosing databases.

   **Wait for the user's response — do not proceed until they choose.**
3. **Run one extraction** with every selected database:

```bash
scai code extract -s <CONNECTION_NAME> -d Sales,Inventory --json
```

Output nests each under `source/<database>/…`, and the Code Unit Registry is regenerated once
after the run (the command re-scans the whole `source/` tree), so all coexist in one project.
Omit `-d` when the connection's own database is the only target.

**The connection's database is missing or wrong.** When the connection's configured database
does not exist on the server (e.g. SQL Server `Cannot open database "<name>"`), do not pick a
replacement yourself. List the databases as in step 1 above, then tell the user:

> The connection `<CONNECTION_NAME>` points at database `<CONFIGURED_DB>`, which doesn't exist on
> this server. I found: `<DATABASE_LIST>`. Which database should I use?

and ask via `ask_user_question`, even when only one database is listed.

**Wait for the user's response — do not proceed until they choose.**

Never change a connection's database without the user's confirmation: every later step
(registry, conversion, deployment, data migration) inherits it, and an unconfirmed switch
migrates the wrong database. This holds for `-d`, re-adding the connection, or editing its
settings alike.

**Driver note (Oracle / Teradata):** `configure()` seeds the driver cache, so `--driver-path` is normally not needed here. If the cache was missed for any reason, pass `--driver-path <PATH_TO_NUPKG>` on first use; SCAI persists the path machine-wide and reuses it across projects.

**Examples:**
```bash
# All objects
scai code extract -s <CONNECTION_NAME> --json

# All objects from a specific database on the server
scai code extract -s <CONNECTION_NAME> --database Sales --json

# Only tables and views in the dbo schema
scai code extract -s <CONNECTION_NAME> --schema dbo -t TABLE,VIEW --json

# Exact table name
scai code extract -s <CONNECTION_NAME> -t TABLE -n "SNAPM_EDB_MODEL_GROUPING" --json

# Procedures matching a wildcard pattern
scai code extract -s <CONNECTION_NAME> -t PROCEDURE -n "Get*Data" --json

# Oracle: first extraction with driver path
scai code extract -s <CONNECTION_NAME> --driver-path ./Oracle.ManagedDataAccess.Core.nupkg --json

# Oracle: extract only packages and procedures from a schema
scai code extract -s <CONNECTION_NAME> --schema HR -t PACKAGE,PROCEDURE --json

# Teradata: first extraction with driver path
scai code extract -s <CONNECTION_NAME> --driver-path ./Teradata.Client.Provider.nupkg --json

# Teradata: extract only procedures from a database
scai code extract -s <CONNECTION_NAME> --schema MY_DB -t PROCEDURE --json
```

### Step 3: Verify Extraction

After extraction completes, verify the results: count `.sql` files under `source/` and list its sub-directories by object type. Use whichever portable form fits the host:

```bash
# macOS / Linux
find source/ -name "*.sql" | wc -l
ls -la source/*/
```

```powershell
# Windows PowerShell
(Get-ChildItem -Recurse -Filter *.sql source/).Count
Get-ChildItem source/ -Directory | ForEach-Object { Get-ChildItem $_ }
```

## Output Structure

```
source/
└── <database>/
    └── <schema>/
        ├── table/
        │   └── *.sql
        ├── view/
        │   └── *.sql
        ├── procedure/
        │   └── *.sql
        └── function/
            └── *.sql
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Failed to test credentials" | Check VPN, firewall rules, or credential validity |
| "IP not allowed" | Add your IP to database firewall (Azure Portal for Azure SQL) |
| "Connection timeout" | Verify network connectivity, increase timeout |
| Empty extraction | Verify schema names, check user permissions |
| `ORA-12154: TNS:could not resolve the connect identifier` | Verify Oracle host, port, and service name |
| `ORA-01017: invalid username/password` | Check Oracle credentials |
| `Socket closed` (Teradata) | Verify Teradata host and port (default 1025) |
| `Logon failed` (Teradata) | Check Teradata credentials |
| `Driver not found` | Re-download the NuGet package and pass `--driver-path` again |

## CHECKPOINT

Check these yourself against the `--json` envelope and the Step 3 listing. Do
**not** turn them into a question — the envelope already says whether the
extraction was complete, and the user cannot verify a count you just computed
for them:

- [ ] `catalog.failed` is 0
- [ ] `catalog.extracted` equals `catalog.discovered`
- [ ] `.sql` files are present under `source/`

Stop and ask only when a check fails: say which one, and what you propose to do
about it.

## On Completion

After the CHECKPOINT passes, tell the user — a statement, not a question. Never
ask whether the object count matches what they expected; narrowing the catalog
is something they raise, not something you prompt for.

Fill placeholders from the JSON envelope returned by `scai code extract --json` (`catalog.{discovered,extracted,failed}`, `byType`, `databases[]`, `failures[]`, `executionTimeSeconds`). When you extracted several databases, read per-database counts from `databases[]` and the aggregate from `catalog` — do not sum envelopes across runs.

> **Extraction complete.** `<extracted>/<discovered>` objects extracted in `<duration>`, broken down by type (filled from `byType`). Files saved under `source/`.
> *If `failed > 0`:* `<failed>` failed. Most common error: `<top_failure_reason>`. Full list in the reports.

Then read `has_etl_code` from `configure()`. Never ask a standalone ETL
yes/no — extras already collected that on the setup/register card.

- If `has_etl_code` is **`false`** (explicitly): say that next we'll convert these to Snowflake SQL — then go straight on (below); the sentence announces the next step, it does not end the turn.
- If `has_etl_code` is **not set**: return to the parent register skill and collect the extras card there, then re-read `has_etl_code`.
- If `has_etl_code` is **`true`** (explicitly): ask which platform via `ask_user_question` (`multiSelect = false`):

> "Which ETL platform is it?"
>
> 1. **SSIS** — `.dtsx` packages (native SnowConvert)
> 2. **Informatica Power Center** — XML repo export (native SnowConvert)
> 3. **Another ETL platform** — Talend, Alteryx, Informatica Cloud / IICS, DataStage,
>    Pentaho, Azure Data Factory, or something else (routes through AI-First)

- **SSIS / Informatica Power Center:** ask for the ETL folder path and
  run (do **not** pass `--overwrite` — the extracted SQL is already in `source/`):

  ```bash
  scai code add -i <ETL_PATH> --json
  ```

  This arranges the packages into `source/_etl/`, where `convert` finds them without an
  external path flag.

  If this or the Power BI `scai code add` below times out, runs in the background or
  fails, handle it as
  [add-code-units Step 3](../add-code-units/SKILL.md#if-the-import-times-out-or-runs-in-the-background)
  says before you go on.

- **Another ETL platform:** these files never go through `scai code add` —
  the native `EtlFileClassifier` under `source/_etl/` only understands SSIS and
  Informatica PowerCenter. Instead:
  1. Ask which platform. Accept a free-form name if it is not in the list. Store the
     lower-case slug (`talend`, `alteryx`, `iics`, `datastage`, `pentaho`, `adf`, …).
  2. Ask for the folder path containing the platform's source documents.
  3. Copy losslessly into `source/_etl_aifirst/<platform>/` by invoking the
     enumeration helper — do **not** hand-copy files. The helper writes no parallel
     manifest; its JSON envelope holds one `units` entry per source document that
     step 4 hands to the MCP `create_registry_unit` tool.

     ```bash
     python3 "<PLUGIN_ROOT>/register-code-units/scripts/import_aifirst_etl.py" \
       --platform <PLATFORM_SLUG> \
       --source "<ETL_PATH>" \
       --json
     ```

     `<PLUGIN_ROOT>` is this skill's grandparent directory
     (`.../plugin/skills/migration`). Add `--overwrite` when the user is re-importing
     on purpose.
  4. Query the deterministic `unit_id` values from the helper first. If an ID
     already exists, verify its platform, format, and `files.source.path` exactly
     match the helper output and do not recreate it; stop on a mismatch. For every
     missing entry, call `create_registry_unit` — this is what `convert` Step 4.5
     reads:

     ```
     create_registry_unit(
       unit_id="<UNIT_ID>",
       name="<NAME>",
       platform="<PLATFORM_SLUG>",
       format="<FORMAT>",
       source_file="<PROJECT_RELATIVE_SOURCE_PATH>"
     )
     ```

     The tool stamps `kind: etl`, `source.objectType: workflow`, keeps unlisted
     platforms under `extensions.sourcePlatform` (never faked as SSIS or
     Informatica), and refuses to overwrite an id. Query-before-create makes an
     identical re-import idempotent while preserving that collision guard.
     Do **not** call `register_units` for these units. Do **not** pass `customKind`;
     that would create a `kind: custom` unit without `files.source.path`, which the
     setup gate and Step 4.5 refuse.

  5. Verify with `query_registry` that each unit exists with `kind = 'etl'`,
     `source.objectType = 'workflow'`, and a `files.source.path` matching its
     vendored source. If any is missing, stop and tell the user — the registry write
     is the contract Step 4.5 reads at convert time.

  Repeat once per platform if there is more than one AI-First ETL source.

Power BI templates are **not** extracted from the database. A local Power BI template (`.pbit`)
is staged separately. After extract (and after any ETL add), read `has_power_bi`
from `configure()`:

- If `has_power_bi` is **`false`**, proceed without asking.
- If `has_power_bi` is not set, return to the parent register skill and collect
  the extras card, then re-read it.
- If `has_power_bi` is **`true`**, ask only for the local folder containing the
  `.pbit` files and run (do **not** pass `--overwrite`):

```bash
scai code add -i <POWER_BI_PATH> --json
```

This copies templates to `source/BI/PowerBI/` and `artifacts/BI/PowerBI/` only. Do not imply a database extract of Power BI.
A timeout, background launch or failure here is handled as
[add-code-units Step 3](../add-code-units/SKILL.md#if-the-import-times-out-or-runs-in-the-background) says.

Then return to the calling skill **in this same turn**. Under setup that means
calling `progress_setup()` now and starting the step it names. Ending the turn
on "next we'll convert" leaves the user watching an idle screen with nothing to
click until they type "continue".
