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

SCAI does the graph work deterministically. This skill does the part a graph
cannot: judging which candidates are real business outcomes, naming them, and
explaining them in process language.

```
scai assessment waves candidates   → candidates.json       (deterministic seeds)
this skill                         → business-use-cases.json (+ graph-enrichment.json)
scai assessment waves use-cases    → use-cases.json        (validated, rated)
scai assessment waves plan         → wave-plan.json + planning.wave / planning.waveRank
```

Every artifact lives in `<project_dir>/artifacts/assessment/waves/` under a
stable name that each run overwrites.

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

## Assessment mode

### 1. Configure and generate candidates

Call `configure(project_dir=...)`. Then:

```bash
scai assessment waves candidates --json
```

Read `artifacts/assessment/waves/candidates.json`. Each candidate carries its
seeds (the ends of a flow), a provisional `label`, a `tier` (`bi`, `etl`,
`sql`), weighted `signals`, `metrics`, `conversion`, direct `reads`/`writes`,
`loaders` and `overlaps` with other candidates. The summary says how many sinks
were skipped as isolated, technical or undeployable — they are not use cases.

Zero candidates is a valid outcome: still run the coverage pass (step 3).

### 2. Adjudicate every candidate

Follow [references/adjudication.md](references/adjudication.md) for each one:
**confirm** it, **merge** candidates that serve one outcome, or **drop**
plumbing by leaving it out of the file. Use the query tools to check what the signals suggest:

```bash
scai assessment waves query relations --id <id> --json        # what it reads and writes
scai assessment waves query closure --id <id> [--id <id>] --json  # what one wave would deploy
scai assessment waves query upstream --id <id> --json
scai assessment waves query downstream --id <id> --json
scai assessment waves query find --name "<words>" --json      # objects by name
scai assessment waves query sinks --tier bi --json            # ends of flows by tier
scai assessment waves query schemas --json                    # what each schema holds
```

Lists are capped (`--limit`, default 50); `truncated: true` means there is
more. A seed's source file may be read when the name and graph leave the
purpose unclear — read only the lines you need.

### 3. Coverage pass

After the candidates, look for outcomes no candidate covers: reports with no
candidate, a schema whose objects no closure includes, a document under
`source/` that names a process. Use `query sinks`, `query schemas` and
`query find` to anchor such an outcome on real ids; it gets
`"origin": "anchor"`. Skip this pass when the candidates already cover the
reports and presentation schemas.

When a package or script clearly writes or reads a table the registry does not
connect it to, record the edge in `graph-enrichment.json` (see the contract)
with its evidence. Waves commands add those edges in memory; the registry is
never modified.

### 4. Write and rate

Write `artifacts/assessment/waves/business-use-cases.json` per
[references/contract.md](references/contract.md). Each narrative is an analysis
of that use case alone: `whyFound` and `enablesOnSnowflake` must say something
that would be false of the others. A sentence reused with the name swapped is
not finished; rewrite it from that use case's closure, metrics and source.
Then:

```bash
scai assessment waves use-cases --json
```

On `ASM0050` the error lists every problem as `useCases[i].field`. Fix them all
and re-run, at most **three** times. Still failing: return `error` with the
remaining problems. `status: noUseCases` means nothing rated is deployable:
skip step 5, because there is no wave to plan, and return `ok` with a summary
saying so and `wave_plan: null`.

### 5. Plan

```bash
scai assessment waves plan --json
```

With no options, every rated use case becomes a wave in rank order; a closing
wave, "Objects not in a business use case", holds every deployable object the
use cases did not place. Read `use-cases.json` for the top three.

### 6. Return

```json
{
  "sub_skill": "business-use-cases",
  "status": "ok | error",
  "output_json": "<project_dir>/artifacts/assessment/waves/use-cases.json | null",
  "wave_plan": "<project_dir>/artifacts/assessment/waves/wave-plan.json | null",
  "summary": "<rated / undeployable counts, waves planned>",
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
`use-cases.json` and `wave-plan.json` — never retyped from memory.

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
- [references/contract.md](references/contract.md) — `business-use-cases.json` and `graph-enrichment.json`
