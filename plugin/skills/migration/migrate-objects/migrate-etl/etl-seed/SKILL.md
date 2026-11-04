---
name: etl-seed
description: Seed the per-unit ETL test YAML for a deployed ETL code unit by running `scai test seed` (which fills pipeline + validation.tables from the CUR), then fill index_columns and have the user confirm before the live comparison runs.
parent_skill: migrate-etl
license: Proprietary. See License-Skills for complete terms
---

# ETL Seed

Generates the `kind: etl` test YAML for a single, already-deployed ETL code unit at `artifacts/<id>/etl-test/<name>.yml`. The YAML declares the `pipeline` (how to launch the source package and which converted target to run) and a `validation.tables` list of source→target table pairs to compare.

**`scai test seed` seeds ETL units — you do not hand-author the file.** For an ETL unit (`kind = 'etl'`; SSIS or Informatica natively, any platform once an `external_command:` section opts in — see Step 2) `scai test seed` walks the Code Unit Registry, takes the unit's **write** dependencies (`INSERT` / `UPDATE` / `MERGE` / `DELETE`), and emits a table entry per written table (`comparison.tables[]` for SSIS and external-command units, `validation.tables[]` for Informatica — see Step 3) — pairing the source table (`source.canonicalName`) with its Snowflake target (`target.canonicalName`). It leaves `index_columns` blank for you to fill. Your job is to run the seeder, fill in the join keys, handle any skipped or empty units, and confirm with the user — not to invent table pairs. A pair the seeder did not emit goes into the file only after the user has named or confirmed it.

## Step 0: Resolve Unit

Read the registry entry (the executor passes `object_id`; if entered by name, locate via `migration_status(mode="my_objects_summary")`):

| Field | Used as |
|---|---|
| `id` | `{ETL_ID}` for the `--where` filter and the `artifacts/<id>/etl-test/` path |
| `source.platform` | source kind (`ssis`, `informatica`, …) |
| `files.source.path` | source definition file (`.dtsx`, `.xml`, …); its stem is the YAML file name |

The `etlSeed` task has a `taskCompleted` precondition on `deploy`, so the executor only dispatches this skill once the unit is deployed — you do not need to re-check deployment here.

## Step 0b: Record skill start

```
transition_status(status="started", task="etlSeed", where="id = '{ETL_ID}'")
```

Do this once at entry. Finish with `transition_status` in Step 4.

## Step 1: Run `scai test seed`

```bash
scai test seed --where "id = '{ETL_ID}'"
```

Add `--append` when a YAML already exists for the unit — it re-emits the table pairs from the current CUR while **preserving** your edited `index_columns` / `test_cases` (matched per source→target pair):

```bash
scai test seed --where "id = '{ETL_ID}'" --append
```

Platform is auto-detected per unit from the registry — no `--platform` flag. On success the file is written to `artifacts/{ETL_ID}/etl-test/<name>.yml` with the execution block and table pairs filled from the CUR. When an `external_command:` section is present, the side it names is emitted as `{type: external_command, wait_seconds: <n>}` — two keys and nothing else, since the command itself lives only in `test_config.yaml` — and the other side keeps its native block. Tune `wait_seconds` per unit if one package runs longer than the shared default.

**A failed seed is not yours to replace.** When `scai test seed` exits with an error — a failed connection test such as `Cannot open database …`, for one — do not write the YAML yourself from the CUR, the package or the Snowflake catalog. Report the command and its error to the user. Re-run it only after fixing the environment properly (starting the service, selecting the right registered connection — never repointing or editing a connection just to pass the test); otherwise this is a **STOPPING POINT**: ask the user how to proceed, and leave `etlSeed` started (Step 4).

## Step 2: Handle a Skipped Unit

If `scai test seed` reports the unit was **skipped**, it names a reason. Do not paper over it by hand-writing tables — fix the cause:

| Skip reason | Meaning / action |
|---|---|
| `NoWriteDependencies` | The CUR records no write (`INSERT`/`UPDATE`/`MERGE`/`DELETE`) deps — nothing to validate. Re-check the unit was fully converted/assessed; confirm with the user whether it actually writes tables. |
| `MissingDependency` | A write-dep is flagged `isMissing` in the CUR — register/resolve that dependency first. |
| `MissingCanonicalName` | A resolved write-dep has no source/target canonical name — fix the registry entry. |
| `UnknownFormat` / `PendingFormat` / `MixedFormat` | The converted part(s) aren't in a seedable target format yet — finish stabilization/deploy for the routable parts. |
| `NoArtifactsPath` | The CUR has no artifacts path — the unit isn't converted/deployed as expected. |
| `UnsupportedPlatform` | Source platform is neither SSIS nor Informatica, and the project has not opted into an external command. Only SSIS and Informatica have a built-in source executor; any other `kind: etl` platform is seedable **only** once `.scai/settings/test_config.yaml` declares an `external_command:` section with `side: source`, which replaces the source executor with a launch-and-wait command. With `side: target` the source is still native, so this skip still applies. Add the section (see `etl-validate`) and re-run with `--append`, or treat the unit as out of scope. |

**An empty table list is not a success.** A task-orchestrated unit whose write targets the CUR cannot resolve — typically write deps recorded as `isMissing` stubs — is still written, with `tables: []` and `ETL Skipped 0`. Do not fill that list from the package, the CUR stubs or the Snowflake catalog. **STOPPING POINT** — tell the user which unit has no pairs and why (name the unresolved write deps you can see), and ask which source/target tables to compare. You may list candidate pairs you found, marked as proposals awaiting their confirmation, but write none of them into the YAML until the user confirms.

Only after the underlying issue is understood should you add a missing pair by hand (with the user's confirmation), only if genuinely necessary, and in the entry shape of Step 3.

## Step 3: Fill `index_columns` and Confirm

`scai test seed` leaves `index_columns` blank. Open `artifacts/{ETL_ID}/etl-test/<name>.yml` and, for each table entry, set the join key used to align rows between source and target. Keep the shape the seeder wrote — the parser rejects keys from the other one:

| File (top-level keys) | Entry | Keys go |
|---|---|---|
| `execution:` / `comparison:` (SSIS, external command) | `comparison.tables[]`: `source:` / `target:` as plain FQN strings | flat on the entry: `index_columns`, `target_index_columns` |
| `pipeline:` / `validation:` (Informatica) | `validation.tables[]`: `source_table:` / `target_table:` as `{name: …}` | under the entry's `comparison:`: `index_columns`, `target_index_columns` |

- `index_columns` — the column(s) that uniquely key a row (usually the natural / primary key).
- `target_index_columns` — only when the target's key column names differ from the source's.

Then show the user the seeded table pairs and their keys, and ask them to confirm or correct — the CUR can miss dynamically-named or conditionally-written tables. Adjust per their feedback. This is a stopping point that needs the user's input — as is Step 3b on an Informatica project — even when the seeder filled every key: end your turn with the pairs, the keys and the question. Asking means your final message, whether or not a question tool is available; the answer arrives in a later turn, so do not advance in this one.

## Step 3b: Set the Informatica `pmcmd` Endpoint (Informatica projects only)

A seeded Informatica unit carries no `service` / `domain`, and `scai test seed` writes no
`informatica:` section to `.scai/settings/test_config.yaml`, nor a warning about either. Both are
the same for every unit of a project and cannot be derived from the CUR, so they are set **once**,
on the pmcmd connection the unit's header calls
`scai connection add-informatica-pmcmd --service ... --domain ...`. That connection also holds
`pmcmd_path`, user and password, in a cleartext, machine-level file under
`~/.snowflake/scai/connections/`; say that plainly if the user asks where the password ends up.

**Have the user register it.** As at Step 3, this is a stopping point that needs the user's input:
nothing on disk holds the Integration Service or the domain, so never infer or invent them. Follow
[`../../../connection/informatica-pmcmd-connection/SKILL.md`](../../../connection/informatica-pmcmd-connection/SKILL.md)
from its **Step 1**. Without `--auth` its command prompts for every value, service and domain
included, even ones passed as flags, and in a shell without a terminal, like yours, it registers
nothing — so the user runs it in their own terminal and types every value there, not in chat.

**A registered connection is used only once it is selected**; registering writes no default.
Select it with `scai connection set-default -l informatica -s <name>` (that skill's Step 3), or
with `informatica_connection: <name>` in `.scai/config/project.yml`; `--etl-connection <name>`
selects it only for the command it is passed to. Unselected, it supplies no credential or endpoint.

**The fallback is a hand-written `informatica:` section in `.scai/settings/test_config.yaml`**,
which the runner still reads — for credentials kept in exported variables, or `pmcmd`'s own domain
defaults (a connection requires `--service` and `--domain`). A selected connection holding
`pmcmd_path`, user and password replaces this section wholesale, ignoring its `service` / `domain`.

```yaml
informatica:
  pmcmd_path: /opt/informatica/10.5/server/bin/pmcmd
  username: ${INFORMATICA_USERNAME}
  password: ${INFORMATICA_PASSWORD}
  service: IS_EDW_NIGHTLY      # pmcmd -sv: the Integration Service running the workflows
  domain: Domain_EDW           # pmcmd -d:  the domain that service belongs to
```

**Never write a credential value into this file.** `username:` / `password:` are `${...}`
references: the file is committed, and nothing downstream catches a literal — `--check-env` passes
on one. If the user offers the password it goes to an exported variable or to the connection's own
hidden prompt, never here. Then verify **every** seeded unit resolves before `etlValidate`:

```bash
scai test etl-validate --platform {PLATFORM_ID} --check-env
```

`informatica_service_domain` quotes the project-wide `informatica.service` / `informatica.domain`
pair: show it to the user, as the selected connection may be a machine-wide default set for
another project. `no service/domain configured anywhere` means the endpoint is unset, often
because no connection is selected: accept it only if the user relies on the domain's defaults. A
failure names the files whose leftover `TODO_INFA_*` or unset `${VAR}` would reach `pmcmd`.

- **Per-unit `TODO_INFA_FOLDER` / `TODO_INFA_WORKFLOW` are separate.** Those are the only
  placeholders still emitted into a unit's own YAML, and only when the CUR could not supply them —
  fill them in that file, not in `test_config.yaml`.
- **A per-unit override is still available.** A project whose workflows span more than one
  Integration Service or domain can set `service:` / `domain:` under that unit's `pipeline.source`;
  a unit-level value wins over the project-wide one. Hand-added overrides survive a re-seed with
  `--append`.

## Step 4: Record Completion

Once the unit's YAML has a non-empty table list (`comparison.tables` / `validation.tables`) with `index_columns` filled and the user has confirmed it in a reply — their message in a later turn, never your own conclusion that the pairs and keys look right:

```
transition_status(status="advance", task="etlSeed", outcome="completed", where="id = '{ETL_ID}'")
```

The state machine routes to `etlValidate`. While a unit's seed has failed (Step 1), its table list is empty, or the user has not yet answered Step 2 or Step 3, do not advance that unit: leave `etlSeed` started and end your turn with the question.

## Step 5: Exclusion

To skip seeding (no live source system, or the packages are deprecated), disable the task at the project level in `.scai/config/plugin.yml`:

```yaml
tasks:
  etlSeed:
    enabled: false
```

A disabled task reads as **excluded** by the state machine: `etlValidate`'s `artifactExists` gate then treats `etlSeed` as a producer that will never run and is itself excluded rather than blocked (a hand-authored test YAML still readies `etlValidate`). This is **project-wide** — it disables `etlSeed` for every ETL unit. Per-unit exclusion is not supported: writing `codeStatus.etlSeed=excluded` on a single entry reads back as *completed*, not excluded.
