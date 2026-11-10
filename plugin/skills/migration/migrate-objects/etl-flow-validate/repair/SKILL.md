---
name: validate-etl-repair
description: Repair one converted ETL unit from a deploy or validation failure without entering stabilization.
license: Proprietary. See License-Skills for complete terms
---

# Validate ETL Repair

Repair one `kind=etl` unit from its exact deploy or ETL validation failure.
This is both a standalone entry point and the isolated `validateEtlRepair`
executor. It is not a router: do not load the live
`migrate-etl/SKILL.md`, SQL-object `migrate-object/DIAGNOSE_FIX.md`,
`rule-engine/apply/SKILL.md`, or any stabilization fixer.

Never stamp or reset `fixCode`, `applyRules`, or live-flow `etlValidate`.
When the machine dispatches this skill, follow the validate-only lifecycle in
Step 6: reset failed `validateEtlValidate`, then complete
`validateEtlRepair`. Those are the only task-status writes this skill owns.

## Contract

Required input:

- one ETL registry id (`ETL_ID`)
- the exact deploy or `scai test etl-validate` failure to repair
- the target connection and database when live deploy verification is requested

Use only current registry data, the failure, and canonical source and converted
files. Do not read or create `scan.json`, `ROADMAP.md`, `STATE.md`,
`test_report.md`, generated one-sided tests, phase files, or anything under
`<UNIT>/stabilization/`. Do not run `scan_unit.py`.

The source package is read-only. Edit converted artifacts only at paths named
by `parts[].target`, or at file-valued `files.converted.path` when `parts[]` is
empty. Never edit the registry to manufacture a missing target. ETL comparison
YAML may be edited only when the failure proves its comparison contract is
wrong.

## Step 1: Resolve the unit and failure

Query the registry for `id`, `kind`, `source`, `files`, `parts`, and
`codeStatus`. Stop with `not-applicable` if `kind` is not `etl`.

Use the recorded deploy failure, or the last `scai test etl-validate` output
and validation status, as the failure evidence. ETL validation does not produce
SQL-object `results.json`; do not enter the `runTests` path.

Build the repair worklist:

1. For every part whose `target.format == "dbt"`, include the dbt project
   folder at `target.path`.
2. For every part whose `target.format == "snowflakeSQL"`, include the SQL
   file at `target.path`.
3. When `parts[]` is empty, include `files.converted.path` only when it is a
   file. This supports ETL units emitted as Snowflake Scripting.
4. If a part has no target, report an unresolved conversion or deploy-routing
   gap. Do not infer or persist a target.

For an AI-First unit (`files.source.path` under `source/_etl_aifirst/`), read
what conversion recorded before choosing a model to touch:

- `extensions.aiFirst.models`: per generated model, its `tier` (1 engine, 2
  `SSC-AI-ASSISTED`, 3 `SSC-AI-AUTHORED`), `sourceElement`, `sourceLines` and
  project path. The map itself is at `extensions.aiFirst.elementMap`.
- The remediation brief, `reports/AiFirstRemediation/<unit>/remediation-brief.json`:
  each item's `lane`, `models`, `source_fragment` / `source_lines` (the
  element's own lines in the source document) and `intent_excerpt`. Its
  `pointers` are project-relative: Gate B verdict and obligations, integrity,
  the IR and the platform table are under `reports/AiFirstGates/<unit>/`.
- The source document is read-only. Read the failing element's lines, not the
  whole document.

## Step 2: Classify before editing

Read the run evidence before the comparison diff. For an `external_command`
source (a launcher), each run leaves
`<files.artifacts.path>/etl-test/runs/<run-id>/<unit>/status.json` and the
platform log beside it (`hop.log` for Hop); its `runtime` object records the time
zone the source ran in. The unit's `snowflake/_etl/<unit>/sink_writes.json`
names each sink's write mode and keys, and `clock_columns.json` its clock
columns. For an AI-First unit (`files.source.path` under `source/_etl_aifirst/`),
the platform table `actions/etl-aifirst/platforms/platform_<id>.json` (`<id>` as
in `convert/etl-aifirst/MIGRATE.md` Step 2) has a `runtime` block: how the
original platform's runtime treats time zones, which transforms keep state
across runs, which write wall-clock values (`wall_clock_transforms`, and
`wall_clock_functions` per expression transform), and which write a new value
on every run (`nondeterministic_transforms`).

Classify the exact failure in this order:

| Failure | Repair |
|---|---|
| `codeStatus.validateEtlValidate.error` is not `comparison` (`tooling`, `UNRESOLVED_BINDING_TOKEN`, `DEPENDENT_TABLE_MISSING`) | The machine does not dispatch these. Entered by hand, stop with `not-applicable` and relay the stop reason; do not edit. |
| `--check-env` failed | Stop. Surface the connection, credential, or platform-tooling error; do not edit conversion output. |
| A compared table is missing on either side (`not found or has no columns`, `does not exist`) | Environment or arrange: `not-applicable`. Name the table and the side; do not edit code or YAML. |
| The source launcher failed: `status.json` `status` is `FAILED`, `timed_out` or `canceled`, or the platform log shows an error | Source runtime: `not-applicable`. Quote the launcher message and the first log error; do not edit. |
| Only timestamp or date columns differ, each by the same whole-hour offset, and that offset matches the source run's `runtime.utc_offset` (or the source ran in a zone other than the target session's) | Source-runtime time zone: `needs-user`. Name the zone the source ran in (`runtime.time_zone`, `runtime.time_zone_source`) and the platform table's `runtime.time_zone.fix_for_user`. Never exclude the column, shift the model's values, or change the launcher's zone yourself. |
| The difference is only in rows a stateful sink held from an earlier run (its transform is listed under the platform table's `runtime.stateful_transforms`, or `sink_writes.json` gives it a keyed or versioned mode) | Arrange or runtime: `not-applicable`. Name the sink and the rows it carried over; do not edit the model or its macros. |
| `UPSTREAM_EMPTY`, `DATA_DRIFT`, or unresolved write-set | Repair ETL seed ordering, isolation, or write-set metadata; do not rewrite generated SQL or dbt. |
| YAML shape, `index_columns`, empty, or vacuous comparison | Edit the ETL test YAML only. Do not deploy. |
| dbt parse, compile, or execution error, including a deploy that failed with "the deployed dbt project does not build" (deploy builds an AI-First unit's models with no rows and names the first model that fails) | Repair the named model in the named dbt project (Step 2b decides whether it may be edited), then redeploy. |
| Deploy/CREATE error on a `snowflakeSQL` target | Edit only the failing `snowflakeSQL` target. |
| Comparison proves a converted-code defect | Repair the responsible canonical dbt or `snowflakeSQL` target. |
| A wall-clock or nondeterministic column: listed in the unit's `clock_columns.json` (its `reasons` say `clock` or `nondeterministic: <element>`), written by a transform the platform table lists under `runtime.wall_clock_transforms` or `runtime.nondeterministic_transforms`, computed by an expression transform from one of its `runtime.wall_clock_functions` alone, or recorded by the seed as a load-time default (the YAML header says which) | Exclude it on that table entry with `source_columns: {mode: exclude, list: [...]}` (and `target_columns` when the target name differs); do not rewrite code. The ETL YAML has no `excluded_columns` key. Only columns on those lists may be excluded: a difference on any other column is a finding to classify, never a column to drop. |
| Designed SSIS source failure whose message matches `expected_failure.message` | The runner already completed that source branch and continued comparison. Leave it. Do not stop with `needs-user`. |
| No exact failure, conflicting evidence, or multiple faithful interpretations | Stop with `needs-user`; ask one concrete question before editing. |

Name the root cause before making a change. If the evidence cannot distinguish
bad seed data, a comparison contract problem, and converted-code behavior, stop
with `needs-user` and the observed differences. An EWI marker alone is not
permission to guess source semantics.

## Step 2b: Decide the layer the fix belongs to (AI-First units)

When the classification is a converted-code defect in a model of an AI-First
unit, the model's tier (`extensions.aiFirst.models.<model>.tier`) decides what
this repair may do:

| Tier | Allowed | Not allowed |
|---|---|---|
| 1, engine-translated | If a brief item for the model or its element has lane `conversion_emitter` or `conversion_ir`, conversion lost a fact it held: stop with `return-to-convert`, naming the element id, the brief item id and the evidence. No edit. Otherwise a minimal edit is allowed, recorded as `engine-defect` (Step 6a) and listed for filing. | A silent hand patch: the next convert overwrites it and the engine defect stays hidden for every customer. |
| 2, engine model with a model-supplied payload (`SSC-AI-ASSISTED`) | The payload is the regenerable source (`<document>.ai.json` beside the source document), and this repair has no sanctioned writer for it. Edit the model, record it as `payload-hand-edit` with the payload correction that should be folded back. | Editing it as if it were model-authored, without naming the payload correction. |
| 3, model-authored (`SSC-AI-AUTHORED`) | Edit the model. Keep the header and add `-- Repaired       : validateEtlRepair attempt <n>: <one line>`. Then the Gate B recheck in Step 5. | Skipping the recheck. |

Reconvert discards tier-2 and tier-3 repairs: each is recorded (Step 6a) so it
can be folded into conversion, and the report lists it.

## Step 3: Repair dbt artifacts

For each affected dbt target:

1. Read `dbt_project.yml`, the active `profiles.yml` (project-local first,
   then an existing `--profiles-dir`), `models/sources.yml`, model SQL, macros,
   the source package, and the exact failure. Read neighboring generated
   projects only for established naming conventions.
2. Fix bootstrap defects first: invalid YAML or Jinja, unresolved placeholders,
   project/profile disagreement, invalid macros, and contradicted source
   declarations. The `profile:` key must name a stanza in `profiles.yml`.
3. Derive names only from the target path, existing project convention,
   registry destination, or explicit failure context. Repair non-secret
   `profiles.yml` fields only from that evidence. Do not write a password,
   token, or private key; preserve `env_var` or equivalent references. If a
   repair needs an unknown secret or name, stop with `needs-user`.
4. Preserve `ref()` and `source()` targets, comments, materialization, and the
   SnowConvert override layer unless the failure proves one is wrong. Never use
   constants, `NULL`, `WHERE FALSE`, deleted predicates, or weaker comparisons
   merely to make a command pass.
5. Run both preflight commands with the existing profile configuration:

   ```bash
   dbt parse --project-dir "<DBT_PROJECT_PATH>"
   dbt compile --project-dir "<DBT_PROJECT_PATH>"
   ```

   Use an existing `--profiles-dir` when required. Never create or print
   credentials. A pass proves only `ready-for-deploy`, not equivalence.

## Step 4: Repair orchestration SQL

For an editable SQL target:

1. Read the source context, the failed comparison, and the current target.
2. Search applicable rules using the primary deploy error or first
   difference.
3. Apply matching regex-mode rules mechanically and record each application.
   Skip AI-mode rules in this executor; semantic rewrites require an explicit
   diagnosis rather than stabilize-flow approval.
4. For a diagnosed conversion defect with no regex rule, make the smallest
   faithful edit to the canonical SQL file. Preserve source comments and
   provenance blocks.
5. Never add a blanket `GETDATE` to `CURRENT_TIMESTAMP` rule. Treat genuine
   wall-clock output as a comparison exclusion.

If the failing part or model carries an EWI or AIM code, resolve its guide:

```bash
python3 <migrate-objects>/actions/etl-stabilization/scripts/stabilization_tools.py \
  ewi-guide-resolve "<CODE>" [--platform <pack>]
```

An AIM code (`AIM-<FAMILY>-<digest>`) is per instance, so it resolves to its
family guide (`AIM-EMIT`, `AIM-EXPR`, `AIM-REPR`, `AIM-SHAPE`, `AIM-SEM`,
`AIM-REF`, `AIM-VAR`) under `actions/etl-stabilization/reference/ewi/`, with a
platform pack's own guide first when one exists. An engine code resolves to
`{CODE}.md`; also look under `rule-engine/resolving-ewis/reference`. Do not
create another reference tree or depend on an EWI MCP scan.

No matching regex rule and no diagnosed code defect is a valid no-op,
especially for a unit without SQL targets.

Preserve task dependencies, suspension behavior, procedure signatures, dbt
project references, tag boundaries, provenance comments, and unaffected SQL.
Do not comment out behavior or create stub tasks or procedures.

## Step 5: Verify the repair

- YAML-only repair: re-run `scai test etl-validate` for the unit.
- Tier-2 or tier-3 model edited (AI-First): before deploy, re-run Gate B for the
  edited models over the project's converted tree, into a new bundle beside the
  conversion's:

  ```bash
  python3 <migrate-objects>/actions/etl-aifirst/scripts/gate_b.py recheck \
    "<files.source.path>" "<files.converted.path>" \
    --bundle "reports/AiFirstGates/<unit>/gateB-recheck-<n>" \
    --models "<model>[,<model>...]" --platform "<platform>"
  ```

  It packs and verifies the tree exactly as conversion's Gate B did and passes
  only when every obligation on the named models is discharged (`recheck.json`
  in the bundle). A failing recheck is `failed`: the edit does not do what the
  source element says, whatever a comparison shows. The repair is done only
  when the recheck **and** the re-validation both pass.
- Converted-artifact repair with a connection and database: run
  `scai code deploy --where "id = '<ETL_ID>'" -c "<CONNECTION>" -d "<DATABASE>"`
  for all repaired parts together. Do not hand-deploy SQL or dbt objects.
- Validation repair: after successful deploy, re-run
  `scai test etl-validate` for the unit.
- Environment failure: do not run comparison until the pre-flight succeeds.

## Step 6a: Record the attempt

Every dispatch is one attempt, whatever its outcome. The machine counts
attempts at `extensions.tasks.validateEtlRepair.attempts` and allows two per
unit (the project can change that in `plugin.yml`; never edit it from a
repair); once they are used, a further failed validation stops for the user
instead of dispatching this skill again. The count restarts when the unit's
validation passes, the records do not: `<n>` is the next number with no
`repair/attempt-<n>.json` yet.

Before any write-back, write `<files.artifacts.path>/repair/attempt-<n>.json`:

```json
{"unit": "<ETL_ID>", "attempt": <n>, "failure_class": "<codeStatus.validateEtlValidate.error>",
 "classification": "<the Step 2 row>", "root_cause": "<one sentence>",
 "action": "none | yaml | model | return-to-convert",
 "files": [{"path": "<project-relative>", "tier": 1, "layer": "engine-defect | payload-hand-edit | model-authored | yaml",
            "lines_changed": 0}],
 "checks": [{"check": "dbt parse | dbt compile | gate_b recheck | deploy | etl-validate", "result": "pass | fail"}],
 "status": "<the Step 7 status>", "fold_into_conversion": "<the change conversion should make, or null>"}
```

and append an entry to `<files.artifacts.path>/repair/fix-log.md` in the
`fix-log-format.md` row form (`actions/etl-stabilization/reference/templates/`),
one row per changed file with its `fix-log-entry` comment. An attempt that
changed nothing still gets its record: "no edit, because ..." is the result.

## Step 6: Return validation to the machine

After the repair is verified enough to return `ready-for-validation`, clear
the failed comparison before completing repair:

1. Call `transition_status(status="reset", task="validateEtlValidate",
   where="id = '<ETL_ID>'")`.
2. Confirm `codeStatus.validateEtlValidate` is pending.
3. Call `transition_status(status="advance", task="validateEtlRepair",
   outcome="completed", where="id = '<ETL_ID>'")`.
4. Confirm the response reports retryable `validateEtlValidate`. If it does
   not, stop with `failed`; do not stamp or reset another task to force it.

A repaired **deploy** failure has no validation stamp to reset: skip steps 1
and 2, advance `validateEtlRepair` `completed` once the scoped deploy succeeds,
then call `next_task`; the walk resumes at the first unfinished task (usually
`validateEtlSeed`).

The completed transition returns the object to retryable
`validateEtlValidate`. Never reverse these calls: a completed repair with a
failed validation stamp would route straight back into repair. For
`ready-for-deploy`, `not-applicable`, `needs-user`, `return-to-convert`, or
`failed`, do not reset validation and do not complete repair; close the attempt
with `transition_status(status="advance", task="validateEtlRepair",
outcome="failed", where="id = '<ETL_ID>'")`, which counts it and stops the
walk, and report the status.

Do not reset `validateEtlRepair`. Its machine status is attempt-scoped to
`codeStatus.validateEtlValidate`: each newer validation attempt automatically
re-arms repair if that attempt fails.

## Step 7: Report and stop

Return exactly one status:

- `ready-for-deploy`: local dbt preflight or another local check passed, but
  live deploy was not run
- `ready-for-validation`: scoped deploy completed for every targeted part
- `not-applicable`: the failure belongs to environment, seed/arrange, routing,
  or another non-repair surface
- `needs-user`: a faithful repair requires missing intent or configuration
- `return-to-convert`: the defect is in engine output conversion should
  regenerate (Step 2b); name the element id and the brief item
- `failed`: a repair or required verification command still fails

Report the ETL id, root cause, files changed, checks and results, unresolved
EWIs, assumptions, and exact next command. A partial multi-part result is
`failed`.

Never claim the pipeline is verified from parse, compile, or deploy. Only a
later non-vacuous `scai test etl-validate` run establishes functional
equivalence. Do not invent task completion when the CLI or registry still
reports failure.
