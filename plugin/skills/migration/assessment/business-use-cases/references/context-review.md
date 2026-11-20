# Context review

The converted code alone produces a catalog, and most use cases from it are
proposals: they rest on structure. A customer can also hand over what runs and
what is read. Read it as an analyst would, use it to confirm, merge, question
and look for use cases, and record what was and was not provided so the report
can show it.

## Contents

- The four inputs
- How to review
- What each input changes
- Limits and safety
- Writing `use-case-context.json`

## The four inputs

| Kind | What it is | Applies when | What it shows |
|---|---|---|---|
| `bi` | Reports and dashboards that read the warehouse | Always; nothing is asked for it | Who consumes an outcome. Already in the catalog as `report` anchors; you only record whether any exist |
| `scheduler` | A scheduler export: Control-M job definitions, a crontab, Autosys, Airflow DAGs | `context.scheduler` is present (Informatica is in scope) | Which workflows or scripts run, how often, in which order, and which are held or disabled |
| `agentJobs` | SQL Server Agent jobs: scripts or the `sql-agent-jobs.sql` result | `context.agent_jobs` is present (SSIS is in scope) | Which packages and procedures run, their schedules, whether the job is enabled, the last run |
| `usage` | An object usage summary from query logs or access views | `context.usage` is present | Which tables and views are still read, by how many users, and when last |

An input that applies but was skipped, or promised for later, is `notProvided`.
One that was given but cannot be read is `unusable`. One you reviewed is
`reviewed`. `bi` is `reviewed` when `anchors.json` found at least one `report`
anchor (`summary.scan.foundByShape.report`) and `notProvided` otherwise.

## How to review

Do this after reading the fact sheets and before writing the draft, so what you
learn shapes which groups you merge, name and question.

1. **Inventory.** For each path in `context`, identify the format from the file
   itself. Read it in place and never copy it. Note only the file *name*. A
   folder is a set of files. Large files: read the structure, then sample with
   `rg` and `head` rather than loading all of it, and say so in `finding`.
2. **Extract entries.** One entry is one thing that runs or is read.
   - Scheduler: job name, the workflow, script or program it runs, its
     schedule, the jobs it waits for, and whether it is held or disabled.
     An Informatica workflow's own `SCHEDULER` element, when the file has one,
     is the same kind of evidence and is already in the drop.
   - Agent jobs: job name, enabled or not, each step's `subsystem` and what it
     runs (an SSIS package path, a procedure), its schedule and last run.
   - Usage: object name, and any of reads, distinct users, last access, and the
     window the summary covers.
3. **Match to the registry.** Never guess. Search by what the entry runs or
   reads (the workflow, script, package, procedure or object), not by the
   scheduler's own job name, which rarely equals it. For every name that matters
   run `scai assessment waves query find --name <name> --json`. A match gives
   you a real code unit id; no match is an `unmatched` entry. Count `entries`
   and `matched`; do not list the unmatched ones.
4. **Use it.** See the next section. Everything you conclude is written into
   `catalog-draft.json` through the fields it already has, and into
   `use-case-context.json`.
5. **Write `use-case-context.json`.** Always, even when nothing was provided.

## What each input changes

Scheduler and agent jobs.

- A group's exit job or workflow appears in the schedule: the outcome is live.
  Add an `evidence` item naming the file and the job, and say how often it runs
  in `howFound`. Say "not stated" when it does not.
- One job waits for another: the groups they belong to are usually one outcome
  when their sources agree. Merge them, or say in `howFound` that they run as a
  chain.
- A job that is held, disabled, or absent from a schedule that otherwise lists
  its neighbours: add an `openQuestions` item ("Held in the scheduler export;
  confirm it is still run") and keep the group. Do not drop it and do not call
  it dead.
- A scheduled job whose target is not in the drop is a gap, not a use case:
  it is counted as unmatched and the customer is asked for the code in
  `openQuestions` of the nearest use case, when there is one.

Usage.

- An outcome's output tables or views are read, by several users, recently:
  put that in `purpose` (who reads it) and `evidence`.
- No reads in the window: add an `openQuestions` item; the window may simply
  be short. Never conclude an outcome is unused from absence alone.
- A heavily read object that no use case contains: find it with `waves query
  find`, then place the anchor group or `anchorIds` that reach it, or name a
  new use case from it. Placing is done only with ids from `anchors.json`.

Both.

- Context does not change the grade. `waves catalog` decides `evidenced` or
  `proposal` from exits and reports; it does not read these files. What you
  learned is recorded as `confirmedBy` in `use-case-context.json`, and the
  report shows it beside the use case. Never describe a proposal as evidenced
  because a schedule or a log supports it.
- Context never creates a use case without an anchor group or anchor from
  `anchors.json`.

## Limits and safety

- **Read it in place; never copy.** Do not copy file contents, commands,
  passwords, connection strings, host names, user names or statement text into
  any artifact, narrative, evidence item, open question or return. Names of
  jobs, workflows, packages and objects, and counts, are fine.
- A query log that includes statement text: use only the object names and the
  counts, never quote the SQL.
- Formats vary. When a file is not a format you can read with confidence, mark
  the input `unusable`, give the reason in `finding`, and do not guess entries.
- Say the window when you know it ("30 days"). It bounds what absence means.
- Keep it proportionate: this review confirms and questions use cases; it does
  not replace reading the sources of the groups you name.

## Writing `use-case-context.json`

Follow the `use-case-context.json` section of [contract.md](contract.md).

- List every input that applies, in the order `bi`, `scheduler`, `agentJobs`,
  `usage`: `reviewed`, `unusable` or `notProvided`. A `notProvided` input needs
  no text; the report says what providing each input adds.
- Under `useCases`, list only use cases from `use-case-catalog.json`, with
  `confirmedBy` naming the inputs that supported them and a one-line `note`
  such as "Runs nightly at 02:00 (job MTG_NIGHTLY); read by 14 users in 30
  days". Leave out a use case no input supports.
- Return which kinds were `reviewed`, `notProvided` and `unusable` in the
  `context` block of the skill's JSON, so the parent can tell the customer what
  would make the catalog more complete.
