# SSC-EWI-SSIS0022 — Bulk Insert FireTriggers Not Supported

A Bulk Insert task had `FireTriggers` set, so the target table's `INSERT` triggers ran for the loaded rows (without it, `BULK INSERT` skips triggers). Snowflake has no triggers, and SnowConvert leaves `CREATE TRIGGER` out of scope. The generated `COPY INTO` loads the rows and nothing more. The marker **breaks compilation**.

## Quick Reference

| Aspect | Detail |
|--------|--------|
| Marker type | `!!!RESOLVE EWI!!!` (compilation-breaking) |
| Breaks compilation? | **Yes** |
| Frequency | Rare (once per Bulk Insert task with FireTriggers) |
| Common action | Find the target's INSERT trigger; none means remove the marker, one means run its logic after the load |

## Identification

```sql
!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0024 - ... ***/!!!!!!RESOLVE EWI!!! /*** SSC-EWI-SSIS0022 - SSIS BULKINSERTTASK FIRETRIGGERS OPTION IS NOT SUPPORTED IN SNOWFLAKE. CONSIDER USING SNOWFLAKE STREAMS AND TASKS TO IMPLEMENT TRIGGER-LIKE BEHAVIOR. ***/!!!
--** SSC-FDM-SSIS0013 - ... **
--** SSC-FDM-SSIS0016 - ... **
COPY INTO dbo.Inventory
FROM '@{STAGE_PLACEHOLDER}'
...
```

Find the trigger in the converted database code: SnowConvert comments it out under `--** SSC-OOS - OUT OF SCOPE CODE UNIT. CREATE TRIGGER IS OUT OF TRANSLATION SCOPE. **`. Search for `CREATE TRIGGER` with `ON <target table>` and `INSERT` in its `FOR` / `AFTER` / `INSTEAD OF` list.

## Fix Patterns

### Pattern 1: No INSERT trigger on the target

`FireTriggers` was set out of habit. Remove the marker; no other change.

### Pattern 2: Trigger logic for this load

Load into a transient table first, run the trigger body against it (it is the trigger's `inserted`), then move the rows on:

```sql
CREATE OR REPLACE TRANSIENT TABLE dbo.Inventory_load LIKE dbo.Inventory;
COPY INTO dbo.Inventory_load FROM @public.landing_stage/inventory/ FILES = ('inventory.csv') FILE_FORMAT = (...) ON_ERROR = SKIP_FILE_10;
-- was trg_Inventory_Audit: INSERT INTO dbo.InventoryAudit SELECT ItemId, GETDATE() FROM inserted
INSERT INTO dbo.InventoryAudit (ItemId, AuditedAt) SELECT ItemId, CURRENT_TIMESTAMP() FROM dbo.Inventory_load;
INSERT INTO dbo.Inventory SELECT * FROM dbo.Inventory_load;
```

A trigger that rejected rows (`RAISERROR` / `ROLLBACK` on a condition) becomes a check on the transient table that raises before the final `INSERT`. An `INSTEAD OF INSERT` trigger replaces the final `INSERT` with its own body.

### Pattern 3: The trigger must cover every writer

When other jobs also insert into the table and rely on the same trigger, use a stream and a task, as the marker suggests:

```sql
CREATE STREAM IF NOT EXISTS dbo.Inventory_ins ON TABLE dbo.Inventory APPEND_ONLY = TRUE;
-- after the COPY, in the same task (or in a task WHEN SYSTEM$STREAM_HAS_DATA('dbo.Inventory_ins'))
INSERT INTO dbo.InventoryAudit (ItemId, AuditedAt) SELECT ItemId, CURRENT_TIMESTAMP() FROM dbo.Inventory_ins;
```

The DML that reads the stream advances it. Create the stream once at deploy time, before the first load.

## Key Points

- **Must** remove the `!!!RESOLVE EWI!!!` marker.
- The trigger source is outside the package. If the converted database code is not in the project and nobody says there is no trigger, add `-- NEEDS-USER: does <table> have an INSERT trigger?` and mark as needs-user.
- Translate the trigger body with the project's T-SQL conversion (`GETDATE()` → `CURRENT_TIMESTAMP()`, `inserted` → the transient table or stream).
- The target's stage still has to be resolved: [SSC-EWI-SSIS0024](SSC-EWI-SSIS0024.md).
