# CUR authoring — id, source, target, dependencies

Field contract for minting or repairing a Code Unit Registry entry.
Schema: `migrations-code-unit-registry` `code-unit.schema.json` (schemaVersion 1).
On disk: `<projectDir>/registry/<id>.json`. Copy `platform`, `format`, and
name casing from a neighboring unit of the same dialect — do not invent a
convention.

Query before you write. A file under `source/` or
`artifacts/source-bindable/` is evidence for identity, not a license to
duplicate a unit that already has an `id`.

Mint with `update_registry(unit={...}, reason=...)`. Repair with
`update_registry(objects=..., patch={...}, reason=...)`. Both are
`cur_reconciler` (or privileged hail_mary) only. The engine generates `id`
when omitted and returns an existing identity instead of duplicating.

## `id`

Stable primary key. Filename stem **is** this value.

- UUID v4, lowercase RFC 4122 (`8-4-4-4-12`).
- One unit, one id. Never reuse. Never mint a second unit for the same
  identity (see `source.canonicalName` below).
- The schema text `{schema}/{type}/{name}.{guid}` is stale. Live ids are
  UUIDs.

Match an existing unit with `query_registry` on identity fields, not by
guessing the filename. Ambiguous identity → escalate, do not mint.

## `source`

Source-side identity. Walkers, sandbox lookup, and `dependsOn` resolution
key off this block (falling back to `target` only when `source` is absent
— SnowConvert helper UDFs).

| Field | Write |
|---|---|
| `objectType` | Closed camelCase enum. SQL files are almost always `table`, `view`, `procedure`, or `function`. Not `Table` / `PROCEDURE`. |
| `platform` | Closed camelCase enum (`sqlServer`, `teradata`, `oracle`, `redshift`, …). Copy the neighbor. |
| `format` | Optional on `databaseObject`. Closed enum (`tSql`, `sql`, `plsql`, `bteq`, …). Copy the neighbor when set. |
| `database` | Source catalog. Preserve source casing. Convert-with-bindings: `${token}` copied from siblings — a live WAVE / SNAP name does not bind into an AIMSBX pair. |
| `schema` | Source schema. Preserve source casing. |
| `package` | Oracle / similar package container only. Omit otherwise. |
| `name` | Object name as written on the source, casing preserved. Bare name — not `schema.name`. |
| `canonicalName` | Identity string. `database.schema[.package].name`. Procedures and functions append `(paramTypes)` with no spaces. |
| `customKind` | `kind=custom` only. Forbidden on `databaseObject`. |

`canonicalName` is the identity. `schema.name` is the display form. Two
overloads of one procedure share a display name and **must** differ in
`canonicalName`. The registry rebuilds `canonicalName` from the unit's
fields on write, so write each overload's parameters in the unit-level
`signature.parameters.arguments` (`[{name, type}]`) — a signature that
appears only inside `canonicalName` is discarded.

Do not write placeholder catalogs: `N/A`, `database_unspecified`,
`defaultdb`. Convert-with-bindings projects store tokens in these slots
(`${NAME}` on source, `<% NAME %>` on target) — copy that shape from
siblings; do not invent tokens.

A name that is only a binding token, with no file-backed object, is
`kind: parameterizedReference`, not a new `databaseObject`.

## `target`

Snowflake-side identity. Computed independently of `source` — names and
types may differ.

| Field | Write |
|---|---|
| `objectType` | Same closed enum as `source`. Tables, views, procedures, functions keep the source type. |
| `format` | Closed enum. Set when the body language is a real choice: `snowflakeSQL`, `snowflakeScripting`, `javascriptInSnowflakeSQL`. Copy the neighbor. |
| `database` / `schema` / `name` | Snowflake identifiers. Copy casing from siblings (often upper). Convert-with-bindings: `database` is `<%token%>` copied from siblings. Tokenless `PUBLIC.X` / two-part CREATE lands on the session catalog, not the sandbox pair. |
| `canonicalName` | `database.schema.name`, or `database.schema.name(paramTypes)` for procedures and functions. When `database` is a token, the token is part of this string. |
| `customKind` | `kind=custom` only. |

Omit `target` only when you have not converted the object yet. A unit
that must deploy or sandbox needs both sides plus `files`. Bindable
identity on **any** object kind (table, view, procedure, function,
helper) is what lets `deploy` substitute catalogs.

## `dependencies`

Write **`dependsOn` only**. Graph refresh derives the rest:

- `requiredBy` — reverse index of everyone else's `dependsOn`
- `dependsOn[i].isMissing` — true when that `id` is absent, or the target
  unit has unit-level `isMissing: true`
- `hasTransitiveMissingDependencies`
- `planning.topologicalRank` (`-1` means a cycle)

A depends-on B means B is the predecessor (deploy B first).

Each `dependsOn` entry is an object, never a bare id string:

```json
{ "id": "<uuid>", "relationTypes": ["SELECT"], "isMissing": false }
```

| Field | Write |
|---|---|
| `id` | Required. The other unit's `id`. |
| `relationTypes` | Required, non-empty array of strings. Open vocabulary. SnowConvert uses `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `EXECUTE`, `FOREIGN KEY`, `SELECT - FROM`, `ref`. A 42S02 table the caller reads is `SELECT`. Copy a neighbor's verb when the SQL is the same kind of reference. |
| `isMissing` | Optional. Refresh overwrites it. Omit rather than guess. |

Merge. Keep existing edges; add the missing id. Do not drop unrelated
deps. Do not add a self-edge.

Unit-level `isMissing: true` is a **stub**: referenced, not found in the
repo. If you located the object under `source/` or
`artifacts/source-bindable/`, author a real unit (`isMissing: false`) and
point the caller at that id. Do not leave the caller on a stub, and do
not mint a second real unit beside a stub for the same identity — retarget
the edges onto the real one.

`requiredBy` is an array of id strings. Do not author it.

## Companion fields (minimum for a real unit)

Not identity, but a sourced `databaseObject` is not walkable without them.

```json
{
  "schemaVersion": 1,
  "kind": "databaseObject",
  "inScope": true,
  "isMissing": false,
  "files": {
    "source": { "path": "source/<dialect-path>/<name>.sql" }
  }
}
```

`files.*.path` is repo-root relative. `files.source.path` points at the
captured file under `source/`. The bindable mirror
(`artifacts/source-bindable/<path after stripping source/>`) is a convert
artifact used to *find* the object; it is not `files.source.path`.
`files.converted.path` when converted SQL exists. Omit `checksum` unless
you hashed with xxHash3-128 (32 hex chars).

Do not stamp `codeStatus.*` or `cloudStatus.*` completed without an
artifact or oracle.

## Closed enums (wire names)

**`objectType`:** `database`, `schema`, `table`, `externalTable`, `view`,
`materializedView`, `dynamicView`, `function`, `procedure`, `macro`,
`stage`, `udfHelper`, `sequence`, `tableType`, `temporalTable`,
`trigger`, `index`, `joinIndex`, `synonym`, `type`, `typeBody`,
`package`, `packageBody`, `dbLink`, `job`, `constraint`, `role`,
`grant`, `pipe`, `stream`, `task`, `workflow`, `mapping`, `fileFormat`,
`policy`, `tag`, `alert`, `integration`, `query`, `other`.

**`platform`:** `ansi`, `azureSynapse`, `bigQuery`, `databricksSql`,
`db2`, `druid`, `greenplum`, `hive`, `informatica`, `netezza`, `oracle`,
`postgres`, `redshift`, `snowflake`, `spark`, `sqlServer`, `ssis`,
`sybaseIq`, `teradata`, `vertica`.

**`source.format`:** `bteq`, `dtsx`, `fload`, `hql`, `mload`, `plsql`,
`sql`, `sqlPlus`, `tpump`, `tpt`, `tSql`, `xml`.

**`target.format`:** `dbt`, `java`, `javascriptInSnowflakeSQL`, `python`,
`scala`, `snowflakeSQL`, `snowflakeScripting`.

**`kind`:** `databaseObject` (SQL object), `script` (BTEQ / FastLoad /
SQL*Plus), `etl`, `parameterizedReference` (tokenized name, no file),
`custom`.
