# `extraction.json` — what `scai assessment powerbi extract` gives you

Path: `<project_dir>/artifacts/assessment/powerbi/extraction.json`. Stable name,
overwritten every run. Schema version 1, `camelCase` keys. Every path it records
is **project-relative**.

## Shape

```json
{
  "schemaVersion": 1,
  "generatedAtUtc": "2026-09-10T17:04:11.2231840Z",
  "reports": [
    {
      "reportKey": "Sales-9f2c1ab40e77",
      "name": "Sales",
      "sourcePath": "source/BI/PowerBI/Sales.pbit",
      "archiveSha256": "c305f93d833690de8fbcaa35158fef751b92a72c999984ec046fc0ddca0a8f27",
      "status": "extracted",
      "errorCode": null,
      "errors": [],
      "warnings": [],
      "rawPath": "artifacts/assessment/powerbi/extracted/Sales-9f2c1ab40e77/raw",
      "normalizedPath": "artifacts/assessment/powerbi/extracted/Sales-9f2c1ab40e77/normalized",
      "members": [
        {
          "path": "DataModelSchema",
          "rawPath": "artifacts/assessment/powerbi/extracted/Sales-9f2c1ab40e77/raw/DataModelSchema",
          "normalizedPath": "artifacts/assessment/powerbi/extracted/Sales-9f2c1ab40e77/normalized/DataModelSchema.json",
          "normalizationError": null,
          "compressedBytes": 1841,
          "uncompressedBytes": 9210
        }
      ],
      "metadata": {
        "tables": [
          {
            "name": "FactSales",
            "columns": [{ "name": "OrderDate" }],
            "measures": [{ "name": "Total", "expression": "SUM(FactSales[Amount])" }],
            "partitions": [
              {
                "name": "FactSales-partition",
                "expression": "let\n  Source = Sql.Database(\"srv01\", \"DW\"),\n  dbo_FactSales = Source{[Schema=\"dbo\",Item=\"FactSales\"]}[Data]\nin\n  dbo_FactSales"
              }
            ]
          }
        ],
        "connectionHints": ["Database=DW", "Provider=System.Data.SqlClient", "Server=srv01"]
      }
    }
  ],
  "curCatalog": [
    {
      "id": "3f1b…",
      "kind": "DatabaseObject",
      "isMissing": false,
      "source": {
        "objectType": "Table",
        "name": "FactSales",
        "platform": "SqlServer",
        "customKind": null,
        "database": "DW",
        "schema": "dbo"
      }
    }
  ]
}
```

## `reports[].status`

| Value | Meaning |
|---|---|
| `extracted` | usable. Only these may appear in the manifest. |
| `error` | the archive was rejected, or a known JSON member could not be normalized. `errors[]` says why. |
| `unsupported` | a `.pbix`. Never parsed; the user must export a `.pbit`. |

A report can be `extracted` **and** carry `errors`/`warnings` — e.g. an
unreadable `Connections` member, or no valid `DataModelSchema` (in which case
`metadata.tables` is empty and the M expressions are simply not available).
Say so in your `summary`; do not treat it as a failure.

## `metadata`

- **`tables[].partitions[].expression`** — the Power Query (M) expression that
  loads the table. This is the primary evidence for a database dependency.
  Sorted by partition name; a multi-line M expression arrives with real
  newlines.
- **`tables[].measures[].expression`** — DAX. Measures compute over the model,
  not over the database, so a measure is **not** a database dependency.
- **`connectionHints[]`** — `Name=`, `Server=`, `Database=`, `DataSource=`,
  `Provider=`, and `Type=` values pulled from the model's `Connections` member
  and from the head of each M expression, sorted, at most 64 entries and 256
  characters each. Credential-bearing values are omitted at extraction time, so
  never look for a password here and never report one if you somehow find it.

## `curCatalog`

A snapshot of the registry taken at extraction time — every code unit with an
id, ordered by id. Match against this, not the registry on disk: it is the same
view the CLI validated against, so an id you take from here is one `enrich` will
accept.

`kind`, `objectType`, and `platform` are the registry's own enum spellings
(`DatabaseObject`, `Table`, `View`, `SqlServer`, …). Copy them verbatim into a
`missingObject` identity — `enrich` parses them by **name**, case-insensitively,
and rejects a number.

`isMissing: true` marks a unit the converted code referenced but never defined.
Such a unit is a perfectly good `existingCodeUnitId` target: it already exists,
so pointing at it is right, and minting a second stub for it is wrong.

## The extracted tree

```
artifacts/assessment/powerbi/extracted/<reportKey>/
├── raw/          every archive member, byte-for-byte
└── normalized/   readable UTF-8 JSON copies of DataModelSchema and
                  UnappliedChanges (each named "<member>.json")
```

`raw/` is customer content in whatever encoding the archive held —
`DataModelSchema` is usually UTF-16. Prefer `normalized/`. A member whose
`normalizedPath` is `null` and whose `normalizationError` is set was not valid
JSON; the raw bytes are still there but nothing parsed them.

Directories under `extracted/` are reconciled against the artifact on every run:
a report key that is no longer in `extraction.json` has its directory removed.
Never write anything into that tree — the next extraction will delete it.
