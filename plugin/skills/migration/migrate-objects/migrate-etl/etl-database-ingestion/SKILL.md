---
name: etl-database-ingestion
description: Hand over database landing after ETL conversion — read the database manifest and let the operator pick generated JDBC Openflow JSON, their own loader, or a SQL Server Change Tracking or CDC connector. Writes a landing plan beside the manifest. Triggers: land my database tables, database landing, database ingestion, change tracking landing, CDC landing, JDBC Openflow.
parent_skill: migrate-etl
license: Proprietary. See License-Skills for complete terms
---

# ETL Database Ingestion

## On Entry

Tell the user:
> **Setting up database landing** — converted SQL already names the Snowflake tables. I'll read the database manifest, you pick how rows get there, and I'll hand you the generated Openflow flow or the source-to-Snowflake pairs. Importing a flow is yours. Skipping this still leaves deploy and activation where they were.

## Step 0: Find the Manifest

Read the newest `database-manifest.json`:

```
artifacts/database-ingestion/<conversion-run>/database-manifest.json
```

When that run folder is absent, use `artifacts/database-ingestion/database-manifest.json`, then `database-manifest.json` under the ETL output root.

`schemaVersion` must be `1.0`. On any other value, stop and tell the user the manifest is newer than this skill.

**No manifest, or no object with `ingestion.state` of `ingestion`:** nothing was classified for landing. Tell the user that and hand control back to [../SKILL.md](../SKILL.md) Step 4. Deploy still finishes.

## Step 1: Report What the Manifest Recorded

Load [references/database-manifest.md](./references/database-manifest.md) and report each object from the manifest. Use the landing name the manifest recorded. When `ingestion.landing` is absent, say the manifest did not record a destination.

## Step 2: Ask

The rows from Step 1 decide which paths exist. **Your own loader** stays on the list every time.

| Classified rows | Paths to offer |
|---|---|
| Any `snapshot` | Generated Openflow snapshot JSON, and their own loader |
| Any `sqlServerChangeTracking` or `sqlServerCdc` | SQL Server connector handoff, and their own loader |
| Both of the above | All three |
| Rejected, unresolved, or excluded only | Their own loader has no classified pair to hand over. Return those rows and go to Step 5. |

Tell the user, dropping any sentence whose row is absent:
> "Classified objects need to land on the names above. **Openflow snapshot** is the generated JDBC flow for snapshot tables — I'll hand you the JSON path and the empty parameter names. **Your own loader** — I'll give you the same source-to-Snowflake pairs. **SQL Server connector** — for Change Tracking or CDC, I'll hand you each source-to-landing pair and you point the connector at it. You can skip. Which fits?"

**Wait for the user's response — do not proceed until they choose.** One answer can mix paths by mode. Skip is a choice.

## Step 3: Hand Off the Chosen Path

Load [references/database-manifest.md](./references/database-manifest.md) for the Openflow file names and the parameter names the flow ships empty.

**Openflow snapshot.** Name the flow JSON and each table-mapping JSON. Name the empty parameter names and the Snowflake connection service. The operator imports the flow and fills those values in Openflow. Snapshot landing tables are the `landing_tables.sql` deploy already ran when this conversion applied a snapshot config.

**Own loader.** Per classified object, give the source identity and the landing `database.schema.table` from the manifest.

**SQL Server connector.** Per Change Tracking or CDC row, give the source identity, the landing identity, and the mode. The connector creates the replication table. Converted SQL already targets that landing name. These rows have no snapshot DDL and no snapshot flow.

**Skip.** Record the skip.

## Step 4: Write the Landing Plan

Write it beside the manifest you read:

```
artifacts/database-ingestion/<conversion-run>/landing-plan.md
```

Headings, in this order:

- **Selected path** — Openflow snapshot, own loader, SQL Server connector, skip, or a mix by mode.
- **Rows** — one row per object from Step 1: id, how it was classified, source identity, and the landing name when the manifest has one.
- **What was handed over** — file paths and parameter or service names, or the source-to-landing pairs.
- **Verification** — Step 5, for whoever later asks whether rows arrived.
- **Re-conversion** — a new conversion writes a new manifest. Re-read it and refresh this plan.

Tell the user where you wrote it.

## Step 5: Verify Rows (only if they ask)

When they ask whether rows arrived, `SELECT COUNT(*)` from the landing names on the manifest for the rows they name. Report the counts.

## Step 6: Return to the Calling Skill

Tell the user:
> "The plan is written beside the database manifest. The next load is yours, on the path you picked. Ask me to count a landing table when you want one checked."

Then return to [../SKILL.md](../SKILL.md) Step 4, at the point that skill offered this one:

- **Entered from that offer** — hand control back to Step 4 and let it make its own `transition_status(task="deploy")` call, so `deploy` advances once.
- **Entered later by skill-match** — stamp nothing. The unit keeps its position.

Activation stays the `deploy` tool with `snowflake_task_activate = true`, only when the user asks.
