---
name: rule-engine
description: Search, apply, extract, propagate, and manage reusable migration rules stored in Snowflake. Rules encode known source-to-Snowflake fix patterns (regex or AI-guided). Triggers: rule engine, search rules, apply rules, migration rules, known fixes, rule setup, extract rule, propagate rule.
parent_skill: migrate-objects
license: Proprietary. See License-Skills for complete terms
---

# Rule Engine

Search, apply, and manage reusable migration rules. All rules live in Snowflake — both built-in patterns from common source-to-Snowflake conversions and rules extracted from previous fix cycles.

## Prerequisites

- Snowflake connection active with direct SQL ability
- Rule engine schema set up (if not, run Setup first)

## Commands

### Search

Find applicable rules for a SQL file. Sends the file content to Snowflake for regex pattern matching (REGEXP_LIKE) and Cortex semantic search.

→ Load [search/SKILL.md](search/SKILL.md)

### Apply

Apply matched rules to local SQL files. Supports single-file and batch application. Runs regex replacements mechanically, presents AI-mode fixes for review.

→ Load [apply/SKILL.md](apply/SKILL.md)

### Extract Rules

Analyze code changes to extract reusable migration rules. Works on interactive fixes (before/after comparison) or git history (retroactive analysis of committed changes).

→ Load [extract/SKILL.md](extract/SKILL.md)

### Propagate

Given a rule, find all code units in the project it applies to. Uses reverse search (regex + Cortex semantic) to identify candidates, then hands off to Apply for batch application.

→ Load [propagate/SKILL.md](propagate/SKILL.md)

### Status

Check what rules exist and recent fix history:

```sql
SELECT id, name, replacement_mode, priority, rule_sentiment, rule_applications, successes, created_from
FROM RULE_ENGINE.RULES
ORDER BY priority;
```

## Tools

| Tool | Purpose |
|------|---------|
| MCP `rule_setup` module | DDL, seeding rules, and Cortex Search setup (in `snowflake_migration_mcp/rule_setup.py`) |
| MCP `search_rules` | Find rules matching a SQL file (regex + Cortex semantic search + EWI scan) |
| MCP `find_similar_rules` | Search rules by text description |
| MCP `reverse_search_rules` | Find code units affected by a rule |
| MCP `sync_sql_files` | Bulk sync SQL files for rule search |
| MCP `create_rule` | Insert a new rule into RULE_ENGINE.RULES |
| MCP `list_rules` | List rules with optional filters |
