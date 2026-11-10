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
| `origin` | `seed` (from a candidate), `anchor` (found in the coverage pass or a `waves cluster` bin) or `onDemand` (someone asked for it) |
| `seedIds` | 1–50 code unit ids: the ends of the flow |
| `memberIds` | 0–2000 code unit ids the graph does not connect to the seeds: other roots of the same outcome |
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

### The closure rule and the ceiling

A wave pulls in what its seeds and members **depend on**, never what depends on
them. So every **root** — an object nothing else uses, whether the end of a
flow or an isolated object that uses nothing either — reaches a use case wave
only when some use case lists it in `seedIds` or `memberIds`. Everything else is
reached through a root. The file therefore holds at most
100 × (50 + 2000) = 205,000 root slots; `waves coverage` reports the roots, how
many are plumbing or data only, and whether the business ones fit
(`ceiling.feasible`).

## `coverage.json` and `clusters.json` (CLI-written)

`scai assessment waves coverage [--use-cases <file>]` writes `coverage.json`:

- `workload` — `objects` (deployable, schemas and databases left out),
  `roots`, `flowEnds`, `isolatedRoots`, `plumbingRoots` and
  `plumbingRootsByReason` (`temporary`, `testing`, `deprecated`, `duplicate`,
  `olderVersion`, `backup`, `platform`, `holding`), `meaningfulRoots`,
  `rootsByRole`, `businessRoots`, `dataOnlyRoots`, `reachableObjects`,
  `businessReachableObjects`, `resolvedReferences`, `ceiling` and `mode`
  (`large` above 3,000 roots or 10,000 objects).
- `draft` — for `business-use-cases.json`, or the file given: `planned`,
  `pct`, `pending`, `pendingByReason` (plumbing reasons, `plumbingOnly`,
  `dataOnly`, `isolated`, `uncoveredFlow`), `pendingPlumbingShare`,
  `uncoveredMeaningfulRoots`, `topUncoveredRoots`, `unknownIds`,
  `contractProblems` and `meetsTarget`. The draft is read for its ids only, so
  placeholder text measures a structural dry run.

Each meaningful root has a role, decided from lineage alone:

| Role | What it is |
|---|---|
| `process` | An ETL workflow or mapping, a script, a procedure, macro or function |
| `fed` | A table or view whose data, reached through views, a process in the project writes or reads; it belongs with that process (an ETL folder, or a routine) |
| `consumer` | A report, or a view joining two or more tables or views, that no process in the project touches. Objects a great many views read (row-level security and calendar tables) do not count as a second input |
| `dataOnly` | A table no process loads or reads, or a view that only passes one such table through, with any number of column functions. Data to migrate, never a use case |

`businessRoots` are the roots that are not `dataOnly`; `uncoveredMeaningfulRoots`
and `topUncoveredRoots` count only those. `resolvedReferences` counts pipeline
references to a table name with no schema (an Informatica target, say) that
SCAI sent to the one table or view of that name, or the one table of that name
outside a sandbox; any other unqualified reference stays missing.

`meetsTarget` is true when `pct` ≥ 0.9, or when at least 0.9 of what stays
pending is plumbing or data only (`pendingPlumbingShare`).

`scai assessment waves cluster [--max-roots 550] [--max-cases 100] [--use-cases <file>]`
writes `clusters.json`: a `summary` (`meaningfulRoots`, `businessRoots`,
`dataOnlyRoots`, `alreadyCovered`, `binned`, `unbinned`, `binCount`,
`maxRootsPerBin`, `binSizeRaised`, `projected` coverage), `bins[]`, `plumbing`
(roots by reason, samples) and `dataOnly` (`roots`, `objects`, `bySchema`,
`samples`): what no bin holds because no code touches it. Only business roots
are binned. Each bin has `id` (`bin-001`…), `label`, `anchor` (`process`: a
workflow folder or routine and what it feeds; `consumer`: joining views or
reports over data no process in the project loads), `mixed`, `rootCount`,
`isolatedRoots`, `sandboxShare`, `suggestedStatus`, `suggestedConfidence`,
`seedIds` (≤ 50, ready to copy), `memberIds`, `newObjects`, `metrics`,
`conversion` and `facts` (`subjects`, `schemas`, `etlFolders`, `workflows`,
`writers`, `mainTables`, `sampleSeeds`, `topMissing`, `externalSources` — the
schemas or connections, such as `Flat_File` or a source system, of what the
processes read or write outside the project — `loadedTables` and
`unloadedTables`). Process bins come first. With `--use-cases`, roots that file
already covers are left out and its use cases count against `--max-cases`.

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
`etlCount`, `scriptCount`, `macroCount`, `bteqCount`, `biCount`, `schemaCount`, `databaseCount`,
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

`scai assessment report` puts a Wave Planning section (Preview) in the sidebar, between Discovery
and Code/ETL Conversion, the same place it has in the assessment report in the
app. It reads `use-cases.json` (and, when they sit beside it, `wave-plan.json`
and `use-case-effort.json`) into that section: each use case's purpose, counts,
what it enables, considerations, and its effort hours, plus a readiness list of
the pending objects. It says both are ready to review in the app. Lineage and
the deployment plan are only in the app, so the HTML report does not link to
them. Pending objects are never presented as a business use case.
