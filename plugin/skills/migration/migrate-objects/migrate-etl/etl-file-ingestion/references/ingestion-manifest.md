# Ingestion Manifest Reference

The conversion writes one manifest per run at `artifacts/ingestion/<conversion-run>/ingestion-manifest.json`. It is the contract between the converted SQL and whatever moves files: the same binding that generated the `COPY` statements generated this file, so the manifest is authoritative about where data must land.

This is conversion output. Read it; never hand-author or hand-edit it.

## Document shape

```json
{
  "schemaVersion": "1.0",
  "stage": { "name": "public.landing_stage" },
  "sources": [ { "…": "one entry per discovered flat-file source" } ]
}
```

`stage.name` is fixed for the project — every converted flat-file read binds to that one stage, and per-source separation happens through prefixes underneath it.

## Per-source fields

| Field | Meaning |
|---|---|
| `id` | Stable source identity (e.g. `ssis:package-cm:ca1e030b2073`). Use it when reporting per-source status. |
| `technology` | Source ETL platform token as the engine records it (`ssis`, …). Compare it verbatim; do not assume a spelling for other platforms. |
| `identityScope` | What the source is keyed on (e.g. `ssisPackageConnectionManager`). |
| `packageName` / `connectionName` | Human-facing names so the user can find it in their own tooling. |
| `boundPrefix` | The prefix the converter bound this source to, relative to the stage. |
| `originalLocations[]` | Where the files live today, as recorded in the source ETL. Basis for the path recommendation. |
| `selection.kind` | `exact` (one named file), a pattern/glob for multi-file sources, or `runtimePath` when the original location is a variable. |
| `selection.fileName` | For `exact`, the file name the `COPY` names. |
| `selection.recurse` | Whether the original source walked subdirectories. |
| `destinationKeyPolicy` | How the landed key is derived. `basename` means the file name alone, no directory structure. |
| `sourceParameters` | Names the source side of the generated Openflow flow: `endpointUrlParameter`, `bucketParameter`, `regionParameter` are parameter-context keys; `credentialsServiceName` is a controller service; `requiresDcp` flags a private-network bucket. The flow also carries `SNOWFLAKE_*` parameters and a Snowflake connection service that this field says nothing about — fill those from the deploy connection. |
| `consumers[].id` | The converted data-flow component that reads this file. |
| `consumers[].fileFormatName` | The deployed `FILE FORMAT` the `COPY` parses with. |
| `resolutionState` | `resolved` means `originalLocations` is a concrete path the uploader can read. `requiresMapping` means the original location is a runtime variable; converted SQL still binds to `mapping.expectedStagePrefix` plus that variable (`runtimePathBinding`). The operator sets the variable to the landed object name and uploads the file to that prefix. Manifest-driven landing skips these sources. |
| `idempotency.mode` | Change detection for re-transfers, e.g. `etagThenSizeAndModifiedTime`. |
| `idempotency.transferWhenChanged` | When true, rewriting a key with new content re-transfers; identical content does not. |
| `mapping.expectedBucketPrefix` | Object **key** prefix (rather than a URI) where upstream writes this source, inside whatever bucket the flow's `SOURCE_BUCKET` parameter names. The list processor (`ListS3`, `ListAzureBlobStorage_v12`, or `ListGCSBucket`) watches this prefix or an enclosing package-level one and preserves each object's key into the stage. |
| `mapping.expectedBucketObjectPath` | For exact sources, the specific object key. |
| `mapping.expectedStagePrefix` | Stage folder the converted SQL reads from. Use verbatim in `PUT`. |
| `mapping.expectedStageObjectPath` | For exact sources, the precise object the `COPY` names. Must match character for character, uncompressed. |

Some `1.0` manifests spell the bucket fields `expectedS3Prefix` / `expectedS3ObjectPath` rather than `expectedBucket*`; treat the two spellings as the same field and accept whichever is present. Drive the landing plan from the stage fields and use the bucket fields only as Openflow input. `expectedStagePrefix` is there for every mapped source; the `*ObjectPath` fields accompany exact selections, so read the destination for a glob source off the prefix.

## Worked example

An SSIS package reading one CSV from a Windows path. Abridged to the fields the landing plan uses — a real entry also carries `identityScope`, `boundPrefix`, `sourceParameters`, `idempotency`, and the bucket mapping fields:

```json
{
  "id": "ssis:package-cm:ca1e030b2073",
  "technology": "ssis",
  "packageName": "FfEmployeesCsvLand",
  "connectionName": "FF_CM_EmployeesCsv",
  "originalLocations": ["C:\\poc\\data\\employees.csv"],
  "selection": { "kind": "exact", "fileName": "employees.csv", "recurse": false },
  "destinationKeyPolicy": "basename",
  "consumers": [
    {
      "id": "FfEmployeesCsvLand.DFT_LandEmployeesCsv_FF_SRC_Employees",
      "fileFormatName": "FfEmployeesCsvLand_DFT_LandEmployeesCsv_FF_SRC_Employees"
    }
  ],
  "resolutionState": "resolved",
  "mapping": {
    "expectedStagePrefix": "@public.landing_stage/ssis/FfEmployeesCsvLand/FF_CM_EmployeesCsv/",
    "expectedStageObjectPath": "@public.landing_stage/ssis/FfEmployeesCsvLand/FF_CM_EmployeesCsv/employees.csv"
  }
}
```

The deployed package reads precisely that object through precisely that file format:

```sql
COPY INTO dbo.EMPLOYEES_STG (EmpId, FullName, Dept, UpdatedAt)
FROM (
   SELECT $1 :: FLOAT, $2 :: VARCHAR(100), $3 :: VARCHAR(100), $4 :: VARCHAR(40)
   FROM @public.landing_stage/ssis/FfEmployeesCsvLand/FF_CM_EmployeesCsv/employees.csv
        (FILE_FORMAT => 'FfEmployeesCsvLand_DFT_LandEmployeesCsv_FF_SRC_Employees')
);
```

Two things follow from that statement, and they are the whole reason the invariants exist:

1. The path is **exact**, so the landed object name and directory have to match it character for character. A compressed upload (`employees.csv.gz`) or an added date folder lands somewhere the statement never reads.
2. The parse is **delegated to the named file format**, so the landed bytes must match its delimiter, header, enclosure, and encoding.

## Handoff table for an existing ingestion tool

When they already own a file mover, fill one row per source from the manifest and hand it over:

| Source id | Original location | Destination (stage) | File format(s) | Notes |
|---|---|---|---|---|
| `ssis:package-cm:ca1e030b2073` | `C:\poc\data\employees.csv` | `@public.landing_stage/ssis/FfEmployeesCsvLand/FF_CM_EmployeesCsv/employees.csv` | `FfEmployeesCsvLand_DFT_LandEmployeesCsv_FF_SRC_Employees` | Exact name, uncompressed, overwrite in place |

State the two invariants alongside the table, because a generic mover will otherwise compress or timestamp the key by default.
