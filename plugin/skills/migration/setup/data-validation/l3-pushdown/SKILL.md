---
name: l3-pushdown-setup
description: Configure L3 signature pushdown extract for cloud data validation. A bucket makes L3 faster; wait if they still need to get one. Then help create a Snowflake external stage and patch workflow YAML plus worker TOML. Triggers: L3 pushdown, row validation extract, external stage for validation, UNLOAD for DV, S3/GCS bucket for validation.
parent_skill: data-validation-setup
license: Proprietary. See License-Skills for complete terms
---

# L3 pushdown extract setup

When **row validation (L3)** is on, the orchestrator always runs signature extract then in-warehouse pushdown compare for **non-Snowflake** sources. How signatures leave the source is `validationConfiguration.extraction.strategy` (same values as data migration).

The **only deciding factor** for the user is whether they can use **object storage** that both the source (or worker) and Snowflake can reach. When they have a bucket, signatures land in object storage and Snowflake compares them in-warehouse. When they do not, the same row checks run through the worker.

**When you ask:** say that **using a bucket is faster**. **Do not** say that not using a bucket is slow (no “slower”, “slow path”, “fallback”, or “without a bucket it is worse”). Option 3 stays neutral: continue without a bucket; same checks; they can add one later.

**Never say strategy enum names to the user** (`regular`, `unload`, `cloud_direct`, and the rest). Say **bucket / object storage** vs **through the worker**. Put enum values only in YAML/TOML.

Load [../references/l3-pushdown-extraction.md](../references/l3-pushdown-extraction.md) for platform → strategy mapping, stage DDL, and TOML keys.

## Skip these cases

Do **not** ask about buckets or stages when any of the following is true:

- Source platform is **Snowflake**. Sf→Sf L3 already runs in-warehouse (row gate + fold). No DEW extract, no `extraction.strategy`, no external stage.
- `rowValidation` / `row_validation` is **off**.

## Reuse data migration landing (skip the question)

Before Step 1, look for an object-store extract already used for **data migration** in this project:

- Workflow YAML under `artifacts/data_migration/` (or equivalent): `extraction.strategy` in `unload` | `write_nos` | `dbms_cloud` | `cet_as` | `export_data` | `cloud_direct` **and** a non-empty `extraction.externalStage`
- And/or `plugin.yml` `data_migration_extraction_strategy` with the same object-store values, plus that stage on the DM workflow
- Worker TOML (`.scai/config/dew_configuration.toml`) already has matching extras (`unload_*`, `export_data_gcs_*`, `write_nos_*`, `dbms_cloud_*`, `cet_as_*`, or `[connections.target.s3|gcs|blob]`), **or** those dump keys are on the named connection in `~/.snowflake/scai/connections/<engine>.toml`

If that is present, **do not ask** the Step 1 question. Copy `strategy` + `externalStage` into the validation workflow (`validationConfiguration.extraction`), keep the existing worker TOML, skip stage creation, and go to Step 4.

Tell the user in one sentence that row-level validation will use the **same object storage** as data migration (name the stage, not the strategy enum). Do not offer Yes / Not yet / No.

If DM is worker-only extract (`regular` / `tpt` / unset), or object-store strategy is set **without** `externalStage`, fall through to Step 1.

## Step 1 — Ask about object storage

Say that **using a bucket is faster**. Do not say the inverse.

Ask verbatim (swap the storage line for the dialect from the mapping table):

> Using a bucket for row-level validation is **faster**. Snowflake reads signatures from object storage (an **external stage**), so more of the compare happens in Snowflake.
>
> We can also run the same row-level checks without a bucket, and you can add one later.
>
> Typical storage for your source: **S3 for Redshift, GCS for BigQuery, S3 / GCS / Azure Blob for PostgreSQL**.
>
> Do you have a bucket (or container) we can use?
> 1. **Yes** — I have one
> 2. **Not yet** — pause. I'll get bucket access, then we'll continue
> 3. **No** — continue without a bucket

Handle the answer:

- **Yes** → Step 2.
- **Not yet** → **stop and wait**. Do not switch the workflow to the worker-only extract, do not call `validate_data(mode="run")`, and do not start L3. Say you will wait until they have a bucket (name, cloud, and that Snowflake can read it). When they return, resume at Step 2. Offer a short list of what they need (bucket/container + prefix, writer identity that can put objects, a role that can create a Snowflake storage integration). Do not invent a bucket while waiting.
- **No** (explicitly skip the wait) → leave `extraction.strategy` unset (worker-only extract). L3 still runs the same checks. Tell them they can add a bucket later and rerun this skill. Do not invent a bucket. Do not name the strategy. Do not call this path slow.

## Step 2 — Collect landing details

1. Cloud: S3, GCS, or Azure Blob (infer from dialect default; ask only if ambiguous).
2. Bucket / container name, optional prefix, region.
3. Whether a **Snowflake external stage** already points at that prefix.

If they have a bucket but **not** the native export path (for example Redshift with only a GCS bucket, not S3), use **`cloud_direct`** instead of the native strategy (`unload` / `export_data` / …). Do not force Redshift UNLOAD onto GCS.

## Step 3 — External stage

If a stage already exists: `SHOW STAGES` / `DESC STAGE` and confirm `URL` covers the prefix the extract will write. Use its three-part name as `externalStage`.

If it does **not** exist, help create:

1. Storage integration (ACCOUNTADMIN or equivalent) whose `STORAGE_ALLOWED_LOCATIONS` covers the prefix.
2. `DESC STORAGE INTEGRATION` → grant the Snowflake principal **read/list** on the bucket (IAM / GCS IAM / Azure).
3. `CREATE STAGE … URL = '<same prefix>' STORAGE_INTEGRATION = <int> FILE_FORMAT = (TYPE = PARQUET)`.
4. `GRANT USAGE` on the integration and `READ` (or `USAGE`) on the stage to the orchestrator role.

SQL templates: [l3-pushdown-extraction.md](../references/l3-pushdown-extraction.md#snowflake-external-stage-sql).

Do not paste fake account IDs, ARNs, or service-account emails. Leave placeholders and have the user fill them, or run `DESC` and use the real values.

The source-side writer (Redshift IAM role, BigQuery SA, Oracle `DBMS_CLOUD` credential, Teradata WRITE_NOS auth, CETAS credential, or worker AWS/GCP/Azure identity for `cloud_direct`) needs **write** on the same prefix. Snowflake only needs **read**.

## Step 4 — Patch configs (hard gate before `validate_data(mode="run")`)

**Workflow YAML** (`artifacts/data_validation/workflows/<hash>.yaml`):

```yaml
validationConfiguration:
  extraction:
    strategy: <unload | export_data | write_nos | dbms_cloud | cet_as | cloud_direct>
    externalStage: MY_DB.MY_SCHEMA.MY_EXT_STAGE
```

Object-store strategies **fail closed** without `externalStage`. Do not run until both keys are set.

**Worker TOML:** dump keys for native export (`unload_*`, `export_data_*`, `write_nos_*`, `dbms_cloud_*`, `cet_as_*`) must live on the **named scai connection** (`~/.snowflake/scai/connections/<engine>.toml`) **or** on an **inlined** `[connections.source.<engine>]` in `.scai/config/dew_configuration.toml`. Do not add them next to `connection_name` — worker start hydrates that name and drops the extras. `[connections.target.s3|gcs|blob]` for `cloud_direct` stays in the project worker file. Restart the worker after TOML changes (`data_infrastructure` / `scai data worker start`).

Show the user the YAML and TOML diffs. For a reused data-migration landing, only the validation YAML should change; do not restart the worker unless you edited TOML.

## Checklist

```
- [ ] Snowflake source? skipped (in-warehouse L3)
- [ ] Reused DM object storage when present (skipped the bucket question)
- [ ] Asked about object-storage access (said using a bucket is faster; did not say going without is slow)
- [ ] Not yet → waited; did not run L3 or silently pick the worker-only extract
- [ ] Explicit no → worker-only extract (no fake stage); did not say strategy names to the user
- [ ] Yes → native strategy if the bucket matches the dialect; else cloud_direct
- [ ] Stage URL and worker/source writer prefix are the same
- [ ] validationConfiguration.extraction.strategy + externalStage written
- [ ] Dump keys on snowct connection or inlined worker source section (not beside `connection_name`); worker restarted if TOML changed
```

Return control to the caller (`data-validation-setup` or `validate_tables`).
