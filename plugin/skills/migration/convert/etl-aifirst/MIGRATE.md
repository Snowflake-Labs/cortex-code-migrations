# AI-First ETL Migration

Guide for the **Something else** branch of Step 2 in `../SKILL.md`, run from Step 4.5. Reached only when the user's ETL platform is not one SnowConvert's native engine translates: that engine has translators for SSIS (`.dtsx`) and Informatica Power Center (XML repo export) and for nothing else, so an unsupported platform cannot be passed to `--etl-replatform-sources-path`.

**This is a fallback, and tell the user so.** The AI-first migrator is not the deterministic code conversion engine. It identifies a document's elements against a per-platform table, emits dbt models and a Snowflake Task graph, then grades its own output and reports what it could not translate. It is built to produce output that is incomplete in named ways rather than output that looks finished. Do not present a run of it as equivalent to a supported-platform conversion.

The SQL conversion from Step 4 has already finished and is unaffected. Nothing in this guide changes it, re-runs it, or depends on it.

## Step 0: Resume producer output before starting a new run

Resolve the registered unit's output root from the Code Unit Registry, then inspect that
root **before** locating or invoking the driver.

- If `<output-root>/Reports/AiFirstRemediation/remediation-brief.json` exists, the
  producer already emitted usable output. This is a resume, not a new conversion. Do
  not run `aifirst-migrate.sh`, do not replace the output tree, and do not regenerate
  missing reports. Skip Steps 1–4 and continue at Step 5 with the artifacts exactly as
  they are.
- If `Reports/AiFirstIssues/issues.json` exists but the remediation brief does not, the
  earlier producer run stopped without a usable handoff. Do not erase that failure by
  rerunning automatically. Skip Steps 1–4 and record the failed conversion in Step 5.
- Only when neither producer artifact exists is this a new conversion. Continue with
  Steps 1–4.

This distinction is critical for lineage. A missing `Reports/AiFirstLineage/lineage.json`
beside an existing remediation brief means that run never measured lineage. Rerunning the
producer to fill the gap changes historical evidence and can manufacture dependencies
that were not measured by the run being resumed.

## Step 1: Locate the driver

The driver ships inside this plugin — no external install or environment variable to resolve:

```
../../migrate-objects/actions/etl-aifirst/scripts/aifirst-migrate.sh
```

Read that action's `SKILL.md` before invoking it if you have not already (`../../migrate-objects/actions/etl-aifirst/SKILL.md`). Confirm the script exists; if it does not, the plugin checkout is broken — stop and tell the user the AI-First action is missing from this install, rather than trying to work around it.

## Step 2: Read the registered unit's platform and source path

The caller reached this guide from `../SKILL.md` Step 4.5 with a `query_registry` row per AI-First ETL unit — each row has `id`, `extensions.sourcePlatform`, and `files.source.path`. Do not read a manifest or ask the user for the path again.

Map `extensions.sourcePlatform` to a checked-in driver identity when one exists:

| Registered platform | Driver identity |
|---|---|
| `adf` | `adf` |
| `alteryx` | `alteryx` |
| `datastage` | `datastage` |
| `pentaho` | `pentaho` |

If the registered platform is anything else (Talend, Informatica Cloud / IICS, a free-form name a user typed), pass it through verbatim as the driver identity — do not refuse and do not relabel. Stage 0 authors a provisional platform table on a platform it has not seen before, validates it structurally before trusting it, and preserves it under `<output-root>.gates/stage0/`. That costs an authoring round, not a refusal, so there is no dead end here the way there is for a platform the *native* engine cannot take.

Never pass `ssis` or `informatica` here to compare paths on production input — those stay on the native `--etl-replatform-sources-path` flag from Step 4. The checked-in tables for those two exist for controlled side-by-side testing only.

## Step 3: Run the driver, once per registered unit

The driver takes **one source document per invocation**, not a directory. Migrate each registered AI-First ETL unit independently, using its own `files.source.path` and `extensions.sourcePlatform` from the Step 2 `query_registry` response.

Stage each run outside the project and move the result in afterwards:

```bash
STAGE=$(mktemp -d)
../../migrate-objects/actions/etl-aifirst/scripts/aifirst-migrate.sh \
  --platform <PLATFORM_IDENTITY> \
  "<DOCUMENT>" \
  "$STAGE" 2>&1 | tee "logs/aifirst-<PACKAGE>.log"
```

Keep the exit code. It is the verdict, and Step 6 reports it. Because the command is piped, read the driver's status (`${PIPESTATUS[0]}` in bash) rather than the pipeline's.

To measure whether the generated SQL actually runs, export `AIFIRST_SNOWFLAKE_CONN=<connection-name>` — a named connection in the user's Snowflake config — before invoking. Without it the driver reports execution as unmeasured, and you may not claim the SQL works.

## Step 4: Move the output into the project

`<PACKAGE>` is the unit directory name the driver created under `$STAGE/Output/ETL/`.

```bash
# REPORT-COPY-BEGIN -- exercised byte-for-byte by the convert fixture tests.
copy_tree_exactly() {
  local source_dir="$1"
  local destination_dir="$2"
  local source_file relative_file destination_file

  if [ ! -d "$source_dir" ]; then
    echo "AI-First copy failed: missing required path: $source_dir" >&2
    return 1
  fi
  mkdir -p "$destination_dir" || return 1
  if ! cp -R "$source_dir/." "$destination_dir/"; then
    echo "AI-First copy failed: could not copy required path: $source_dir" >&2
    return 1
  fi
  while IFS= read -r -d '' source_file; do
    relative_file=${source_file#"$source_dir"/}
    destination_file="$destination_dir/$relative_file"
    if [ ! -f "$destination_file" ]; then
      echo "AI-First copy failed: missing copied path: $destination_file" >&2
      return 1
    fi
    if ! cmp -s "$source_file" "$destination_file"; then
      echo "AI-First copy failed: incomplete copied path: $destination_file" >&2
      return 1
    fi
  done < <(find "$source_dir" -type f -print0)
}

require_report() {
  if [ ! -f "$1" ]; then
    echo "AI-First copy failed: missing required path: $1" >&2
    return 1
  fi
}

# Step 4.5 runs once per registered AI-First unit, and each run's assessment CSV
# covers only that unit -- native SnowConvert emits one combined project-wide CSV
# instead. Append rather than overwrite so an earlier unit's rows survive a later
# unit's run; write the header only for the first unit that creates the file.
merge_report_csv() {
  local source_file="$1"
  local destination_file="$2"
  if [ ! -f "$destination_file" ]; then
    cp "$source_file" "$destination_file" || return 1
    cmp -s "$source_file" "$destination_file" || return 1
    return 0
  fi
  local before_count added_count after_count
  before_count=$(grep -c '' "$destination_file")
  added_count=$(($(grep -c '' "$source_file") - 1))
  tail -n +2 "$source_file" >>"$destination_file" || return 1
  after_count=$(grep -c '' "$destination_file")
  [ "$after_count" -eq "$((before_count + added_count))" ]
}

# ProducerReports.cs emits this complete root assessment CSV set. Stage 5 then
# updates ETL.Issues in place, so copy only after the driver has returned.
required_csvs=(
  "ObjectReferences.NA.csv"
  "ETL.Elements.NA.csv"
  "ETL.Issues.NA.csv"
)
for report_name in "${required_csvs[@]}"; do
  require_report "$STAGE/Reports/$report_name" || exit 1
done
require_report "$STAGE/Reports/AiFirstIssues/issues.json" || exit 1
require_report "$STAGE/Reports/AiFirstIssues/types-cited.json" || exit 1
require_report "$STAGE/Reports/AiFirstRemediation/remediation-brief.json" || exit 1

copy_tree_exactly "$STAGE/Output/ETL/<PACKAGE>" "snowflake/_etl/<PACKAGE>" || exit 1
mkdir -p reports/SnowConvert || exit 1
for report_name in "${required_csvs[@]}"; do
  if ! merge_report_csv "$STAGE/Reports/$report_name" "reports/SnowConvert/$report_name"; then
    echo "AI-First copy failed: incomplete copied path: reports/SnowConvert/$report_name" >&2
    exit 1
  fi
done

# Keep every report subtree recursively and package-scoped. This retains the
# required issue/remediation contract and optional non-gating lineage output,
# without flattening nested files or allowing units to overwrite one another.
for source_dir in "$STAGE"/Reports/*/; do
  [ -d "$source_dir" ] || continue
  report_group=${source_dir%/}
  report_group=${report_group##*/}
  copy_tree_exactly "${source_dir%/}" "reports/$report_group/<PACKAGE>" || exit 1
done

rm -rf "$STAGE"
# REPORT-COPY-END
```

This keeps the native report layout: the three producer assessment CSVs land in
`reports/SnowConvert/`, merged across every unit run rather than overwritten -- each
unit's producer emits a CSV scoped to just that unit, so a later unit's rows are
appended (header written once) instead of replacing the file. AI-First report trees
remain recursively intact under `reports/<report-group>/<PACKAGE>/`, one directory per
unit, so units never overwrite one another there either. The copy checks every
required source before moving anything, byte-compares or row-counts every copied
file, and removes `$STAGE` only after the complete contract has been verified. A
missing or changed artifact names its path and stops the conversion step instead of
reporting completion.

This is the same location the native ETL path uses — `snowflake/_etl/<package_name>/<package_name>.sql` with the dbt project beside it — so the orchestration SQL lands where the rest of the migration flow already looks for it.

## Step 5: Record the unit in the Code Unit Registry

Moving files is not the end of the unit's migration — the registry is where the
rest of the flow reads its state from, and `./SKILL.md` holds the exact contract.
Read its two sections, "When conversion may be recorded as completed" and
"Writing lineage into the Code Unit Registry", and follow them for this unit:

- Conversion status comes from what the producer left beside the output root. A
  real `Reports/AiFirstRemediation/remediation-brief.json` is what lets you
  `transition_status(status="advance", task="convert", outcome="completed", …)`;
  issues without a brief, or neither artifact, is an honest `outcome="failed"`
  with the reason. Never invent either artifact to reach `completed`.
- Dependencies come from `Reports/AiFirstLineage/lineage.json`. Resolve each
  `sources` entry with `query_registry` and write them in one
  `update_registry(field="dependencies.dependsOn", …)` call, marking an
  unresolved table `"isMissing": true`. An absent report means the producer
  never measured lineage — skip the write rather than writing an empty array, and
  never reconstruct the dependencies from the emitted models or the seed CSVs.

Without this step the unit stays pending and contributes nothing to the
ObjectReferences report, which is rebuilt generically from `dependencies.dependsOn`.

## Step 6: Report the verdict, exactly

For a new run, the exit code is the finding. Report it as it came:

| Exit | Meaning | How to report it |
|------|---------|------------------|
| `0` | Migrated, no degradation detected | Output exists and every gate the driver runs was satisfied. Still unverified against Snowflake unless `AIFIRST_SNOWFLAKE_CONN` was set. |
| `3` | **Migrated with degradation — the expected outcome** | Output exists and is incomplete in ways the driver names. This is **not a failure** and not a reason to retry. Report the degradations it listed. |
| `1` | Failed — no usable output | Nothing usable was produced. Say so plainly and do not present a partial tree as a conversion. |
| `2` | Usage error | The invocation was wrong, not the input. Fix the arguments and run again. |

**Exit 3 is what a first run on an unsupported platform normally returns.** Do not round it up into success and do not round it down into failure. Quote the driver's own verdict line together with the degradations printed above it.

For a Step 0 resume, there is no new exit code. Report the preserved artifact state:
whether a remediation brief exists, whether lineage was measured, and any degradation
already named by the existing reports. Never claim that the resume reran or revalidated
the producer.

Two claims you must not make:

- **That the generated SQL runs.** It is unverified unless `AIFIRST_SNOWFLAKE_CONN` was supplied and the run reported an execution count. Without that, call the SQL **unverified** — which is neither a claim that it works nor a claim that it does not.
- **That this equals a supported-platform conversion.** What the driver could not translate is written to `reports/AiFirstIssues/<PACKAGE>/`. Point the user at that directory by name.

## CHECKPOINT

Confirm with user:
- [ ] They were told their platform is unsupported by the native engine and that this path is a fallback
- [ ] A new run's exit code was reported using the table above, or a resume's preserved artifact state was reported without inventing a new run
- [ ] Converted output is under `snowflake/_etl/<PACKAGE>/`, issues under `reports/AiFirstIssues/<PACKAGE>/`
- [ ] Whether the SQL was executed in Snowflake was stated either way, never left implied
- [ ] Existing producer output was resumed without invoking the driver or replacing its reports
- [ ] The unit's conversion was advanced per Step 5 — `completed` only with a real remediation brief, otherwise `failed` with the reason
- [ ] Lineage was written once from `lineage.json`, or deliberately skipped because the producer never measured it

Then return to `../SKILL.md`.
