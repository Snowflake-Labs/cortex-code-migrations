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
| Alteryx (`.yxmd`), Azure Data Factory, DataStage (`.dsx`), Hop (`.hpl`/`.hwf`), Pentaho (`.ktr`/`.kjb`) | AI-First action | no native converter |
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

For a new run, take the source document from the unit's `files.source.path`, then hand it
to the action's driver. Follow [MIGRATE.md](MIGRATE.md) Steps 3 and 4 exactly; from the
project directory they are:

```bash
STAGE=$(mktemp -d)
export AIFIRST_TESTBED_PROJECT="$PWD"
"<skill_root>/migrate-objects/actions/etl-aifirst/scripts/aifirst-migrate.sh" \
  --platform <platform-identity> \
  "$PWD/<files.source.path>" \
  "$STAGE" 2>&1 | tee "logs/aifirst-<PACKAGE>.log"
```

`<output-root>` is always that staging directory, never `snowflake/_etl/<PACKAGE>`: the
driver writes `$STAGE/Output/ETL/<PACKAGE>/` and `$STAGE/Reports/`, and refuses (exit 2)
an output root under `snowflake/_etl/`. Then run the whole `REPORT-COPY` block of
MIGRATE.md Step 4 unchanged. It is what copies
`"$STAGE/Output/ETL/<PACKAGE>"` into `"snowflake/_etl/<PACKAGE>"` (flat: the dbt project
and orchestration SQL directly under the unit folder) and the reports into `reports/`,
verifies every file, and removes `$STAGE`. Only then write `files.converted.path`.

Checked-in identities: `adf`, `alteryx`, `datastage`, `hop`, `informatica`, `pentaho`, `ssis`.
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

An ETL unit on a platform with no native converter is unsupported when `kind == "etl"` and
`source.platform` is unset or an AI-First platform (`apacheHop`). The stated platform lives on
`extensions.sourcePlatform` (never faked as SSIS or Informatica). Do not run `scai code convert` for that unit.

Check beside the unit's output root for `Reports/AiFirstIssues/issues.json` and
`Reports/AiFirstRemediation/remediation-brief.json`.

## Record where the output landed, before advancing conversion

Registration wrote `files.source.path`. Conversion owns the other two pointers, and
until they are set the unit is converted on disk and invisible to everything that
runs after convert:

- **Deploy cannot see it.** `IsDeployable()` returns false on an empty
  `files.converted.path`, so the unit is dropped from the deploy batch with a log
  line and no run-level error.
- **The test seed and `scai testbed init` cannot find its output.** Both locate
  per-unit artifacts through `files.artifacts.path`; the seed emitter skips with
  `NoArtifactsPath`, and testbed init returns success having done nothing.
- **`finish_objects` will not land the generated tree.** It stages
  `files.{source,converted,artifacts}.path` and **silently skips** whichever
  sub-field is absent, so the commit carries `registry/<id>.json` without the dbt
  project it describes.
- **A native re-convert will overwrite it without warning.** The guard that warns
  "converting replaces the AI-First output already written" tests
  `files.converted.path` first and returns false when it is empty.

Write both as soon as the output tree exists, using the paths the copy step above
produced:

```
update_registry(field="files.converted.path", status="snowflake/_etl/<PACKAGE>", objects=["<unit_id>"])
update_registry(field="files.artifacts.path", status="artifacts/etl/<PACKAGE>", objects=["<unit_id>"])
```

Both are **project-relative** — every consumer joins them against the project
directory, and `update_registry` refuses an absolute path rather than normalizing
one.

Do this **before** `transition_status`, not after. A unit that carries
`files.source.path` while `files.converted` is still unset matches the orphaned-ETL
predicate in `load_units`: if its vendored source document is missing — cleaned,
moved, or recorded against the wrong root — the row is dropped from every query,
and with it the wave graph, `next_objects` and the dashboard. Setting
`files.converted.path` takes the unit out of that shape permanently.

If the conversion failed, write neither. A half-populated unit claims output that
does not exist, which is worse than one that plainly has none — the same reason
this skill never writes an empty `dependencies.dependsOn` array.

## Record the unit's parts

An ETL unit is **one** code unit whose generated artifacts are `parts[]` inside it —
never separate units. This is the structure the rest of the migration hangs off, and
it is not optional decoration:

- **Deployment cannot be represented without it.** Root `cloudStatus` is
  schema-forbidden on `kind: etl`, so deployment and testing status can only live at
  `parts[].cloudStatus`. A unit with no parts has nowhere to record either.
- **Deploy produces nothing to deploy.** The native deploy path builds one deployable
  item per part from `parts[*].{id,name,target.format,target.path}`. Its empty-parts
  fallback only covers `format == "snowflakeSQL"` and is scoped away from dbt by
  design, so a dbt unit with no parts yields zero deployable items.

**Do not assemble the parts payload by hand — derive it with the script.** Run:

```bash
python3 <action>/scripts/derive_parts.py \
  --output-root snowflake/_etl/<PACKAGE> \
  --project-dir . \
  --issues reports/AiFirstIssues/<PACKAGE>/issues.json
```

It prints the exact JSON array to pass through:

```
update_registry(field="parts", objects=["<unit_id>"], value=<the script's output>)
```

Pass the output verbatim. It reads the emitted dbt tree — one `dataFlow` part per
dbt **project** (its `target.path` is the project directory, which is what
`scai code deploy` deploys), one `controlFlow` part for the orchestration SQL beside
the project — rolls the EMIT findings that name a generated file up onto that part's
`issues[]`, sorts deterministically so re-running produces a byte-identical payload, and
emits `[]` rather than failing when nothing was emitted (a legal CUR state meaning
"no parts yet", though it warns on stderr because an empty conversion is far more
likely a defect than a job with no models). The PACKAGE root is the right
`--output-root` even when Step 4 copied the driver tree as
`<PACKAGE>/<PACKAGE>/models` (native `_etl` layout). Do not point `--output-root`
at the inner dbt directory — that drops the orchestration SQL sitting beside the
package.

`name` is the **stability key** — the writer matches on it to carry a part's `id`
forward across conversion passes, so re-deriving does not churn ids. You never supply
`id`; the writer mints one for a genuinely new part. `modelName` is only legal when
`format == "dbt"` and is refused otherwise.

The script reads the **emitted tree**, not the `ETL.Elements` census, on purpose:
the census's `FullName` is a source element *id* (`'6'`), so joining it to a model
would mean re-deriving `model_name`, which is table-driven per platform
(`naming_policy`) and already drifted once in this codebase. The emitted tree is what
those rules produced, so reading it cannot disagree with them. The census remains the
right source for which elements exist and how they fared — that belongs in the
stakeholder report, not the part list.

The writer also carries forward each matched part's existing `dependencies`, `issues`
and `cloudStatus` unless you state them explicitly, so a structure-only rewrite cannot
wipe per-part deployment status or lineage. An explicitly stated value always wins, so
clearing something remains possible — pass `"issues": []` to mean empty, not absent.

If a part has no `target.path`, the write still succeeds but reports a warning naming
it: consumers that route on `target.objectType` skip such parts silently, so treat the
warning as a defect in the parts derivation rather than noise.

## Record each model's tier and source element

Parts stay one per dbt project (that is what deploy deploys), so the per-model facts a
repair needs go on the unit. The driver wrote
`reports/AiFirstElementMap/<PACKAGE>/element_map.json`: for every generated model, who
wrote it (tier 1 engine, tier 2 `SSC-AI-ASSISTED`, tier 3 `SSC-AI-AUTHORED`), the source
element it stands for and that element's lines in the source document. Write it through:

```bash
python3 <action>/scripts/element_map.py --cur-extension \
  reports/AiFirstElementMap/<PACKAGE>/element_map.json --package-root snowflake/_etl/<PACKAGE>
```

```
update_registry(field="extensions.aiFirst", objects=["<unit_id>"], value=<the script's output>)
```

Pass the output verbatim. A model with `sourceElement: null` (an error route the
emitter synthesised, for example) is stated as such; never fill it in by hand. When the
map is absent (an older run, or the driver could not build it) skip the write and say so.

## Record per-part lineage

Per-part dependencies are the ground truth; the unit-level array is a rollup derived
from them. Write them inside the part objects above:

```
"dependencies": {"dependsOn": [{"id": "<resolved unit id>", "relationTypes": ["SELECT"]}]}
```

Do **not** set `isMissing` — the writer resolves it against the live registry and
overwrites whatever you pass, for per-part and unit-level edges alike.

Keep writing the unit-level `dependencies.dependsOn` as well while parts coverage is
still growing per platform, so a unit with no parts yet is not left with no lineage at
all. Both writes are refused unless a real `lineage.json` is on disk — the gate exists
because resolving a bare table name to a registry id is a judgement call the driver
cannot make deterministically, so the one thing that *can* be enforced is that you
read a real lineage report instead of inferring edges. If the driver produced no
lineage report, write no dependencies. Hop sink writes (next section) merge
into that same array; they do not replace the gate.

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

**Hop / `apacheHop` POC:** there is no named Hop pack. Do **not** start
`platforms/unsupported/` acting-loop work (unfiled I-36) and do not run
`dbt-fixer` against a Hop tree to invent one. An AI-First unit takes the validate-first
route (`etl_flow=validate`) whatever the project's `etl_flow`: after convert the machine routes the unit to
deploy, then `validateEtlSeed`, then `validateEtlValidate`
(`scai test etl-validate --platform apacheHop`). A comparison failure (or an
ETL deploy failure) is then dispatched to `validateEtlRepair`, the test-fix
loop that reads this unit's brief, element map and gate evidence; other
failure classes stop with their reason. Never write
`etlStabilization` status yourself — not completed, not excluded, not
skipped; the machine owns which ETL tasks run. Validate uses the generic
`external_command:` opt-in, not a native `hop-run` executor. scai ships the
launcher: the command is `python3 "{launchers_dir}/hop_run_launcher.py" ...`,
where scai fills `{launchers_dir}`; never point it at a repository path. The
block goes in the **project** `.scai/settings/test_config.yaml` (full recipe in
`etl-seed` Step 0b). `HOP_HOME` (or `HOP_RUN`), `HOP_JAVA_HOME` (Java 17+ for
Hop 2.x), `HOP_PROJECT` and `HOP_ENVIRONMENT` go under `env:` because the
child does not inherit the harness environment.

## Writing lineage into the Code Unit Registry

So the unit shows up in ObjectReferences CSV the same way an engine-converted unit's
dependencies do — that report is rebuilt generically from any unit's
`dependencies.dependsOn`.

1. Read `Reports/AiFirstLineage/lineage.json` beside this unit's output root (producer
   Stage 7, `lineage.py`). Its `sources` array lists the bare `(schema, table)` names
   this unit's emitted SQL reads via `source()`; `schema` is the one the generated
   `sources.yml` declares (the source document's own qualifier, e.g. `DBO`), else the
   dbt source name. If the file is absent or its stage
   logged `LINEAGE UNMEASURED`, skip this write — an absent report is not "no
   dependencies"; do not invent an empty array.

   That report is the only admissible evidence **for reads**. Do not reconstruct the
   `source()` array from the emitted dbt project, its `sources.yml`, the seed CSVs,
   or the source document. Those show what you can read, not what the producer
   measured, and a dependency derived from them is fabricated even when it happens
   to be right.
2. For each `(schema, table)` pair, resolve it with `query_registry` by table name:
   match the registry's `source.name` case-insensitively
   (`where="source.name ILIKE '<table>'"`). The pair's `schema` is the dbt `source()`
   group the emitter wrote (often `raw`), not the registry's schema, so a match whose
   schema differs is still that table; do not reject it for the schema. The emitter
   never invents a database/schema for a `source()` call.
   - Exactly one match: that entry's `id` is the dependency.
   - Zero matches: use the bare table name as `id` and set `"isMissing": true`. Do not drop it.
   - More than one match: do not guess; escalate.
3. **Hop writes.** `lineage.json` does not measure Hop sinks (TableOutput,
   Insert/Update, Update, Delete, Synchronize after merge, Dimension and
   Combination lookup/update). If `files.source.path` is a Hop `.hpl` / `.hwf`,
   also run:

   ```bash
   python3 <action>/scripts/hop_write_deps.py --source <files.source.path>
   ```

   Merge each edge into the same `dependsOn` array with its `relationTypes`
   exactly as printed (INSERT, UPDATE, DELETE), using the same
   `query_registry` resolution as step 2 (canonical names already live on the
   SQL-extracted table unit). Do not drop the source() edges. Do not mint a
   table unit. A missing sink stays in the array with `isMissing: true`. Skip a
   transform the helper omitted (`tablename_in_field=Y`, empty `<table>`, a
   lookup that does not update). This is not a miner TABLE factory and not
   Formula binding.
4. Call once per unit, replacing (not merging) the assembled array:

```
update_registry(field="dependencies.dependsOn", objects=["<unit_id>"],
                depends_on='[{"id": "<resolved_id>", "relationTypes": ["source"]},
                              {"id": "<sink_id>", "relationTypes": ["INSERT"]}]')
```

Do not write `dependencies.dependsOn` from `lineage.json`'s `intra_project_refs` — those
are `ref()` calls between this unit's own emitted models.
