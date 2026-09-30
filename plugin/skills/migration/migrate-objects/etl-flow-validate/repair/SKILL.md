---
name: validate-etl-repair
description: Repair one converted ETL unit from a deploy or validation failure without entering stabilization.
license: Proprietary. See License-Skills for complete terms
---

# Validate ETL Repair

Repair one `kind=etl` unit from its exact deploy or ETL validation failure.
This is both a standalone entry point and the isolated future
`validateEtlRepair` executor. It is not a router: do not load the live
`migrate-etl/SKILL.md`, SQL-object `migrate-object/DIAGNOSE_FIX.md`,
`rule-engine/apply/SKILL.md`, or any stabilization fixer.

Do not call `transition_status` or stamp `fixCode`, `applyRules`, `etlValidate`,
or `validateEtlRepair`. The machine owns retry and status transitions when it
eventually dispatches this skill.

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
and validation status, as the failure oracle. ETL validation does not produce
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

## Step 2: Classify before editing

Classify the exact failure in this order:

| Failure | Repair |
|---|---|
| `--check-env` failed | Stop. Surface the connection, credential, or platform-tooling error; do not edit conversion output. |
| `UPSTREAM_EMPTY`, `DATA_DRIFT`, or unresolved write-set | Repair ETL seed ordering, isolation, or write-set metadata; do not rewrite generated SQL or dbt. |
| YAML shape, `index_columns`, `excluded_columns`, empty, or vacuous comparison | Edit the ETL test YAML only. Do not deploy. |
| dbt parse, compile, or execution error | Repair the named dbt project. |
| Deploy/CREATE error | Edit only the failing `snowflakeSQL` target. |
| Comparison proves a converted-code defect | Repair the responsible canonical dbt or `snowflakeSQL` target. |
| Clock-derived value such as `DepreciatedAt` | Add the column to YAML `comparison.excluded_columns`; do not rewrite code. |
| No exact failure, conflicting evidence, or multiple faithful interpretations | Stop with `needs-user`; ask one concrete question before editing. |

Name the root cause before making a change. If the evidence cannot distinguish
bad seed data, a comparison contract problem, and converted-code behavior, stop
with `needs-user` and the observed differences. An EWI marker alone is not
permission to guess source semantics.

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

If the failing part contains an EWI code, glob `{CODE}.md` under
`rule-engine/resolving-ewis/reference` and
`actions/etl-stabilization/platforms/*/ewi`. Use an existing reference when
present; do not create another reference tree or depend on an EWI MCP scan.

No matching regex rule and no diagnosed code defect is a valid no-op,
especially for a unit without SQL targets.

Preserve task dependencies, suspension behavior, procedure signatures, dbt
project references, tag boundaries, provenance comments, and unaffected SQL.
Do not comment out behavior or create stub tasks or procedures.

## Step 5: Verify the repair

- YAML-only repair: re-run `scai test etl-validate` for the unit.
- Converted-artifact repair with a connection and database: run
  `scai code deploy --where "id = '<ETL_ID>'" -c "<CONNECTION>" -d "<DATABASE>"`
  for all repaired parts together. Do not hand-deploy SQL or dbt objects.
- Validation repair: after successful deploy, re-run
  `scai test etl-validate` for the unit.
- Environment failure: do not run comparison until the pre-flight succeeds.

## Step 6: Report and stop

Return exactly one status:

- `ready-for-deploy`: local dbt preflight or another local check passed, but
  live deploy was not run
- `ready-for-validation`: scoped deploy completed for every targeted part
- `not-applicable`: the failure belongs to environment, seed/arrange, routing,
  or another non-repair surface
- `needs-user`: a faithful repair requires missing intent or configuration
- `failed`: a repair or required verification command still fails

Report the ETL id, root cause, files changed, checks and results, unresolved
EWIs, assumptions, and exact next command. A partial multi-part result is
`failed`.

Never claim the pipeline is verified from parse, compile, or deploy. Only a
later non-vacuous `scai test etl-validate` run establishes functional
equivalence. Do not invent task completion when the CLI or registry still
reports failure.
