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
| `origin` | `seed` (from a candidate), `anchor` (found in the coverage pass or a `waves cluster` bin), `onDemand` (someone asked for it) or `aiAnalysis` (deduced from the code of objects no landing evidence ties to an outcome) |
| `missingEvidence` | Optional; required on `aiAnalysis`. Distinct kinds of `bi`, `scheduler`, `usage`, `loader`, `exit`: what would confirm the use case and the drop does not hold. The Planning page and the report show it on the use case |
| `seedIds` | 1–50 code unit ids: the ends of the flow |
| `memberIds` | Any number of code unit ids the graph does not connect to the seeds: other roots of the same outcome. Above 2000, `waves catalog` reports the use case as oversized |
| `evidence` | 1–5 items of 1–240 characters |
| `openQuestions` | 1–5 items of 1–240 characters: what could still be missing or needs confirming (shown as Considerations) |

`purpose`, `whyFound`, `howFound` and `enablesOnSnowflake` are an analysis of
that use case, written from its closure, metrics, conversion and source, for a
reader who does not know the code. The page shows `whyFound` and
`enablesOnSnowflake` as one **Why migrate this** card. `whyFound` and
`enablesOnSnowflake` must not match another use case once the
name is swapped. [adjudication.md](adjudication.md) says how to write them.

Every `seedIds` and `memberIds` entry must be a code unit id in the registry.
Validation reports every problem in one pass, as `useCases[i].field`, so one
fix round can clear them all.

Only use cases go in the file: a candidate that is not one is left out.

`waves use-cases` grows each case into its wave — seeds, members,
what they depend on, and loaders of the tables they read — and writes the rated
`use-cases.json`. A case whose wave deploys nothing (only reports, or only
missing objects) is listed under `undeployable` with the reason.

### The flow rule, the closure rule and the ceiling

A landing object's **flow** is what it reads, every object that writes a table
reached, and what those writers read, back to the sources; never what reads
it. A table with ten or more writers is a **shared sink** (run parameters,
registries, control and log tables): it stays in the flow, but its writers do
not join through it, unless it is the landing object itself.
`waves query flow --id` shows one flow, `anchors.json` gives each anchor's
`flowSize`, and `waves catalog` builds a use case from the union of its landing
objects' flows.

A wave pulls in what its seeds and members **depend on**, never what depends on
them, and the loaders of the tables they read, under the same shared-sink rule.
So every **root** — an object nothing else uses, whether the end of a
flow or an isolated object that uses nothing either — reaches a use case wave
only when some use case lists it in `seedIds` or `memberIds`. Everything else is
reached through a root. `waves cluster` bins hold at most 50 + 2000 roots, so
100 bins give 205,000 root slots; `waves coverage` reports the roots, how
many are plumbing or data only, and whether the business ones fit
(`ceiling.feasible`).

## `coverage.json` and `clusters.json` (CLI-written)

`scai assessment waves coverage [--use-cases <file>]` writes `coverage.json`:

- `workload` — `objects` (deployable, schemas and databases left out),
  `roots`, `flowEnds`, `isolatedRoots`, `plumbingRoots` and
  `plumbingRootsByReason` (`temporary`, `testing`, `deprecated`, `duplicate`,
  `olderVersion`, all from object exclusion), `meaningfulRoots`,
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
SCAI sent to the one table or view of that name, or the one table of that name;
any other unqualified reference stays missing.

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
`isolatedRoots`, `suggestedStatus`, `suggestedConfidence`,
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

## `anchors.json` (CLI-written)

`scai assessment waves anchors` writes it; never edit it. `summary.scan`
counts anchors found and skipped by shape and reason; `groups` holds one fact
sheet per anchor group, sorted by `key` (`report:`, `etl:`, `folder:`,
`schema:`, `unplaced`); `anchors` lists every anchor — every landing object —
with its `shape` (`report`, `exitJob`, `readerSink`, `writeOnlyTarget`),
`detections` (kind and `path:line` citation), `hints` and `flowSize`, the
deployable objects of its flow. A `writeOnlyTarget` is written and never read,
or read only through views that re-expose it and that nothing reads
(`publishedView` hint: the publishing layer for readers outside the drop). A
`readerSink` that no process writes is skipped as `dataOnly`. Other hints are
`technicalName`, `neverReadTable` and `sharedSink`. Hints never removed
anything.

## `catalog-draft.json`

You write it. Members are never listed: `waves catalog` gathers them.

```json
{
  "schemaVersion": 1,
  "useCases": [
    {
      "id": "partner-revenue-feeds",
      "name": "Partner Revenue Feeds",
      "purpose": "…",
      "groupKeys": ["folder:source/BTEQ/…/feeds"],
      "anchorIds": [],
      "whyFound": "…",
      "howFound": "…",
      "enablesOnSnowflake": "…",
      "evidence": ["source/BTEQ/…/feeds/<script>.bteq"],
      "openQuestions": ["…"]
    }
  ],
  "technicalGroups": [
    {"groupKey": "folder:source/…/housekeeping", "reason": "Purges and re-grants; no output leaves the system."}
  ]
}
```

| Field | Rule |
|---|---|
| `groupKeys` / `anchorIds` | At least one between them; every key and id copied from `anchors.json`. Prefer `anchorIds`, the landing objects of the outcome; a whole group only when all of its landing objects serve it |
| `origin` | Optional: `anchor` (the default) or `aiAnalysis`, which `catalog_draft.py merge` sets on what it takes from `other-objects-draft.json` |
| `missingEvidence` | Optional; required on `aiAnalysis`. As in `business-use-cases.json` |
| No landing object twice | An `aiAnalysis` use case may not hold a landing object that a lineage use case holds, through a group or by id; `merge` removes them and `waves catalog` rejects what is left |
| `technicalGroups[].groupKey` | A group in `anchors.json` that no use case uses |
| `technicalGroups[].reason` | Required; what the source shows |
| Narrative fields | The `business-use-cases.json` limits below; `waves catalog` checks them on the bridged file |

## `use-case-catalog.json` (CLI-written)

`scai assessment waves catalog` writes it, and the same use cases to
`business-use-cases.json`. Use cases are sorted by id — the catalog is a set
of buckets, not a plan — and may share members. `grade` is `evidenced` when an
anchor is a report or has an exit, `proposal` otherwise; a proposal's first
open question asks the customer to confirm it. `estate.counts` classifies
every deployable object no use case covers: `technicalGroup`, `copy`,
`plumbing`, `dataOnly`, `unknown`. In `business-use-cases.json`, `evidenced`
becomes `status: confirmed` and `proposal` becomes `status: proposed`; the
first 50 landing objects, exits and reports first, then tables nothing reads,
then reader sinks, become `seedIds`, and every other member is kept.
`summary.oversized` lists the use cases above `summary.oversizedAbove` (2000)
members: split them. `summary.aiAnalysis` counts the use cases found by AI
analysis; each catalog use case carries its `origin` and `missingEvidence`,
and `business-use-cases.json` and `use-cases.json` keep both.

## `other-objects-draft.json`

The other-objects search writes it:
`<project_dir>/artifacts/assessment/waves/other-objects-draft.json`, the
`catalog-draft.json` shape with `origin: aiAnalysis` and `missingEvidence` on
every use case, and no `technicalGroups`. `catalog_draft.py check-ai` reviews
it with the same narrative check as `business-use-cases.json`;
[other-objects.md](other-objects.md) says how to write it. No CLI command reads
it: `catalog_draft.py merge` folds it into `catalog-draft.json`.

## `assessment-context-ai.md`

The context pass writes `<project_dir>/artifacts/assessment/assessment-context-ai.md`,
markdown for the two searches to read ([context-pass.md](context-pass.md)). No
CLI command reads it, and it never changes a grade or a wave.

## `use-case-context.json`

You write it: `<project_dir>/artifacts/assessment/waves/use-case-context.json`,
camelCase. It records which optional inputs the customer provided and which use
cases they supported. The HTML report reads it from beside `use-cases.json`;
no CLI command reads it, so it never changes the catalog, a grade or a wave.
[context-review.md](context-review.md) says how to fill it.

```json
{
  "schemaVersion": 1,
  "inputs": [
    {
      "kind": "scheduler",
      "label": "Control-M job definitions",
      "status": "reviewed",
      "files": ["ctm-jobs.xml"],
      "entries": 412,
      "matched": 380,
      "finding": "380 of 412 jobs run workflows in this drop; 61 are held."
    },
    {"kind": "usage", "status": "notProvided"}
  ],
  "useCases": [
    {
      "id": "store-replenishment",
      "confirmedBy": ["scheduler"],
      "note": "Runs nightly at 02:00 (job RPL_NIGHTLY)."
    }
  ]
}
```

| Field | Rule |
|---|---|
| `schemaVersion` | `1` |
| `inputs[].kind` | `bi`, `scheduler`, `agentJobs` or `usage`; one entry per kind, only for the kinds that apply |
| `inputs[].status` | `reviewed`, `notProvided` or `unusable` |
| `inputs[].label` | Optional, 1–80 characters, for example "Control-M job definitions"; the report names the kind when it is absent |
| `inputs[].files` | Optional, 1–5 file names, never paths |
| `inputs[].entries` / `matched` | Optional counts: entries read, and how many of them the registry matched |
| `inputs[].finding` | Optional, 1–240 characters: what the input showed. Counts and names of jobs or objects only, never commands, credentials, host names or statement text |
| `useCases[].id` | A use case id from `use-case-catalog.json`; an unknown id is ignored |
| `useCases[].confirmedBy` | One or more of `bi`, `scheduler`, `agentJobs`, `usage` |
| `useCases[].note` | Optional, 1–240 characters |

A `notProvided` input needs no other field: the report supplies the text for what
providing each input adds, so do not write it. The report lists every input in
the file under "What these use cases are based on" and, on each use case,
a line built from its `confirmedBy` and `note`: "Confirmed by the scheduler
export. Runs nightly at 02:00 (job RPL_NIGHTLY)."

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
`pendingObjectCount`, `pendingWaveCount` and `pendingReasons` (the pending
objects by estate category, adding up to `pendingObjectCount`). Never present a
pending wave as a business use case.

## HTML report

`scai assessment report` puts a Wave Planning section (Preview) in the sidebar, between Discovery
and Code/ETL Conversion, the same place it has in the assessment report in the
app. It reads `use-cases.json` (and, when they sit beside it, `wave-plan.json`,
`use-case-effort.json` and `use-case-context.json`) into that section: each use
case's purpose, counts, what it enables, considerations, its effort hours and
the inputs that confirmed it, a panel of what the use cases were based on, and
an **Other objects** tab. That tab lists the waves that migrate the objects no
use case includes and explains why they are outside one, from
`wave-plan.json`'s `summary.pendingReasons` and the inputs
`use-case-context.json` marks not provided or unusable. It says both are ready
to review in the app. Lineage and the deployment plan are only in the app, so
the HTML report does not link to them. Other objects are never presented as a
business use case, nor as pending or failed: they migrate like the rest.
