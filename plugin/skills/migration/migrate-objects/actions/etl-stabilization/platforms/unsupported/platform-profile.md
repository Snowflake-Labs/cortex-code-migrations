# Platform Profile: Unsupported (agnostic fallback)

`findings/61` SS13.1: this is the **fallback** pack, selected when no named platform pack
(`ssis`, `informatica`, later `alteryx`, ...) applies. It is deliberately generic — no tool
names, no `.yxmd`/dialect procedures. Alteryx is the proving corpus for hardening this pack
(SS13.4 P2), not its identity.

**Scope:** post-conversion trees only — output that AI-First Migrator or SnowConvert already
emitted. Not a general SQL repair product; see SS13.1 "scope of handles anything".

## Identity
- platform_id: unsupported
- platform_name: "Unsupported source (agnostic fallback)"
- source_file_extension: null
- source_file_label: "none — no named source format; the tree is already emitted SQL/dbt"
- source_file_format: null

## Source of Truth
- source_description: >
    There is no raw source file this profile is licensed to read as ground truth — that is
    exactly why no named pack applied. The **AI-First remediation brief**
    (`Reports/AiFirstRemediation/remediation-brief.json`, findings/61 SS10) is the source of
    truth when present: it indexes Gate B divergences, integrity outstanding items, and AIM
    instances, each with a pointer back to source/IR loci. When no brief exists for an AI-First
    unit, this profile must fail loudly rather than invent source intent (SS13.2 row 3).
- assertion_derivation: >
    Derive assertions ONLY from a brief item's `intent_excerpt.source_says` (or an explicit
    pointer it names). Never derive assertions from the converted SQL alone, and never guess at
    source intent when the brief carries no pointer for that item — register it `residual`
    instead (SS13.3).
- traceability_format: "-- (Trace: brief {item_id} → lane {lane} → {reverify})"

## Guides
- orchestration_guide: brief-guide.md
- transformation_guide: lane-actions-guide.md
- element_types: element-types.md
- ewi_directory: null

## Dead Code Stripping
- strip_script: null
- strip_description: null

## Element Classification
- disabled_marker: null
- disabled_reason: "unsupported-profile-no-source-marker"
- pipeline_type: null
- external_dep_types: []

## Source-Specific Vocabulary
- orchestration_term: "unit orchestration"
- transformation_term: "unit transformation"
- unit_term: "post-conversion unit"
- task_term: "task"
- container_term: "unit"
- variable_binding: "n/a — no source variable binding; use brief `element_ids`/`models`"
- sql_source_attribute: "n/a — read `intent_excerpt.source_says` from the brief instead"

## Selection Fallback (why this pack was chosen)

Per `findings/61` SS13.2, the scanner selects `unsupported` when:
1. no platform was named (omitted/null/ambiguous source extension), or
2. a platform was named but has no pack directory under `platforms/`.

The scanner records the selection (fallback flag + reason) in `scan.json` and propagates it into
`tracking/session_status.json` — never a silent `platform_id: null`. If the unit carries AI-First
artifacts (`Reports/AiFirstIssues/issues.json`) but no remediation brief, the scanner fails loudly
(non-zero exit) instead of proceeding as if this were a known platform.

This pack does not implement the brief-driven repair loop itself (`findings/61` SS13.4 P1 —
tracked as `I-16b`); it defines the contract that loop consumes.
