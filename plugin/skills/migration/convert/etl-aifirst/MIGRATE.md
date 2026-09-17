# AI-First ETL Migration

Guide for the **Something else** branch of Step 2 in `../SKILL.md`, run from Step 4.5. Reached only when the user's ETL platform is not one SnowConvert's native engine translates: that engine has translators for SSIS (`.dtsx`) and Informatica Power Center (XML repo export) and for nothing else, so an unsupported platform cannot be passed to `--etl-replatform-sources-path`.

**This is a fallback, and tell the user so.** The AI-first migrator is not the SnowConvert engine. It identifies a document's elements against a per-platform table, emits dbt models and a Snowflake Task graph, then grades its own output and reports what it could not translate. It is built to produce output that is incomplete in named ways rather than output that looks finished. Do not present a run of it as equivalent to a supported-platform conversion.

The SQL conversion from Step 4 has already finished and is unaffected. Nothing in this guide changes it, re-runs it, or depends on it.

## Step 1: Locate the driver

The driver ships inside this plugin — no external install or environment variable to resolve:

```
../../migrate-objects/actions/etl-aifirst/scripts/aifirst-migrate.sh
```

Read that action's `SKILL.md` before invoking it if you have not already (`../../migrate-objects/actions/etl-aifirst/SKILL.md`). Confirm the script exists; if it does not, the plugin checkout is broken — stop and tell the user the AI-First action is missing from this install, rather than trying to work around it.

## Step 2: Pick the platform identity

Ask the user which platform the document is from, and map their answer to a checked-in identity when one exists:

| Platform | Identity |
|----------|----------|
| Azure Data Factory | `adf` |
| Alteryx (`.yxmd`) | `alteryx` |
| DataStage (`.dsx`) | `datastage` |
| Pentaho / Kettle (`.ktr` / `.kjb`) | `pentaho` |

If the user names something not in that table, use their own name as the identity anyway and pass it through — do not refuse. Stage 0 authors a provisional platform table on a platform it has not seen before, validates it structurally before trusting it, and preserves it under `<output-root>.gates/stage0/`. That costs an authoring round, not a refusal, so there is no dead end here the way there is for a platform the *native* engine cannot take.

Never pass `ssis` or `informatica` here to compare paths on production input — those stay on the native `--etl-replatform-sources-path` flag from Step 4. The checked-in tables for those two exist for controlled side-by-side testing only.

## Step 3: Run the driver, once per document

The driver takes **one source document per invocation**, not a directory. List the platform's documents under `<AIFIRST_ETL_PATH>`, tell the user how many you found, and migrate each one independently.

Stage each run outside the project and move the result in afterwards:

```bash
STAGE=$(mktemp -d)
../../migrate-objects/actions/etl-aifirst/scripts/aifirst-migrate.sh \
  --platform <PLATFORM_IDENTITY> \
  "<DOCUMENT>" \
  "$STAGE" 2>&1 | tee "logs/aifirst-<PACKAGE>.log"
```

Keep the exit code. It is the verdict, and Step 5 reports it. Because the command is piped, read the driver's status (`${PIPESTATUS[0]}` in bash) rather than the pipeline's.

To measure whether the generated SQL actually runs, export `AIFIRST_SNOWFLAKE_CONN=<connection-name>` — a named connection in the user's Snowflake config — before invoking. Without it the driver reports execution as unmeasured, and you may not claim the SQL works.

## Step 4: Move the output into the project

`<PACKAGE>` is the unit directory name the driver created under `$STAGE/Output/ETL/`.

```bash
mkdir -p snowflake/_etl "reports/AiFirstIssues/<PACKAGE>"
cp -R "$STAGE/Output/ETL/<PACKAGE>" "snowflake/_etl/<PACKAGE>"
cp -R "$STAGE/Reports/AiFirstIssues/." "reports/AiFirstIssues/<PACKAGE>/"
rm -rf "$STAGE"
```

This is the same location the native ETL path uses — `snowflake/_etl/<package_name>/<package_name>.sql` with the dbt project beside it — so the orchestration SQL lands where the rest of the migration flow already looks for it.

## Step 5: Report the verdict, exactly

The exit code is the finding. Report it as it came:

| Exit | Meaning | How to report it |
|------|---------|------------------|
| `0` | Migrated, no degradation detected | Output exists and every gate the driver runs was satisfied. Still unverified against Snowflake unless `AIFIRST_SNOWFLAKE_CONN` was set. |
| `3` | **Migrated with degradation — the expected outcome** | Output exists and is incomplete in ways the driver names. This is **not a failure** and not a reason to retry. Report the degradations it listed. |
| `1` | Failed — no usable output | Nothing usable was produced. Say so plainly and do not present a partial tree as a conversion. |
| `2` | Usage error | The invocation was wrong, not the input. Fix the arguments and run again. |

**Exit 3 is what a first run on an unsupported platform normally returns.** Do not round it up into success and do not round it down into failure. Quote the driver's own verdict line together with the degradations printed above it.

Two claims you must not make:

- **That the generated SQL runs.** It is unverified unless `AIFIRST_SNOWFLAKE_CONN` was supplied and the run reported an execution count. Without that, call the SQL **unverified** — which is neither a claim that it works nor a claim that it does not.
- **That this equals a supported-platform conversion.** What the driver could not translate is written to `reports/AiFirstIssues/<PACKAGE>/`. Point the user at that directory by name.

## CHECKPOINT

Confirm with user:
- [ ] They were told their platform is unsupported by the native engine and that this path is a fallback
- [ ] The exit code was reported using the table above, exit 3 included and not softened
- [ ] Converted output is under `snowflake/_etl/<PACKAGE>/`, issues under `reports/AiFirstIssues/<PACKAGE>/`
- [ ] Whether the SQL was executed in Snowflake was stated either way, never left implied

Then return to `../SKILL.md`.
