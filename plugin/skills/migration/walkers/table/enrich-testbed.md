# Enrich a table's testbed

Spawn one foreground `testbed_generator` (`run_in_background=false`,
`subagent_type="testbed_generator"`). You keep the claim; the helper only
prepares this table's testbed spec.

```
Prepare this table's testbed spec, following your agent definition.

objectId:  <objectId>
projectDir: <projectDir>
pluginDir: <pluginDir>
```

| Helper `result` | Do |
|---|---|
| `done` | `walk(action="done")`. |
| `busy` | Return `partial`. Another call holds this table, a helper sent ahead of you is still enriching it, or the testbed's locks stayed busy for the whole call. Do not enrich the table yourself. |
| `escalate` | `walk(action="escalate")` with the helper's `reason` and `asks`, then return `stuck`. |

The CSV is generated later, by `deployCommonSandbox`'s `walk_run(op="source")`.
