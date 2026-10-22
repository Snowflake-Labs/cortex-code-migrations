# Object-store path restrictions

## External volume and unload stage

Iceberg storage here is a Snowflake external volume. Before `migrate_data(mode="run")`:

1. `DESC STAGE <extraction.externalStage>` and read `URL`. That is where the parquets are unloaded.
2. `DESC EXTERNAL VOLUME <icebergConfig.externalVolume>` and read `STORAGE_BASE_URL`.
3. The stage URL must be that base URL, or a path under it. Same bucket or container.

If the stage URL is outside the volume, `LIST` finds no files and the partition is marked complete with 0 rows.

`baseLocationPrefix` is the table path under that volume. It is not the unload path.

## Worker prefix

S3 and GCS `cloud_direct` use `bucket_name` plus an optional `prefix`. Azure uses `container_name`, an optional `prefix`, and a credential (`account_name` with `use_default_credential`, or `account_key` / `sas_token` with `account_name`, or `connection_string`).

The worker writes `task_results/workflows/...` under that location. The stage URL is the same bucket or container plus `prefix` when `prefix` is set. The orchestrator lists `@stage/` plus `task_results/workflows/...`.

Snowflake often shows GCS as `gcs://` while workers use `gs://`. Those name the same bucket.
