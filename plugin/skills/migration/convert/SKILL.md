---
name: convert
description: Convert source code to Snowflake SQL using Snowflake's deterministic code conversion engine. Transforms full-migration sources and code-conversion-only sources to Snowflake-compatible syntax, and optionally repoints Power BI reports and Tableau workbooks. Triggers: convert, snowconvert, transform code, convert to snowflake, power bi, tableau.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# Code Conversion

## On Entry

Tell the user:
> **Code Conversion.**
>
> Here's what I'll do:
> 1. Run the deterministic code conversion engine against your source SQL files, transforming each into Snowflake SQL syntax (optionally tailoring conversion settings to your source first, or going with defaults).
> 2. Generate reports flagging anything that needs manual review (EWIs, FDMs, performance remarks, out-of-scope items).
> 3. Save converted code under `snowflake/`; conversion reports are available through AIM Assessment.

That message announces the conversion; it does not end the turn. Go straight on to
Step 1 in the same turn, and keep going until `scai code convert` has returned its
envelope or a step below says to ask or to end the turn. Saying the
conversion is running is not running it: the conversion itself asks the user nothing, so a
turn that ends here leaves setup stalled.

Convert source code to Snowflake SQL using the deterministic code conversion engine.

Report the result from the `--json` envelope and hand off. Reading the generated
reports, counting EWIs by severity or judging what needs fixing is the
assessment's job — do that here only if the user asks a direct question.

## Prerequisites

- Migration project initialized (`scai init`)
- Source SQL in `source/` **or** ETL to convert:
  - native ETL under `source/_etl/` (SSIS `.dtsx` or Informatica PowerCenter XML repo export), or
  - AI-First ETL registered in the Code Unit Registry with `kind: etl` and the source
    document vendored under `source/_etl_aifirst/<platform>/` (unlisted platforms live
    on `extensions.sourcePlatform` — never faked as SSIS or Informatica)
  **or** Tableau repointing with `TABLEAU_PATH` set (Tableau-only is allowed with an empty `source/`; Step 3.5 applies the dialect gate). An AI-First-ETL-only project is also allowed — Step 2 will detect it via `query_registry` and Step 4 skips `scai code convert`.

## Workflow

### Step 1: Verify Source Code Exists

Confirm `source/` contains `.sql` files (use whichever portable form fits the host). Note whether SQL is present; do not stop yet.

If `source/` has no `.sql` files, continue to Steps 2–3.5. After those steps, if there
is still no SQL **and** `TABLEAU_PATH` is unset **and** `PBIT_PATH` is unset **and**
`<AIFIRST_ETL_PATH>` is unset **and** `query_registry(where="kind = 'etl' AND
extensions.sourcePlatform IS NOT NULL")` returns no units, return to the parent setup
skill so it can re-query `progress_setup()`. Tableau-only conversions (Step 3.5 sets
`TABLEAU_PATH`) and AI-First-ETL-only projects (Step 2 sets `<AIFIRST_ETL_PATH>` from
the registry) are allowed with an empty `source/` — do not bounce back to setup in
those two cases.

### Step 1.5: dbt Fast-Path

A dbt workload was routed here from the dbt branch of the Setup machine. Detect it
deterministically — `dbt_project.yml` lands in `source/` when the dbt project is added
(via `scai code add`) — and shortcut the generic conversion questions:

> If `source/dbt_project.yml` exists (a dbt Jinja project), this is a **dbt conversion**.
> Skip Steps 2, 3, and 3.5 entirely (no ETL, no Power BI, no custom settings) and run
> the dbt-specific conversion in Step 4:
> ```bash
> scai code convert --dbt --json
> ```
> The `--dbt` flag is an internal engine detail, never surfaced — the Jinja tokenization,
> translation, and restoration all happen inside the engine. Repointed models land in
> `snowflake/models/`. After a successful envelope, the Setup machine routes to the dbt
> repointing skill for agentic YAML/macro refinement.

If `source/dbt_project.yml` does **not** exist, continue to Step 2 normally.

### Step 2: Check for ETL Code

**Skip this entire step if `source/dbt_project.yml` exists** (see Step 1.5). A dbt workload has no
SSIS or Informatica packages — do not ask any ETL question, go straight to Step 4.

ETL in this project reaches convert through one of two roots, kept apart on purpose:

- **Native ETL** — `source/_etl/`. Populated by `scai code add` during register. Only
  SSIS `.dtsx` and Informatica PowerCenter XML repo exports live here; the native
  `EtlFileClassifier` is what fills it and is deliberately not widened for other
  platforms.
- **AI-First ETL** — vendored under `source/_etl_aifirst/<platform>/` and registered
  in the Code Unit Registry with `kind: etl`, `source.objectType: workflow`, and the
  stated platform on `extensions.sourcePlatform`. Written by the register skills'
  `import_aifirst_etl.py` helper (lossless copy + enumeration) and the MCP
  `create_registry_unit` tool the register skill calls once per source document
  (Talend, Alteryx, Informatica Cloud / IICS, DataStage, Pentaho, Azure Data Factory,
  or anything else the user names).

**Read both.** Check `source/_etl/` for a native platform, then ask the Code Unit
Registry for AI-First platforms:

```
query_registry(
  where="kind = 'etl' AND extensions.sourcePlatform IS NOT NULL",
  fields="id,kind,source,files,extensions"
)
```

It is valid for a project to have one, both, or neither. There is no side manifest;
the registry is the system of record.

> **Fail closed on dual-classified files.** A `.dtsx` sitting under
> `source/_etl_aifirst/` or a `.yxmd` sitting under `source/_etl/` means register got
> the routing wrong. Stop and tell the user which files land under the wrong root
> rather than converting them twice or picking one arbitrarily. Do not silently
> reclassify.

Classify the **native** ETL platform from the files when extensions are decisive —
`.dtsx` is **SSIS**, Informatica PowerCenter repo export is XML. If the files under
`source/_etl/` are ambiguous, ask via `ask_user_question` (`multiSelect = false`):

> "Which ETL platform is the native ETL code from?"
>
> 1. **SSIS**
> 2. **Informatica Power Center**

- If `source/_etl/` is **missing or empty**, skip the native ETL prompts.
- If it contains **SSIS** (`.dtsx`), do not route it to AI-First. Follow [references/ssis-target.md](references/ssis-target.md) before any dbt question. It asks dbt or Snowflake Scripting, sets `SSIS_SCRIPTING_MODE` for Step 4 when Snowflake Scripting is chosen, and loads `../dbt-consolidation/SKILL.md` for dbt.
- If it contains **Informatica PowerCenter** XML, ask the remaining ETL questions up front, in one sequence, before running the conversion:
    1. Conversion target, via `ask_user_question` (`multiSelect = false`):
       > "How should Informatica PowerCenter mappings be converted?
       > 1. **dbt**: each mapping becomes a dbt model orchestrated by Snowflake Tasks. Supports ETL stabilization and deploy.
       > 2. **Snowflake Scripting** (Preview): each mapping becomes a standalone Snowflake stored procedure the Task graph calls. Stabilization and deploy are skipped for this preview flavor."
       Do not label either option recommended.
    2. If the answer is **dbt** and SSIS is absent or chose Snowflake Scripting, load `../dbt-consolidation/SKILL.md`. For Informatica with no dbt SSIS it asks one question: consolidate dbt projects and models by folder, or generate 1 project per mapping. Return here when complete. When SSIS also chose dbt, the SSIS bullet above loads `dbt-consolidation` once after both answers.
    3. If the answer is **Snowflake Scripting**, set `SCRIPTING_MODE = true` for Step 4. Do **not** load `dbt-consolidation`.

    Persist the choice with the MCP `configure` tool: `etl_informatica_target = "dbt"` or `"scripting"`. When the target is Snowflake Scripting, the `--informatica-to-snowflake-scripting` convert flag in Step 4 additionally records the project-level `etl_target` in `project.yml` that gates the scripting-preview routing.

    These questions are still required: the conversion target is not something `scai code add` can infer from the imported files. **Informatica Cloud / IICS is a different platform** — it is AI-First, not native, and the two Informatica flavors must not share this prompt.

Then handle the AI-First ETL side. If `query_registry` returned one or more `kind:
etl` rows with `extensions.sourcePlatform` set, set `<AIFIRST_ETL_PATH> =
source/_etl_aifirst/` and keep the returned rows for Step 4.5: each row carries the
`id`, the platform on `extensions.sourcePlatform`, and the vendored source at
`files.source.path`. Common platforms you will see include **Talend**, **Alteryx**
(`.yxmd`), **Informatica Cloud / IICS**, **DataStage** (`.dsx`), **Pentaho** (`.ktr`
/ `.kjb`), and **Azure Data Factory**, but any other name the user typed is valid —
Step 4.5 passes it through.

If the registry has no AI-First ETL rows but the user tells you mid-conversation that
they have an unsupported ETL platform, load
`../register-code-units/add-code-units/SKILL.md` (Step 4, option 4) to run the copy
helper and call `create_registry_unit`, then come back here. Do not stash a raw
external path as `<AIFIRST_ETL_PATH>` — the register step is where paths get vendored
into the project.

If neither root has ETL, proceed to Step 3 with no ETL to convert.

### Step 2.5: Optional database-ingestion config

Skip this step unless Step 2 found SSIS or Informatica. Load [./etl-database-ingestion-config/SKILL.md](./etl-database-ingestion-config/SKILL.md) and return here when it finishes. That skill returns only after the user skips or the on-disk config validates, so Step 3 starts from a file conversion can read.

### Step 3: Check for Power BI Reports

Read `source_language` and `has_power_bi` from `configure()` (set upfront by the `chooseMigrationExtras` multi-select). Snowflake is validation-only, so skip this step for a Snowflake source and leave `PBIT_PATH` unset.

- If `has_power_bi` is **`false`** (explicitly): skip to Step 3.5. `PBIT_PATH` stays unset.
- If `has_power_bi` is **`true`** (explicitly): user confirmed they have Power BI reports — load `../powerbi-repointing/SKILL.md` immediately. It collects `PBIT_PATH` and tells you to append `--powerbi-repointing <PBIT_PATH>` to the convert command in Step 4. Return here when complete.
- If `has_power_bi` is **not set** (re-entry or legacy session): **do not ask yet** — defer to the batched question in Step 3.6 so extras and settings appear together.

### Step 3.5: Check for Tableau Workbooks (Oracle and SQL Server)

Read `source_language` from `configure()`. Tableau repointing is supported when `source_language` is **Oracle** or **SqlServer** (compare case-insensitively). If it is any other dialect, skip this step: `TABLEAU_PATH` stays unset; do not pass `--tableauRepointing`.

If it **is** Oracle or SqlServer, read `has_tableau` from `configure()`:

- If `has_tableau` is **`false`** (explicitly): skip to Step 3.6. `TABLEAU_PATH` stays unset.
- If `has_tableau` is **`true`** (explicitly): user confirmed they have Tableau workbooks — load `../tableau-repointing/SKILL.md` in path-only mode. It collects `TABLEAU_PATH` and tells you to append `--tableauRepointing <TABLEAU_PATH>` to the convert command in Step 4. Return here when complete.
- If `has_tableau` is **not set** (re-entry or legacy session): **do not ask here.** Step 3.6 hands it to setup's prompt.

### Step 3.6: Offer Custom Conversion Settings (+ batch any unasked extras)

Read `tailor_conversion_settings` from `configure()` (set upfront by the `chooseConversionSettings` setup prompt):

- If `tailor_conversion_settings` is **`false`** (explicitly) **and** both `has_power_bi` and `has_tableau` are already set: `<SETTINGS_FLAGS>` stays empty; proceed to Step 4. Do not ask, unless the user has asked in this conversation for custom settings or a specific conversion flag: then follow [Changing Conversion Settings Later](#changing-conversion-settings-later) before Step 4.
- If `tailor_conversion_settings` is **`true`** (explicitly) **and** both extras flags are already set: skip the settings question and load `./recommend-settings/SKILL.md` immediately. Store the returned flag string as `<SETTINGS_FLAGS>` for Step 4. If the user declines all suggestions, the catalog can't be loaded, or `source/` is empty (Tableau-only), leave `<SETTINGS_FLAGS>` empty. Return here when complete.
- If **any** of `has_power_bi`, `has_tableau`, or `tailor_conversion_settings` is **not set**, do **not** ask. Do not compose an `ask_user_question` for extras or conversion settings, and do not split them into yes/no questions. Call `progress_setup()` with no answers and let setup's prompt ask them. If the reply has `shown_on_card: true`, AIM shows them on its card: end the turn. Otherwise ask that prompt as setup/SKILL.md step 3 says (one `ask_user_question` call) and submit the answers with `progress_setup(answers={...})`. Then re-read the flags and continue this step.

After the user answers:
- If Power BI (or extras multi-select includes Power BI) is **Yes**: load `../powerbi-repointing/SKILL.md` to collect `PBIT_PATH`.
- If Tableau (or extras multi-select includes Tableau) is **Yes**: load `../tableau-repointing/SKILL.md` in path-only mode to collect `TABLEAU_PATH`.
- On **Go with defaults**: `<SETTINGS_FLAGS>` stays empty; proceed to Step 4.
- On **Tailor settings**: load `./recommend-settings/SKILL.md`. It scans the source, proposes dialect-specific settings, and — after the user confirms — returns a flag string. Store it as `<SETTINGS_FLAGS>` for Step 4. If the user declines all suggestions or the catalog can't be loaded, `<SETTINGS_FLAGS>` stays empty. Return here when complete. If `source/` is empty (Tableau-only), skip tailoring and leave `<SETTINGS_FLAGS>` empty.

### Step 4: Run Conversion

Before running, tell the user what the conversion will cover: the SQL and native ETL already in the project (`source/`, plus `source/_etl/` when present), Power BI repointing if `PBIT_PATH` was set, and Tableau repointing if `TABLEAU_PATH` was set. Tableau-only (empty `source/`, `TABLEAU_PATH` set) is valid. On a SqlServer project, also tell them convert will write `.scai/bindings/database-bindings.yaml` by default so each source catalog maps to a Snowflake database — they can opt out before you run if they want the older single-database convert. On other dialects, say nothing about bindings. AI-First ETL under `source/_etl_aifirst/` is **not** part of `scai code convert` — Step 4.5 handles it independently.

> **Skip `scai code convert` entirely** when there is nothing native to run against:
> `source/` has no `.sql`, `source/_etl/` is missing or empty, `PBIT_PATH` is unset,
> and `TABLEAU_PATH` is unset. Say so ("no native SQL, Power BI, Tableau, or SSIS /
> Informatica PowerCenter ETL to convert — going straight to AI-First for the
> registered platforms") and go straight to Step 4.5. Do not invoke `scai code
> convert` just to watch it emit an empty envelope.

Otherwise, start from the base command:

```bash
scai code convert <SETTINGS_FLAGS> --json
```

`--json` is always required so you can parse the result envelope. Substitute `<SETTINGS_FLAGS>` with the confirmed flags from Step 3.6 (or omit the token when empty). Then append one flag per decision already recorded in the steps above — nothing else. Do **not** pass `--etl-replatform-sources-path`; ETL already lives under `source/_etl/` from register.

Append `--generate-source-bindable-format --generate-snowflake-bindable-format` (**default on / opt-out**) **only when `source_language` from `configure()` is SqlServer** (compare case-insensitively), and never on the dbt repointing path — they are invalid alongside `--dbt` and the engine rejects the command (see `dbt/SKILL.md` Step 2). They tokenise source (`${name}`) and Snowflake (`<%name%>`) catalog names and write `.scai/bindings/database-bindings.yaml`. Omit both flags when the user explicitly opts out. Deploy stays legacy-safe: projects converted earlier, with no bindings file, still use `-d snowflake_database`. Bare `scai code convert` without these flags (engine default) is also opt-out.

Only SQL Server's conversion settings define the bindable-format flags today; on every other dialect scai rejects them (`CVT0013`, "Unrecognized option"). So on a non-SQL Server project, leave them off and say nothing about them — it is not an opt-out and not a scai version problem. If you are unsure whether this dialect supports them, `scai code convert --list-settings --json` lists the settings it accepts. If a convert ever fails with `CVT0013` on one of these flags, rerun without them and do **not** tell the user their scai is outdated or unsupported — the flag is simply not defined for their dialect.

| Append | When |
|--------|------|
| `--generate-source-bindable-format --generate-snowflake-bindable-format` | `source_language` is SqlServer (interactive and `subagent_mode`). Skip on explicit opt-out, on any other dialect, and on the `--dbt` path, where scai rejects them. |
| `--informatica-to-snowflake-scripting` | `SCRIPTING_MODE` was set in Step 2 (Informatica target is Snowflake Scripting) |
| `--ssis-to-snowflake-scripting` | `SSIS_SCRIPTING_MODE` was set in Step 2 (SSIS target is Snowflake Scripting) |
| `--consolidate-dbt-projects` | `CONSOLIDATE_DBT_PROJECTS` was set by `../dbt-consolidation/SKILL.md` (SSIS dbt, or Informatica dbt) |
| `--consolidate-as-single-dbt-project` | `CONSOLIDATE_AS_SINGLE_DBT_PROJECT` was set by `../dbt-consolidation/SKILL.md` (SSIS dbt only, single-project choice) |
| `--powerbi-repointing <PBIT_PATH>` | `PBIT_PATH` was set in Step 3 |
| `--tableauRepointing <TABLEAU_PATH>` | `TABLEAU_PATH` was set in Step 3.5 |

The two Informatica flags are mutually exclusive — they come from the same single-select answer, so at most one can apply. The SSIS scripting flag and the SSIS dbt-consolidation flags come from the SSIS answer, so a scripting SSIS convert does not also pass a consolidation flag. `--consolidate-as-single-dbt-project` is exclusive with `--consolidate-dbt-projects` and with `--ssis-to-snowflake-scripting`: pass it only when the SSIS-only answer set `CONSOLIDATE_AS_SINGLE_DBT_PROJECT`. Either platform's choice combines with `--powerbi-repointing` and/or `--tableauRepointing`, and with the other platform's choice. If none of the conditions hold, run the base command as-is.

Substitute `<PBIT_PATH>` and `<TABLEAU_PATH>` with the actual paths you stored. Do not emit literal placeholder tokens to the shell.

### Step 4.5: AI-First ETL Migration (unsupported ETL platforms)

Skip this step unless Step 2 set `<AIFIRST_ETL_PATH>` — the Code Unit Registry has
one or more `kind: etl` rows with `extensions.sourcePlatform` set. Load
`./etl-aifirst/MIGRATE.md` and follow it once per registered AI-First ETL unit,
passing that unit's `id`, `extensions.sourcePlatform`, and `files.source.path` from
the Step 2 `query_registry` response. It routes each platform (Talend, Alteryx,
Informatica Cloud / IICS, DataStage, Pentaho, Azure Data Factory, or another name
the user typed) through the AI-First convert action instead of the native engine,
reports its exit code, and returns here when done. It does not touch the SQL
conversion Step 4 just produced.

For an AI-First-ETL-only project (Step 4 was skipped), Step 4.5 is the whole
conversion — do not treat the missing native envelope as an error.

Its registry step defers to `./etl-aifirst/SKILL.md`, which is the contract for when an unsupported-platform unit may be recorded as converted and how its lineage is written. Read that file too; a unit left pending there is missing from every report rebuilt from `dependencies.dependsOn`.

### Step 5: Read the Result Envelope

`--json` returns the result. That envelope is the whole story for this step —
**don't open the reports, the CSVs or the logs to work out what happened.**

Conversion writes:
- **Converted code** in `snowflake/`
- **Conversion reports** under `.scai/reports/SnowConvert/` — for tooling only. Users get them through AIM Assessment
- **Logs** in `logs/`

Name the converted-code and log locations. Direct users to Assessment for reports.
Do not present `.scai/reports/` as a place for users to browse.

#### Registry Not Updated (CVT0036)

`CVT0036` means the engine finished and the converted SQL in `snowflake/` and the
reports exist, but the registry was not written: the units it names still show
`conversion: pending`. Surface the error and its suggestion verbatim, then stop.
Do not go on to the assessment.

- Do not re-run `scai code convert`, with or without `--overwrite-working-directory`,
  to fix it. A re-run hits the same engine failure and leaves the registry as it is.
- Never call units left `conversion: pending` after convert, or an empty conversion
  issues panel, expected. Only `scai code convert` writes a converted unit's
  conversion status; no later phase (assessment, migrate-objects, deploy) fills it in.

### Conversion Options

| Option | Description |
|--------|-------------|
| `-x, --show-ewis` | Show detailed EWI breakdown |
| `--overwrite-working-directory` | Overwrite output files in `snowflake/` and registry |
| `--informatica-to-snowflake-scripting` | Convert Informatica mappings to standalone Snowflake stored procedures (Snowflake Scripting) instead of dbt projects. Preview flavor; ETL stabilization and deploy are skipped for these units. |
| `--ssis-to-snowflake-scripting` | Convert SSIS data flows to standalone Snowflake stored procedures (Snowflake Scripting) instead of dbt projects. Preview flavor; stabilization and deploy are not part of this flow. |

For dbt consolidation options, see `../dbt-consolidation/SKILL.md`.
For Power BI options, see `../powerbi-repointing/SKILL.md`. For Tableau options, see `../tableau-repointing/SKILL.md`.

**Example with options:**
```bash
scai code convert --show-ewis --overwrite-working-directory --json
```

## Changing Conversion Settings Later

"Go with defaults" is not final. When the user asks, at any point, to tailor
conversion settings, change or add a conversion flag, or asks how to do so on
this project ("I picked defaults but need flag X", "can I change the conversion
settings?"), offer it here, even when `tailor_conversion_settings` is `false`
and the setup step shows as done. Never tell them to start a new project or
re-import their source for this: the settings apply to the project they have.

1. Call `configure(tailor_conversion_settings=true)` so the choice is saved and
   a later convert in this or another session tailors too.
2. Check whether conversion has run: `snowflake/` already holds converted code.
3. **Conversion has not run yet** (still registering, or about to convert):
   tell the user the new settings will be applied when conversion runs, and
   that the import already in progress carries on. If you are in Step 3.6 now,
   load `./recommend-settings/SKILL.md` there; otherwise do nothing else now:
   Step 3.6 reads `true` and loads it before the convert runs. If the user named
   a flag, pass it to recommend-settings so it is proposed.
4. **Conversion has already run:** load `./recommend-settings/SKILL.md` now to
   collect `<SETTINGS_FLAGS>`. Applying them means converting again with
   `--overwrite-working-directory`, which replaces the converted code under
   `snowflake/` and its Code Unit Registry files, so any hand edits to converted
   code are lost. Say so plainly and ask the user to confirm before running.
   On yes, rerun Step 4's command with the flags Steps 2–3.5 append (re-read
   from `configure()` as on the first run), plus `<SETTINGS_FLAGS>` and
   `--overwrite-working-directory`, then Step 5. If
   an assessment already ran, tell the user its results reflect the earlier
   conversion until it is run again. On no, change nothing.

## Understanding EWIs

Reference for answering a question the user asks — not a prompt to go analyze
the run. EWIs (Early Warning Issues) indicate conversion items needing attention:

| Severity | Action Required |
|----------|----------------|
| **Critical** | Must fix before deployment |
| **High** | Should fix, may cause runtime errors |
| **Medium** | Review recommended |
| **Low** | Minor issues, optional fixes |

**Common EWI codes:**
- `SSC-EWI-0030`: Dynamic SQL (requires manual review)
- `SSC-FDM-*`: Functional differences (behavior may differ)
- `SSC-PRF-*`: Performance remarks (optimization suggested)

## Output Structure

```
snowflake/
├── <database>/
│   └── <schema>/
│       ├── table/
│       ├── view/
│       ├── procedure/
│       └── function/
└── _etl/                              # Converted ETL code — both native (SSIS / Informatica PowerCenter)
                                       # and AI-First (Talend / Alteryx / IICS / DataStage / Pentaho / ADF /…)
                                       # land here once Step 4 and Step 4.5 finish, so downstream skills
                                       # find every converted package under one root
    └── <package_name>/
        ├── <package_name>.sql         # Snowflake Task graph
        └── <data_pipeline>/
            └── models/                # dbt models (staging, intermediate, marts) when target is dbt
.scai/
└── reports/
    ├── SnowConvert/
    │   ├── TopLevelCodeUnits.*.csv
    │   ├── Issues.*.csv
    │   ├── ObjectReferences.*.csv
    │   ├── Assessment.*.json
    │   ├── ETL.Elements.*.csv             # ETL elements processed (packages, tasks, data flows)
    │   └── ETL.Issues.*.csv               # ETL-specific conversion issues
    ├── GenericScanner/
    ├── ArrangeReports/
    └── conversion-reports.zip
source/
└── _etl_aifirst/                       # AI-First ETL inputs, one directory per platform, written by register
    └── <platform>/                     # (Talend, Alteryx, IICS, DataStage, Pentaho, ADF, …)
reports/
└── AiFirstIssues/                     # Present only after Step 4.5 (AI-First "Something else" ETL path)
    └── <package_name>/
logs/
artifacts/
└── repointing_output/
    └── tableauResults/                 # Durable repointed .twb/.tds output when Tableau was requested
```

For Power BI output paths, see `../powerbi-repointing/SKILL.md`. For Tableau, use only
`result.tableauRepointing.outputPath` from the JSON envelope; it resolves to
`artifacts/repointing_output/tableauResults/`. Never report the temporary
`.scai/.snowconvert/tableauResults` engine path.

## CHECKPOINT

The envelope's own status is the check — don't go looking for corroboration.

- [ ] The convert command exited successfully and the envelope reports no conversion errors
- [ ] If dbt consolidation was offered, follow the CHECKPOINT addendum in `../dbt-consolidation/SKILL.md`
- [ ] If Power BI reports were included, follow the CHECKPOINT addendum in `../powerbi-repointing/SKILL.md`
- [ ] If Tableau workbooks were included, follow the CHECKPOINT addendum in `../tableau-repointing/SKILL.md`

If the envelope reports errors, surface them verbatim and stop. For `CVT0036`, follow
"Registry Not Updated (CVT0036)" in Step 5. Otherwise move on
— don't ask the user to review EWI counts or confirm that files landed.

## On Completion

Show a concise result line using only values from the JSON envelope:

> **Conversion complete.** SQL: `<codeConversion.filesProcessed>` files processed,
> `<codeConversion.codeUnitsConverted>` code units converted. ETL:
> `<etlReplatforming.processedFiles>` files processed. Converted code is in
> `snowflake/`; conversion reports are available through AIM Assessment.

If the envelope has no `etlReplatforming` result, omit the ETL sentence. Never
invent a missing count.

Then show the JSON envelope from `scai code convert --json` **as-is**, in a
fenced `json` block.

When Tableau was requested, the envelope's `result.tableauRepointing` block is
authoritative: success contains `processedFiles` and the durable `outputPath`;
`{"message":"None found"}` means no Tableau result was processed. Do not construct
or infer a different output path.

If you appended the bindable-format flags (the default on SqlServer), also tell the user once:

> Convert wrote `.scai/bindings/database-bindings.yaml` — each source catalog maps to a Snowflake database there (1:1 by default). Edit that file before deploy if you want different target names.

Skip that line when you did not append the flags (opt-out or a non-SqlServer dialect).

Then one line on what's next. Return to the parent setup flow after conversion. Do not open `assessment/SKILL.md` directly from this skill; the parent controls the transition and honors explicit stop requests:

> Next, we'll run an assessment to plan your migration: dependency waves, object categorization, and a deployment plan.

Do not break issues down by severity, rank them, or say which ones need fixing
— the assessment does that with the full picture. The concise result line above
is the only prose summary of envelope numbers. If the user asks about a number,
an EWI code, or a specific file, dig in *then*; the reference sections above
are for that.

*If `SCRIPTING_MODE` was set*, also tell the user:
> Informatica mappings were converted to Snowflake Scripting stored procedures (preview). **ETL Stabilization is not supported for Snowflake Scripting conversions (dbt only)**, and deploy is not part of this preview flow - both are skipped for these ETL units. The generated procedures and Task graph are under `snowflake/_etl/` for review.

*If `SSIS_SCRIPTING_MODE` was set*, follow "After a Snowflake Scripting conversion" in [references/ssis-target.md](references/ssis-target.md).

*If Step 4.5 ran*, its own CHECKPOINT already reported the AI-First exit-code verdict in full — do not repeat or soften it here.

There is now enough converted code for the local dashboard to be worth looking
at. If `configure` reported a dashboard URL at session start, mention it once:
> You can watch progress at `<url>` — read-only, and only on your machine.

Skip the line if no URL came back (the user opted out, or the port was busy).
Don't guess a URL, and don't repeat this every step.

Then return to the calling skill.
