# Brief Guide (orchestration equivalent for the unsupported profile)

Named platforms navigate a source file (control-flow XML, workflow XML, ...) to recover
orchestration structure. This profile has no such file — it navigates the **AI-First remediation
brief** instead. This guide replaces a source-navigation guide with a brief-navigation one.

## Locating the brief

Walk upward from the unit folder for `Reports/SnowConvert/` (the same convention `scan_unit.py`
already uses to find `reports_dir`). The brief lives beside it:

```
{output_root}/Reports/AiFirstRemediation/remediation-brief.json
```

`{output_root}` is `reports_dir`'s grandparent (`reports_dir = {output_root}/Reports/SnowConvert`).

If this path does not exist:
- **AI-First unit** (has `{output_root}/Reports/AiFirstIssues/issues.json`): fail loudly. Do not
  proceed as if this were a known platform, and do not invent an intent repair with no brief to
  point at (`findings/61` SS13.2 row 3). The scanner (`scan_unit.py`) already enforces this at
  scan time; this profile must not silently retry past that failure.
- **Not an AI-First unit** (no AI-First artifacts at all): the fallback is legitimately operating
  on a tree with no brief. There is nothing to repair beyond hardening; register everything
  outstanding as `residual` (see `lane-actions-guide.md`) rather than guessing.

## Reading the brief (`schema: aim.remediation-brief.v1`)

| field | meaning |
|---|---|
| `platform` | the platform AI-First resolved when it emitted the tree (may differ from `unsupported` — this is the *convert-time* platform, not the Stabilization pack id) |
| `document` | the source document name, for traceability only — do not open it |
| `conversion_exit` | AI-First's own exit code for this unit |
| `pointers.*` | paths to the Gate B verdict/obligations, integrity report, AIM issues, and (if staged) the source document / IR — the only permitted context beyond the brief itself |
| `summary.*` | raw counts already computed by the gates the brief indexes — never recompute these here |
| `items[]` | the work list — see fields below |

Each `items[]` entry:

| field | meaning |
|---|---|
| `id` | stable identifier for this finding |
| `lane` | who acts next — see the lane table below |
| `priority` | lower is more urgent |
| `element_ids` / `models` | the affected node(s), named the way the emitter names them (not a source-platform element type) |
| `from[]` | which gate(s) raised this, with enough detail (`subject`, `why`, `verdict`) to avoid re-deriving a verdict a gate already reached |
| `intent_excerpt.source_says` / `.sql_says` | the only source-intent context this profile is allowed to use — absent means no pointer, which forces `residual` |
| `allowed_actions` / `forbidden_actions` | the verbs this item permits — see `lane-actions-guide.md` |
| `reverify` | gate obligation ids to re-check after acting on this item |

## Lane table (division of labor — `findings/61` SS10)

| lane | meaning | who acts |
|---|---|---|
| `conversion_emitter` | IR held the fact; emission lost or mangled it | AI-First producer/migrator — return to convert, do not fix here |
| `conversion_ir` | Gate A residual / missing kind still open | AI-First identify — return to convert, do not fix here |
| `stabilization_repair` | good-faith convert; intent still wrong or incomplete | **this profile**, guided by the item's `intent_excerpt` |
| `stabilization_harden` | connections, runtime, naming hygiene, profile checklists | **this profile** |
| `residual` | explicitly left broken; AIM/ENG ticket; not a silent pass | neither party "fixes" this — register it honestly |

This profile only acts on `stabilization_repair` / `stabilization_harden` items. `conversion_*`
items are handed back, not attempted here — see `lane-actions-guide.md`.
