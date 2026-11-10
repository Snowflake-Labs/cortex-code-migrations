# Adjudicating candidates

A candidate is a hypothesis: "these seeds and everything they need serve one
business outcome." Its `signals` say why SCAI thinks so. Your job is to check
the hypothesis against the graph and, when needed, the source.

## Reading the signals

| Signal | Weight | What it suggests | Check |
|---|---|---|---|
| `consumer` | +3 | A report or BI asset reads the flow | Which report, and what it shows |
| `businessName` | +2 | A seed or written table carries a business word (sales, invoice, claim, stock…) | Whether the word names the outcome or just a column |
| `presentationLayer` | +2 | It lands in a reporting, mart or presentation schema | Who reads that schema |
| `crossSchemaFlow` | +2 | Data moves from one schema to another | Source system to target layer is a pipeline |
| `landsData` | +1 | It writes tables | What the tables hold |
| `relatedSeeds` | +1 | Several seeds were grouped | That they really serve one outcome |
| `cleanConversion` | +1 | Every member converted cleanly | Nothing to check; it eases wave 1 |
| `missingObjects` | −1 | It needs objects the project does not hold | `closure` → `missing`; an open question |

The score orders the list; it does not decide. A score-2 candidate that feeds
the finance close is a use case; a score-6 candidate that only shuffles audit
rows is not.

## What can be a use case

A use case needs a **process** — a workflow, mapping, script, procedure or
macro that loads or computes data — or a **consumer**: a report, or a view that
joins data into something new. Its wave then carries the tables the process
writes and the views that publish them. Tables with only their access views
(`SELECT * FROM` one table, row-level security over one table, a view that
validates columns of one table) have neither: nothing in the project produces
them and nothing turns them into an outcome. That is **data only** (see
`dataOnly` in `clusters.json` and `pendingByReason.dataOnly`), and it never
becomes a use case, however many objects it holds or whatever its names say.
Report it instead: which areas it sits in, and that its loaders were not
delivered.

A consumer with no process (joining views over data no code loads) is a
`proposed` use case at best: the reporting layer is real, but how its data
arrives is not in the project. Ask for it in `openQuestions`.

## Decide

**Confirm** (`status: confirmed`) when the evidence shows an outcome someone
uses: a report, a mart, an export, a decision table another process reads.

**Propose** (`status: proposed`) when it is plausible but rests on names alone,
or a key input is missing. Put the doubt in `openQuestions`.

**Merge** candidates when they serve the same outcome: one feeds the other,
they write the same mart tables, or they are steps of one process
(`load-…`, `transform-…`, `publish-…`). A merged use case lists every seed in
`seedIds`. SCAI merges only by shared objects and ETL name families, never by
SQL naming conventions — a shared `Vw*` prefix proves nothing, but a shared
outcome does. Use `query closure` with every seed's `--id` to see the merged
wave before you commit to it.

**Drop** plumbing that serves no outcome on its own: logging, auditing, error
capture, purge and archive jobs, metadata loaders, utility functions. Leave it
out of the file entirely — do not record it, and do not mention it in the
summary or the narrative. Its objects still migrate in the closing wave.

**Add members** with `memberIds` only for objects the graph does not connect
to the seeds but the outcome needs (a lookup table read through dynamic SQL,
a script called by a scheduler), and for the outcome's other roots once the 50
seeds are used: a wave never pulls in what depends on its seeds, so a root no
use case lists stays pending. Every member must come from a query result or
`clusters.json`.

## Name it

- `name`: the outcome in business words, at most 80 characters —
  "Store Replenishment", "Daily and Weekly Booking Snapshots". A person who
  works with the data should recognize it. Never an object name, a schema, or
  a subject token. `BKG data (LUV_ALL)`, `SC / WEIGHT data (LDB_SBOX_ENG)` and
  `AIR data (LJV_MAIN) 2` are not names: the token is a hint, and a second bin
  of the same token is a different outcome, named for what sets it apart
  (approval stages, not "AIR data 2").
- `id`: a lowercase hyphenated slug of that name — `store-replenishment`.
  Never `bin-001` or `bin-001-air`. Stable across runs: reuse the id an earlier
  `business-use-cases.json` gave the same outcome.

## Write the narrative

The Planning page shows `purpose` under the title and four cards: **Why
migrate this**, **How it was found**, **What it enables on Snowflake** and
**Considerations** (from `openQuestions`). A migration architect reads them to decide what to migrate
first, so each one must say something the name does not. Write process
language that can be read aloud; object names belong in `evidence`.

Compact, not thin: no filler or repetition across fields, but enough that a
reader who never saw the code understands the outcome.

| Field | Length | Covers |
|---|---|---|
| `purpose` | 2–3 sentences, 120–320 characters | Who uses it, what they decide or produce with it, and how often |
| `whyFound` | 3–5 sentences, 240–700 characters | Why this outcome is worth migrating on its own: who is hurt if it is late or wrong, what else depends on it, and what its own conversion counts say |
| `howFound` | 3–5 sentences, 240–700 characters | The flow from sources through processing to where it lands and who reads it, naming source systems and layers in business terms, and its schedule when known. The card is titled "How it was found"; that means how the outcome is produced, never how you found the bin |
| `enablesOnSnowflake` | 3–5 sentences, 240–700 characters | What this flow's consumers keep, what changes for this flow from its schedule or a step the graph shows, and which of its own objects can be retired |
| `evidence` | 1–5 checkable facts | Object-level proof from the waves tools or source files, at least one citing a source file you read (`source/…/wf_x.xml: loads FLT_LEGS from the OAG flat file`); kept for review, not shown on the page |
| `openQuestions` | 1–5 considerations | Shown in the **Considerations** card: what could still be missing or needs confirming — a consumer no report shows, a dependency the project lacks, a schedule nobody stated, a source outside the workload. The page adds missing objects, conversion work and use cases that must deploy first on its own, so add what only the analysis knows |

Say "not stated" in a field rather than invent an audience, a schedule or a
benefit the evidence does not show. Never mention waves, wave numbers or
confidence in any field: the page shows each use case on its own, and how
sure you are is internal.

Each use case gets its own analysis. Write `purpose`, `whyFound`, `howFound`
and `enablesOnSnowflake` from that use case's closure, metrics, conversion and
source. Then read the paragraph with the name removed. If it would still be
true of another use case, it is a template: rewrite it from this use case's
facts. Do not fill `whyFound` or `enablesOnSnowflake` by swapping the name into
a shared sentence. Name the output, the consumer, the schedule or the objects
that belong to this use case. Do not claim scale, a shared estate, or
retirement of objects this use case does not own.

**Example** (Store Replenishment):

- `purpose`: "Store buyers check every morning which stores are below their reorder
  point for each product, and raise the day's purchase orders from that list
  before deliveries are scheduled."
- `whyFound`: "It is the only flow behind the Store Stock report that buyers open
  every morning, so a late or wrong number reaches purchasing the same day.
  Nothing else in the workload depends on it, and eight of its nine objects
  converted cleanly, so it can move first and prove the migration on a process
  people use daily."
- `howFound`: "Point-of-sale sales and store reorder points are loaded every night
  from the store systems into staging. A stock procedure aggregates sales per
  store and product, compares them with the reorder points and writes the daily
  stock mart, which two reporting views expose to the Store Stock report."
- `enablesOnSnowflake`: "Buyers keep the same morning report while the nightly
  loads and the reorder logic run on Snowflake, so the report can be ready
  earlier and refreshed during the day. Once the report is repointed, the
  legacy stock schema and its two load jobs can be retired."
- `evidence`: "The Store Stock report reads RPT.vw_store_stock." /
  "usp_stock_kpis writes MART.store_stock_daily from STG.pos_sales."
- `openQuestions`: "Does anyone still read the weekly variant of the report?"

The example names this report, its nightly load and its two jobs. Another use
case needs its own facts, not these sentences with the nouns replaced.

## Confidence

| Confidence | When |
|---|---|
| `high` | A consumer or a clearly named outcome, and the wave needs no missing object |
| `medium` | A business-named flow without a known consumer, or a few missing inputs |
| `low` | Mostly inferred from names, or the purpose is not stated anywhere |

Rating ranks confirmed before proposed, then confidence, then fewest missing
objects, then smallest wave, then fewest EWIs. Rank 1 is the recommended
Wave 1, so a clean, small, well-evidenced use case should come first.

## What to avoid

- Describing the analysis instead of the outcome. This is not a narrative:

  > Clustered by scai assessment waves cluster as bin-092 (sc / weight + 77 more),
  > binning roots that share specific tables after layer prefixes were stripped.
  > A structural dry run measured the wave at 571 objects with 14 loaders across
  > 24 schemas.

  It names the tool, the bin and the method, and says nothing a reader can act
  on. The same objects, read properly, become a flow: which system lands the
  data, what the workflows do with it, which views publish it and who reads
  them. "SCAI grouped 395 roots", "sandbox share is 80%", "one wave of 571
  objects" and "Delivers the sc data that downstream users read" are the same
  failure in the other cards. Counts, schemas and conversion totals support a
  sentence; they are not the sentence.
- A name that is the bin label, a schema, or `TOKEN data (SCHEMA)`, including
  one numbered `2` because another bin shared the token.
- A use case made only of tables and the views over them. If no workflow,
  routine, report or joining view is in it, it is data only, not an outcome.
- Edge lists as narrative ("A reads B, B reads C").
- One use case per object when several objects serve one outcome.
- One giant use case that swallows the estate: when a closure holds most of
  the workload, split it by outcome, or keep the seeds that matter and let the
  closing wave take the rest.
- Temporary tables (`#…`) and staging copies as evidence of an outcome.
- The same `whyFound` or `enablesOnSnowflake` on two use cases, including a
  sentence that matches once the name is swapped.
