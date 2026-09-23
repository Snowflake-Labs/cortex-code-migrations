---
name: convert-etl-aifirst
parent_skill: convert
description: >
  Routing for ETL platforms SnowConvert does not natively convert. Decides between the
  native ETL replatform path and the AI-First convert action, states what each exit
  code means, when the Code Unit Registry may record conversion as completed,
  and how lineage is written into the Code Unit Registry.
  Instruction-only: the runtime lives in the etl-aifirst action.
license: Proprietary. See License-Skills for complete terms
---

# Routing ETL That SnowConvert Does Not Natively Convert

This skill decides *which* convert path an ETL document takes. It runs no conversion
itself; the runtime is the `etl-aifirst` action under
`../../migrate-objects/actions/etl-aifirst/`.

## Prefer the native path whenever it exists

SnowConvert's own ETL replatform is the mature path: it has translators the AI-First
chain reuses, an issue taxonomy, and years of workload coverage behind it. AI-First
exists because that path does not yet cover every platform, not to replace it.

So the rule is a preference, not a capability test:

| Source platform | Path | Why |
|---|---|---|
| SSIS (`.dtsx`) | native `scai code convert` (ETL already in `source/_etl/`) | natively converted |
| Informatica Power Center (XML repo export) | native, same command | natively converted |
| Alteryx (`.yxmd`), Azure Data Factory, DataStage (`.dsx`), Pentaho (`.ktr`/`.kjb`) | AI-First action | no native converter |
| Anything else the user names | AI-First action | no native converter |

A checked-in platform table exists for `ssis` and `informatica` as well. That is for
comparing the two paths on the same input, not an invitation to route production work
away from the native converter. Do not send SSIS or Informatica here because the AI-First
path is available.

## Routing the AI-First case

First resolve the registered unit's output root. If a real
`Reports/AiFirstRemediation/remediation-brief.json` already exists there, the producer
already ran. Resume those artifacts: do not invoke the driver, replace output, or
regenerate a missing lineage report. If issues exist without a brief, preserve that
failed run and record it as failed below. Only ask for the source document and start a
new producer run when neither artifact exists.

For a new run, ask for the filesystem path of the source document, then hand it to the action's driver.
Read that action's `SKILL.md` before invoking it; the entry is:

```bash
scripts/aifirst-migrate.sh --platform <platform-identity> <source-document> <output-root>
```

Checked-in identities: `adf`, `alteryx`, `datastage`, `informatica`, `pentaho`, `ssis`.
Pass the identity, not a table path — Stage 0 picks the checked-in table when one matches.

For a platform with no checked-in table, pass the identity anyway. Stage 0 authors a
provisional table in an isolated view, accepts it only after structural and
source-accounting validation, and preserves it under `<output-root>.gates/stage0/`. A
platform seen for the first time therefore costs an authoring round, not a refusal.

## What the exit code obliges you to do

The driver distinguishes "no output" from "output you must not trust silently". Report the
distinction to the user rather than collapsing it to pass/fail:

| Exit | Meaning | What to do |
|---|---|---|
| 0 | migrated, no degradation detected | proceed |
| 3 | migrated **with degradation** — output exists and is loudly incomplete | proceed only after telling the user what degraded; the remediation brief names each item |
| 1 | failed, no usable output | do not proceed; report the stage that stopped and its stated cause |
| 2 | usage error | fix the invocation; no stage ran |

Exit 3 is not a warning to pass over. It means elements were lost, or emitted SQL carries
a sentinel a human must resolve, and the converted output would mislead anyone who read it
as complete.

## When conversion may be recorded as completed

An ETL unit on a platform with no native converter is unsupported when `source.platform`
is unset and `kind == "etl"`. The stated platform lives on `extensions.sourcePlatform`
(never faked as SSIS or Informatica). Do not run `scai code convert` for that unit.

Check beside the unit's output root for `Reports/AiFirstIssues/issues.json` and
`Reports/AiFirstRemediation/remediation-brief.json`.

**a. Remediation brief present.** A Stabilization profile can receive the unit next.
Advance conversion:

```
transition_status(status="advance", task="convert", outcome="completed", where="id = '<unit_id>'")
```

The MCP server also enforces this: `transition_status` with `task=convert` and
`outcome=completed` for an unlisted-platform ETL unit fails if no real
`remediation-brief.json` is on disk.

**b. Issues present but no remediation brief.** Fail loudly:

```
transition_status(status="advance", task="convert", outcome="failed", error="unsupported ETL platform: AI-First artifacts present but remediation brief missing", where="id = '<unit_id>'")
```

**c. Neither artifact present.** Fail loudly:

```
transition_status(status="advance", task="convert", outcome="failed", error="unsupported ETL platform: AI-First artifacts missing (no remediation brief)", where="id = '<unit_id>'")
```

Do not invent a conversion or a brief. An honest `failed` in (b) or (c) is correct.

## Handing off to Stabilization

AI-First writes a remediation brief indexing its Gate B obligations, integrity findings,
and AIM issues. That brief is what `etl-stabilization` consumes to repair emitted output;
it is the seam between the two actions. Do not attempt post-emission repair here — this
skill routes, and Stabilization repairs.

## Writing lineage into the Code Unit Registry

So the unit shows up in ObjectReferences CSV the same way an engine-converted unit's
dependencies do — that report is rebuilt generically from any unit's
`dependencies.dependsOn`.

1. Read `Reports/AiFirstLineage/lineage.json` beside this unit's output root (producer
   Stage 7, `lineage.py`). Its `sources` array lists the bare `(schema, table)` names
   this unit's emitted SQL reads via `source()`. If the file is absent or its stage
   logged `LINEAGE UNMEASURED`, skip this write — an absent report is not "no
   dependencies"; do not invent an empty array.

   That report is the only admissible evidence. Do not reconstruct the array from the
   emitted dbt project, its `sources.yml`, the seed CSVs, or the source document. Those
   show what you can read, not what the producer measured, and a dependency derived
   from them is fabricated even when it happens to be right.
2. For each `(schema, table)` pair, resolve it with `query_registry`. The emitter never
   invents a database/schema for a `source()` call.
   - Exactly one match: that entry's `id` is the dependency.
   - Zero matches: use the bare table name as `id` and set `"isMissing": true`. Do not drop it.
   - More than one match: do not guess; escalate.
3. Call once per unit, replacing (not merging) the array:

```
update_registry(field="dependencies.dependsOn", objects=["<unit_id>"],
                depends_on='[{"id": "<resolved_id>", "relationTypes": ["source"]},
                              {"id": "<bare_table_name>", "isMissing": true, "relationTypes": ["source"]}]')
```

Do not write `dependencies.dependsOn` from `lineage.json`'s `intra_project_refs` — those
are `ref()` calls between this unit's own emitted models.
