# Apply Rules

Apply the step's `rules` to `files.converted`, then `walk(action="done")`. The
server already ran `search_rules` on that file: do not search again. (When
nothing matches it records this task itself and hands out `fixCode`.) No
`rules` on the step means its search failed: `search_rules(file_path="<files.converted>")`.

Process `rules` in ascending `priority` (already sorted). Re-read
the file before each rule — an earlier fix may change later matches. Write every
change to the file; never deploy SQL that is not on disk.

| `replacement_mode` | Apply |
|---|---|
| `regex` | Replace every `replacement_find` match with `replacement_replace`. No match (the `match_pattern` hit was already fixed) → skip. |
| `ai` | Use `ai_context` and `examples` to fix every instance of the pattern. Skip a rule whose `ai_context` does not fit this object. `note` a fix that chose among meanings. |

After each rule that changed the file:
`record_rule_application(rule_id=<id>, outcome="applied", code_unit_name=<object>, file_path=<file>)`.
When the retried task later passes, record `outcome="success"` for those rules
(valid outcomes: `applied` / `success` / `failure`).
