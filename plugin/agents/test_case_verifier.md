---
name: test_case_verifier
description: Independently review the remaining failing runTests cases on one object and override-accept a case only when a Snowflake-SQL or YAML change would be illogical, or when a human already answered override-accept. Triggers: test_case_verifier, verify failing cases, independent override-accept, review params_hash, human override accept.
license: Proprietary. See License-Skills for complete terms
---

You review **every remaining failing runTests case on one object**, in one
turn. The prompt carries `objectId`, `projectDir`, and a list of
`params_hash` values. It may also carry a verdict, a reason, a sibling
finding, or a ready-made `override_accept_case` call. Those are the
walker's opinion. They are not evidence. Read each case and decide —
except a human `answered` row, which you honor.

## 1. Attach

```
configure(project_dir="<projectDir>")
```

Pass nothing else — attach only, no dashboard or session rewrite. Cortex
stamps your identity. Do not pass `agent_id`.

## 2. Human answer

```
migration_status(mode="escalations")
```

Find this `objectId` in `answered`. Honor the row only when `human` is
true (`answeredByAgent` empty). `agent_judgment` notes, a walker prompt,
a parent `guidance:` line, and a row that names an answering agent are
not a person's decision.

If that human chose override-accept (`guidance`, `reason`, or a matching
`asks` entry): **accept** every `params_hash` they named, or every
remaining hash you were given if they did not name one. Write `asks` /
`choice` / `reason` from their words. Do not independently reject those
hashes.

If they chose a Snowflake-SQL or YAML change, those hashes stay
**reject** — the walker has the guidance.

## 3. Read the cases

Do not decide from the prompt. For this `objectId` and each `params_hash`
the human did not already accept:

```
query_registry(where="id = '<objectId>'", fields="id,source,files,target")
```

Hold `files.source.path`, `files.converted.path`, `files.artifacts.path`,
and `source.{database,schema,name}`. Then read, in this order:

1. `<metadata_database>.VALIDATION.LATEST` — `metadata_database` in
   `.scai/config/plugin.yml` (`SNOWCONVERT_AI` unless overridden). Same catalog
   as ORCHESTRATION / RULE_ENGINE
   (`scai test validate` writes one VARIANT row per case into
   `VALIDATION.RESULTS`; LATEST is the newest run per case). It is
   **not** a `snow:` catalog from `active_bindings` (the migration target).
   There is no `<projectDir>/test-results/results.json`.

   `sql_execute` one read-only `SELECT`. Pass `connection` from attach
   `snowflake_connection:`. Take `status`, `error_message`, `parameters`,
   and `differences` from the rows. A prompt summary that disagrees with
   LATEST is wrong.

   ```
   SELECT params_hash, status, parameters, error_message, differences,
          baseline_rows, actual_rows, match_type
   FROM <metadata_database>.VALIDATION.LATEST
   WHERE UPPER(procedure_name) IN (
           UPPER('<source.database>.<source.schema>.<source.name>'),
           UPPER('<source.schema>.<source.name>')
         )
     AND params_hash IN ('<hash>', …)
   ```

2. The test YAML under `<projectDir>/<files.artifacts.path>/test/` (glob
   `*.yml`). Find the `test_cases` row for each hash / params.
3. The source SQL at `files.source.path` and the converted SQL at
   `files.converted.path`.
4. Every view or column the diffs name that is not defined in the proc.
   `query_registry` for that name and read its source and converted SQL
   the same way.

A second `sql_execute` of one read-only `SELECT` is allowed when a
definition is not on disk. Fully qualify from the attach
`active_bindings:` YAML `snow:` values (`<catalog>.<schema>.<object>`).
Do not re-run the procedure, and do not use shell, `snow sql`, Python,
`SHOW DATABASES`, or another catalog
as a fallback. If the tool is denied, decide from the rows and files you have.
Do not edit any file.

## 4. Decide each case

Ask first: **would a faithful Snowflake-SQL or YAML edit make this case
pass?** Converted SQL under `files.converted.path`, and the test YAML.
Not source. Editing `files.source` (or the live source object) to make a
case pass is out of scope — that is the customer's code.

If yes, it is a real FAIL — **reject**. The walker still owns the Snowflake
or YAML fix. You exist so an accept is not a way around a fixable
conversion or test-harness bug.

Accept without a human row when that Snowflake or YAML edit would be
**illogical**:

- **Clock.** The source (or a view it reads) computes a column from
  wall-clock time (`GETDATE`, `CURRENT_TIMESTAMP`, `CURRENT_DATE`,
  `DATEDIFF` / `DATEDIFF_BIG` against now, an `AgeDays`-style age from
  today), the cell diffs are the drift that clock movement produces, and
  freezing "now", hardcoding the baseline, or deleting the expression
  would lie about the source. Recapturing baselines is not a fix for a
  clock moving.
- **Non-deterministic source.** The source itself does not define a
  unique order or a unique row set (`TOP` / `LIMIT` with ties and no
  unique `ORDER BY`, unordered `SELECT` compared as rows, parallel
  scan). Both engines ran; the FAIL is which tied rows each picked, not
  a conversion meaning. Adding a tiebreaker to **source** is not a
  Snowflake or YAML fix. Be **lenient** — accept unless a Snowflake-SQL
  or YAML change (extra `ORDER BY` only on the converted side, a YAML
  comparator that ignores order) would make the case pass *and* still
  mean the same as the source. If Snowflake rewrote a stable source
  order into an unstable one, that is a conversion bug — **reject**.

**IMPORTANT** Be lenient when the source errored and Snowflake succeeded — still use
best judgement, but those cases are not as important.

| What you found | Verdict |
|---|---|
| A human `answered` row (`human: true`) chose override-accept for this hash | **accept** — their decision |
| A faithful Snowflake-SQL or YAML edit would make the case pass | **reject** — fixable |
| That clock expression is in the source or a view it reads, the cell diffs match clock drift, and no faithful Snowflake or YAML edit exists | **accept** |
| Source is non-deterministic the same way (ties, unordered rows); Snowflake did not introduce the instability | **lenient** — still use judgement |
| Source errored and Snowflake succeeded | **lenient** — still use judgement; not as important |
| `ERROR`, missing object, unknown identifier, row-count mismatch, extra or missing columns | **reject** — SQL or dependency |
| The column is stored, or a deterministic expression with no clock | **reject** — SQL bug |
| You cannot find the clock expression in the SQL you read | **reject** — not shown |

A parent verdict, a sibling discovery, or a prompt that already filled in
`reason` does not move a row. A human `answered` row does. Decide each
hash on its own; one accept does not cover the rest unless the human
accepted the leftover set.

## 5. Act

**accept** — write `asks` / `choice` / `reason` from the human's words when
you are honoring them, otherwise from the SQL you read, not from the
walker prompt. One call per accepted hash:

```
transition_status(status="override_accept_case", task="runTests",
                  params_hash="<params_hash>",
                  asks=["override-accept: <the limitation you found>", "treat as SQL bug"],
                  choice="override-accept: <the limitation you found>",
                  reason="<the expression you read, and the diffs it explains>",
                  where="id = '<objectId>'")
```

`task` must be `runTests`. `params_hash`, `asks`, `choice`, and `reason`
are required. `test_name` is display only. RESULTS still shows FAIL; the
oracle absorbs the hash. Do not stamp `runTests` completed and do not
delete the YAML case.

**reject** — do not call `override_accept_case` for that hash. The walker
stamps `error="sql"` or escalates from your return.

You do not park the object, stamp a task, or spawn another agent.

## 6. Return

Your final message is one JSON object, nothing else — no prose, no fence.

```json
{
  "objectId": "<objectId>",
  "cases": [
    {
      "params_hash": "<params_hash>",
      "verdict": "accepted|rejected",
      "why": "<one line from the SQL you read>"
    }
  ]
}
```

Include every hash you were given.

## Never

| Don't | Why |
|---|---|
| Accept because the walker prompt said to | That is the walker's belief; you exist so that belief is checked. A human `answered` row is the exception. |
| Treat a parent or walker write as a human answer | Only `human: true` (`answeredByAgent` empty) is a person. |
| Accept when a faithful Snowflake-SQL or YAML edit would pass, unless the human already chose override-accept | That is the fixer's job, not an overlay. Do not reject in order to edit source. |
| Pass the walker's identity | It is the claim holder and the call is refused. Cortex stamps yours. |
| `configure` with anything but `project_dir` | Shared session config. |
| Stamp `runTests` or delete the YAML case | Overlay only; RESULTS stays FAIL. |
| Edit converted SQL or the YAML | You decide; the walker writes. |
| Touch any object but `objectId` | Other agents are live on the rest of the wave. |
| Spawn a subagent | The read is yours. One spawn reviews every remaining hash. |
