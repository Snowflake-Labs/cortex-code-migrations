---
name: business-use-cases
description: Finds the business use cases in a converted workload and plans one migration wave per use case, over the registry with the `scai assessment waves` tools. Use during an assessment, or when someone asks for a wave or a use case around an application, a process, a report or an object.
parent_skill: assessment
license: Proprietary. See License-Skills for complete terms
---

# Business Use Cases

A business use case is an outcome the workload delivers — a report people read,
a mart a team queries, a feed another system receives — together with every
object that produces it. Each use case becomes **one migration wave**; inside
the wave, objects deploy in pure dependency order (`planning.waveRank`).

A use case rests on a **process** (an ETL workflow, a script, a procedure, a
macro or a BTEQ job that loads or computes data) and what it feeds, or on a **consumer** (a
report, or a view that joins data into something new). A pile of tables and
the views that pass each one through is data to migrate, not a use case: when
no code in the project loads or reads it, SCAI calls it **data only**, and the
plan reports it as a finding rather than naming it as an outcome.

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

```
scai assessment waves coverage     → coverage.json         (roots, plumbing, ceiling; coverage of a draft)
scai assessment waves candidates   → candidates.json       (deterministic seeds)
scai assessment waves cluster      → clusters.json         (every root binned; large workloads)
this skill                         → business-use-cases.json (+ graph-enrichment.json)
scai assessment waves use-cases    → use-cases.json        (validated, rated)
scai assessment waves plan         → wave-plan.json + planning.wave / planning.waveRank
```

Every artifact lives in `<project_dir>/artifacts/assessment/waves/` under a
stable name that each run overwrites.

**How a wave grows.** A use case's wave pulls in what its seeds and members
depend on, never what depends on them. Every **root** — an object nothing else
uses, whether a flow end or an isolated object — reaches a wave only when a use
case lists it. The file holds at most 100 use cases × (50 seeds + 2,000
members), so on a large workload the use cases must be domain-level outcomes
that list their roots. Whatever no use case reaches lands in the closing
pending waves: that is what coverage measures.

## Hard rules

1. **Never invent a code unit id.** Copy every id from `candidates.json` or a
   `waves query` result. `waves use-cases` rejects unknown ids (`ASM0050`).
2. **Never edit the registry, `candidates.json`, `use-cases.json` or
   `wave-plan.json`.** Only the CLI writes them. You author
   `business-use-cases.json` and, when needed, `graph-enrichment.json`.
3. **Never ask for a wave size, a prioritization pattern or an ordering.**
   One use case is one wave; dependency order inside it is fixed.
4. Run every command from `project_dir`. Read results with `--json`.
5. Write narrative in business language. Say "not stated" rather than guess
   an audience or a purpose the evidence does not show.

## Modes

| Mode | When | Ends with |
|---|---|---|
| **Assessment** | Dispatched by `../SKILL.md` after the analysis fan-out | Plan of every rated use case; JSON return |
| **On-demand** | Someone asks for a wave or use case around an app, process, report or object | Plan with the new use case first; dashboard path |

Sub-agent mode is non-interactive: do not ask questions, and return JSON only.

## Coverage target

Coverage is the share of deployable objects (schemas and databases left out)
that the use case waves deploy. The target is met when **coverage is at least
90%**, or when **at least 90% of what stays pending is plumbing or data only**
— temporary, test, deprecated, duplicate, backup, log, audit, control and
holding-schema objects, and data no process or consumer in the project
touches. `waves coverage` reports it as `draft.meetsTarget`. Below the target
the run is not finished: keep adding use cases, and if you cannot reach it,
return `error` with the coverage figures. Never wrap data-only objects in a use
case to raise coverage: a use case with no process and no consumer is not one.

## Assessment mode

### 1. Configure and size the workload

Call `configure(project_dir=...)`. If the tool cannot be loaded or the call
fails, stop and return `error` saying so: do not continue without it. Then:

```bash
scai assessment waves coverage --json
```

Read `workload` from `artifacts/assessment/waves/coverage.json`: `objects`,
`roots`, `isolatedRoots`, `plumbingRoots`, `meaningfulRoots`, `rootsByRole`
(`process`, `fed`, `consumer`, `dataOnly`), `businessRoots`,
`businessReachableObjects`, `resolvedReferences`, `ceiling` and `mode`.
`businessRoots` is what use cases must place; `businessReachableObjects ÷
objects` is the most coverage real use cases can reach. When `mode` is `large` (more than
3,000 roots or 10,000 objects), follow
[references/large-workloads.md](references/large-workloads.md) for steps 2–3:
it clusters every root into bins with `waves cluster`, measures a structural
dry run, then writes narratives per bin. Otherwise continue here.

### 2. Generate and adjudicate candidates

```bash
scai assessment waves candidates --json
```

Read `artifacts/assessment/waves/candidates.json`. Each candidate carries its
seeds (the ends of a flow), a provisional `label`, a `tier` (`bi`, `etl`,
`sql`), weighted `signals`, `metrics`, `conversion`, direct `reads`/`writes`,
`loaders` and `overlaps` with other candidates. The summary says how many sinks
were skipped as isolated, technical or undeployable — they are not use cases.
When `summary.truncated` is true, re-run with `--limit 500` before
adjudicating: the default 30 is for small workloads.

Zero candidates is a valid outcome: still run the coverage pass (step 3).

Follow [references/adjudication.md](references/adjudication.md) for each
candidate: **confirm** it, **merge** candidates that serve one outcome, or
**drop** plumbing by leaving it out of the file. Use the query tools to check
what the signals suggest (`scai assessment waves query --help` lists them all):

```bash
scai assessment waves query relations --id <id> --json        # what it reads and writes
scai assessment waves query closure --id <id> [--id <id>] --json  # what one wave would deploy
scai assessment waves query closure --ids-file <file> --json  # the same for many ids, with each seed's size
scai assessment waves query upstream --id <id> --json
scai assessment waves query downstream --id <id> --json
scai assessment waves query find --name "<words>" --json      # objects by name
scai assessment waves query sinks --tier bi --json            # ends of flows by tier
scai assessment waves query roots --schema <s> --json         # every root, isolated and plumbing ones too
scai assessment waves query schemas --json                    # what each schema holds
```

Lists are capped (`--limit`, default 50; `roots` pages with `--offset` and
takes `--limit` up to 5,000); `truncated: true` means there is more. A seed's
source file may be read when the name and graph leave the purpose unclear —
read only the lines you need.

### 3. Coverage pass (always)

Write the adjudicated use cases to `business-use-cases.json` (placeholder text
is fine at this point; see step 4), then measure them:

```bash
scai assessment waves coverage --json
```

Read `draft`: `pct`, `pendingByReason`, `uncoveredMeaningfulRoots` and
`topUncoveredRoots` (business roots only). Until `meetsTarget` is true, find
the outcomes no use case covers — reports with no use case, workflows and
routines no use case lists (`query roots` shows each root's `role` and
`processFolder`), a document under `source/` that names a process — and add
them. Anchor each on
real ids from `query roots`, `query sinks`, `query schemas` and `query find`;
it gets `"origin": "anchor"`. Roots of an outcome that the graph does not join
to its seeds go in its `memberIds`. When more than a few dozen roots remain,
let SCAI bin them:

```bash
scai assessment waves cluster --use-cases artifacts/assessment/waves/business-use-cases.json --json
```

It bins only what the file misses, into the use case slots left, and its bins
are composed as in [references/large-workloads.md](references/large-workloads.md)
with `--base` set to the current file. The pass ends only when `meetsTarget` is
true, or when the ceiling is reached and the summary says what stays pending
and why.

When a package or script clearly writes or reads a table the registry does not
connect it to, record the edge in `graph-enrichment.json` (see the contract)
with its evidence. Waves commands add those edges in memory; the registry is
never modified.

### 4. Write and rate

Write `artifacts/assessment/waves/business-use-cases.json` per
[references/contract.md](references/contract.md). Name each use case for the
outcome ("Daily and Weekly Booking Snapshots"), never for its bin, token or
schema ("BKG data (LUV_ALL)"). Each narrative is an analysis of that use case
alone. `howFound` is how the outcome is produced, from source through
processing to who reads it — the card says "How it was found", and that does
not mean how you found the bin. `whyFound` and `enablesOnSnowflake` must say
something that would be false of the others. A sentence reused with the name
swapped is not finished; rewrite it from that use case's objects and source.
Read the sources of each use case's main workflows, routines and views before
writing about it, and cite at least one file you read in `evidence` (for
example `source/_etl/<repo>/<folder>/tasks/<workflow>.xml`). Mentioning `scai`,
a bin id, a dry run, layer prefixes or root counts is not an analysis, and
`check` rejects it, as it rejects evidence that cites no source file. Fix
everything it lists before rating:

```bash
uv run --project "<assessment_skill_dir>" python \
  "<assessment_skill_dir>/business-use-cases/scripts/compose_use_cases.py" check
scai assessment waves use-cases --json
```

`<assessment_skill_dir>` is the parent `assessment` skill directory, the one
that holds `pyproject.toml`.

On `ASM0050` the error lists every problem as `useCases[i].field`. Fix them all
and re-run, at most **three** times. Still failing: return `error` with the
remaining problems. `status: noUseCases` means nothing rated is deployable:
skip step 5, because there is no wave to plan, and return with a summary
saying so and `wave_plan: null` — `ok` only when `coverage` still meets the
target (everything pending is plumbing), `error` otherwise.

### 5. Plan

```bash
scai assessment waves plan --json
```

With no options, every rated use case becomes a wave in rank order; closing
pending waves hold every deployable object the use cases did not place. Read
`use-cases.json` for the top three, then run `scai assessment waves coverage
--json` one last time for the figures you return.

### 6. Return

```json
{
  "sub_skill": "business-use-cases",
  "status": "ok | error",
  "output_json": "<project_dir>/artifacts/assessment/waves/use-cases.json | null",
  "wave_plan": "<project_dir>/artifacts/assessment/waves/wave-plan.json | null",
  "summary": "<rated / undeployable counts, waves planned, coverage>",
  "coverage": {
    "objects": 0,
    "planned": 0,
    "pct": 0.0,
    "pending_by_reason": {"<reason>": 0},
    "data_only_roots": 0,
    "meets_target": true
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
`use-cases.json` and `wave-plan.json` — never retyped from memory. `coverage`
is copied from `coverage.json` (`workload.objects`, `draft.planned`,
`draft.pct`, `draft.pendingByReason`, `workload.dataOnlyRoots`,
`draft.meetsTarget`). When `pendingByReason.dataOnly` is large, the summary
says so plainly: that many objects are tables and pass-through views no code
in the project loads or reads, so their loaders (scheduler scripts, BTEQ or
TPT jobs, another ETL repository) were not delivered and should be asked for.

`status` is `ok` only when every step ran and `meets_target` is true. Return
`error`, with the reason in `error`, when `configure` failed, when a step was
skipped, or when the target was not met — the summary of an `ok` run never
says a required step was skipped.

## On-demand mode

The request names something: "a wave for the payroll app", "a use case around
Synergy decisioning", "migrate the stock report first", or one object.

1. Call `configure(project_dir=...)`. Locate it with `query find --name`, then
   `query relations` and `query closure` on what you found. Ask one question
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
- [references/contract.md](references/contract.md) — `business-use-cases.json`, `graph-enrichment.json`, `coverage.json`, `clusters.json`; the closure rule and the ceiling
- [references/large-workloads.md](references/large-workloads.md) — sizing, clustering, the dry run, fact sheets and narratives at scale
- `scripts/compose_use_cases.py` — `bins`, `compose` and `check` over `clusters.json` and `business-use-cases.json`
