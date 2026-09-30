# Data Validation Task Model Reference (DMVF)

DV-specific task model for debugging validation workflows. Task structure, lifecycle, dependency model, and the pause/resume/cancel procedures are shared with data migration: see the [DMVF task model reference](../../../migrate-objects/actions/data-migration/references/task-model-reference.md). Full internal docs: `dmvf/docs/data-migration-orchestrator/task-model.md` and `scopes.md`.

## Executors in validation

| Executor | Validation work |
|----------|-----------------|
| `orchestrator` | Level evaluation (`Evaluate[LEVEL]`), reconcile of `POSSIBLE_MISMATCH` |
| `data-exchange-agent` | Checksum collection, validation query execution against the source |
| `warehouse` | Snowpipe drain barriers for validation results |

## Task flow

Validation runs L1 (schema) → L2 (metrics, per partition) → L3 (row hash, per partition) chains per table, with Snowpipe drain barriers when `useSnowpipeForResults` is true.

## Data validation scopes

Validation tasks are prefixed with `DV::` so they never collide with migration scopes.

| Pattern | Meaning |
|---------|---------|
| `DV::Table[ID]::Preprocessing` | Validation metadata / table prep |
| `DV::Table[ID]::SchemaValidation` | L1 schema validation |
| `DV::Table[ID]::Partition[N]::MetricsValidation` | L2 metrics validation |
| `DV::Table[ID]::Partition[N]::RowValidation` | L3 row-hash validation |
| `DV::Table[ID]::Partition[N]::CellDrilldown` | Hybrid L3 cell drill-down (may carry `Batch[k]` before the op) |
| `DV::Table[ID]::Partition[N]::WriteResults[row\|cell]` | Write results (row-hash or cell); batched as `...::Batch[k]::WriteResults[cell]` |
| `DV::Table[ID]::Evaluate[LEVEL]` | Evaluate a completed level |
| `DV::Table[ID]::ReconcilePossibleMismatches` | Post-drilldown reconcile of `POSSIBLE_MISMATCH` |
| `DV::Table[ID]::L3EarlyStopMonitor` | Periodic L3 early-stop monitor |
| `DV::Table[ID]::DetectionComplete` / `::SyncBaseline` / `::SyncFinalize` | Incremental validation bookkeeping |
| `DV::Pipe[KEY]::SnowpipeSetup\|SnowpipeTeardown\|SnowpipeDrain\|SnowpipePrepareDrain` | Snowpipe ops for validation results |
| `DV::ObjectTypeDetection::Preprocessing` | Object-type dispatch task |

Scope matching uses SQL `LIKE`, as for migration scopes: for example `DV::Table[%]::Partition%::RowValidation` selects L3 tasks for scope-filtered queries, pause/cancel, or rate-limit `SCOPE_PATTERN` rules. See [rate limiting](../../../data-infrastructure/references/advanced-operations-reference.md#rate-limiting-protect-source-or-shared-resources).

## `POSSIBLE_MISMATCH` after completion

Hybrid L3 may stop early when `earlyStoppingForRowHashing` or `maxFailedRowsNumber` triggers. A finished workflow can report `POSSIBLE_MISMATCH` — this is **not** a clean pass. Review L3 result rows before signing off.

## Related references

- [Validation troubleshooting reference](./troubleshooting-reference.md)
- [DMVF task model reference](../../../migrate-objects/actions/data-migration/references/task-model-reference.md)
- [Validation levels reference](./validation-levels-reference.md)
