---
name: etl-file-ingestion
description: Hand over the landing contract for converted flat-file ETL — read the ingestion manifest, pick Openflow / direct PUT / their own mover, and hand over the uploader, the generated flow, or a filled path table to run on the host that has the files. Writes a landing plan to disk. Optional: verify a landed object parses. Triggers: file ingestion, land my files, landing stage, set up Openflow, upload files to the stage, flat file ingestion, go live with ETL files, where do my CSVs go.
parent_skill: migrate-etl
license: Proprietary. See License-Skills for complete terms
---

# ETL File Ingestion (Go-Live)

## On Entry

Tell the user:
> **Setting up file landing** — converted packages read from a Snowflake stage. I'll read the conversion's ingestion manifest, you pick a path, and I'll hand you the script, Openflow flow, or mover table to run on the host that has the files, on your own schedule.

## Step 0: Find the Manifest

The conversion writes one manifest per run. Read the newest:

```
artifacts/ingestion/<conversion-run>/ingestion-manifest.json
```

`schemaVersion` must be `1.0`. On any other value, stop and tell the user the manifest is newer than this skill rather than guessing at renamed fields.

**No manifest, or `sources` is empty:** this conversion reads no flat files. Tell the user landing is unnecessary here and hand control straight back to [../SKILL.md](../SKILL.md) Step 4, so the deploy still finishes.

Otherwise report what you found per source — `id`, `packageName`, and `mapping.expectedStagePrefix` — so the user sees which packages depend on files arriving.

## Step 1: Confirm the Landing Contract Is Deployed

The stage and the file formats come from `scai code deploy`. Confirm they exist before planning uploads into them:

```
snow sql -q 'DESC STAGE public.landing_stage' -c <connection> --database <database>
snow sql -q 'SHOW FILE FORMATS IN DATABASE' -c <connection> --database <database>
```

Match each `consumers[].fileFormatName` against that listing case-insensitively and across schemas — unquoted names are created uppercase, so a `LIKE '<name>'` filter reports a deployed format as missing.

If the stage or a needed format is absent, the unit is not fully deployed: return to [../SKILL.md](../SKILL.md) Step 4 to finish the deploy, and stop here. Creating those objects by hand drifts from the generated definitions (encoding, header, delimiter, enclosure), which surfaces later as unexplained bad rows rather than an error.

## Step 2: Classify Each Source, Then Ask

`originalLocations[]` is where the files live today, and it decides which paths are even possible. Load [references/ingestion-manifest.md](./references/ingestion-manifest.md) for any field you need to interpret.

| `originalLocations[]` | What is possible |
|---|---|
| `s3://…`, `gs://…`, `azure://…`, `https://<account>.blob.core.windows.net/…` | Already in a bucket — Openflow can watch it (Step 3). |
| Windows or UNC (`C:\…`, `\\server\share\…`) | Files sit on a host. Either a job of theirs copies them to a bucket and Openflow takes it from there (Step 3), or that host uploads straight to the stage (Step 4). |
| POSIX path or mount (`/data/…`, `/mnt/share/…`) | Same two options. |
| Any of the above, and they already run Fivetran, NiFi, Airflow, or an in-house mover | Hand that tool the contract instead of building a second path (Step 5). |

`resolutionState` other than `resolved` (typically `requiresMapping`) is a runtime path: `originalLocations` is a variable or expression (`@[User::FileName]`, a folder variable plus a file name). Converted SQL already reads `mapping.expectedStagePrefix` plus that variable. The operator sets the converted variable (`runtimePathBinding.parameters`, e.g. `User_FileName`) to the object they land, and uploads the file under that prefix. Manifest landing — `land-files` and the generated Openflow — only processes `resolved` sources.

State the classification per source, then ask. Keep **Your own mover** on the list every time, so Step 5 stays reachable. Offer three ways when any source sits on a host, two when every source is already in a bucket — with no host to run a script on, drop the Direct upload sentence and say "two ways".

Tell the user:
> "These files live on <location> today. Three ways to get them into Snowflake. **Openflow** is managed, polls continuously, and the flow is already generated — the files reach it through a cloud bucket. **Direct upload** is a script you run on the machine that has the files, writing straight to the stage — fewer moving parts and no bucket, but you own the script. **Your own mover** — if you already move files with Airflow, NiFi, or an in-house job, I'll give that tool the exact paths instead of building a second pipeline. Which fits?"

When locations are mixed, pick per class in that one answer: bucket sources take Openflow or their mover, host-local sources take direct upload or their mover. One combined choice, one landing plan.

**Wait for the user's response — do not proceed until they choose.** That choice is the only wait here. Produce the payload for their path, write it up in Step 6, then return in Step 8.

## Step 3: Openflow

The conversion generated the flow, one per cloud, under `<ETL root>/openflow/`:

```
SnowConvert ETL Landing.json          (S3)
SnowConvert ETL Landing (Azure).json
SnowConvert ETL Landing (GCS).json
```

They ship disabled and already wired end to end. Each variant's list processor (`ListS3`, `ListAzureBlobStorage_v12`, `ListGCSBucket`) watches a bound key prefix, fetches each object, and writes it into `public.landing_stage`. Import the matching JSON; what the user supplies is the parameter context and the credential services.

1. Pick the variant for their cloud and import it into Openflow.
2. Fill every value in the flow's parameter context. It ships with all of them empty: the `SOURCE_*` keys `sourceParameters` records (`SOURCE_BUCKET`, `SOURCE_REGION`, `SOURCE_ENDPOINT`) plus the Snowflake side the flow writes through — `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_ROLE`, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA`, `SNOWFLAKE_AUTHENTICATION_STRATEGY`. Use the same database the deploy used. These values live in Openflow rather than in the migration project.
3. Supply credentials in the flow's controller services, which sit outside the parameter context: the cloud credentials provider named by `sourceParameters.credentialsServiceName` and the Snowflake connection service.
4. Name who writes objects to `mapping.expectedBucketPrefix` (some manifests spell this `expectedS3Prefix` — same field), an object **key** prefix inside that bucket rather than a URI, and for an exact source precisely `mapping.expectedBucketObjectPath` / `expectedS3ObjectPath`. The list processor watches the enclosing package prefix and preserves each object's key into the stage, so the key upstream writes is what the `COPY` reads.
5. Enable the flow when they are ready. Record enablement in the landing plan as an operator-owned step.

**Openflow starts at the bucket, so name an owner for the hop into that prefix.** For an on-prem source that is their existing upload job, or a scheduled `aws s3 sync` / `azcopy` / `gsutil rsync`.

Hand them the JSON path, the parameter and service names, and the bucket prefix. Then Step 6.

`idempotency` is the contract for that first hop: with `transferWhenChanged: true`, rewriting a key with new content must move data while rewriting identical content should not. A daily job that overwrites the same file name fits it. Apply it to whatever writes the bucket.

If `sourceParameters.requiresDcp` is true, the bucket reaches Snowflake over a private network, so DCP setup is an Openflow prerequisite. Record it in the landing plan with an owner, then continue to Step 6.

## Step 4: Direct Upload to the Stage

This skill ships the uploader — do not hand-author `PUT` commands per source. One script reads the manifest, plans every resolved source that has a stage mapping, and reports the rest, which is what makes a migration with hundreds of packages one command.

| Source host | Script |
|---|---|
| Windows, UNC paths | [scripts/land-files.ps1](./scripts/land-files.ps1) |
| Linux, macOS, mounts | [scripts/land-files.py](./scripts/land-files.py) |

Copy that script and `ingestion-manifest.json` to the source host. Those two files are the whole payload. The script reads the manifest at run time, so a later re-conversion means copying the new manifest across and refreshing the plan, with the script left as is.

Tell the user:
> "These two files are the whole payload. Copy them onto the host that has the files and run the dry-run there. Come back when you want a landed object checked."

Do not run the dry-run in this session. The command below is for that host:

```
python3 land-files.py ingestion-manifest.json --connection <connection> --database <database> --dry-run
```

The output classifies every source as `UPLOAD`, `SKIPPED`, `NO FILES`, `WARN`, or `ERROR`. [references/direct-upload.md](./references/direct-upload.md) has the argument reference, how to read each line, and Task Scheduler and cron examples — go there rather than reconstructing the invocation.

Scheduling is theirs. Point them at those examples as starting points, and say which knobs are site-specific: the cadence (match it to when the upstream job writes the files), the account the job runs as, and where the log and alerts go.

Two of those lines need the user's judgement, not yours:

- `SKIPPED` is a `requiresMapping` source, or one with no `mapping.expectedStagePrefix`. The operator sets the converted variable and lands the file under the stage prefix; the script leaves those sources alone.
- `WARN` means same-named files in recursed subdirectories flatten onto one prefix and only the last survives. Ask whether those files are genuinely different before treating the run as good.

Tell the user:
> "Every upload sends the exact object name, uncompressed, overwriting in place — that is what the generated `COPY` reads. Compress it and you land a `.gz` the `COPY` skips, which shows up as an empty load rather than an error. Each run replaces the same object, so treat the prefix as a landing slot."

Credentials come from an existing `snow` named connection on that host, so passwords, private keys, and tokens stay in the Snowflake CLI config rather than in the script, the project, or the manifest folder.

Hand them the two files, the dry-run command, and the compression warning. Then Step 6.

## Step 5: Hand the Contract to an Existing Mover

When they already own a file mover, give it the contract rather than building a second pipeline. Per source: the source id, the original location, the destination (`expectedStageObjectPath` for exact sources, otherwise `expectedStagePrefix`), and the distinct `consumers[].fileFormatName` values.

Tell the user:
> "Whatever moves the file has to land it under that exact name, uncompressed and in that exact directory, and the bytes have to parse under the file format the package was deployed with. Generic movers compress the object and stamp a date into the key by default, so both of those are worth saying out loud to whoever configures it."

[references/ingestion-manifest.md](./references/ingestion-manifest.md) has the handoff table to fill from the manifest.

Fill that table, then Step 6.

## Step 6: Write the Landing Plan

The work happens on someone else's host, often days later and often by someone outside this chat. Write the plan to disk beside the manifest so it outlives the session:

```
artifacts/ingestion/<conversion-run>/landing-plan.md
```

Write it under these headings, in this order, so every plan reads the same way:

- **Selected path** — Openflow, direct upload, or their own mover, and which sources take it when the answer was mixed.
- **Source contract** — one row per source: source id, package, original location, destination (`expectedStageObjectPath` for exact sources, otherwise `expectedStagePrefix`), and the distinct `consumers[].fileFormatName` values. These come from the manifest verbatim.
- **Invariants** — the exact object name, uncompressed, overwriting in place, in the stage directory the manifest names.
- **What to run** — the two files and the dry-run command (direct upload), the flow variant plus its parameter and service names and the bucket prefix (Openflow), or the filled handoff table (their own mover).
- **Ownership** — who owns each hop. For Openflow, name whoever writes into the bucket prefix and whoever enables the flow.
- **Prerequisites** — anything outstanding before files can land: DCP for a private-network bucket; for each `requiresMapping` source, the converted variable name and the stage prefix the operator uploads into.
- **Verification** — Step 7's `LIST` and read-through-format check, for whoever wants to confirm a landed object later.
- **Re-conversion** — a new conversion writes a new manifest; re-read it, re-copy it to the host if the uploader lives there, and refresh this plan.

Spell the contract and invariants out here rather than linking to the references: whoever reads this file may be doing it days later, on another host, with no session loaded.

Tell the user where you wrote it, then verify (Step 7) or return (Step 8).

## Step 7: Verify a Real File Lands (only if they ask)

Run this when an object is already in the stage — they said so, or they came back to have one checked.

Configuration is not evidence. Confirm the object arrived:

```
snow sql -q 'LIST <expectedStagePrefix>' -c <connection> --database <database>
```

For an exact source (`selection.kind: exact`), compare the listed name against `mapping.expectedStageObjectPath` character for character — a `.gz` suffix, an extra folder, or a rename each leave the `COPY` reading an object that is not there. For a glob source, pick one listed object, confirm its key follows `destinationKeyPolicy`, and verify that object; the exact-path field is an exact-source field.

Then read the file through the deployed file format — the same parse the package does, read-only. Write the statement to `verify-landing.sql` and run it with `-f`; inline it breaks on `$1` and on the quoted format name.

```sql
SELECT $1, $2, $3
FROM <the object you just listed> (FILE_FORMAT => '<fileFormatName>')
LIMIT 5;
```

```
snow sql -f verify-landing.sql -c <connection> --database <database>
```

Garbled text points at the encoding, a header row appearing as data at `SKIP_HEADER`, and everything arriving in `$1` at the delimiter. Fix the upload. If the file itself disagrees with the deployed format, tell the user their source data and the converted contract differ and let them decide which one moves.

Then Step 8.

## Step 8: Return to the Calling Skill

Tell the user:
> "The plan is written to `artifacts/ingestion/<conversion-run>/landing-plan.md`, so whoever runs the move has the contract. A one-time upload later proves it; the next scheduled run reads whatever is sitting at that path. Landing has to be continuous for the graph to keep producing fresh data. Ask me to check a landed file when you have one."

Then return to [../SKILL.md](../SKILL.md) Step 4, at the point that skill offered this one:

- **Entered from that offer** — hand control back to Step 4 and let it make its own `transition_status(task="deploy")` call, so `deploy` advances once and the unit reaches `etlSeed`.
- **Entered later by skill-match** — the machine already sits at `etlSeed`, `etlValidate`, or done. Stamp nothing; the unit keeps its position.

Activation stays where it was in either case: the `deploy` tool with `snowflake_task_activate = true`, only when the user asks.
