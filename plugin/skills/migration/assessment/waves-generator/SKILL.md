---
name: sql-migration-waves-generator
description: Size-based deployment waves over the registry, only when someone explicitly asks for them — a wave size, name patterns to prioritize, or category ordering. The assessment plans one wave per business use case instead (`../business-use-cases/SKILL.md`).
parent_skill: assessment
license: Proprietary. See License-Skills for complete terms
---

# Size-Based Migration Waves

## Overview

The assessment plans **one wave per business use case** with
`../business-use-cases/SKILL.md`; that is the default and needs no input. This
skill is the alternative a user asks for by name: bin-packed waves of a target
size, optionally with name patterns pulled into the earliest waves. It runs
`scai assessment waves` from inside a SCAI project and writes one consolidated
JSON file.

**Use this skill only when the request says so:**
- "Waves of 20-30 objects", "smaller batches", "at most 5 waves"
- "Prioritize `*Payroll*` into the first wave"
- "Order waves by object type" or "mix object types by dependency level"

Requests for a wave around an application, a process, a report or an object
belong to `../business-use-cases/SKILL.md` in on-demand mode.

## It replaces the business plan

`scai assessment waves` rewrites `planning.wave` on every unit it places, so it
replaces the business-use-case plan the assessment wrote. Say so in one
sentence before running it. To return to business waves afterwards, run
`scai assessment waves plan` (see `../business-use-cases/SKILL.md`).

## Inputs

Use only what the request states. **Do not ask for object prioritization**, a
size or an ordering the user did not mention: the defaults apply (40-80
objects per wave, no patterns, category ordering). Do not prompt for paths —
the command reads the registry of the current project.

The working directory must be a SCAI project (`.scai/` exists and the registry
is initialized). The parent `assessment/SKILL.md` ensures the project is
bootstrapped before routing here.

## Command Reference

Run from the SCAI project root; the command takes no `--project-dir`.

```bash
scai assessment waves                                   # defaults
scai assessment waves --min-size 15 --max-size 50       # target size
scai assessment waves --prioritize "*Payroll*" --prioritize "dbo.Customer"
scai assessment waves --no-category-waves               # mix types by dependency level
```

| Argument | Default | Description |
|----------|---------|-------------|
| `--min-size <N>` | 40 | Minimum target wave size for bin-packing |
| `--max-size <N>` | 80 | Maximum wave size for bin-packing |
| `--prioritize <PATTERN>` | — | Glob for objects to place in the earliest waves (repeatable): `PKG_*`, `*OrthoContract*`, `[SCHEMA].[TABLE]` |
| `--no-category-waves` | off | Mix all object types by dependency level instead of TABLE → VIEW → FUNCTION → PROCEDURE → ETL |

Run `scai assessment waves -h` for the latest list of flags.

## Output

`<projectRoot>/assessment/waves_analysis_YYYYMMDD_HHMMSS.json`:

| Section | Purpose |
|---------|---------|
| `graph_summary` | Total nodes, edges, weakly connected components, cycle counts |
| `partitions` | Wave composition: partition number, size, type, members, root/leaf flags |
| `sccs` | Strongly connected components (circular dependencies) |
| `excluded_edges` | Edges excluded from partitioning (self-refs, undefined objects, temp tables) |
| `top_dependencies` | Objects with the most dependencies and dependents |
| `scc_priority_order` | Priority tier distribution (User-Prioritized / Regular / ETL) |
| `objects` | Per-object metadata (category, conversion status, assigned partition, root/leaf flags) |
| `statistics` | Per-category counts, size distributions, cycle/missing-dep totals |

`scai assessment report` picks up the newest file for its Waves tab.

## Algorithm

1. **Dependency graph** of deployable in-scope objects from `dependencies.dependsOn`; self-references excluded, undefined references tracked separately.
2. **Category waves (default)** — tables, then views, then functions, with a convergence loop for cross-category dependencies. Disabled by `--no-category-waves`.
3. **Priority tiers** — user-prioritized (`--prioritize`) first, then regular SQL objects, then ETL.
4. **Partitioning** — prioritized objects with their dependencies first, then roots onward; partitions between `--min-size` and `--max-size`; cycles via Tarjan SCC.
5. **Merging** — partitions under `--min-size` merge with neighbours while preserving order.
6. **Validation** — each partition depends only on earlier partitions.

## After Generating Waves

Tell the user where the prioritized objects landed and how many waves were
produced, from the JSON. For the HTML report, return to the parent skill's
report step (`scai assessment report`); never write HTML by hand.

## Troubleshooting

| Symptom | Cause | Action |
|---|---|---|
| "must run inside a SCAI project" | Not in the project root | `cd` into it, or bootstrap via `../setup/SKILL.md` |
| Many single-object partitions | Many disconnected components | Adjust `--min-size` / `--max-size`, or accept isolated objects |
| Circular dependencies | Objects depend on each other | Review `sccs`; may need refactoring |
| High excluded edge count | Temp tables and dynamic objects | Normal for SQL Server; review `excluded_edges` |
