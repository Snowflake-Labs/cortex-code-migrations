# Verify

A function or procedure with **no source side** (SnowConvert UDF helpers under
`snowflake/UDF Helpers/`) reaches `verify` after `deploy`. There is nothing to
seed or baseline, and no `scai` command: verify by what the object allows, then
`walk done`. Do not seed, capture a baseline, or author a test YAML.

| Situation | Check | Verdict |
|---|---|---|
| Open invalidation (`invalidation` on the step, or a prompt `reason`) | That reason is the defect. Probe its named inputs: `query_source` of the source builtin vs a `SELECT` of this object. Matching those inputs is enough — no grammar corpus. Do not escalate because the file is a SnowConvert template. | Match → `walk(action="done")`. Mismatch → `walk(action="done", failed="sql")`. Never done on existence alone. |
| Unresolved EWIs on the converted output | — | `walk(action="done", failed="sql")` |
| Otherwise | `SHOW FUNCTIONS` / `SHOW PROCEDURES` / `DESC` confirms it exists, and a few smoke inputs show it is callable. | `walk(action="done")` |

"Conversion reported success" is not evidence. After a fix-loop retry, the same
named-input probe is the completion test.
