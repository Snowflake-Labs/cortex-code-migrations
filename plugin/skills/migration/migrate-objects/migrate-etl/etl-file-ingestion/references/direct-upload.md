# Direct-to-Stage Upload

For Step 4 of the parent skill: the host that owns the files uploads straight into `public.landing_stage` with `PUT`, so the files reach the stage without passing through a cloud bucket.

Two scripts ship with this skill. Both read `ingestion-manifest.json` at run time and plan every resolved, stage-mapped source it names, so a re-conversion that changes the manifest is picked up by copying the new manifest across, with the script left as is.

| Source host | Script | Needs on that host |
|---|---|---|
| Windows, UNC paths | `scripts/land-files.ps1` | PowerShell 5.1 (in-box since Windows Server 2016) and the Snowflake CLI |
| Linux, macOS, mounts | `scripts/land-files.py` | `python3` (standard library only) and the Snowflake CLI |

Copy the script and the manifest to the source host. Those two files are the whole payload.

## Arguments

Identical across both, modulo PowerShell's `-Name` versus POSIX `--name`.

| Argument | Meaning |
|---|---|
| `manifest` / `-Manifest` | Path to `ingestion-manifest.json`. |
| `--connection` / `-Connection` | An existing `snow` named connection on that host. |
| `--database` / `-Database`, `--schema` / `-Schema` | Where the stage lives. Use the same values `scai code deploy` used. |
| `--dry-run` / `-DryRun` | Print the plan and upload nothing. |
| `--source-id` / `-SourceId` | Limit the run to specific manifest source ids. Repeatable. |
| `--path-root` / `-PathRoot` | Rewrite a manifest location prefix onto this host, e.g. `'C:=/mnt/c'`. Repeatable. |
| `--parallel` / `-Parallel` | `PUT PARALLEL` setting, default 8. |

`--path-root` exists for hosts that hold the same files under a different root than the one the conversion recorded. When the script runs on the box that actually ran the packages, `originalLocations` is already correct and no mapping is needed.

## Always dry-run first

```
python3 land-files.py ingestion-manifest.json --connection <conn> --database <db> --dry-run
```

```powershell
powershell -ExecutionPolicy Bypass -File land-files.ps1 `
  -Manifest ingestion-manifest.json -Connection <conn> -Database <db> -DryRun
```

Read the output with the user before uploading anything:

| Line | Meaning |
|---|---|
| `UPLOAD` | A planned `PUT`: a file or wildcard, the stage prefix, and how many files matched. |
| `SKIPPED` | `requiresMapping`, or no stage mapping. The operator sets the converted runtime variable and lands the file under `expectedStagePrefix`; this script only PUTs `resolved` sources. |
| `NO FILES` | The directory resolved but nothing matched the `fileSpec` right now. Normal for a source that only receives files on some days; suspicious if they expected data. |
| `WARN` | Same file names repeat across recursed subdirectories and flatten onto one prefix, so only the last upload of each survives. Real data loss if those files are genuinely different. |
| `ERROR` | A path does not exist on this host, or two sources claim the same stage object. A missing path does not cancel the other planned `PUT`s. A cross-source collision (`both land on`) stops the run before any `PUT` and exits 1 — `OVERWRITE = TRUE` would otherwise let the last writer replace the object the `COPY` names. |

Exit code is `0` only when every planned `PUT` succeeded and nothing errored.

## What the scripts guarantee

| Behavior | Reason |
|---|---|
| `AUTO_COMPRESS = FALSE` on every `PUT` | The generated `COPY` names the exact object. Snowflake's default stores `<name>.gz`, which the `COPY` never reads — and it fails silently, not loudly. |
| `OVERWRITE = TRUE` on every `PUT` | The prefix is a landing slot, not an archive. Each run replaces the object in place. |
| Destination taken from `mapping.expectedStagePrefix` verbatim | Re-deriving the prefix from package or connection names drifts from what the deployed SQL reads. |
| Stage destination quoted in the `PUT`, limited to `@public.landing_stage/` paths of letters, digits, `_`, `.`, `-` and spaces | A subfolder such as `2024 Q1` lands under its own name. A quote, backslash or `;` cannot pass, so a manifest cannot end the literal and append SQL; such a source is an `ERROR`. |
| One `PUT` per directory, not per file | A wildcard upload moves a whole directory in parallel, which is what makes hundreds of files per run practical. |
| A failed `PUT` does not stop the remaining sources | One unreachable package should not strand the other hundreds. Failures are counted and reported, and the exit code reflects them. A cross-source collision is not one of these failures: it stops the run before any upload. |
| Credentials come from the named `snow` connection | Passwords, private keys, and tokens stay in the Snowflake CLI config on that host, outside the script, the project, and the manifest folder. |

Have them confirm the connection resolves on that host before scheduling:

```
snow connection test -c <connection>
```

## Scheduling

The user owns the schedule: it runs on their scheduler, under their service account, at a cadence that matches when the upstream job produces the files — hourly, nightly, or on whatever trigger the old ETL used. Hand these over as starting points to adapt.

Windows, Task Scheduler:

```powershell
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -File "C:\scai\land-files.ps1" ' +
               '-Manifest "C:\scai\ingestion-manifest.json" -Connection prod -Database MIGRATED')
$trigger = New-ScheduledTaskTrigger -Daily -At 2am
Register-ScheduledTask -TaskName 'Snowflake file landing' -Action $action -Trigger $trigger
```

Register it as an account that already has read access to the source files. Add `-RunLevel Highest` only if the files need elevation — it also requires an elevated session to register.

Linux, cron:

```cron
0 2 * * * /usr/bin/python3 /opt/scai/land-files.py /opt/scai/ingestion-manifest.json \
  --connection prod --database MIGRATED >> /var/log/scai-landing.log 2>&1
```

The nonzero exit on failure is what makes the log worth monitoring — wire it to whatever alerting they already run.

Three things they tune per site: the cadence above, the account the job runs as (it needs read access to the source files), and where the log and its alerts go.

## Limits worth saying out loud

- The scripts upload and leave the source host untouched, so archiving, renaming, and deleting stay with whatever handles them today. An SSIS package that moved files to an archive folder after loading still needs that behavior somewhere.
- Every run re-uploads whatever currently matches, whether or not it changed. `idempotency.transferWhenChanged` describes the contract the manifest wants; `OVERWRITE = TRUE` satisfies it correctly but not cheaply. For a large directory that rarely changes, that is bandwidth worth discussing.
- A `WARN` about flattening is the script reporting what `destinationKeyPolicy: basename` asks for. Changing it is a conversion-side decision, not something to patch in the upload.

## After the first run

Verify with Step 7 of the parent skill: `LIST` the prefix, then read a few rows of a landed object through the deployed file format. For an exact source, compare the listed name against `mapping.expectedStageObjectPath`; for a glob source, pick one listed object and check its key against `destinationKeyPolicy`. A clean exit from `PUT` proves the transfer, and this proves the `COPY` will find and parse the object.
