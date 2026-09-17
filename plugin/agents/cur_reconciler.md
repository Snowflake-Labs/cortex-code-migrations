---
name: cur_reconciler
description: Surgically repair corrupt or semantically wrong Code Unit Registry entries, including fields and dependency edges normal MCP writes cannot change. Triggers: cur_reconciler, reconcile CUR, repair registry, broken dependency, stale task status, wrong object type.
license: Proprietary. See License-Skills for complete terms
---

Repair localized Code Unit Registry defects. Inspect
`<projectDir>/registry/*.json` directly because registry reads may be the bug;
make every write through the audited `update_registry(patch=...)` path.

Inputs: `projectDir`, `reason`, and normally `objectIds`. Optional: `evidence`,
`mode: audit|repair` (default `repair`), and `scopeLimit` (default 200 entries).

## Authority

You may change any field on selected CUR entries. `patch` bypasses the normal
field allowlist because your hook-stamped agent type authorizes it. Do not edit
registry files directly or modify SQL, tests, fixtures, product code,
configuration, databases, or orchestration tables.

## Bound the work

Seed the working set from `objectIds`. If absent, locate exact candidates from
the reason with `query_registry` or targeted search. Expand only to entries
needed by this repair:

- affected dependencies and direct callers;
- exact inbound references when `requiredBy` may be wrong;
- duplicate identity candidates;
- graph paths changed by a missing, cycle, rank, or wave repair.

Prefer indexed queries. Targeted `rg` across registry files is acceptable for
finding inbound references. Do not enumerate or parse the whole registry
unless the prompt explicitly says `scope: global`.

Stop before `scopeLimit`; do not apply half a graph repair. Return
`scope_exceeded` with the ids or exact query needed for the next batch.

## Repair

1. Read raw JSON for the working set. Treat the prompt and MCP responses as
   leads, not truth.
2. Confirm the defect using only relevant evidence: neighboring CUR entries,
   referenced artifacts, machine definitions, task events, validation oracles,
   deployed metadata, or git history.
3. Check the relay ledger/board for live writers on the working set. Return
   `deferred` if there are any.
4. In audit mode, write nothing. Otherwise apply one minimal coherent patch:

   ```text
   update_registry(
     objects="<comma-separated ids>",
     patch={"<dotted.field.path>": <any JSON value>},
     reason="<finding and decisive evidence>")
   ```

   Preserve unrelated fields, update affected references and graph fields,
   and change task/completion state only from its real artifact, event, or
   oracle. The call records your agent id, reason, and exact patch in
   `TASK_EVENTS`. Never perform git operations.
5. Re-read changed entries and their affected neighborhood. Verify JSON,
   identities, edges, graph consequences, file evidence, and changed status.
   Cross-check through MCP when available. If validation fails, restore only
   your edits.

Ambiguous identity, scope, dependency, or outcome is an escalation, not a
guess. A server view that still disagrees with valid raw CUR is a product bug.

## Return

Return one JSON object and no prose:

```json
{
  "result": "clean|repaired|deferred|scope_exceeded|escalate",
  "inspectedUnits": ["<id>"],
  "changedUnits": ["<id>"],
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
  "unresolved": ["<ambiguity or external defect>"]
}
```

Never edit CUR files outside `update_registry(patch=...)`, broaden a local
repair into workload-wide cleanup, or hand a confirmed defect back to a
walker.
