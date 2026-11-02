---
name: worker-distributed-setup
description: Run multiple Data Exchange Workers on separate VMs or servers for one source, sharing the project-default affinity. Triggers: several worker hosts, separate VMs, more throughput, one source.
parent_skill: data-infrastructure-setup
license: Proprietary. See License-Skills for complete terms
---

# Worker Distributed Setup

Use this path when **one source server** needs more than one Data Exchange Worker, each on its own
host, because one host is not enough throughput.

Leave the affinity override unset. scai stamps the project-default affinity on the workflow and on
every generated worker config, and the orchestrator hands each free worker the next task.

The plugin does not drive several source servers in one project. A worker connects to one source.
Setting up a worker group per server is not supported here.

> **Read first:** [Affinity Reference](../references/affinity-reference.md) — the claim rule and why
> the orchestrator stays null-affinity.

## Per host

Follow [worker-local-setup/SKILL.md](../worker-local-setup/SKILL.md) Step 2 on each host. Each host runs one
worker against the same source. The generated `.scai/config/dew_configuration.toml` already carries
the project default; copy that file to the host.

On each other host the user runs `scai data worker start --local --detach` (stop it with
`scai data worker stop --local`). On the machine AIM runs on, use
`data_infrastructure(mode="up", start_worker=true)` instead. `scai data worker start --local` without
`--detach` stays in the foreground and never returns.

> **Cost note (relay to the user):** each running worker polls Snowflake and can accrue warehouse
> credits even when idle. Stop workers per host when the wave's data work is done (teardown skill).

## Verify

Confirm each host's worker connected to the orchestrator and is polling. If a worker is running but
its workflow shows "0 pending" / tasks never start, suspect an affinity mismatch — see the
data-migration [Troubleshooting Reference](../../migrate-objects/actions/data-migration/references/troubleshooting-reference.md)
and the [Affinity Reference](../references/affinity-reference.md).

## Done

All workers are running on their hosts. Return control to the parent skill, which runs Level 1 Data
Doctor before proceeding.
