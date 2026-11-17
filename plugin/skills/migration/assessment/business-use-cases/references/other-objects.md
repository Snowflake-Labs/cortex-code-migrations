# Other objects search

The third business use case agent. It runs beside the lineage search, after the
context pass, and looks where landing evidence cannot: the anchor groups no
export, file, mail, feed or report backs. Those groups often hold real outcomes
whose consumer is outside the drop (a BI tool nobody exported, a team reading a
table directly), and a lineage search leaves them unplaced because nothing
proves them. This agent reads their code, deduces what they do, and proposes
them as use cases **from AI analysis**, each saying what evidence would
confirm it.

It writes only `artifacts/assessment/waves/other-objects-draft.json`. The parent
merges it into `catalog-draft.json` after both searches return, drops what a
lineage use case already holds, and builds the catalog.

## Steps

1. Call `configure(project_dir=...)`. If it fails, return `error`.
2. Read `artifacts/assessment/assessment-context-ai.md` in full. It names the
   subject areas, the scratch areas and what the code cannot show.
3. List what no evidence backs, most members first, and page it to the end:

   ```bash
   uv run --project "<assessment_skill_dir>" python \
     "<assessment_skill_dir>/business-use-cases/scripts/catalog_draft.py" unevidenced --offset 0 --limit 25
   ```

4. For each group, largest first, read its code:
   `catalog_draft.py landing --group <key>`, `scai assessment waves query flow
   --id <landing object id> --json`, then the sources of its scripts, jobs,
   procedures and views: header comments, the tables they write, the columns
   they compute, the filters and joins. Deduce what the group produces and for
   whom. Group landing objects that serve one outcome, across folders and
   schemas, as the lineage search does.
5. Write the draft, then check it, and fix every problem, at most three rounds:

   ```bash
   uv run --project "<assessment_skill_dir>" python \
     "<assessment_skill_dir>/business-use-cases/scripts/catalog_draft.py" check-ai
   ```

6. Return.

## What can be a use case here

The bar is the same as for any use case: a **process** in the drop (a script, a
BTEQ job, a workflow, a procedure or a macro that loads or computes data) and
what it feeds. The code must show what the result is for: a comment, a name the
code explains, columns that only make sense for one purpose, a downstream step
that formats it for people. What is missing is the proof that someone uses it.

Not a use case, even here:

- A pile of tables and views no code in the drop loads. It is data to migrate;
  the plan lists it under Other objects. `waves use-cases` rejects it as data
  only.
- One person's scratch work (`sqluser/<id>` folders, test copies, dated
  backups) unless its code loads something a team reads, which you can cite.
- A group whose purpose you cannot state from its code. Leave it out.

Never decide by a name list: read the source. A folder that looks like scratch
can hold the only loader of a mart.

## `other-objects-draft.json`

The `catalog-draft.json` shape ([contract.md](contract.md)), with every use
case marked:

```json
{
  "schemaVersion": 1,
  "useCases": [
    {
      "id": "fleet-maintenance-planning",
      "name": "Fleet Maintenance Planning",
      "origin": "aiAnalysis",
      "missingEvidence": ["bi", "scheduler"],
      "groupKeys": ["folder:source/BTEQ/…/scripts/ENG"],
      "anchorIds": [],
      "purpose": "…",
      "whyFound": "…",
      "howFound": "…",
      "enablesOnSnowflake": "…",
      "evidence": ["source/BTEQ/…/scripts/ENG/load_checks.bteq"],
      "openQuestions": ["Which report or tool do the planners open to read the due list?"]
    }
  ]
}
```

| Field | Rule |
|---|---|
| `origin` | Always `aiAnalysis` |
| `missingEvidence` | One or more of `bi` (no report or BI tool in the drop reads it), `scheduler` (no export shows its jobs run), `usage` (no query log shows it is read), `loader` (some of its tables have no loader in the drop), `exit` (no export, file or feed shows data leaving). List what would confirm it, not every input that is absent |
| `groupKeys` / `anchorIds` | Copied from `anchors.json`; prefer `anchorIds` when a group holds more than one outcome |
| Narrative fields | As in [adjudication.md](adjudication.md). `howFound` says the use case was deduced from its code, what the code shows, and what would confirm it |
| `openQuestions` | The first one asks the customer for the missing evidence by name ("Which report reads the due list?") |

`waves catalog` grades every use case from its landing objects, so these are
proposals unless a landing object has an exit: AI analysis never raises a
grade.

## Rules

- Never invent a code unit id or a group key. Copy them from `anchors.json`,
  `unevidenced` or a `waves query` result.
- Never write `catalog-draft.json`, `use-case-catalog.json`,
  `business-use-cases.json`, `use-cases.json` or `wave-plan.json`, and never run
  `waves catalog`, `waves use-cases` or `waves plan`: the lineage search is
  using them, and the parent runs them after the merge.
- Do not search for what has an exit or a report: the lineage search owns
  those groups. A group both searches place stays with the lineage use case.
- Never copy a command, a password, a connection string or a host name into the
  draft. Names of jobs and objects, and counts, are fine.
- Non-interactive: do not ask questions; return JSON only.

## Return

```json
{
  "sub_skill": "business-use-cases-other-objects",
  "status": "ok | error",
  "output_json": "<project_dir>/artifacts/assessment/waves/other-objects-draft.json | null",
  "summary": "<groups read, use cases proposed, members they cover, groups left out and why>",
  "use_cases": 0,
  "error": "<message> | null"
}
```

`ok` with zero use cases is a valid answer when nothing outside the evidence
holds an outcome the code can show; write the draft with an empty `useCases`
list and say why in the summary.
