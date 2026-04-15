---
name: extract-code-units
description: Extract DDL and source code from a connected source database using scai CLI. Pulls tables, views, procedures, functions, and other objects. Triggers: extract, pull ddl, extract code, get source code.
parent_skill: register-code-units
license: Proprietary. See License-Skills for complete terms
---

# Code Extraction

Extract DDL and source code from a connected source database.

## Prerequisites

- Migration project initialized (`scai init`)
- Source database connection configured and tested
- Network access to source database

## Workflow

### Step 1: Verify Connection

Before extracting, verify the connection works:

```bash
scai connection test -l <sqlserver|redshift> -c <CONNECTION_NAME>
```

### Step 2: Ask What to Extract

Ask the user what they want to extract. Present the available object types for their source dialect:

- **SqlServer:** TABLE, VIEW, FUNCTION, PROCEDURE, SEQUENCE, TABLE_TYPE, TRIGGER
- **Redshift:** TABLE, VIEW, MATERIALIZED_VIEW, FUNCTION, PROCEDURE

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
```

**Examples:**
```bash
# All objects
scai code extract -s <CONNECTION_NAME>

# Only tables and views in the dbo schema
scai code extract -s <CONNECTION_NAME> --schema dbo -t TABLE,VIEW

# Procedures matching a pattern
scai code extract -s <CONNECTION_NAME> -t PROCEDURE -n "Get*Data"
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

## CHECKPOINT

Confirm with user:
- [ ] Extraction completed without errors
- [ ] Expected number of objects extracted
- [ ] Source files appear in `source/` directory

## Next Steps

Return to the calling skill.
