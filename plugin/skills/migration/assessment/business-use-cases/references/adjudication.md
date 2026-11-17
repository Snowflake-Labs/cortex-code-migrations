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
macro that loads or computes data — or a **consumer**: a report that reads the
data. Its wave then carries the tables the process writes and the views that
publish them. Tables with only their access views (`SELECT * FROM` one table,
row-level security over one table, a view that validates columns of one table)
have neither. A view that joins two tables nothing in the project loads is the
same: it is not an outcome just because it joins. That is **data only** (see
`dataOnly` in `clusters.json`, `pendingByReason.dataOnly`, and
`skippedByReason.dataOnly` on `anchors.json`), and it never becomes a use
case, however many objects it holds or whatever its names say. Report it
instead: which areas it sits in, and that its loaders were not delivered.

A report with no process in the drop is a `proposed` use case at best: the
reporting layer is real, but how its data arrives is not in the project. Ask
for it in `openQuestions`. A joining view without a report and without a
loader is not a proposal; leave it unplaced.

## Start from where the data lands

A use case is the outcome behind one or more **landing objects**: the reports,
exports, files and tables the data reaches last. Read them before you group
anything, and read them the way a person new to the warehouse would:

1. Which systems feed which pipelines, and what they write (`catalog_draft.py
   lineage`).
2. Which objects the data lands in (`catalog_draft.py landing`), and what each
   one's flow holds (`waves query flow --id`): the jobs that produce it, the
   tables they read, the sources those come from.
3. What the source says: the landing object's definition, the header comments
   of the jobs on its flow, the exits they cite.

Then group: landing objects whose flows share their main jobs and whose sources
describe one outcome are one use case. A landing object's folder or schema
does not decide where it goes. Analysis tables in a team sandbox belong with
the subject flow that feeds them, and one folder can hold the landing objects
of two outcomes. A flow that reaches most of the warehouse is the sign of a
wrong grouping, not of a big outcome.

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

The Planning page shows `purpose` under the title and three cards: **How it
was found**, **Why migrate this** (this also covers what people can do on
Snowflake) and **Considerations** (from `openQuestions`). The reader is a
person who opened the report, not an engineer who already knows the drop.
Write as if they know nothing: no dialect, no table, no schema, no job name,
unless the same sentence says what that thing is.

Compact, not thin: no filler or repetition across fields, but enough that a
reader who never saw the code understands the outcome.

### Read before you write

Answer these from the use case's own material before writing a word:

| Question | Where the answer is |
|---|---|
| What business process is this, and who runs it? | The anchor's source, report and job names, comments and file headers |
| What comes in, from which systems, and how often? | Loaders, source definitions, file and connection names, the schedule in a scheduler export or an Agent job |
| What does the code do with it, the business rules? | The main workflows and routines: matching, allocation, aggregation, pricing, status changes |
| What comes out, and who reads it? | Exits (exports, files), the views over its final tables, BI reports, query logs |
| What breaks if it is late or wrong? | Its consumers, other use cases that read its output, its cadence |
| What did the context confirm, and what is missing? | `use-case-context.json`: the inputs that confirmed it, the ones not provided |

When the material does not answer a question, the field says "not stated" and
the gap becomes a consideration. Do not fill it from the name.

| Field | Length | Covers |
|---|---|---|
| `purpose` | 2–3 sentences, 120–320 characters | What it is, what it does in the system and what it resolves for the business |
| `howFound` | 3–5 sentences, 240–700 characters | How this use case was identified, in the order a reader can follow: where data comes from, what happens to it, where it lands and who that landing is for |
| `whyFound` | 3–5 sentences, 240–700 characters | Why migrate it, and what people can do on Snowflake once it is there. Shown as one card |
| `enablesOnSnowflake` | 3–5 sentences, 240–700 characters | Written into the same **Why migrate this** card. Keep filling the field; the page concatenates it after `whyFound` |
| `evidence` | 1–5 checkable facts | Object-level proof from the waves tools or source files, at least one citing a source file you read (`source/…/wf_x.xml: loads FLT_LEGS from the OAG flat file`); kept for review, not shown on the page |
| `openQuestions` | 1–5 considerations | What only the analysis knows is missing or needs confirming for this use case |

### Purpose

Two or three sentences: **what it is** (the business process, named as its
owners would name it), **what it does in the system** (what it takes in, the
rule it applies, what it produces) and **what it resolves** (the decision or
obligation it serves, and for whom). `check` rejects a purpose of one sentence.

- Too vague: "Tracks dynamic package bookings, order lines, price elements and
  allocation of orders, so package sales can be reported and allocated." It
  lists tables and ends on verbs nobody can check: reported to whom, allocated
  to what, and what goes wrong without it?
- Better: "Revenue allocation for holidays sold as one package. Each night it
  splits every booking's price into flight, hotel and extras and assigns each
  part to the supplier and the channel that earned it, so finance can pay
  suppliers and report margin per channel."

The facts in that example are invented to show the shape. Yours come from the
use case's source and context.

### How it was found

Write this for someone who has never seen the code: do not assume the reader knows
what a mapping, a BTEQ script, a view or a schema is unless you say so. Follow
this order:

1. Where the data comes from, in business terms (the warehouse's customer
   records, nightly store sales, bookings from the reservations system).
2. What happens to it (it is checked, joined, priced, allocated).
3. Where all of this use case's data lands, and what that landing is for. If
   everything is written to a set of views, say they look like they can be
   consumed by a report or another system, because that is where this use case
   ends. If a file is produced, say which system that file is for.
4. What proves it is a use case: an export, a report, a scheduled job, or an
   input in `use-case-context.json`. Never how you found the bin.

Name a table, a schema, a view, a script or a job only when the sentence says
what it is. "Named outputs include CDS_AUDIT_LOG, CDS_Output" is not a
sentence a report reader can use. "The last step writes a customer-attribute
file named CDS_Output, which is the file the Audience Hub reads" is.

### Why migrate this

One card, two fields. `whyFound` is why this outcome is worth moving as a
unit: who is hurt if it is late or wrong, and what depends on it. Then
`enablesOnSnowflake` is what people can do on Snowflake once it is there, for
this use case's own outputs. The page shows them as one paragraph. Do not
repeat the purpose, and do not list code units.

| Its output | What to say |
|---|---|
| A BI report or dashboard | Which report keeps working, read from Snowflake, and what changes for its readers, such as a refresh during the day when the load allows it |
| Tables or views, no BI layer seen | Which results become queryable on Snowflake and for what decision. Say it plainly: No BI layer was provided, so who reads them is not known; add that to Considerations |
| A file or feed to another system | Which feed Snowflake now produces, for which system, and what that system keeps unchanged |
| A scheduled chain of jobs | The chain that runs on Snowflake, in the order the source shows, and which legacy jobs stop |
| Objects only this use case owns | What can be retired once its consumers are repointed |

Generic platform claims are true of any workload and `check` rejects them:
"single source of truth", "scalability", "seamless", "unlock", "data-driven",
"actionable insights", "modern data platform", "better performance".

### Considerations

`openQuestions` holds one to five items only the analysis knows for this use
case: a consumer no report shows, a source system outside the drop, a schedule
nobody stated, dynamic SQL whose targets are unknown, a step the converted code
cannot do, or the input in `use-case-context.json` that would confirm it. Each
item names its subject and says what to confirm, with whom. `check` rejects a
consideration repeated on another use case, except the proposal question
`waves catalog` adds itself. The page adds missing objects, conversion work and
use cases that must deploy first on its own.

### Every field

Say "not stated" in a field rather than invent an audience, a schedule or a
benefit the evidence does not show. Never mention waves, wave numbers or
confidence in any field: the page shows each use case on its own, and how
sure you are is internal.

Each use case gets its own analysis. Write `purpose`, `whyFound`, `howFound`
and `enablesOnSnowflake` from that use case's closure, metrics, conversion and
source. Then read the paragraph with the name removed. If it would still be
true of another use case, it is a template: rewrite it from this use case's
facts. Do not fill `whyFound` or `enablesOnSnowflake` by swapping the name into
a shared sentence. Name the output, the consumer or the schedule that belongs
to this use case, in words a stranger can follow. Do not claim scale, a shared
estate, or retirement of objects this use case does not own.

**Example** (Store Replenishment):

- `purpose`: "The daily reorder process for store stock. Each night it compares
  every store's sales with its reorder points and lists the products to
  reorder, so buyers raise the day's purchase orders before deliveries are
  scheduled."
- `whyFound`: "It is the only flow behind the Store Stock report that buyers open
  every morning, so a late or wrong number reaches purchasing the same day.
  Nothing else in the workload depends on it, so it can move first and prove
  the migration on a process people use daily."
- `howFound`: "Every night, store systems send the day's sales and each store's
  reorder points into this process. A stock routine compares the two and writes
  one daily list of what each store must order; that list is where all of this
  use case's data lands. Two reporting views sit on top of that list, which is
  what the Store Stock report reads. The scheduler export runs the load at
  02:00, which confirms it is live."
- `enablesOnSnowflake`: "Buyers keep the same morning report, now read from
  Snowflake, and it can be ready earlier and refreshed during the day. Once
  the report is pointed at Snowflake, the old stock tables and the two nightly
  load jobs that filled them can be retired."
- `evidence`: "The Store Stock report reads RPT.vw_store_stock." /
  "usp_stock_kpis writes MART.store_stock_daily from STG.pos_sales."
- `openQuestions`: "Does anyone still read the weekly variant of the Store Stock
  report? Confirm with the buying team before the legacy report is switched off."

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
  routine or report is in it, it is data only, not an outcome — including a
  view that joins tables nothing loads.
- Edge lists as narrative ("A reads B, B reads C").
- One use case per object when several objects serve one outcome.
- One giant use case that swallows the estate: when a closure holds most of
  the workload, split it by outcome, or keep the seeds that matter and let the
  closing wave take the rest. `waves catalog` lists such use cases in
  `summary.oversized`.
- Use cases drawn as folders or schemas rather than as the landing objects of
  one outcome.
- Temporary tables (`#…`) and staging copies as evidence of an outcome.
- The same sentence in any narrative field, or the same consideration, on two
  use cases, including a sentence that matches once the name is swapped.
- A purpose that lists tables and ends on a verb ("so sales can be reported"):
  say what the process is, what it does and what it resolves.
- Platform claims any workload could make ("single source of truth",
  "scalability"): say what this use case's people can do.
- A list of object names with no gloss ("Named outputs include CDS_AUDIT_LOG,
  CDS_Output"): the reader of the report does not know those names. Either
  introduce each one ("the customer-attribute file named CDS_Output, which the
  Audience Hub reads") or drop the name and describe the thing.
