# Large workloads

Read this when `waves coverage` reports `"mode": "large"`: more than 3,000 roots
or 10,000 objects. At that size, use cases built one candidate at a time cover a
few percent of the workload and leave the rest in pending waves. Use cases have
to be **domain-level outcomes**, packed close to the ceiling, and every step is
measured before any narrative is written.

## Why flow-level use cases fail here

A wave pulls in what its seeds and members depend on, never what depends on
them. Every root (a flow end, or an isolated object nothing uses and that uses
nothing) therefore needs a slot of its own, as a seed or a member. A warehouse
of 80,000 objects easily has 50,000 roots. Thirty candidates, or even two
hundred, cannot reach them: the closing wave ends up with nearly everything.

`waves coverage` gives the arithmetic up front:

| Field | Meaning |
|---|---|
| `roots`, `flowEnds`, `isolatedRoots` | What needs a slot |
| `plumbingRoots`, `plumbingRootsByReason` | Roots that should stay pending: temporary, test, deprecated, duplicate, older version, backup, platform (log, audit, error, control, batch, metadata), holding schemas (temp, hold, DBA) |
| `meaningfulRoots` | Roots that are not plumbing |
| `rootsByRole` | `process`, `fed`, `consumer`, `dataOnly` (see [contract.md](contract.md)) |
| `businessRoots` | What the use cases must place: meaningful roots that are not data only |
| `ceiling.slots`, `ceiling.feasible` | 100 × (50 + 2000) slots; whether the business roots fit |
| `businessReachableObjects` | Objects the business roots' waves would deploy: the most real use cases cover |
| `resolvedReferences` | Pipeline references to an unqualified table name sent to the one table of that name |

In a large warehouse most roots are often data only: landing tables and the
access views over them (`SELECT * FROM` one table, row-level security joining
one table to the shared access tables) whose loaders — BTEQ, TPT, scheduler
scripts, another ETL repository — are not in the code drop. They are real
objects to migrate, but no outcome can be named from them, so they stay
pending as `dataOnly` and the summary asks for their loaders.

## Method

1. **Size.** `scai assessment waves coverage --json`. Note `rootsByRole`,
   `businessRoots` and `businessReachableObjects ÷ objects`. When `dataOnly`
   is most of the roots, that is the first finding of the assessment.
2. **Cluster.** `scai assessment waves cluster --json` (defaults
   `--max-roots 550 --max-cases 100`). SCAI bins only business roots:
   - **Process bins** (`anchor: process`) hold one ETL folder (a workflow
     folder in Informatica, a package directory in SSIS) or one routine, the
     tables it writes and reads, and the views that read those tables. A folder
     too large for one bin is split in name order.
   - **Consumer bins** (`anchor: consumer`) group reports and joining views
     no process touches, by the tables they share.
   When the roots do not fit, the bin size rises (`binSizeRaised`) up to
   2,050. Plumbing is counted under `plumbing`, data only under `dataOnly`
   (`bySchema`, `samples`). Neither is binned.
3. **Dry run.** Before any narrative:

   ```bash
   uv run --project "<assessment_skill_dir>" python \
     "<assessment_skill_dir>/business-use-cases/scripts/compose_use_cases.py" compose --placeholder
   scai assessment waves coverage --use-cases artifacts/assessment/waves/business-use-cases.dry-run.json --json
   ```

   `draft.meetsTarget` must be true. If it is not, read `pendingByReason` and
   `topUncoveredRoots`: uncovered flows mean bins are missing (raise
   `--max-cases` back to 100, or lower `--max-roots` so fewer roots are left
   over); isolated roots that are real work belong as members of the bin of
   their schema or subject.
4. **Shape the use cases.** Page through the fact sheets:

   ```bash
   uv run --project "<assessment_skill_dir>" python \
     "<assessment_skill_dir>/business-use-cases/scripts/compose_use_cases.py" bins --offset 0 --limit 10
   ```

   Each sheet gives the anchor, subjects, schemas, ETL folders, workflows,
   writers, main tables, external sources, loaded and unloaded tables, sample
   seeds, top missing objects, metrics and conversion. Decide per bin: keep it,
   merge it with a related bin (list both under one entry's `bins`), or give it
   a better name. Folders of one system often belong together (a load folder
   and its extract folder); merge them when their workflows share tables. A bin
   can also be split by moving ids into a second entry's `seedIds` /
   `memberIds`. Use `waves query relations` and `waves query closure
   --ids-file` to check a bin you are unsure of.
5. **Read the sources, then write narratives** into a narratives file, a JSON
   list with one entry per use case. A bin is a pile of objects, not a use
   case. For each one, open what does the work:
   - **Process bins.** When `metrics.macroCount` or `metrics.bteqCount` is
     above zero, open those macro and BTEQ files first. They are the program
     that loads or computes the tables, and a bin of them with no ETL folder
     is still a process. Then read two or three of its workflows (the `tasks/` or
     `workflows/` XML under the folder in `etlFolders`) and the mappings they
     run: what source they read (`externalSources`: a flat file, a queue, a
     source system's schema), what they transform, which tables they load
     (`loadedTables`). Then read the main views over those tables. A folder
     name is a hint, not a name: `vw_Dynamic_Packaging` whose workflows parse
     booking XML into package tables is holiday package bookings; confirm each
     abbreviation in the sources rather than guessing it.
   - **Consumer bins.** Read the joining views: what they join and what they
     compute (balances, case histories, liability). `unloadedTables` are the
     inputs nothing in the project loads; name them in `openQuestions`.
   Then name the outcome, per [adjudication.md](adjudication.md). Two bins with
   the same token are two outcomes (approval stages, document tasks), not "AIR
   data" and "AIR data 2". `howFound` is the flow you read, from source to
   reader. It is never how the bin was built: no `scai`, no bin id, no "layer
   prefixes", no "structural dry run", no root counts. `evidence` cites the
   files you read. `compose check` rejects both failures, and a file of them is
   not done.

   ```json
   [
     {
       "id": "loyalty-accrual",
       "bins": ["bin-001", "bin-014"],
       "name": "Loyalty Accrual and Redemption",
       "purpose": "…", "whyFound": "…", "howFound": "…", "enablesOnSnowflake": "…",
       "evidence": ["…"], "openQuestions": ["…"]
     }
   ]
   ```

   `status`, `confidence` and `origin` may be given; otherwise the weakest
   suggestion of the entry's bins is used and `origin` is `anchor`. The facts
   choose which objects you read; the sentences come from what those objects
   do, per [adjudication.md](adjudication.md). Put the bin's `topMissing`
   objects in `openQuestions` when they matter.
6. **Compose and check.**

   ```bash
   uv run --project "<assessment_skill_dir>" python \
     "<assessment_skill_dir>/business-use-cases/scripts/compose_use_cases.py" compose \
     --narratives <narratives.json> [--base <use cases written earlier>]
   ```

   `compose` copies every id from `clusters.json`, keeps seeds within 50 and
   members within 2,000, refuses an entry that would exceed them, and runs
   `check`: every length, list size, repeated name and sentence shared between
   use cases (with the names swapped out), in one pass. Fix what it lists and
   re-run `check` until it reports nothing. Then `waves coverage` once more,
   and `waves use-cases`.

## Judgement calls

- **Macros and BTEQ are the program.** A macro that writes or computes, and a
  BTEQ script that loads, are processes even when the project has no
  Informatica folder for those tables. Name the step they perform. Other
  script types (FastLoad, MultiLoad, TPT) stay in the ETL count; only `.bteq`
  and `.btq` are BTEQ. The Planning table shows them in their own column when
  any use case has them.
- **Data only is a finding, not a use case.** Never build an entry from
  `dataOnly` samples or schemas to raise coverage. Report `dataOnly.roots`,
  `dataOnly.objects` and the largest `bySchema` areas in the summary, and say
  the loaders for them were not delivered.
- **Consumer bins** come out `proposed` / `medium`: the reporting is real, but
  how its data arrives is not in the project. Confirm one only when a report or
  document says who uses it.
- **External sources.** A process bin whose `externalSources` are flat files or
  another system's schema is an inbound feed; say which system in `purpose`. A
  bin whose `unloadedTables` outnumber its `loadedTables` depends on loads
  outside the project; ask for them in `openQuestions`.
- **Sandboxes.** A bin whose roots mostly sit in team sandboxes
  (`sandboxShare` ≥ 0.5) is `proposed` / `low`: real work, rarely a production
  outcome. Say so in the narrative and ask in `openQuestions` whether it is
  still used.
- **Mixed bins** (`mixed: true`) gather small subjects. Name them for what they
  share; when they share nothing, `proposed` / `medium` and say so.
- **Bins named only by a schema** come out `proposed` / `low`. Look at their
  sources before keeping the name.
- **No reports.** With no BI files the use cases rest on ETL and SQL only.
  Say that confidence is limited by it, and recommend collecting the Power BI
  or Tableau files before the plan is used to sequence work.
- **Candidates still count.** `waves candidates --limit 500` lists the
  strongest flow ends with their signals; use them to name bins and to pick
  which use cases deserve `confirmed`.
