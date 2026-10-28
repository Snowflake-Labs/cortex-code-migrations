# hail_mary

When to send [`hail_mary`](../../../../../agents/hail_mary.md), and when never
to, is in [SKILL.md](../SKILL.md) 2e. This page is the send itself and what to
do when it returns.

## First send

No `resume`. One `task` call per parked object:

```
Unstick this parked object, following your agent definition.

objectId:            <id>
projectDir:          <absolute project_dir>
pluginDir:           <absolute plugin root>
snowflakeConnection: <the same target connection passed to configure>
task:                <the parked task if you already have it from the escalate call>
```

Do not put `asks` in the prompt — that child reads `mode="escalations"` with
`details=true`.

## When it returns

- `guidance` / `decompose` in `answered` → first-send a **new** `general_task`
  with `guidance:` (the old walker conversation is done).
- `forced` / `skip` / `mark_done` → re-read the board.
- `needs_repair` / `refused` → leave parked.

Do not `status='answer'` for a hail_mary return; you relay only an explicit
user reply (2e).
