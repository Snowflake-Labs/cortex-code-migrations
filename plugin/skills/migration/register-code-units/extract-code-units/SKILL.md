---
name: extract-code-units
description: Extract DDL and source code from a connected source database using scai CLI. Pulls tables, views, procedures, functions, and other objects. Triggers: extract, pull ddl, extract code, get source code.
parent_skill: register-code-units
license: Proprietary. See License-Skills for complete terms
---

# Code Extraction

## On Entry

Tell the user:
> **Extracting from source database** — I'll connect to your source database and pull out the DDL and code for your tables, views, procedures, and functions.

## Prerequisites

- Migration project initialized (`scai init`)
- Source database connection configured and tested
- Network access to source database
- **Oracle / Teradata only:** the dialect's NuGet driver must be resolvable. If it isn't already cached at `~/.snowflake/scai/drivers/<dialect>/`, Step 1 will run the canonical bootstrap from [`../../connection/references/driver-bootstrap.md`](../../connection/references/driver-bootstrap.md) and ask the user how to provide it before any `curl` is run.

## Workflow

### Step 1: Verify Connection

**For SQL Server / Redshift:** No driver needed, test directly:

```bash
scai connection test -l <sqlserver|redshift> -s <CONNECTION_NAME>
```

**For Oracle or Teradata:** Resolve the driver per [`../../connection/references/driver-bootstrap.md`](../../connection/references/driver-bootstrap.md), substituting the dialect parameters from that doc. In most flows the driver was already resolved when the connection was set up, so the cache check at 1a will hit and you'll skip straight to 1e. If it doesn't hit, walk 1b → 1c/1d → 1e silently — never run `curl` without first asking how the user wants to supply the driver, and don't narrate the procedure to the user.

For this skill, 1e is the `connection test` invocation:

```bash
# After Branch A / B (driver not yet cached) — pass --driver-path once
scai connection test -l <oracle|teradata> -s <CONNECTION_NAME> --driver-path <PATH_TO_NUPKG>

# Cache hit — --driver-path not needed
scai connection test -l <oracle|teradata> -s <CONNECTION_NAME>
```

### Step 2: Ask What to Extract

Ask the user what they want to extract. Present the available object types for their source dialect:

- **SqlServer:** TABLE, VIEW, FUNCTION, PROCEDURE, SEQUENCE, TABLE_TYPE, TRIGGER
- **Redshift:** TABLE, VIEW, MATERIALIZED_VIEW, FUNCTION, PROCEDURE
- **Oracle:** TABLE, VIEW, MATERIALIZED_VIEW, FUNCTION, PROCEDURE, PACKAGE, PACKAGE_BODY, TRIGGER, SEQUENCE, TYPE, TYPE_BODY, SYNONYM
- **Teradata:** TABLE, VIEW, FUNCTION, PROCEDURE

Ask:
> "What would you like to extract? You can choose:"
> 1. **All objects** - Extract everything from the source database
> 2. **Specific object types** - e.g. just tables and views, or just procedures
> 3. **Specific schemas** - Limit to one or more schemas
> 4. **Name pattern** - Match objects by name (e.g. `Get*Data`)

Allow combining options (e.g. specific types within a specific schema).

### Step 3: Run Extraction

Build the `scai code extract` command based on user selections:

```bash
# Base command
scai code extract -s <CONNECTION_NAME>

# Add flags based on user choices:
#   --schema <SCHEMA>        filter by schema
#   -t TYPE1,TYPE2           filter by object type
#   -n "pattern"             filter by name pattern
#   --driver-path <PATH>     path to driver .nupkg (Oracle only, first use)
```

**Driver note (Oracle / Teradata):** If the driver was not already cached at the start of Step 1 (i.e. the user went through Branch A or B), include `--driver-path <PATH_TO_NUPKG>` here too. SCAI persists the driver path machine-wide after first use, so subsequent extractions (even in other projects) do not need it.

**Examples:**
```bash
# All objects
scai code extract -s <CONNECTION_NAME>

# Only tables and views in the dbo schema
scai code extract -s <CONNECTION_NAME> --schema dbo -t TABLE,VIEW

# Procedures matching a pattern
scai code extract -s <CONNECTION_NAME> -t PROCEDURE -n "Get*Data"

# Oracle: first extraction with driver path
scai code extract -s <CONNECTION_NAME> --driver-path ./Oracle.ManagedDataAccess.Core.nupkg

# Oracle: extract only packages and procedures from a schema
scai code extract -s <CONNECTION_NAME> --schema HR -t PACKAGE,PROCEDURE

# Teradata: first extraction with driver path
scai code extract -s <CONNECTION_NAME> --driver-path ./Teradata.Client.Provider.nupkg

# Teradata: extract only procedures from a database
scai code extract -s <CONNECTION_NAME> --schema MY_DB -t PROCEDURE
```

### Step 4: Verify Extraction

After extraction completes, verify the results:

```bash
# Check extracted files
find source/ -name "*.sql" | wc -l

# List by object type
ls -la source/*/
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

Confirm with user:
- [ ] Extraction completed without errors
- [ ] Expected number of objects extracted
- [ ] Source files appear in `source/` directory

## On Completion

After the CHECKPOINT passes, tell the user:
> **Extraction complete** — <N> SQL files extracted from your source database into `source/`. Next, we'll convert these to Snowflake SQL.

Then return to the calling skill.
