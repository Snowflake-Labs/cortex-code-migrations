---
name: business-use-cases
description: Finds the business use cases in a converted workload with the `scai assessment waves` tools. Use during an assessment, or when someone asks for a use case around an application, a process, a report or an object. Size-based waves still assign every object's wave number and rank.
parent_skill: assessment
license: Proprietary. See License-Skills for complete terms
---

# Business Use Cases

A business use case is an outcome the workload delivers — a report people read,
a mart a team queries, a feed another system receives — together with every
object that produces it. The catalog is unordered. Size-based `scai assessment
waves` still assigns every deployable object a `planning.wave` and
`planning.waveRank` in category packs of about 100–200 objects. Selecting a
use case to rewrite those registry fields is a later change.

A use case rests on a **process** (an ETL workflow, a script, a procedure, a
macro or a BTEQ job that loads or computes data) and what it feeds, or on a **consumer** (a
report that reads the data). A pile of tables and the views that pass or join
them is data to migrate, not a use case, when no code in the project loads
them and no report reads them. SCAI calls that **data only**, and the plan
reports it as a finding rather than naming it as an outcome. A joining view is
only a landing object when a process writes at least one table it reads.

A **macro** is a stored program in the database: parameterized SQL that loads,
updates or computes. A **BTEQ** file (`.bteq`, `.btq`) is a batch job that logs
on and runs SQL, often the nightly load and the caller of those macros. Both
are processes. Read them the way you read a workflow, and say what they do.
The Planning table adds a **Macros / BTEQ** column only when a use case
contains either, so a reader can see that logic and not only the tables, views
and ETL packages. They stay inside the SQL and ETL counts as well.

SCAI does the graph work deterministically. This skill does the part a graph
cannot: judging which candidates are real business outcomes, naming them, and
explaining them in process language.

**Work the way a person would, from where the data lands.** Read the context
the customer gave. See where the data goes in the lineage. Find the places it
lands: tables, views, files and feeds nothing in the code reads after them.
Each one is the root of its own **flow**: what it reads, who writes that, and
what they read, back to the sources, and never what reads it. That flow is the
minimal set of objects the landing object needs to work. Read the landing
objects' sources and comments, then group the landing objects that serve one
outcome into a use case. A use case is the union of its landing objects' flows.

```
context pass                       → anchors.json (scai assessment waves anchors), assessment-context-ai.md
lineage search (this skill)        → catalog-draft.json (+ graph-enrichment.json), use-case-context.json
other-objects search               → other-objects-draft.json (use cases from AI analysis)
catalog_draft.py merge             → catalog-draft.json with both, nothing held twice
scai assessment waves catalog      → use-case-catalog.json + business-use-cases.json (from catalog-draft.json)
scai assessment waves use-cases    → use-cases.json        (validated, rated)
scai assessment waves plan         → wave-plan.json (does not rewrite planning.wave)
```

In assessment mode three agents do this, then the parent: the **context
pass** ([references/context-pass.md](references/context-pass.md)) reads the
code freely and writes `artifacts/assessment/assessment-context-ai.md`; then,
side by side, the **lineage search** (this file) works from where data lands
and the evidence of an outcome, and the **other-objects search**
([references/other-objects.md](references/other-objects.md)) reads the code
of what no exit or report backs and proposes the outcomes it can deduce, each
marked `aiAnalysis` with the evidence that would confirm it
(`missingEvidence`). The parent merges the two drafts, keeping every landing
object with the lineage use case that holds it, then builds, checks, rates and
plans once.

Every artifact lives in `<project_dir>/artifacts/assessment/waves/` under a
stable name that each run overwrites.

**How a wave grows.** A use case's wave pulls in what its landing objects
need upstream, never what depends on them. A table ten or more jobs write (run
parameters, registries, control and log tables) stays in every flow that reads
it, but its writers do not join through it: they belong to the flows they land
in. Every **root** — an object nothing else uses, whether a flow end or an
isolated object — reaches a wave only when a use case lists it. Whatever no use
case reaches lands in the closing pending waves; the catalog reports them as
the estate it did not place.

## Hard rules

1. **Never invent a code unit id.** Copy every id and group key from
   `anchors.json` or a `waves query` result. `waves use-cases` rejects unknown
   ids (`ASM0050`).
2. **Never list members.** You choose which landing objects (anchors) or
   anchor groups form an outcome; `waves catalog` gathers their flows from the
   registry. A draft that lists objects other than anchors is wrong.
3. **Never decide by a name list.** Do not drop a group because its schema,
   folder or object names look like a sandbox, a log or an audit table. Read
   the group's headers and source; mark it technical only with a reason the
   source shows. Do not group by folder or schema either: a landing object
   belongs with the outcome its flow and source serve, wherever its file sits.
4. **Never edit the registry, `anchors.json`, `use-case-catalog.json`,
   `business-use-cases.json`, `use-cases.json` or `wave-plan.json`.** Only the
   CLI writes them. You author `catalog-draft.json`, `use-case-context.json`
   and, when needed, `graph-enrichment.json`.
5. **Never ask for a wave size, a prioritization pattern or an ordering.**
   Size-based `scai assessment waves` assigns the registry waves.
6. Run every command from `project_dir`. Read results with `--json`.
7. Write narrative in business language. Say "not stated" rather than guess
   an audience or a purpose the evidence does not show.
8. **Context never changes the grade.** A schedule or a usage summary supports
   a use case and is recorded in `use-case-context.json`; `waves catalog` alone
   decides `evidenced` or `proposal`. It also never creates a use case without
   an anchor group or anchor from `anchors.json`.
9. **Never copy a command, a password, a connection string or a host name** from
   a context file into any artifact, narrative or return. Names of jobs and
   objects, and counts, are fine.

## Modes

| Mode | When | Ends with |
|---|---|---|
| **Assessment** | Dispatched by `../SKILL.md` after the analysis fan-out, as the lineage search beside the other-objects search, once the context pass has returned | Rated, checked catalog of the lineage draft; JSON return. The parent merges, rates and plans |
| **On-demand** | Someone asks for a wave or use case around an app, process, report or object | Plan with the new use case first; dashboard path |

Sub-agent mode is non-interactive: do not ask questions, and return JSON only.

## What a finished catalog looks like

Every landing object with a flow worth naming is in a use case, and every
anchor group is either part of a use case, marked technical with a
reason, or left unplaced on purpose because nothing in its source or headers
says what it serves. `catalog_draft.py unplaced` lists what you have not
placed, biggest first; work down it until what remains is small groups you
cannot explain. **Proposals are expected** when the drop has no exits,
reports, schedules or logs for an outcome: name it, write it, and let its
open questions ask the customer to confirm it. Never invent evidence to turn a
proposal into an evidenced use case; `waves catalog` decides the grade.

## Assessment mode

### 1. Configure and find where data lands

Call `configure(project_dir=...)`. If the tool cannot be loaded or the call
fails, stop and return `error` saying so: do not continue without it. The
context pass already ran `scai assessment waves anchors`; read
`artifacts/assessment/waves/anchors.json` and do not run it again, because the
other-objects search reads the same file while you work. Run it only when the
file is missing (on-demand mode, or an older run).

Then read `artifacts/assessment/assessment-context-ai.md` in full when it
exists: the subject areas, pipelines, scratch areas and gaps the context pass
found. Use it to know the estate before you name anything; it is a map, not
evidence, and never changes a grade.

The anchors are the **landing objects**: reports, jobs whose source exports,
mails or writes a file or another database, tables written and never read
(or read only through views nothing reads, the `publishedView` hint), and
objects nothing uses that read something. Each carries `flowSize`, the
deployable objects of its own flow. The summary says how many were kept, in how
many groups, and what was skipped (pass-through views, sinks no process
feeds, jobs with no exit, sinks on missing objects, assessed copies). Jobs with
no exit are not lost: they are in the flows of the tables they load.

### 2. Review the context

The dispatch may carry `context`: a scheduler export (`scheduler`, Informatica),
SQL Server Agent jobs (`agent_jobs`, SSIS) and an object usage summary
(`usage`), each with a `mode` and absolute `paths`. They are optional, and the
catalog is complete without them. Read
[references/context-review.md](references/context-review.md) and follow it:
read each provided file in place, match what it runs or reads to the registry
with `waves query find`, and let it confirm, merge and question the use cases you
write in step 5. A report or a dashboard is the strongest landing object there
is: when a BI layer was provided, start from what it reads. When the dispatch
carries no `context`, still write `use-case-context.json` so the report says
what was not provided.

Write `artifacts/assessment/waves/use-case-context.json` per
[references/contract.md](references/contract.md), listing every input that applies as
`reviewed`, `unusable` or `notProvided`. Write it after step 6, once
`use-case-catalog.json` gives you the use case ids it names.

### 3. See where the data goes

```bash
uv run --project "<assessment_skill_dir>" python \
  "<assessment_skill_dir>/business-use-cases/scripts/catalog_draft.py" lineage
```

It summarizes `artifacts/assessment/data-lineage.json`, which the Data Lineage
step wrote: the source systems, the pipelines (Informatica folders and
workflows, scripts, packages) and the systems they write, the busiest
source-to-target flows, and the inputs the lineage asks for (`missingInputs`).
When the file is missing, run `scai assessment data-lineage` and retry. Use it
as the map of the estate: which subject areas move data from where to where,
before you name any object.

### 4. Read the landing objects

```bash
uv run --project "<assessment_skill_dir>" python \
  "<assessment_skill_dir>/business-use-cases/scripts/catalog_draft.py" landing --offset 0 --limit 25
uv run --project "<assessment_skill_dir>" python \
  "<assessment_skill_dir>/business-use-cases/scripts/catalog_draft.py" groups --offset 0 --limit 25
```

`landing` lists the landing objects, largest flow first, with their shape,
group, `flowSize`, source path, exit citations and hints; `--group <key>`
restricts it to one group. `groups` pages the fact sheets, one per anchor
group: anchors by shape, exits (`detectionsByKind`, `citations`), reviewer
`hints`, member counts and types, the shared foundation it touches, the groups
it overlaps (`sharedWith`) and header comments. Page both until `next` is null.

For each landing object you place, see its flow:

```bash
scai assessment waves query flow --id <landing object id> --json
```

Then read the source of the landing object and of the main jobs on its flow,
their header comments and the cited exits. What the code says the object is
for decides the outcome, not its folder, schema or name. Use the other
`scai assessment waves query` operations (`relations`, `find`, `downstream`)
when a flow is not enough.

### 5. Write the draft

Write `artifacts/assessment/waves/catalog-draft.json` per
[references/contract.md](references/contract.md): one entry per outcome. List
the landing objects that serve it in `anchorIds`, and use `groupKeys` only when
every landing object of the group serves that outcome. Landing objects of one
folder can belong to different use cases, and one use case can span folders
and schemas: survey analysis tables in an operations sandbox belong with the
survey flow that feeds them. Merge groups that `sharedWith` and their sources
show are one outcome; list groups that serve the platform under
`technicalGroups` with a reason. Then:

```bash
uv run --project "<assessment_skill_dir>" python \
  "<assessment_skill_dir>/business-use-cases/scripts/catalog_draft.py" unplaced
```

Place or explain what it lists, largest first.

When a package or script clearly writes or reads a table the registry does not
connect it to, record the edge in `graph-enrichment.json` (see the contract)
with its evidence. Waves commands add those edges in memory; the registry is
never modified.

### 6. Build, check and rate

```bash
scai assessment waves catalog --json
uv run --project "<assessment_skill_dir>" python \
  "<assessment_skill_dir>/business-use-cases/scripts/compose_use_cases.py" check
scai assessment waves use-cases --json
```

`waves catalog` writes `use-case-catalog.json` and the same use cases to
`business-use-cases.json`; each use case's members are the union of its landing
objects' flows. On `ASM0055` it lists every problem; fix the draft and re-run,
at most **three** times. A use case listed in `summary.oversized` holds more
than `summary.oversizedAbove` objects and almost always joins several
outcomes: split it by landing object and rebuild. `check` reviews the
narratives in `business-use-cases.json`; fix them in `catalog-draft.json` and
rebuild.

Name each use case for the outcome ("Daily and Weekly Booking Snapshots"),
never for its bin, token or schema ("BKG data (LUV_ALL)"). Each narrative is an analysis of that use case
alone, written for a person reading the report who knows none of the code:
`purpose` says what it is, what it does in the system and what it resolves, in two or
three sentences; `howFound` says how the use case was identified, from where
the data comes, what happens to it, and where all of this use case's data lands;
`whyFound` and `enablesOnSnowflake` are one card on the page (Why migrate this)
and together say why it is worth moving and what people can do on Snowflake once
it is there, including when no BI layer was provided; each consideration
belongs to that use case alone. Follow "Write the narrative" in
[references/adjudication.md](references/adjudication.md) card by card. Name a
table, a schema, a view, a script or a job only when the sentence says what it
is. `howFound` is never how you found the bin. `whyFound` and `enablesOnSnowflake` must say
something that would be false of the others. A sentence reused with the name
swapped is not finished; rewrite it from that use case's objects and source.
Read the sources of each use case's main workflows, routines and views before
writing about it, and cite at least one file you read in `evidence` (for
example `source/_etl/<repo>/<folder>/tasks/<workflow>.xml`). Mentioning `scai`,
a bin id, a dry run, layer prefixes or root counts is not an analysis, and
`check` rejects it, as it rejects evidence that cites no source file, a
one-sentence purpose, generic platform claims, an unexplained object name, and a
sentence or a consideration repeated on another use case. Fix
everything it lists before rating.

`<assessment_skill_dir>` is the parent `assessment` skill directory, the one
that holds `pyproject.toml`.

On `ASM0050` the error lists every problem as `useCases[i].field`. Fix them all
and re-run, at most **three** times. Still failing: return `error` with the
remaining problems. `status: noUseCases` means nothing rated is deployable:
skip step 7, because there is no wave to plan, and return with a summary
saying so and `wave_plan: null` — `error`, because a catalog with no
deployable use case is not a finished run.

### 7. Plan

In assessment mode, stop here: the parent merges the other-objects draft into
yours, rebuilds and plans once, so `wave_plan` is `null` in your return. The
step below is for a run without the parent, and for on-demand mode.

```bash
scai assessment waves plan --json
```

With no options, every rated use case becomes a wave in rank order; closing
pending waves hold every deployable object the use cases did not place. Read
`use-cases.json` for the top three.

### 8. Return

```json
{
  "sub_skill": "business-use-cases",
  "status": "ok | error",
  "output_json": "<project_dir>/artifacts/assessment/waves/use-cases.json | null",
  "wave_plan": "<project_dir>/artifacts/assessment/waves/wave-plan.json | null",
  "summary": "<rated / undeployable counts, waves planned, evidenced vs proposed>",
  "catalog": {
    "use_cases": 0,
    "evidenced": 0,
    "proposals": 0,
    "deployable_objects": 0,
    "covered_objects": 0,
    "unplaced_groups": 0,
    "estate": {"technicalGroup": 0, "copy": 0, "plumbing": 0, "dataOnly": 0, "unknown": 0}
  },
  "context": {
    "reviewed": ["scheduler"],
    "not_provided": ["usage"],
    "unusable": []
  },
  "top_use_cases": [
    {
      "rank": 1,
      "id": "<slug>",
      "name": "<name>",
      "purpose": "<one sentence>",
      "objects": 0, "sql": 0, "etl": 0, "bi": 0,
      "confidence": "high | medium | low",
      "wave": 1
    }
  ],
  "error": "<message> | null"
}
```

`top_use_cases` holds at most three entries, rank order, copied from
`use-cases.json` and `wave-plan.json` — never retyped from memory. `catalog`
is copied from `use-case-catalog.json` (`summary.useCases`,
`summary.evidenced`, `summary.proposals`, `summary.deployableObjects`,
`summary.coveredObjects`, `summary.unplacedGroups`, `estate.counts`). When
`proposals` is most of the catalog, the summary says so plainly: the drop holds
no exits or reports for those outcomes, and query logs, scheduler exports or
the BI layer would confirm them. `context` copies the kinds from
`use-case-context.json` by status, so the parent can say what was reviewed and
which input, when provided, would make the catalog more complete.

In assessment mode `top_use_cases` are read from `use-cases.json` with
`wave: null`; the parent fills the waves after it plans.

`status` is `ok` only when every step ran and the catalog holds at least one use case.
Return `error`, with the reason in `error`, when `configure` failed, when a
step was skipped, or when `waves catalog` still fails after three rounds.

## On-demand mode

The request names something: "a wave for the payroll app", "a use case around
Synergy decisioning", "migrate the stock report first", or one object. The
context review belongs to assessment mode: leave `use-case-context.json` as it is.

1. Call `configure(project_dir=...)`. Locate it with `query find --name`, then
   `query relations`, `query flow` and `query closure` on what you found. Ask one question
   only when two different outcomes match and the request does not say which.
2. Read the existing `business-use-cases.json` (create it with
   `schemaVersion: 1` when absent) and add or replace one entry. The user
   asked for it, so `"origin": "onDemand"` and `"status": "confirmed"`. A
   single object is a use case seeded with that one id. Keep every other
   entry, and write the narrative as for any other use case.
3. Run `scai assessment waves use-cases --json`, then plan the new case first
   and the other rated cases after it in rank order:

   ```bash
   scai assessment waves plan --use-case <new-id> --use-case <rank-1-id> ... --json
   ```

   Every use case must be listed: a rated case left off the command lands in
   the closing wave. `--object <id>` adds a wave for one object without a use
   case, but object waves always follow the use-case waves.
4. Answer with the use case's name, purpose, counts and wave number, and the
   dashboard path `/assessment/planning/use-cases/<id>`. When `configure`
   reported a dashboard URL, give the full link `<url>/assessment/planning/use-cases/<id>`.

## Reference

- [references/adjudication.md](references/adjudication.md) — confirm, merge, drop; naming; narrative; confidence
- [references/contract.md](references/contract.md) — `anchors.json`, `catalog-draft.json`, `use-case-catalog.json`, `business-use-cases.json`, `graph-enrichment.json`, `coverage.json`, `clusters.json`; the closure rule and the ceiling
- [references/large-workloads.md](references/large-workloads.md) — sizing, clustering, the dry run, fact sheets and narratives at scale
- [references/context-pass.md](references/context-pass.md) — the first agent: reads the code and writes `assessment-context-ai.md`
- [references/other-objects.md](references/other-objects.md) — the agent beside this one: use cases deduced by AI analysis from what no evidence backs, in `other-objects-draft.json`
- [references/context-review.md](references/context-review.md) — reviewing a scheduler export, SQL Server Agent jobs and a usage summary, and writing `use-case-context.json`
- `references/sql-agent-jobs.sql` — the read-only msdb query the parent hands out when SSIS users will provide their Agent jobs later
- `scripts/compose_use_cases.py` — `bins`, `compose` and `check` over `clusters.json` and `business-use-cases.json`
- `scripts/catalog_draft.py` — `lineage` over `data-lineage.json`; `landing`, `groups` and `unplaced` over `anchors.json` and `catalog-draft.json`; `unevidenced`, `check-ai` and `merge` for the other-objects search
