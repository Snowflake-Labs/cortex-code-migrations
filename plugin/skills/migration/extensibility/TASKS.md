# Customizing the migration plugin

The plugin walks each object through a sequence of tasks (register → convert → deploy → validate → ...). You can replace the skill that runs for any task with your own — useful when your team has a non-standard step (custom auth, in-house deploy tooling, extra validation, ...) without re-implementing the whole plugin.

This page is the contract you need: the list of overridable task ids, what each task is expected to do, and how to signal completion.

## How to override a task

Drop a `SKILL.md` under either path; the plugin loads it instead of the built-in skill the next time that task runs.

| Path | When to use |
|---|---|
| `<project_dir>/.scai/skills/<task_id>/SKILL.md` | Override scoped to a single project. Project-local overrides take precedence. |
| `$AIM_SKILL_EXT_DIR/<task_id>/SKILL.md` | Set `AIM_SKILL_EXT_DIR` to a directory you maintain (e.g. a shared internal skills repo). Used as a fallback when the project does not carry the override. |

Your override SKILL.md is loaded as a normal agent skill — write it the same way you would any other skill. There is no template to subclass and no required imports.

To check what's currently in effect, run:

```
migration_status(mode='extensions')
```

It returns the catalog of every overridable task, the default executor the plugin would use, and the path of any active override.

## How to exclude a task

Some tasks aren't relevant to every project. Disable one with the `configure` tool's `tasks` parameter — the plugin then treats it as `excluded` and follows the task's `excluded` branch instead of running it:

```
configure(tasks={"validateView": false})
```

The choice persists to `<project_dir>/.scai/config/plugin.yml` under `tasks.*`, so it holds across sessions.

- **Locked tasks can't be disabled.** Load-bearing steps are marked `locked` in the machine — `configure` rejects disabling them (the core setup steps, plus `registration`, `convert`, `deploy`, `etlStabilization`, `seedSynthetic`, `fixCode`).
- **Structural nodes can't be disabled.** Internal prompts, routers, and terminals have no executor to override — `configure` rejects attempts to exclude them too.

## Task catalog

Tasks fall into two categories: `setup` (one-time per project) and `main` (per-object migration). Below is every task id you can override; internal routing nodes and setup prompts are not listed.

<cat>

### `setup` (one-time per project)

| Task id | What it does |
|---|---|
| `midwayEntry` | Imports an existing pre-converted Snowflake project to be compatible with AIM projects. |
| `configureSourceConnection` | Configures the source database connection. |
| `configureGit` | Configures git integration (main branch + remote). |
| `registerCode` | Pulls source SQL into the project. |
| `convertCode` | Runs the source → Snowflake conversion. |
| `runAssessment` | Generates a migration assessment report. |
| `generateTestbed` | Builds the synthetic testbed for the workload (mine → validate → compile → generate). |

### `main` (per-object migration)

| Task id | What it does |
|---|---|
| `registration` | Register (or update) one object's source DDL (per-object). |
| `convert` | Converts one object via SnowConvert (per-object). |
| `etlStabilization` | Stabilizes a converted ETL code unit (SSIS, Informatica, ...) and validates the functionality. |
| `etlSeed` | Runs `scai test seed` to generate the per-unit ETL test YAML (pipeline + validation.tables) with the source/target table pairs filled from the Code Unit Registry write-dependencies; the agent fills index_columns and the user confirms before validation runs. |
| `etlValidate` | Runs `scai test etl-validate --platform <platform>` to compare source package output with the converted Snowflake output. |
| `seedSourceDb` | Captures test inputs from the source database. |
| `seedSynthetic` | Generates synthetic test inputs. |
| `seedScript` | Writes a BTEQ script's test YAML, resolving binding values and staging .IMPORT fixtures from the shell script that runs it via `scai test seed --bindings-from`; values that can't be resolved statically become `{ eval }` recipes or stay `__REPLACE_ME__` for manual fill, and bindings shared across scripts are hoisted to the global test_config.yaml. Requires the bteq binary on PATH. |
| `captureBaseline` | Captures a source object's output as a test baseline (procedures, functions, and BTEQ scripts). |
| `deploy` | Deploys one object to Snowflake. |
| `validateView` | Validates a deployed view against its source. |
| `migrateData` | Migrates data into a deployed table. |
| `validateData` | Validates migrated data against the source. |
| `runTests` | Runs the scai test suite for an object. |
| `extractRules` | Extracts reusable migration rules from a fix. |
| `applyRules` | Applies matched migration rules to an object. |
| `fixCode` | Diagnoses and fixes a failing object. |

</cat>

## Per-task contracts

Every entry below names the task id, what your override needs as input, and the signal that tells the plugin the task is complete. "Done when" is the only completion contract — once the listed condition holds, the plugin moves on.

> **Signaling completion via the registry.** Several tasks complete by updating the per-object registry entry. Use the `transition_status(action='advance', task='<task_id>', where=...)` MCP tool from your override skill — it stamps the correct fields and unblocks the next task. You do not need to write into the registry directly. Reads completed means: registryField.status = 'completed' (if status does not exist in registryField object, we take existence of the field as completion).

> **Signaling completion via session config.** Setup tasks that gather user choices complete by calling the `configure` MCP tool with the relevant field set (e.g. `configure(source_language='sqlserver')`). The plugin reads from the session config to know the task is done.

<cntrc>

### `setup` (one-time per project)

#### `midwayEntry`
- **Inputs:** An existing project tree containing pre-converted SQL.
- **Done when:** At least one file exists at `<project_dir>/snowflake/**/*.sql`.

#### `configureSourceConnection`
- **Done when:** Session config has `source_connection` set — call `configure(source_connection=...)`.

#### `configureGit`
- **Done when:** Session config has `git_main_branch` set — call `configure(git_main_branch=...)`.

#### `registerCode`
- **Inputs:** Either a configured source connection (extracted via scai) or a folder of `.sql` files to register as-is.
- **Done when:** At least one file exists at `<project_dir>/source/**/*.sql`.

#### `convertCode`
- **Inputs:** Registered source code from the `registerCode` task.
- **Done when:** At least one file exists at `<project_dir>/snowflake/**/*.sql`.

#### `runAssessment`
- **Inputs:** A converted project from the `convertCode` task.
- **Done when:** At least one file exists at `<project_dir>/**/multi_report*.html`.

#### `generateTestbed`
- **Inputs:** A converted, assessed workload with testbed mining artifacts under `artifacts/**/testbed/*.testbed.json`. A source connection is still required downstream.
- **Done when:** The generate deliverable exists at `testbed/generate/summary-view.json` (synthetic-data summary; CSVs + `manifest.json` land under `testbed/generate/data/`).

### `main` (per-object migration)

#### `registration`
- **Inputs:** Object id with source DDL available.
- **Done when:** Registry field `codeStatus.registration` reads completed.

#### `convert`
- **Inputs:** Registered object.
- **Done when:** Registry field `codeStatus.conversion` reads completed.

#### `etlStabilization`
- **Inputs:** A converted ETL code unit (converted artifacts + source definition resolved from its registry entry); its dependency tables deployed.
- **Done when:** Registry field `codeStatus.stabilization` reads completed.

#### `etlSeed`
- **Inputs:** Stabilized ETL unit deployed to Snowflake (deploy enforced via precondition).
- **Done when:** Registry field `codeStatus.etlSeed` reads completed.

#### `etlValidate`
- **Inputs:** ETL test YAML present (from etlSeed or hand-authored); ETL unit deployed to Snowflake and source/Snowflake connections configured — all enforced via preconditions.
- **Done when:** Registry field `codeStatus.etlValidate` reads completed.

#### `seedSourceDb`
- **Inputs:** Object that needs test inputs; configured source connection.
- **Done when:** Per-object YAML exists at `<project_dir>/artifacts/<id>/test/<name>.yml`.

#### `seedSynthetic`
- **Inputs:** Object that needs test inputs (no source connection required).
- **Done when:** Per-object YAML exists at `<project_dir>/artifacts/<id>/test/<name>.yml`.

#### `seedScript`
- **Inputs:** A converted BTEQ script unit; the shell script(s) that set its variables and run bteq (plus any invocation args); configured source connection; bteq binary installed.
- **Done when:** Per-object YAML exists at `<project_dir>/artifacts/<id>/test/<name>.yml`.

#### `captureBaseline`
- **Inputs:** Object with seed data; configured source connection.
- **Done when:** Procedures/functions: the per-object YAML exists (proc seeding captures the baseline into it). BTEQ: `extensions.tasks.captureBaseline` is set — `scai test capture` uploads the baseline to the Snowflake stage and writes no local artifact, so the YAML (which `seedScript` already wrote) cannot signal capture; the agent stamps this after running capture.

#### `deploy`
- **Inputs:** Converted SQL for the object.
- **Done when:** Registry field `cloudStatus.deployment` is set, or the deployed-object metadata exists in Snowflake.

#### `validateView`
- **Inputs:** Deployed view; configured source connection.
- **Done when:** Registry field `extensions.tasks.validateView` reads completed.

#### `migrateData`
- **Inputs:** Deployed table; configured source connection; completed data infrastructure setup.
- **Done when:** Registry field `extensions.dataMigration` reads completed.

#### `validateData`
- **Inputs:** Object with migrated data.
- **Done when:** Registry field `extensions.dataValidation` reads completed.

#### `runTests`
- **Inputs:** Object with a captured baseline; procedures and functions are also deployed first (BTEQ scripts are not).
- **Done when:** Registry field `codeStatus.testing` reads completed.

#### `extractRules`
- **Inputs:** A fixed object's diff (the change you want to make reusable).
- **Done when:** Registry field `extensions.tasks.extractRules` is set, or the object's converted SQL is unchanged since its last conversion.

#### `applyRules`
- **Inputs:** An object with outstanding issues that one or more migration rules apply to.
- **Done when:** Registry field `extensions.tasks.applyRules` is set.

#### `fixCode`
- **Inputs:** A failing object (compilation error, EWI, test failure).
- **Done when:** Registry field `extensions.tasks.fixCode` is set.

</cntrc>
