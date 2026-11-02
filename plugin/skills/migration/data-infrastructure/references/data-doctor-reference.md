# Data Doctor reference

Run `scai data doctor` before starting data migration or data validation. The command checks Snowflake grants, worker (DEW) configuration, orchestrator connectivity, workflow YAML schema (when `--config` is passed), and partition-key feasibility on the source (migration configs). It does **not** create or modify Snowflake objects. When the orchestrator venv is missing it creates that venv and pip-installs the orchestrator, including when the orchestrator runs in SPCS, because the orchestrator doctor checks run from that local venv.

Use `--json` (a global flag) so you can parse structured results. Run from the project root.

## JSON contract

The envelope is the standard CLI shape. On success it carries a `result` object; on a runtime error it carries an `error` object instead of `result`:

```json
{
  "success": true,
  "warnings": ["..."],
  "result": {
    "hasFailures": false,
    "hasWarnings": true,
    "checks": [
      {
        "label": "Role grants",
        "status": "Pass",
        "detail": "Role MIGRATION_ROLE has USAGE on SNOWCONVERT_AI.DATA_MIGRATION",
        "suggestion": null,
        "section": "Snowflake"
      },
      {
        "label": "Partition key — dbo.Orders",
        "status": "Warning",
        "detail": "High NULL ratio (12%) in OrderDate",
        "suggestion": "Choose a non-nullable column or accept skewed partitions",
        "section": "Partition key"
      }
    ],
    "recommendations": {
      "advice": "...",
      "suggestedMaxThreads": 8
    }
  }
}
```

- `result.hasFailures` / `result.hasWarnings` are precomputed booleans — gate on `hasFailures` directly instead of re-scanning.
- `result.checks[].status` is one of `Pass`, `Warning`, `Fail`, `Skipped` (PascalCase — match exactly).
- `result.checks[].section` is one of `Snowflake`, `DEW`, `Orchestrator`, `Partition key`, `Data validation`.
- `suggestion` is populated only for `Warning` and `Fail` checks; it is `null` otherwise. Skipped rows may still carry a `suggestion` that says how to unlock the check.
- `warnings` is omitted when empty.

## Result handling (all levels)

1. **If there is no `result` object** — the envelope has a top-level `error` (`code`, `message`, `suggestion`, `details`) or the command emitted no JSON at all — surface stderr / the error to the user and stop. This is a runtime error (bad connection name, missing TOML, command crash), not a check failure; do **not** treat it as a passing run.
2. Read `result.checks`. **Group by `section`**, then list **Fail** first, then **Warning**, then **Skipped**.
3. **Gate on `result.hasFailures`** — when you run doctor manually (Level 1, before setup), don't proceed to workflow setup while it is `true`. `data_infrastructure(mode="up")` enforces the same gate before starting shared infrastructure. `migrate_data(mode="run")` and `validate_data(mode="run")` require that infrastructure to be ready but do not rerun Doctor. Present each failure's `detail` and `suggestion` to the user with concrete next steps (grants SQL, TOML edits, partition column changes, etc.); you do not need to auto-fix everything.
4. **Iterate** — after the user applies fixes, re-run the same doctor command until `hasFailures` is `false`.
5. **Warnings** — the CLI exits 0 with warnings. Summarize them and ask whether to fix now or proceed.
6. **Skipped** — explain what was skipped and which flag unlocks that check (usually `--config` or `--source-connection`).

| Section | Common fixes |
|---------|----------------|
| Snowflake | Grants from [data-infrastructure/SKILL.md](../SKILL.md), through its [grant procedures](../SKILL.md#grant-procedures) when the metadata database has them; warehouse on connection; [troubleshooting-reference.md](../../migrate-objects/actions/data-migration/references/troubleshooting-reference.md#spcs-service-privilege-errors) |
| DEW | Worker TOML placeholders, ODBC driver, [worker-config-reference.md](./worker-config-reference.md) |
| Orchestrator | Service suspended → `ALTER SERVICE … RESUME`; affinity mismatch → migration troubleshooting |
| Partition key | Set or change `columnNamesToPartitionBy`; use `--analyze-partition-keys` for suggestions |
| Data validation | Source-platform prerequisites below. Fix the named grant, UDF, or column type, then re-run doctor |

## Source-platform prerequisites

When `--config` is a workflow, doctor runs only the checks for that source. A failing row blocks `scai data migrate start` and `scai data validate start` the same way it blocks `scai data doctor`.

| Source | When it runs | Fail means |
|--------|----------------|------------|
| Teradata | Validation with `rowValidation` | `HASH_MD5` is not callable in the worker's default database |
| Oracle | Validation with `rowValidation` and a `CLOB`, `NCLOB`, `BLOB`, or `XMLTYPE` column | The source user cannot `EXECUTE` `DBMS_CRYPTO` |
| BigQuery | Migration or validation config that names tables | A column is bare `BIGNUMERIC` or `BIGDECIMAL` (no precision and scale) |
| Redshift | Any table uses extraction strategy `unload` | The worker config is missing `unload_s3_bucket` or `unload_iam_role_arn`, or the value is still a placeholder |

Other dialects emit none of these rows. Oracle with no LOB or XMLTYPE column passes without asking for the grant. A `columnTypeMappings` or `customColumnTransforms` entry that names the BigQuery column (or the bare type) passes that column.

## Source probes under `--spcs-mode full-spcs`

Doctor runs the partition-key and source-prerequisite probes from the machine running scai, not from the worker. Under `--spcs-mode full-spcs`, with no local worker, the worker connects to the source over SPCS's network. So when this machine cannot reach the source, each probe row is a **Warning**, not a Fail, and the run does not fail on it:

- `Source connection` (Partition key section) gives the connection error and says doctor can't confirm the SPCS worker will reach the source.
- Each partition-key row says doctor can't confirm the column has no NULLs and enough distinct values.
- The Teradata `HASH_MD5`, Oracle `DBMS_CRYPTO` and BigQuery `BIGNUMERIC` rows say what they could not confirm. No probe runs, so a connection error never reads as a missing prerequisite. The Redshift UNLOAD row sends no query and is unchanged.

To check these rows, run doctor from a machine that can reach the source. When this machine can reach it, the rows are checked as in every other mode. Hybrid, full-local, no `--spcs-mode`, and the pre-run doctor of `scai data migrate|validate start` (which runs a local worker) keep failing an unreachable source.

---

## Level 1: Infrastructure (no workflow YAML)

**When:** After compute pool registration and worker config are complete (end of [data-infrastructure/SKILL.md](../SKILL.md) or any worker sub-skill), **before** generating or running a migration/validation workflow.

Resolve connection names from the latest `configure()` response (`snowflake_connection`, `source_connection`).

```bash
scai data doctor \
  -c <snowflake_connection> \
  --source-connection <source_connection> \
  --json
```

Omit `-c` or `--source-connection` only when not yet configured; those sections will show `Skipped` checks with instructions to pass the flag.

**Done when:** `result.hasFailures` is `false`. User has acknowledged or resolved warnings.

---

## Level 2: Infrastructure gate (automatic during `up`)

`data_infrastructure(mode="up")` runs the quick infrastructure Doctor (no `--config`) after generating and applying the selected worker configuration. It **refuses to start** when `hasFailures` is `true` and returns `doctor_failures`. Whether a row is a Fail is scai's call; the gate never promotes a Warning. `up` passes `--local-processes` naming the processes it is about to start on this machine (`none` when it starts neither), and scai skips this machine's worker checks (RAM, CPU, disk, source drivers, worker config) when the list leaves the worker out. It reports three local-process prerequisites as Fail for a listed process and as Warnings otherwise: `Orchestrator environment` (the orchestrator's Python venv did not build) for a local orchestrator; `DEW environment` (the worker's venv did not build) and a `Data Exchange Worker config` row saying the worker config's source connection could not be resolved, for a local worker. Without `--local-processes`, `--spcs-mode` implies the placement (`full-local` runs both locally, `hybrid` the worker); with neither, they stay Warnings. An SPCS orchestrator still needs that local venv. Doctor creates it and pip-installs the orchestrator package before running `python -m data_migration_orchestrator doctor`, including when `--local-processes` omits `orchestrator`. Expect the install during `up` with `orchestrator_placement: spcs`. In that placement a venv that fails to build stays a Warning; it becomes a Fail only when the orchestrator process itself is local. The orchestrator doctor rows run only after the venv exists. scai reports the cryptography/OpenSSL load failure (a migration venv's `cryptography` cannot load its OpenSSL symbols) as a failing `DEW doctor` / `Orchestrator doctor` row in every mode, with the repair as its suggestion, so it blocks like any other failure. The migration and validation run tools then require that infrastructure to be ready; they do not invoke Doctor again.

- **The starts after a passing gate:** when this Doctor passes, `up` starts the local orchestrator and worker with `--skip-doctor`, so `scai data orchestrator start --local` and `scai data worker start --local` do not repeat the checks it just ran. When it could not run, returned a result without a boolean `hasFailures: false`, or `skip_doctor=true` overrode its failures, the starts run their own checks, as before.
- **On `doctor_failures`:** surface each failure's `detail` / `suggestion` to the user and fix it, then call `data_infrastructure(mode="up")` again. To proceed despite failures, pass `skip_doctor=true` to `data_infrastructure` — only after the user explicitly accepts them. With failures overridden, `up` never reports `ready`: a bring-up that would otherwise be ready reports `status="degraded"` instead, while `failed` (a process exited) and `not_ready` (still bootstrapping) keep their status. Every one of them lists the overridden checks in `blocking_checks`, and a dispatch can fail or sit Pending until they are fixed.
- **On `Access to existing objects in <schema>` rows in `doctor_warnings`:** the active role neither owns nor inherits that metadata schema, so the orchestrator would fail on its existing tables one statement at a time. scai's doctor reports one row per scai metadata schema (`DATA_MIGRATION`, `DATA_VALIDATION`, `COMMON`, `TEMP` as configured) and `up` adds one for `ORCHESTRATION`, so a single `up` lists every schema the role can't use. A scai schema the role can't see is Skipped here and explained by its schema row; once that is granted, the next `up` may add its Warning. An `ORCHESTRATION` the role can't see gets its own Warning, since no other row covers it. Show the rows together and apply the user's chosen fix (use the owner role, `GRANT ROLE <owner>`, or every grant in the suggestion) for all listed schemas before the next `up`. They are Warnings because explicit grants can already cover a non-owner; if the user confirms that, continue, and don't raise the same rows again on later `up`s in this session.
- **Workflow-schema validation** is enforced separately: the MCP run preflight rejects known structural errors, and `scai ... create-workflow` performs the authoritative full configuration validation.

### Partition-key analysis (setup, not run)

`migrate_data(mode="setup")` runs the partition-key probe (`--analyze-partition-keys`: NULL-ratio and cardinality queries against the source, plus PK-based suggestions from the Code Unit Registry) and returns `partition_key_findings`; `validate_data(mode="setup")` runs the same probe against the validation workflow. Both also return every other Fail and Warning from that run as `doctor_findings` (`failures`, `warnings`), so workflow-schema, extraction-stage and worker-config problems surface at setup instead of at dispatch. For a table large enough to partition, doctor compares the leading `columnNamesToPartitionBy` entry to the column the source can prune on (Redshift sort key, SQL Server or Synapse clustered index, Teradata level-1 RANGE_N partitioning column, PostgreSQL partition key, correlated BRIN column, or cluster key, Oracle partition key or IOT primary key, Snowflake clustering key, BigQuery partition column / `_PARTITIONTIME` / leading clustering column). A mismatch is a `Partition prune:` warning — except on BigQuery when `require_partition_filter` is true, which is a Fail because extraction queries that omit a partition filter are rejected. Show it and wait for confirmation before editing the YAML or starting the run. Other partition findings stay advisory and never block.

Suggestion order when `columnNamesToPartitionBy` is omitted: physical prune column (if any), then the first primary-key column in table column order, then (Redshift dist key from `svv_table_info.diststyle`, Teradata primary index from `DBC.IndicesV`). Only the prune column triggers the `Partition prune:` warning — a Redshift distribution key does not let Redshift skip blocks, and a Teradata primary index does not prune range scans (use row partitioning). For Redshift, `sortkey1 = AUTO(SORTKEY)` means no declared sort key (no prune column); `AUTO(SORTKEY(<col>))` yields `<col>`. For Teradata, `ConstraintText` that is expression `RANGE_N` / `CASE_N` / no row partitioning yields no prune column. For BigQuery, prefer the partition column (`is_partitioning_column`), then `_PARTITIONTIME` on ingestion-time tables, then the leading clustering column; `_PARTITIONTIME` suggestions need sync `none`.

### Manual invocation (debugging only)

To reproduce what infrastructure setup runs, e.g. when diagnosing persistent `doctor_failures`, name the processes `up` starts on this machine with `--local-processes`: `orchestrator,worker` for a fully local setup, `orchestrator` when the worker runs elsewhere or `start_worker=false`, `worker` when only the worker is local (SPCS orchestrator), and `none` when nothing runs locally (SPCS orchestrator and SPCS or external worker). Omitting the flag runs the local worker checks, so a worker-only row such as a missing unixODBC fails a machine no worker runs on. No value skips the orchestrator venv install. Without it (and without `--spcs-mode`) the environment and worker source-connection rows stay Warnings, so the `doctor_failures` they cause do not reproduce.

```bash
scai data doctor -c <snowflake_connection> --source-connection <source_connection> \
  --local-processes orchestrator,worker --json
# add --config <workflow_path> --analyze-partition-keys to mirror the setup probe
```

