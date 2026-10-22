---
name: cur_reconciler
description: Repair Code Unit Registry entries and bindable dependency references in converted SQL. Mint a unit when the object exists under source/ or source-bindable but has no CUR entry. Qualify tokenless catalogs so sandbox bindings substitute — any object kind. Triggers: cur_reconciler, reconcile CUR, repair registry, broken dependency, bindable reference, tokenless catalog, unknown UDF, PUBLIC. function, missing from CUR, stale task status, wrong object type.
license: Proprietary. See License-Skills for complete terms
---

## Authority

You may change any field on selected CUR entries and mint a unit that is not
in the registry. You may qualify converted and source-bindable SQL so
`.scai/bindings` can substitute. You may not edit customer `files.source`.

## Bound the work

Seed the working set from `objectIds`. If absent, locate exact candidates from
the reason with `query_registry` or targeted search. Expand only to entries
needed by this repair:

- affected dependencies and direct callers;
- converted and source-bindable files that name those objects;
- exact inbound references when `requiredBy` may be wrong;
- duplicate identity candidates;
- graph paths changed by a missing, cycle, rank, or wave repair.

Load <skills>/migrate-objects/cur/authoring.md before you mint or rewrite
identity fields.

## Missing object / reference

A 42S02 / `failure_class=missing_object`, where the object was not picked up
by CUR but might be present in the source directories.

1. Try to find it in registry under a different, similar name. `query_registry`
   should be helpful. If you find it: repair the dependencies edges, then
   continue to **Bindable references** for that unit and its callers.
2. If CUR doesn't have a match, search `<projectDir>/source/` and
   `<projectDir>/artifacts/source-bindable/` for the object's DDL.
3. If you find the missing DDL, author a real unit per authoring.md, then
   continue to **Bindable references**.
4. No file, several files, or an ambiguous identity → `escalate` with
   `asks` of register / stub / out of scope. Do not guess. Do not mint a
   stub.

## Bindable references

Anything wrong with **how code names a dependency** — not conversion
meaning, not fixture rows. Any object kind: table, view, procedure,
function, helper UDF. The defect is that sandbox / common bindings cannot
substitute, so the name resolves on the session or SNAP catalog instead of
the pair.

Confirm from files, not the prompt. Typical evidence:

- Converted or source-bindable SQL uses a two-part name (`PUBLIC.X`,
  `dbo.X`) or a literal SNAP / WAVE / AIMSBX catalog.
- `CREATE` has no bindable catalog (`USE DATABASE <%token%>` or
  `<%token%>.schema.name` on converted; `${token}` on source-bindable).
- CUR `target.database` / `source.database` is empty, a placeholder, or a
  live catalog name when siblings store tokens.
- Call sites of a unit that *is* on `dependsOn` still fail in AIMSBX
  (`Unknown user-defined function`, unknown procedure, 42S02) because
  the callee landed on the common catalog.

Do not send this to sqlFixLoop. Do not inline, stub, or hardcode SNAP.

### Token

Copy spelling from siblings (`<%token%>` on converted / `target`,
`${token}` on source-bindable / `source`). Pick **one**:

1. The referent unit's `target.database` or `source.database` when it is
   already a token.
2. Else this caller's matching slot.
3. Else the unique key in the active bindings yaml (`snow:` / `source:`).

Two keys could apply, or the name matches more than one unit → `escalate`.
Do not invent a token. Do not write SNAP / configure / AIMSBX names into
files or CUR identity.

### Qualify

Minimal edits so bindings substitute. Match the neighbor's shape
(`USE DATABASE <%token%>` then `schema.name`, or
`<%token%>.schema.name` on every catalog-sensitive name).

1. **Referent DDL** — `files.converted.path` (and source-bindable when that
   twin must resolve). Leading `USE DATABASE` stays; the deploy tool
   comments it out after substitution.
2. **Call sites** — converted (and source-bindable when the source twin
   names it) of the assigned object and of `requiredBy` / direct callers.
   Dynamic SQL string literals that concatenate the object name get the
   same qualifier.
3. **CUR** — `update_registry` patch `target.database` /
   `target.canonicalName` (and `source.database` / `source.canonicalName`
   when that side exists) to the tokenized identity. Merge `dependsOn` on
   the caller if the edge is missing. Do not drop unrelated deps.

Do not edit `files.source`. Do not change procedure logic, types, or
comments except the qualifier. A compile defect that is not a catalog
reference is sqlFixLoop — return `deferred` and name it in `unresolved`.

## Repair existing object

1. Read raw JSON for the working set. Treat the prompt and MCP responses as
   leads, not truth.
2. Confirm the defect.
3. Apply one minimal coherent patch:

   ```text
   update_registry(
     objects="<comma-separated ids>",
     patch={"<dotted.field.path>": <any JSON value>},
     reason="<finding and decisive evidence>")
   ```

   Preserve unrelated fields, update affected references and graph fields,
   and change task/completion state only from its real artifact, event, or
   oracle.
4. Re-read changed entries and their affected neighborhood. Verify JSON,
   identities, edges, graph consequences, file evidence, and changed status.

Don't guess if you can't find evidence. Escalate if needed.

## Return

Return one JSON object and no prose:

```json
{
  "result": "clean|repaired|deferred|scope_exceeded|escalate",
  "inspectedUnits": ["<id>"],
  "changedUnits": ["<id>"],
  "createdUnits": ["<id>"],
  "changes": [
    {
      "unitIds": ["<id>"],
      "fields": ["dependencies.dependsOn"],
      "why": "<finding>",
      "evidence": "<decisive evidence>"
    }
  ],
  "recheckObjects": ["<id>"],
  "remainingScope": ["<id or query>"],
  "unresolved": ["<ambiguity or external defect>"],
  "asks": ["<choice>", "<choice>"]
}
```

`createdUnits` and `asks` are empty unless you minted a unit or escalated.
`changes[].fields` lists CUR paths and SQL files you qualified.
Registry writes go only through `update_registry`. Converted /
source-bindable SQL only for bindable qualification.
