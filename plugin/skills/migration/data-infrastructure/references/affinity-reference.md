# Affinity Reference — routing workers to workflows

Affinity is a **routing label** that binds a workflow's tasks to the worker(s) allowed to run them.
It is the mechanism that lets **several workers for one source** share the load without one of them
sitting idle on a label the others don't carry.

## How the orchestrator matches (the claim rule)

When a worker (or the orchestrator itself) pulls tasks, the queue matches on affinity with this rule
(consumer = the puller's affinity; task = the affinity stamped on the task row):

```
consumer IS NULL            → claims tasks of EVERY affinity
task affinity IS NULL       → claimable by ANY consumer
consumer == task            → exact, case-sensitive match
consumer contains '*'       → glob match (e.g. "team-*" matches "team-sales")
```

Only the consumer value is a pattern; the task value is literal. In a consumer value that contains `*`,
`%` and `_` also act as wildcards in the claim SQL, so keep labels to letters, digits and `-`.
`RATE_LIMIT.AFFINITY` is different: it matches a task's affinity exactly, never as a glob.

Two consequences drive everything below:

1. **A null-affinity consumer claims all tasks.** This is why the **orchestrator must never be given an
   affinity** — a null orchestrator drains workflows of *every* affinity, and stamps each task with its
   own workflow's affinity so the right worker picks it up. If you gave the orchestrator an affinity it
   would partition itself, and workflows of other affinities would sit at "0 pending" forever. **The
   plugin never sets the orchestrator's affinity.** Isolation happens at the *worker* layer.
2. **A worker and its workflow must carry the same label when you set one.** A null worker claims
   every task. A null workflow is claimed by any worker. For one source, leave both on the project
   default and don't set an override.

## The two carriers that must agree

Affinity lives in **two** files that must carry the same value:

| Carrier | Where | Set by |
|---|---|---|
| **Workflow config** (`affinity:`) | `artifacts/data_{migration,validation}/workflows/*.yaml` | `migrate_data`/`validate_data` (`mode="setup"`) |
| **Worker config** (`[application].affinity`) | project-relative `.scai/config/dew_configuration.toml` (local worker) | `data_infrastructure(mode="up")` |
| **Worker env** (`AGENT_AFFINITY`) | SPCS spec / k8s Deployment manifest | the worker-spcs / worker-k8s-external skill (set it to the **same** label) |

## Project default vs explicit override

scai gives each project a stable default affinity, `<project-name-slug>-<first 8 hex of project id>`
such as `northwind-3f9a1c2b` (`default_affinity` in `.scai/config/project.yml`). When no `--affinity`
is passed, `scai data migrate|validate generate-config`, `scai data worker setup` and
`scai data worker generate-config` all apply it. This is the normal path for one source server and
requires no user-selected label.

A worker labelled by hand does not claim workflows stamped with the project default, and a
default-labelled worker does not claim a workflow you generated with a different `--affinity`. Set
both sides from the same label.

`configure(affinity="<label>")` persists one override to project-relative `.scai/config/plugin.yml`
and forwards it to both generators. It holds one label at a time. Don't use it to split one project
across source servers: the plugin doesn't drive that.

- **Local worker:** `data_infrastructure(mode="up")` generates the DEW config with the same override.
  If an existing generated config carries a different affinity, the plugin regenerates it.
- **SPCS / Kubernetes worker:** set the same override as `AGENT_AFFINITY` in the worker spec/manifest.
  The worker-spcs and worker-k8s-external skills do this.

The plugin never passes affinity to the orchestrator.

## Dispatch diagnostics

Bare `create-workflow` performs an advisory affinity-aware readiness check. It warns when no running
orchestrator or worker can claim the workflow affinity; the workflow is still created. A separate
warning can say an explicit workflow override differs from the project's default affinity. Verify
that the worker carries the same override.

`migrate_data` / `validate_data` `run` refuse instead of warning when no running servicer claims the
workflow's affinity.

## When affinity is the cause of a stall

"Found 0 pending workflows" / tasks stuck non-terminal is often an affinity mismatch: the workflow
carries one label and no worker carries a matching (or null) one, or the orchestrator was mistakenly
given an affinity. See the data-migration [Troubleshooting Reference](../../migrate-objects/actions/data-migration/references/troubleshooting-reference.md).
