---
name: etl-aifirst
parent_skill: migrate-etl
description: >
  AI-First convert path for ETL platforms SnowConvert does not natively support.
  Identifies elements, hydrates IR, runs verification gates, and emits dbt output
  with honest degradation exit codes. Use when convert routes unsupported ETL to
  the AI-first migrator. Sibling of etl-stabilization (post-convert repair).
license: Proprietary. See License-Skills for complete terms
---

# ETL AI-First Convert

Convert unsupported ETL documents through the AI-First producer + gate chain.

## Layout

| Path | Role |
|------|------|
| `scripts/` | Runtime: identify/emit, gates, driver, helpers, AIM issues, sidecar |
| `tools/` | Lab/table-build helpers (not on the convert path) |
| `platforms/` | Platform element tables (`platform_*.json`) |
| `pyproject.toml` / `uv.lock` | Action dependencies (Stabilization convention) |

Instruction-only routing for the convert skill lives under
`ai/plugin/skills/migration/convert/etl-aifirst/` (markdown only).

## Entry

`scripts/aifirst-migrate.sh <platform-table.json> <source-document> <output-root>`

This checked-in-table form is preferred and remains the compatibility path.

When the caller has a platform identity rather than a table path:

`scripts/aifirst-migrate.sh --platform <platform-identity> <source-document> <output-root>`

Stage 0 uses the matching checked-in table when one exists. Otherwise it authors a provisional table
in an isolated view, accepts it only after structural and source-accounting validation, preserves it
under `<output-root>.gates/stage0/`, and feeds those accepted bytes to the deterministic stages. Set
`AIFIRST_TABLE_AUTHOR_CLI` to select the authoring CLI; it falls back to `AIFIRST_VERIFIER_CLI`, then
`cortex`. Model-backed stages (sidecar produce, Gate A/B) use the same Cortex default.

## Sidecar

When identify/census finds an element the IR cannot represent, Stage 3a2 of the driver produces
`<document>.ai.json` (via `sidecar_producer.py` against the first emitted tree), re-represents so
`emit.py` hydrates `$kind` / columns, re-emits, then Stage 3b `ai_fill` writes any `ModelSql`.
A sidecar already beside the document is consumed and not rewritten. Set
`AIFIRST_SKIP_SIDECAR_PRODUCE=1` to keep the consume-only path (convert-ctrl / nosidecar).
