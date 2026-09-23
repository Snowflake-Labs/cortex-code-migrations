# The dependency manifest — schema v1

The one file this skill authors. `scai assessment powerbi enrich --manifest
<path>` reads it, validates it in full, and only then writes to the Code Unit
Registry — so a rejected manifest leaves the registry byte-for-byte unchanged.

Write it to `<project_dir>/artifacts/assessment/powerbi/manifest.json` unless the
parent's context block names a different path. It must resolve inside the
project, must be at most 16 MiB, and must not be `extraction.json` or
`enrichment.json` (the CLI rejects being handed its own output).

Keys are `camelCase`. Unknown keys are ignored; missing required ones are not.

## Schema

```
{
  "schemaVersion": 1,                        // int, must be exactly 1
  "extraction": {
    "artifactPath": "artifacts/assessment/powerbi/extraction.json",
                                             // must resolve to exactly this file
    "schemaVersion": 1                       // int, must be exactly 1
  },
  "reports": [                               // at least one entry
    {
      "reportKey":     "<copied verbatim from extraction.json>",
      "sourcePath":    "<copied verbatim; must start with source/BI/PowerBI/>",
      "archiveSha256": "<copied verbatim>",
      "name":          "<human-readable report name>",
      "dependencies": [                      // may be empty
        {
          // exactly ONE of these two:
          "existingCodeUnitId": "<an id from extraction.json's curCatalog>",
          "missingObject": {
            "objectType":    "<required, e.g. Table / View / Procedure>",
            "name":          "<required>",
            "platform":      "<optional, e.g. SqlServer>",
            "customKind":    "<optional>",
            "database":      "<optional>",
            "schema":        "<optional>",
            "canonicalName": "<optional, fully-qualified display name>"
          },

          "relationTypes": ["reads"],        // at least one of reads | references
          "evidence": [                      // optional, audit metadata only
            {
              "kind":       "<free text, e.g. partitionExpression>",
              "reference":  "<where you saw it, e.g. FactSales/FactSales-partition>",
              "expression": "<the fragment you read it from>"
            }
          ]
        }
      ]
    }
  ]
}
```

### Field notes

- **`reportKey` / `sourcePath` / `archiveSha256`** must all agree with the same
  report's entry in `extraction.json`, and that report's `status` must be
  `extracted`. A hash mismatch means the template changed since extraction —
  rerun `extract` and re-author, do not edit the hash.
- **`relationTypes`** is a closed set: `reads` and `references`, matched
  case-insensitively, normalized to lower case. There is no write verb — a Power
  BI report consumes data. An unrecognised verb rejects the manifest.
- **`objectType` and `platform`** are parsed by enum **name** only, so use the
  spellings `curCatalog` uses (`Table`, `View`, `Procedure`, `SqlServer`, …). A
  numeric value is rejected: a manifest must never address an enum member
  positionally.
- **An unset qualifier widens the identity, it does not narrow it.** `database`,
  `schema`, `platform`, and `customKind` are compared only when *both* sides
  populate them, so a stub that omits `schema` is reconcilable with a registry
  unit in every schema — and colliding with one is a rejection. Qualify a
  `missingObject` as fully as the evidence allows. When even a fully-qualified
  identity still collides, the dependency does not belong in the manifest at
  all: omit it and report it, as
  [dependency-analysis.md](dependency-analysis.md) describes.
- **`canonicalName`** is excluded from the stub's normalized identity, so two reports may
  spell it differently and still reconcile to one stub — but two *different* explicit
  spellings for the same stub are a real disagreement and are rejected. Omit it
  rather than guess.
- **`evidence`** is echoed into `enrichment.json` for a human to read and is
  **never** written into the registry. Quote the source; do not paraphrase it.

### What you must never write

There is no place in this schema for a code unit id you invented, a
`requiredBy`, or a `topologicalRank`. Report and stub GUIDs are assigned by the
registry; back-edges and ranks are derived there too. If you find yourself wanting a field for one
of those, the answer is that the CLI already owns it.

## Worked example

```json
{
  "schemaVersion": 1,
  "extraction": {
    "artifactPath": "artifacts/assessment/powerbi/extraction.json",
    "schemaVersion": 1
  },
  "reports": [
    {
      "reportKey": "Sales-9f2c1ab40e77",
      "sourcePath": "source/BI/PowerBI/Sales.pbit",
      "archiveSha256": "c305f93d833690de8fbcaa35158fef751b92a72c999984ec046fc0ddca0a8f27",
      "name": "Sales",
      "dependencies": [
        {
          "existingCodeUnitId": "3f1b2c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
          "relationTypes": ["reads"],
          "evidence": [
            {
              "kind": "partitionExpression",
              "reference": "FactSales/FactSales-partition",
              "expression": "Source{[Schema=\"dbo\",Item=\"FactSales\"]}[Data]"
            }
          ]
        },
        {
          "missingObject": {
            "objectType": "Table",
            "platform": "SqlServer",
            "database": "DW",
            "schema": "dbo",
            "name": "DIM_DATE",
            "canonicalName": "DW.dbo.DIM_DATE"
          },
          "relationTypes": ["reads"],
          "evidence": [
            {
              "kind": "partitionExpression",
              "reference": "DimDate/DimDate-partition",
              "expression": "Source{[Schema=\"dbo\",Item=\"DIM_DATE\"]}[Data]"
            }
          ]
        }
      ]
    },
    {
      "reportKey": "Ops-4d18ba2c9e30",
      "sourcePath": "source/BI/PowerBI/Ops.pbit",
      "archiveSha256": "d0c1ff9666015cf15bf5cb552bfc58071419ba5275b26ca94285026cde90756f",
      "name": "Operations",
      "dependencies": []
    }
  ]
}
```

## Rejections (`ASM0042`)

Validation runs to completion, so `enrichment.json` lists **every** problem at
once, each with a `reports[i].dependencies[j].field`-style location. Fix them all
in one pass.

| Rejected because | Fix |
|---|---|
| `schemaVersion` is not `1`, or `reports` is empty | correct the header |
| `extraction.artifactPath` is not the project's `extraction.json`, or `extraction.schemaVersion` is not `1` | copy the path from the table above |
| a `reportKey` is not in the extraction artifact, or did not extract successfully | drop it; only `extracted` reports belong here |
| `sourcePath` is rooted, contains `..`, or is not under `source/BI/PowerBI/` | copy it verbatim from the artifact |
| `archiveSha256` disagrees with the artifact | rerun `extract`, re-author |
| two `reports[]` entries resolve to one code unit id | one entry per template |
| a dependency names both or neither of `existingCodeUnitId` / `missingObject` | name exactly one |
| two dependencies of one report resolve to the same target | merge them |
| `relationTypes` is empty or holds anything but `reads` / `references` | use the closed set |
| `existingCodeUnitId` is absent from the registry, is the report itself, or is a Power BI report unit | dependencies must name database objects |
| `objectType` / `platform` is unknown, or is a number | use the `curCatalog` spelling |
| a `missingObject` normalizes onto exactly one existing registry unit | reference it with `existingCodeUnitId` instead |
| a `missingObject` matches two or more registry units | add the qualifiers the evidence supports and match again; if it is still ambiguous, omit the dependency and report it — never leave it vague to hedge |
| a derived stub id is already taken by a non-stub, or by a stub describing a different object | qualify the identity so it names the object you mean |
| two `missingObject`s **in this manifest** describe reconcilable identities but spell them differently — `DIM_DATE` + `schema: dbo` in one, `dbo.DIM_DATE` in another, or one qualifier simply left off | spell the object the same way in both, or qualify them so they genuinely name different objects. The error names both call sites |
| two dependencies share a stub but declare different `canonicalName`s | drop the canonical name, or agree on one |

The same-manifest duplicate is worth avoiding rather than fixing: pick one
spelling per object *before* you write anything, and reuse it everywhere that
object appears, across every report. Two spellings derive two ids, and two ids
would be two CUR units for one table, each holding half its back-edges — so
`enrich` rejects the manifest rather than write them. It has no basis for
choosing which spelling is the real one; you do.

## Idempotency

Rerunning the same manifest converges: the same reports and stubs are upserted,
the artifact is byte-identical apart from `generatedAtUtc` and the
created-vs-updated tallies. Removing a dependency from a report's entry rewrites
that report's forward edges and nothing else — a shared stub survives as long as
another report still names it.
