# Deploy a table to the shared source catalog

## 1. Ready the table's testbed enrichment

Skip to step 2 when the step's `done` lists `enrichTestbed`. Otherwise spawn one foreground
`testbed_generator` (`run_in_background=false`, `subagent_type="testbed_generator"`). You keep
the claim; the helper only enriches this table's testbed.

```
Make this table's testbed enrichment ready, following your agent definition.

objectId:  <objectId>
projectDir: <projectDir>
pluginDir: <pluginDir>
```

| Helper `result` | Do |
|---|---|
| `done` | Go to step 2. |
| `busy` | Return `partial`. Another call holds this table, a helper sent ahead of you is still enriching it, or the testbed's locks stayed busy for the whole call. Do not enrich the table yourself. |
| `escalate` | Escalate with the helper's `reason` and `asks`, then return `stuck`. |

## 2. Deploy

Follow [../shared/deploy-common-sandbox.md](../shared/deploy-common-sandbox.md);
`walk_run(op="source")` compiles and generates this table's CSV, unless it was
generated when its enrichment, or its wave's first mine, finished; then loads it.
