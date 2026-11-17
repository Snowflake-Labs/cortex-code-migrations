# `scai assessment waves query`: API Reference

The read-only JSON query interface over the Code Unit Registry (CUR) dependency graph, as it exists today. The business-use-cases skill reads the graph through this command. It is hidden from `scai assessment --help`.

**CUR** = Code Unit Registry (`.scai/registry/` or `registry/`).

---

## 1. Summary

```
scai assessment waves query <operation> [options] --json
```

| Property | Value |
|---|---|
| Transport | CLI. JSON on stdout, or inside the JSON envelope when `--json` is set |
| Visibility | Hidden (skill tool) |
| Project | Requires an SCAI project (`RequiresProject = true`) |
| Graph source | C# `CurGraph`, rebuilt from the registry on every call (no cache) |
| Errors | `ASM0048` (`WavesQueryInvalid`) |
| Operations | 9: `schemas`, `sinks`, `roots`, `relations`, `find`, `upstream`, `downstream`, `flow`, `closure` |

---

## 2. Source files

| Concern | File |
|---|---|
| CLI command (operation parse, project check, request build) | `Snowflake.SnowConvertDesktop/Snowflake.SnowConvert.Cli/Commands/Assessment/Waves/WavesQueryCommand.cs` |
| CLI settings (options and help text) | `Snowflake.SnowConvert.Cli/Commands/Assessment/Waves/WavesQuerySettings.cs` |
| JSON output | `Snowflake.SnowConvert.Cli/Commands/Assessment/Waves/WavesJsonOutput.cs` |
| Validation, ids-file, dispatch | `Snowflake.SnowConvert.Assessment/Services/Waves/WavesQueryService.cs` |
| Request, response, operation enum, limits | `Snowflake.SnowConvert.Assessment/Models/Waves/Graph/WavesQueryRequest.cs` |
| Query implementations | `Snowflake.SnowConvert.Assessment/Services/Waves/Graph/CurGraphQueries.cs` |
| Result models | `Snowflake.SnowConvert.Assessment/Models/Waves/Graph/WaveGraphModels.cs`, `WaveQueryModels.cs` |
| Object summaries | `Snowflake.SnowConvert.Assessment/Services/Waves/Graph/WaveUnitFacts.cs` |
| Graph loader | `Snowflake.SnowConvert.Assessment/Services/Waves/Graph/CurGraphLoader.cs` |
| Flow rule | `Snowflake.SnowConvert.Assessment/Services/Waves/Graph/FlowRule.cs` |
| Roots paging | `Snowflake.SnowConvert.Assessment/Services/Waves/Coverage/WaveRootsQuery.cs` |
| Error code | `Snowflake.SnowConvert.Results/Domains/Assessment/ScErrors.Assessment.cs` (`WavesQueryInvalid = ASM0048`) |
| Tests | `Snowflake.SnowConvert.Assessment.Test/Services/Waves/WavesQueryServiceTests.cs`, `Snowflake.SnowConvert.Cli.Test/Commands/Assessment/Waves/WavesQueryCommandTests.cs` |

---

## 3. Command-line options

| Option | Applies to | Rules |
|---|---|---|
| `<operation>` | all | One of the nine operations. Parsed by `WavesQueryOperations.TryParse`. An unknown name fails with `ASM0048` |
| `--id <ID>` (repeatable) | `relations`, `upstream`, `downstream`, `flow` (exactly one); `closure` (one or more) | CUR code unit id. Not a name. Use `find` to look one up |
| `--ids-file <FILE>` | `closure` only | JSON array of ids, or one id per line. Blank lines and lines starting with `#` are skipped. Relative paths resolve against the project root. Merged with `--id` values and de-duplicated |
| `--name <TEXT>` | `find` (required), `roots` (optional) | Every whitespace-separated word must match |
| `--tier <TIER>` | `sinks`, `roots` | Trimmed and lowercased. Must be `bi`, `etl`, or `sql` |
| `--schema <NAME>` | `roots` only | Restrict roots to one schema |
| `--max-downstream <N>` | `sinks` only | Keep sinks with at most N downstream dependents. Default 0 |
| `--offset <N>` | `roots` only | Roots to skip before the page. Must not be negative. Default 0 |
| `--limit <N>` | all | Default 50 (`WavesQueryRequest.DefaultLimit`). Max 500, or 5000 for `roots` |
| `--json` | all | Wraps the result in the JSON envelope |

Option and operation mismatches are rejected. Examples of the exact messages:

- `--name applies only to 'find' and 'roots'.`
- `--tier applies only to 'sinks' and 'roots'.`
- `--max-downstream applies only to 'sinks'.`
- `--schema applies only to 'roots'.`
- `--offset applies only to 'roots'.`
- `--ids-file applies only to 'closure'.`

---

## 4. Output

### 4.1 Envelope

With `--json`, the result is wrapped as:

```json
{
  "operation": "relations",
  "result": { ... }
}
```

`operation` is the lowercased operation name. Without `--json`, the bare result is written to stdout.

Serialization: camelCase property names; null properties are omitted.

### 4.2 Bounded lists

Most lists use `WaveBoundedList<T>`:

```json
{
  "items": [ ... ],
  "total": 412,
  "truncated": true
}
```

- `items`: the first `limit` entries, in the operation's documented order
- `total`: every match before the cap
- `truncated`: `true` when `total` is greater than `limit`

### 4.3 Object summary

Every object in a result is a `WaveObjectSummary`:

| Field | Type | Notes |
|---|---|---|
| `id` | string | CUR id |
| `name` | string | Display name |
| `type` | string | Object type, for example `TABLE`, `VIEW`, `PROCEDURE`, `ETL`, `SCRIPT`, `REPORT` |
| `category` | string | `sql`, `etl`, `script`, `bi`, or `other` |
| `platform` | string? | Source platform, or custom kind |
| `database` | string? | Database, when recorded |
| `schema` | string? | Schema, when recorded |
| `isMissing` | bool | `true` for an object the project references but does not hold |
| `conversionStatus` | string? | `Success`, `Require Attention`, or `Pending Conversion`. Null for missing and BI units |
| `sourcePath` | string? | Source file, when recorded |

An id the graph does not hold is summarized as `{ id, name: <id>, type: "UNKNOWN", category: "other", isMissing: true }`. This happens in relation and closure results. The service rejects unknown ids before the query runs, so this only appears for ids the graph references but does not hold.

---

## 5. Operations

### 5.1 `schemas`

Groups present objects by database and schema.

- **Arguments:** none
- **Present** means not missing and `inScope != false`.
- **Result:**

```json
{
  "schemas": {
    "items": [
      { "database": "SALES_DB", "schema": "DBO", "objectCount": 120, "typeCounts": { "TABLE": 80, "VIEW": 40 } }
    ],
    "total": 9,
    "truncated": false
  },
  "withoutSchema": { "PROCEDURE": 3 }
}
```

- **Grouping key:** database and schema, upper-cased.
- **Order:** object count descending, then database, then schema (case-insensitive).
- `withoutSchema` counts present objects that have no schema, by type. It is not capped.

### 5.2 `sinks`

Objects that few other units depend on. These are where a flow ends, and the candidate seeds for a use case.

- **Arguments:** optional `--tier`, optional `--max-downstream` (default 0)
- **Tier:** `bi` (BI units), `etl` (ETL and script units), or `sql` (SQL objects). Other categories are not included.
- **Filter:** `downstreamCount <= --max-downstream`
- **Item fields:**

```json
{
  "object": { ... },
  "tier": "sql",
  "downstreamCount": 0,
  "directDependencyCount": 3
}
```

  - `downstreamCount`: how many units depend on this one
  - `directDependencyCount`: its direct dependencies, excluding container objects (schema and database)
- **Order:** tier (`bi`, `etl`, `sql`), then `downstreamCount`, then name, then id.

### 5.3 `roots`

Pages through roots. A root is a plannable unit that no other plannable unit outside its own cycle depends on. A use case reaches a root only when it lists the root.

- **Arguments:** optional `--name`, `--tier`, `--schema`; paging with `--offset` and `--limit`
- **Limit:** up to 5000 per page
- **Paging:** `Skip(offset).Take(limit)`. `total` counts every match, not just the page.
- **Item fields** (`WaveRootSummary`):
  - `object`: the object summary
  - `tier`: `bi`, `etl`, `sql`, or null
  - `isIsolated`: uses nothing but its containers
  - `directDependencyCount`: direct dependencies, excluding containers
  - `writes`: writes rows into some table
  - `plumbingReason`: why it should stay pending (for example, a temporary, test, or deprecated object flagged by object exclusion). Null otherwise
  - `role`: `process`, `fed`, `consumer`, or `dataOnly`. Null for plumbing
  - `processFolder`: the ETL folder of the process it serves, when one does
- **Result:**

```json
{ "offset": 0, "roots": { "items": [ ... ], "total": 1840, "truncated": true } }
```

Page through a schema:

```
scai assessment waves query roots --schema SALES --limit 1000 --offset 0 --json
scai assessment waves query roots --schema SALES --limit 1000 --offset 1000 --json
```

### 5.4 `relations`

The direct edges around one object.

- **Arguments:** exactly one `--id`
- **Result:**

```json
{
  "object": { ... },
  "dependsOn": { "items": [ { "object": { ... }, "relation": "reads" } ], "total": 4, "truncated": false },
  "requiredBy": { "items": [ { "object": { ... }, "relation": "writes" } ], "total": 2, "truncated": false }
}
```

- **`dependsOn`:** what this object uses. `relation` says how this object uses it.
- **`requiredBy`:** what uses this object. `relation` says how that unit uses this object.
- **Relation values** (`WaveRelationKinds`):
  - `reads`: a read, and the target is a SQL data object (not a procedure or function)
  - `writes`: a write
  - `readsWrites`: both, with a data target
  - `references`: any other dependency with no read or write verb
- **Order:** name, then id, within each list.

### 5.5 `find`

Searches the registry by text.

- **Arguments:** `--name` (required, not blank)
- **Match:** every word must appear in the object's haystack. The haystack is the display name, canonical name, source name, source file path, and id. Case-insensitive.
- **Result:** bounded list of object summaries.
- **Order:** exact name match first, then present before missing, then name, then id.

```
scai assessment waves query find --name "daily sales" --json
```

### 5.6 `upstream`

Everything the object reaches by following dependencies, transitively. The start object is excluded.

- **Arguments:** exactly one `--id`
- **Result:** `{ "object": ..., "units": { items, total, truncated } }`, ordered by name, then id.

### 5.7 `downstream`

Everything that transitively depends on the object. Same shape as `upstream`, in the other direction.

### 5.8 `flow`

The flow behind a place where data lands: the jobs that produce it, and what those jobs read. This is what the skill uses to see what produces a landing table.

- **Arguments:** exactly one `--id`
- **Walk** (`FlowRule.Walk`, applied backward from the object):
  1. Start from the object.
  2. For each unit reached, follow its writers. The start object follows all of its writers. Any other unit follows its writers only when it is not a shared sink.
  3. For each unit reached that is present (not missing), follow the non-container targets it reads.
  4. Missing units are included but not walked through. Schemas and databases are never walked.
- **Shared sink:** a table written by 10 or more units (`FlowRule.SharedSinkWriters = 10`). The table stays in the flow. Its writers are not followed, unless the table is the start object. This stops unrelated jobs that write a control or log table from joining into one flow.
- **Result:** same shape as `upstream` (`object`, `units`). The start object is excluded from `units`.

### 5.9 `closure`

The slice one wave would deploy for one or more seeds.

- **Arguments:** one or more `--id`, or `--ids-file`, or both (merged and de-duplicated)
- **Unknown seed:** the whole call fails with `ASM0048` and the message `No code unit has id '<id>'. Look one up with the 'find' operation.`
- **Slice rule** (`WaveSliceBuilder`, per `CLAUDE.md`):
  - The slice is the seeds plus everything they depend on.
  - Reports are kept as anchors: counted, never deployed.
  - Missing units are reported.
  - Loaders (units that write a table the slice reads, unless that table is a shared sink) join with their own closure. Loaders of those loaders' inputs do not join.
- **Result:**

| Field | Type | Meaning |
|---|---|---|
| `seeds` | array of summaries | The seeds, capped at `--limit` |
| `metrics` | object | `objectCount` (deployable members), `sqlObjectCount`, `etlCount`, `scriptCount`, `macroCount`, `bteqCount`, `biCount` (anchors), `schemaCount`, `databaseCount`, `loaderCount`, `missingCount`, `typeCounts` |
| `conversion` | object | `clean`, `requiresAttention`, `notConverted`, `ewiCount` (actionable EWI/OOS findings across members) |
| `members` | bounded list | Members of the slice |
| `loaders` | bounded list | Loaders in the slice |
| `anchors` | bounded list | Reports and other anchors |
| `missing` | bounded list | Missing objects the slice references |
| `perSeed` | array of `{ id, objectCount }` | Present only when there are two or more seeds. Each seed's own slice size, for the first `--limit` seeds |

- Bounded lists are ordered by name, then id.

```
scai assessment waves query closure --id <ID> --id <ID> --json
scai assessment waves query closure --ids-file seeds.txt --json
```

### 5.10 `ids-file` format

A file whose text starts with `[` is parsed as a JSON array of strings:

```json
["8f1c...-id-one", "8f1c...-id-two"]
```

Anything else is read one id per line:

```
# seeds for the sales wave
8f1c...-id-one
8f1c...-id-two
```

A file that yields no ids, combined with no `--id` values, fails with `--ids-file '<path>' holds no ids.` A file that does not exist fails with `--ids-file '<path>' does not exist.` Malformed JSON fails with `--ids-file '<path>' is not a JSON array of ids: <parser message>`.

---

## 6. Limits

| Constant | Value | Applies to |
|---|---|---|
| `WavesQueryRequest.DefaultLimit` | 50 | Every operation when `--limit` is omitted |
| `WavesQueryRequest.MaxLimit` | 500 | Every operation except `roots` |
| `WavesQueryRequest.MaxRootsLimit` | 5000 | `roots` |
| `FlowRule.SharedSinkWriters` | 10 | `flow`, and the same rule in closure and use-case membership |

There is no server-side cache. The graph is loaded from the registry on every invocation.

---

## 7. Errors

All validation and lookup failures use `ASM0048` (`WavesQueryInvalid`). The result carries a suggestion that points to `scai assessment waves query find --name <TEXT>`.

| Case | Message |
|---|---|
| Unknown operation | `Unknown operation '<name>'. Use one of: <names>.` |
| Wrong number of ids | `'<operation>' needs exactly one --id.` |
| Closure with no seeds | `'closure' needs at least one --id or an --ids-file.` |
| Find without name | `'find' needs --name.` |
| Bad tier | `--tier must be one of: bi, etl, sql.` |
| Limit out of range | `--limit must be between 1 and <max>.` |
| Negative `--max-downstream` | `--max-downstream must not be negative.` |
| Negative `--offset` | `--offset must not be negative.` |
| Option on the wrong operation | See §3 |
| Unknown id | `No code unit has id '<id>'. Look one up with the 'find' operation.` |
| `--ids-file` missing, empty, or malformed | See §5.10 |
| Graph load failure | The graph loader's own error is returned |

---

## 8. Related commands

These are the other `scai assessment waves` commands, per `Snowflake.SnowConvertDesktop/Snowflake.SnowConvert.Assessment/CLAUDE.md`:

| Command | Writes | Role |
|---|---|---|
| `waves coverage` | `coverage.json` | Sizes the workload |
| `waves candidates` | `candidates.json` | Deterministic seeds |
| `waves cluster` | `clusters.json` | Clusters every root, for large workloads |
| `waves anchors` | `anchors.json` | Anchor shapes, each with a `flowSize` |
| `waves use-cases` | `use-cases.json` | Validates and rates the skill's `business-use-cases.json` |
| `waves plan` | `wave-plan.json` | Plans use-case and pending waves; does not rewrite `planning.wave` |

`waves query` is the skill's read-only view of the graph. The batch commands above write artifacts. The Rust dashboard's Object Lineage endpoints (`/api/assessment/object-lineage/*`) are a separate implementation in `ai/crates/mcp-server/src/assessment/object_lineage.rs`. They do not run this command.

---

## 9. Usage in the business-use-cases skill

Source: `ai/plugin/skills/migration/assessment/business-use-cases/`

| File | Line | Operation | Purpose |
|---|---|---|---|
| `SKILL.md` | ~162 | `find` | Match candidate use cases to what the customer named |
| `SKILL.md` | ~207 | `flow --id` | Trace a landing object's flow |
| `SKILL.md` | ~213 | `relations`, `find`, `downstream` | Direct edges, search, and downstream reach |
| `references/context-pass.md` | ~34 | `find --name <word>` | Match an outcome word to objects |
| `references/context-review.md` | ~52, ~84 | `find --name` | Confirm a named object, and find heavily read objects that no use case contains |
| `references/adjudication.md` | ~52 | `flow --id` | Jobs that produce a candidate landing table |
| `references/other-objects.md` | ~29 | `flow --id` (with `catalog_draft.py landing`) | Flow of a landing object |
| `references/contract.md` | ~76 | `flow --id` | One flow, alongside `anchors.json` |
| `references/large-workloads.md` | ~86 | `relations`, `closure` | Direct edges and slice size on large workloads |

Sub-agent dispatch also uses `flow` to read each landing object's sources: `ai/plugin/skills/migration/assessment/references/subagent-dispatch.md` (~391, ~426).

---

## 10. Examples

```
# Find objects by name
scai assessment waves query find --name "loyalty points" --json

# Direct edges around an object
scai assessment waves query relations --id <ID> --json

# The flow behind a landing table
scai assessment waves query flow --id <ID> --json

# ETL-tier sinks with no dependents
scai assessment waves query sinks --tier etl --max-downstream 0 --limit 100 --json

# Every root in one schema, 1000 at a time
scai assessment waves query roots --schema SALES --limit 1000 --offset 0 --json

# One slice for several seeds
scai assessment waves query closure --id <ID> --id <ID> --json

# One slice for the ids in a file
scai assessment waves query closure --ids-file seeds.txt --json

# Schema inventory
scai assessment waves query schemas --limit 20 --json
```

---

## 11. Known gaps in the docs

- `Snowflake.SnowConvertDesktop/Snowflake.SnowConvert.Assessment/CLAUDE.md` lists eight operations in its `waves query` usage line (`schemas|sinks|roots|relations|find|upstream|downstream|closure`). The command accepts nine. `flow` is missing from that line.
- The `WavesQuerySettings` help text lists all nine operations, so the command's own help is the more complete source.
