# Dispatch

The unit of dispatch is one object, and the child is always
[`general_task`](../../../../../agents/general_task.md). It walks its object
through every task the machine offers — convert, deploy, tests, fixes — and
stops when the object is done or needs a human. Do not route by task.

Run at most `N` children at once. First sends and later sends are different
`task` calls.

## First send

Use a first send when there is no Cortex `resume` id for this object. Spawn all
first sends for the turn together, one prompt each, and always pass
`description` with a short object label. Do not pass `resume` or
`fork_conversation_history`.

```
Migrate this object end-to-end, following your agent definition.

objectId:            <a single id>
projectDir:          <absolute project_dir>
pluginDir:           <absolute plugin root — the directory this skill was loaded from, above skills/migration/>
snowflakeConnection: <the target connection passed to configure(snowflake_connection=...) — NOT the system-reminder "active SQL connection">
guidance:            <verbatim words from answered — only when there are some>
reason:              <from a reopened return — only when there is one>
```

`task` returns an `agentId` UUID. Store it as this object's `resume` id. That is
the conversation. A later `task(resume=...)` returns a different UUID: a wait
handle for that send only. Do not overwrite the stored `resume` id with the wait
handle, and do not call `agent_output` with either one.

The imperative first line matters. Bare `key: value` pairs read as context
rather than a request, so an unattended child asks what to do. Say what to do
once and leave the behavior contract to the agent definition.

`pluginDir` is required because `executor.skill` values are relative to the
plugin's `skills/migration/` directory and the child cannot locate that on its
own. Do not put `agentId` in the prompt; Cortex stamps the child's session id
on every MCP call.

`snowflakeConnection` is the target connection — the same value the parent passed
to `configure(snowflake_connection=...)` in preflight, and never the
system-reminder "active SQL connection", which is the agent's inference account
and has no deployment privileges. Without it the child omits `-c` and hits that
default account. The child's attach lists `active_bindings:`; read `snow:` and
`source:` from that YAML to qualify SQL, because without it the child qualifies
SQL with the source catalog name.

Do not tell the child to load `snowflake-migration:migration`; that is the
interactive router. The [`general_task`](../../../../../agents/general_task.md)
definition already carries the loop, fix-loop thresholds, escalation test, and
return schema. Extra retry limits, invented response fields, custom return
shapes, or instructions not to escalate conflict with that contract.

## Later send

Use a later send when the existing conversation still has the walk and returned
`waiting`, `partial`, or `stuck`. Call `task` with the stored `resume` id,
`description`, and a prompt containing only the new line. Do not repeat the
object/project/plugin/connection values or the migrate-this-object line. Do not
pass `fork_conversation_history`.

For a relay wake:

```
relay_wake: <the wake line, verbatim>
```

After a person answered:

```
guidance: <verbatim words from answered>
```

When the board is ready after a `partial` result or remediated reset:

```
Continue this object from the machine's next task.
```

Store the UUID returned by this `task` call as the wait handle. Do not wait yet:
finish every other first send and wake for the turn, then wait once. Keep
resuming the original stored conversation id.

If the `resume` id is lost, use a first send with the full prompt. That is the
killed-session path.

## Object uniqueness and guidance

One live child per object, never two. Board `flight`, not memory, is the check.
Resuming the same conversation is sequential reuse. A leftover first-send is
only for an object `next_objects` listed under `leftover_claims`, never for a
harvested waiter that still carries an `agentId`; the server can reclaim a dead
holder's claim but cannot referee two live children editing the same object.

Track in-flight work by object id, not task. A child walks the full pipeline, so
an object mid-walk resolves to a new task whenever the board is read. A
`resume` call is not a second child.

Check `answered` before every send. An answered escalation has already
unparked its object and looks like ordinary work. If the escalation response
lists the object under `answered`, use a later send with `guidance:` when the
conversation id is known, or a first send including that guidance when it is
not. Dropping the guidance asks a child to remake a decision a person already
made.

`N` is the only dispatch limit the parent controls. Do not inspect why a
sibling is blocked or which task it is on.
