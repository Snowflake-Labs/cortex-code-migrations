# Context pass

The first of the three business use case agents. It reads the code freely and
writes `artifacts/assessment/assessment-context-ai.md`: an overview of what the
workload does, in business words, that the two searches after it read before
they name anything. It finds no use cases and writes no draft.

The lineage search starts from where data lands and needs evidence of an
outcome. The other-objects search starts from what that evidence cannot reach.
Both are better when they already know the estate: which subject areas exist,
which systems feed them, where the scratch and sandbox areas are, and what the
customer did not provide. That is this file.

## Steps

1. Call `configure(project_dir=...)`. If it fails, return `error`.
2. Run `scai assessment waves anchors --json` from `project_dir`. Both searches
   read the `anchors.json` it writes, so it runs once, here.
3. See where the data goes:

   ```bash
   uv run --project "<assessment_skill_dir>" python \
     "<assessment_skill_dir>/business-use-cases/scripts/catalog_draft.py" lineage
   ```

4. Read the estate. You are free to read anything under `source/`. Start wide,
   then go deep where the code is dense:
   - the folder tree of `source/` and the schemas in `source/database/`, with
     how many files each holds;
   - `catalog_draft.py groups --offset 0 --limit 25`, paged to the end, for
     the headers and the exits each group cites;
   - the header comments and the first statements of the largest scripts,
     workflows, procedures and macros of each area;
   - `scai assessment waves query find --name <word> --json` and
     `query relations` when a name needs its readers or writers;
   - the exclusion findings under `artifacts/assessment/` when present, for the
     copies, backups and test objects they list.
5. Write the file, then return.

Spend your reading on understanding, not on counting: the CLI already counts.
Stop when another hour of reading would not change a section.

## `assessment-context-ai.md`

Plain markdown, at most about 400 lines, with these sections in this order.
Write for an analyst who has never seen the code.

```markdown
# Workload context

## At a glance
Platforms, the number of scripts, workflows, procedures, tables and views, and
the source systems the lineage names. Two to four sentences.

## Subject areas
One subsection per business area the code serves (bookings, loyalty, crew,
maintenance…). For each: what it is for, the schemas and folders that hold it,
the main jobs and what they load or compute, where its data comes from, and
who or what reads the result when the code says so.

## Pipelines and schedules
How data moves: the loaders, their order, the control and run tables, and any
schedule the code names (a Control-M condition, a cron line, a calendar table).

## Where data leaves
Exports, files, mails, feeds to other systems and reports the code shows, by
subject area.

## Scratch, sandbox and personal areas
Folders and schemas that hold one person's or one team's ad hoc work, tests,
copies and backups, with what the code shows about each. Say when an area looks
like scratch but its code loads something others read.

## What the code cannot show
What would confirm an outcome and the drop lacks: a BI layer, a scheduler
export, query logs, missing loaders. Name the subject areas each gap affects.
```

## Rules

- Never copy a command, a password, a connection string or a host name into
  the file. Names of jobs, objects, folders and schemas, and counts, are fine.
- Say "not stated" rather than guess an audience or a purpose the code does
  not show.
- Never edit the registry or any CLI artifact. This file and `anchors.json`
  (through the CLI) are the only things this agent writes.
- Cite the files you read inline, as paths, so a search can open them.

## Return

```json
{
  "sub_skill": "business-use-cases-context",
  "status": "ok | error",
  "output_json": null,
  "context_md": "<project_dir>/artifacts/assessment/assessment-context-ai.md | null",
  "summary": "<subject areas found, anchors kept, groups>",
  "error": "<message> | null"
}
```
