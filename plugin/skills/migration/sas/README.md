# SAS → Snowflake (parallel domain)

> **Status: Preview.** This capability ships as a Preview and is discoverable by the migration router — natural-language SAS requests (e.g. "assess this SAS portfolio", "convert MyJob.sas to Snowflake") route here via the migration `<skill-match>`. It has no dedicated slash commands.

This folder is the **SAS parallel track** inside the AIM migration plugin. It hosts vendored skills for assessing SAS portfolios, converting `.sas` programs to Snowflake, and bulk-loading `.sas7bdat` datasets from a stage.

Unlike the main AIM workflow, this track does **not** use SnowConvert, the object registry, MCP state machines, or wave claims. The agent routes SAS-specific requests here and follows the child skill end-to-end without requiring `configure` or an AIM project.

## Skills

| Skill | Path | Purpose |
|-------|------|---------|
| **sas** (router) | `SKILL.md` | Classifies intent and loads exactly one child skill |
| **assess-sas-migration** | `assess-sas-migration/SKILL.md` | Portfolio analysis — complexity, volume, dependencies, wave plan, LOE |
| **convert-sas-to-snowflake** | `convert-sas-to-snowflake/SKILL.md` | Convert `.sas` programs (DATA steps, PROC, macros) to Snowflake SQL / stored procedures |
| **validate-sas-conversion** | `convert-sas-to-snowflake/validate-sas-conversion/SKILL.md` | Validate an existing SAS conversion (sub-skill of convert) |
| **migrate-sas7bdat-to-snowflake** | `migrate-sas7bdat-to-snowflake/SKILL.md` | Bulk-load `.sas7bdat` files from a Snowflake stage into tables |

## Recommended flow

```
Assess → Convert
```

1. **Assess** produces portfolio-level analysis (`assessment.json`, reports, wave plan).
2. **Convert** reuses `assessment.json` when present to prioritize and inform conversion.

**Migrate-data** (`.sas7bdat` load) is **independent** — it does not require Assess or Convert and can run on its own when the user only needs dataset ingestion from a stage.

## Provenance

Vendored from an internal Snowflake SAS-to-Snowflake skill repository on **2026-08-10**. The three primary skill trees (`assess-sas-migration/`, `convert-sas-to-snowflake/`, `migrate-sas7bdat-to-snowflake/`) were copied into this nested domain under `plugin/skills/migration/sas/`.

Upstream `.snowflake/cortex/plans/` and generated test output were **not** vendored.

## Non-goals

This domain deliberately does **not**:

- Register SAS as a SnowConvert source dialect
- Add SAS tasks to MCP state machines or `OBJECT_CLAIMS`
- Require an AIM project, `configure`, or `migration_status` before starting
- Add a second top-level skill root in `plugin.json` (packaging stays `skills/migration` only)

See [INTEGRATION.md](./INTEGRATION.md) for wiring details and verification steps.

## How to extend

To add a new SAS capability:

1. Create `sas/<new-skill>/SKILL.md` (+ references, scripts, assets as needed).
2. Add a routing row to `sas/SKILL.md` intent table.
3. Add a skill-match bullet under the SAS section in `plugin/skills/migration/SKILL.md`.
4. Update the required path list in `ai/crates/mcp-server/tests/sas_skill_integration_check.rs`.
5. Update this README and `INTEGRATION.md`.
