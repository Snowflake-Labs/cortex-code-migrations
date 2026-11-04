# Extract Rules

Turn the fix you made to this object's converted SQL into a reusable rule, or
decide there is nothing new; either way `walk(action="done")`.

1. **Diff.** After = `files.converted`. Before = its previous version from
   read-only git (`git diff` / `git log -p` on the file). No history → nothing to extract.
2. **Patterns.** For each distinct fix pattern another object could hit (not a
   one-off name or data edit), name what changed and which Snowflake
   incompatibility it fixes:
   - Mechanical find/replace → `replacement_mode="regex"`, `match_pattern`
     (detection regex), `replacement_find`, `replacement_replace`.
   - Context-dependent → `replacement_mode="ai"`, `match_pattern`, `ai_context`
     (what to look for, how to fix, edge cases).
3. **Duplicates.** `find_similar_rules(query=<pattern description>)`, or
   `list_rules(detailed=true)` when it errors. A match → no new rule. Both
   erroring → no new rule: an empty `rules` beside an `error` is not "none".
4. **Create.** `create_rule(name=…, match_pattern=…, replacement_mode=…, …,
   examples_json='[{"before": "…", "after": "…"}]')` with examples taken from the
   actual diff. Optional: `description`, `category`, `priority` (default 50; lower
   runs first), `source_platforms` / `object_types` (JSON array strings),
   `source_object` (this object, `database.schema.name`).
   `status: "duplicate"` names the rules already matching it: apply those, no new rule.

The rule tools failing → `walk(action="done", failed="infra"|"sql", reason=…)`: the
walk records the skip and the object still finishes. A step saying it failed earlier is a re-run.
