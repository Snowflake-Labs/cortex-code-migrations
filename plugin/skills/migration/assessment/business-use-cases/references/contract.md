# Contract

Mirrors `BusinessUseCaseContract` and `WaveGraphEnrichmentFile` in SCAI
(`Snowflake.SnowConvert.Assessment`). SCAI is the source of truth: when this
page and an `ASM0050` / `ASM0049` message disagree, follow the message.

## `business-use-cases.json`

`<project_dir>/artifacts/assessment/waves/business-use-cases.json`, camelCase:

```json
{
  "schemaVersion": 1,
  "useCases": [
    {
      "id": "store-replenishment",
      "name": "Store Replenishment",
      "purpose": "Store buyers check every morning which stores are below their reorder point for each product, and raise the day's purchase orders from that list before deliveries are scheduled.",
      "status": "confirmed",
      "confidence": "high",
      "origin": "seed",
      "seedIds": ["<code unit id>"],
      "memberIds": [],
      "whyFound": "…",
      "howFound": "…",
      "enablesOnSnowflake": "…",
      "evidence": ["…"],
      "openQuestions": ["Does anyone still read the weekly variant of the report?"]
    }
  ]
}
```

| Field | Rule |
|---|---|
| `schemaVersion` | `1` |
| `useCases` | At most 100 |
| `id` | Lowercase hyphenated slug, 1–64 characters, unique in the file |
| `name` | 1–80 characters |
| `purpose` | 120–320 characters (2–3 sentences) |
| `whyFound`, `howFound`, `enablesOnSnowflake` | 240–700 characters each (3–5 sentences) |
| `status` | `confirmed` (backed by evidence) or `proposed` (a person still needs to confirm it) |
| `confidence` | `high`, `medium` or `low` |
| `origin` | `seed` (from a candidate), `anchor` (found in the coverage pass) or `onDemand` (someone asked for it) |
| `seedIds` | 1–50 code unit ids: the ends of the flow |
| `memberIds` | 0–500 code unit ids the graph does not connect to the seeds |
| `evidence` | 1–5 items of 1–240 characters |
| `openQuestions` | 1–5 items of 1–240 characters: what could still be missing or needs confirming (shown as Considerations) |

`purpose`, `whyFound`, `howFound` and `enablesOnSnowflake` are an analysis of
that use case, written from its closure, metrics, conversion and source.
`whyFound` and `enablesOnSnowflake` must not match another use case once the
name is swapped. [adjudication.md](adjudication.md) says how to write them.

Every `seedIds` and `memberIds` entry must be a code unit id in the registry.
Validation reports every problem in one pass, as `useCases[i].field`, so one
fix round can clear them all.

Only use cases go in the file: a candidate that is not one is left out.

`waves use-cases` grows each case into its wave — seeds, members,
what they depend on, and loaders of the tables they read — and writes the rated
`use-cases.json`. A case whose wave deploys nothing (only reports, or only
missing objects) is listed under `undeployable` with the reason.

## `graph-enrichment.json` (optional)

`<project_dir>/artifacts/assessment/waves/graph-enrichment.json`. Write it only
for dependencies you can show and the registry lacks — typically the tables an
ETL package or script writes when conversion recorded none.

```json
{
  "schemaVersion": 1,
  "edges": [
    {
      "fromId": "<package id>",
      "toId": "<table id>",
      "relationTypes": ["INSERT"],
      "evidence": "LoadStock.dtsx, data flow 'Write daily stock' → OLE DB destination MART.store_stock_daily"
    }
  ]
}
```

- `fromId` depends on `toId`; both are existing code unit ids.
- `relationTypes` spell the verb as conversion does: `INSERT`, `UPDATE`,
  `DELETE`, `MERGE` load rows; `SELECT - FROM` reads; `EXECUTE` calls.
- `evidence` names the file and the component or line.

Every waves command reads this file, so an invalid one fails them all with
`ASM0049`. Fix or delete it, then re-run.

## Rated output the parent reads

`use-cases.json` → `useCases[]` in rank order, each with `rank`,
`recommended` (rank 1), `seeds`, `metrics` (`objectCount`, `sqlObjectCount`,
`etlCount`, `scriptCount`, `biCount`, `schemaCount`, `databaseCount`,
`loaderCount`, `missingCount`, `typeCounts`) and `conversion` (`clean`,
`requiresAttention`, `notConverted`, `ewiCount`).

`wave-plan.json` → `waves[]`, each with `waveNumber`, `seed`
(`kind`: `useCase`, `object` or `pending`; `id`; `name`), `objectCount`,
`rankCount`, `sharedObjectCount` and `ranks[]` (rank 1 deploys first). Waves
are independent: each deploys every object its use case needs, and
`sharedObjectCount` says how many of them other waves deploy too. Objects no
use case includes follow in `pending` waves ("Wave 1", "Wave 2"…) of up to
`--wave-size` objects, related objects together; `pendingObjectCount` is how
many of a pending wave's objects are its own, and `summary` gives
`pendingObjectCount` and `pendingWaveCount`. Never present a pending wave as a
business use case.

## HTML report

`scai assessment report` puts a Planning section in the sidebar, between Discovery
and Code/ETL Conversion, the same place it has in the assessment report in the
app. It reads `use-cases.json` (and, when they sit beside it, `wave-plan.json`
and `use-case-effort.json`) into that section: each use case's purpose, counts,
what it enables, considerations, and its effort hours, plus a readiness list of
the pending objects. It says both are ready to review in the app. Lineage and
the deployment plan are only in the app, so the HTML report does not link to
them. Pending objects are never presented as a business use case.
