# Informatica `pmcmd` Connection Reference

Deferred detail for the `etl-validate` skill, read **only** when `{PLATFORM_ID}` is `informatica`.
Two sections, matching the two places the skill points here:

- **Which connection the run will use** — Step 0c. Informational: it works out what the run will
  pick up. It registers nothing.
- **Fixing a failing `pmcmd_credentials`** — Step 1. The remediation, with its stopping point.

`scai test etl-validate` launches PowerCenter workflows with `pmcmd`, which needs a repository user
and password. A registered `scai` connection supplies them once, instead of re-exporting
`INFORMATICA_USERNAME` / `INFORMATICA_PASSWORD` in every shell.

## Which connection the run will use

**First, work out which connection name the run will select.** There is no flag for it —
`scai test etl-validate` has **no** `--informatica-connection` option, because the flag lives on the
underlying `test-runner` CLI and the CSnakes bridge `scai` runs through does not forward it. The name
comes from configuration, in the two tiers the runner reads:

- **Per project** — `informatica_connection: <CONNECTION_NAME>` in `.scai/config/project.yml`.
  Reach for this when the right connection differs per repository; it is committed with the project.
  `project.local.yml` is read first where it exists, so a developer can point at their own
  connection without editing the committed file.
- **Per machine** — `default_connection_name` in `informatica.toml`, written by
  `scai connection set-default -l informatica -s <CONNECTION_NAME>`.

`.scai/config/project.yml` wins over `default_connection_name` when both are present.

**Then check whether that name is registered:**

```bash
scai connection list -l informatica --json
```

Registration and selection are separate — `add-informatica-pmcmd` writes the connection but never a
`default_connection_name` — so read both out of the same payload: `defaultConnectionName` at the top
level and `isDefault` per connection, both camelCase. `isDefault` is **omitted** rather than `false`
on a non-default connection, so test for `true` or for the field's presence, never for `== false`.

| What you find | What it means for the run |
|---|---|
| The selected name is registered | Those are the credentials `pmcmd` will get. Continue to Step 1, where `pmcmd_credentials` confirms they resolve and names the route each value came from. |
| A connection exists, but it is not the selected one | The run will ignore it and fall back to `test_config.yaml`. Selecting it costs nothing and involves no password, so do that now: [`../../../../connection/informatica-pmcmd-connection/SKILL.md`](../../../../connection/informatica-pmcmd-connection/SKILL.md) from its **Step 3** (`set-default`, then `connection test`). This is the one misconfiguration the probe cannot report — a leftover connection from another project resolves fine, so `pmcmd_credentials` passes while the run uses credentials nobody chose. |
| Nothing registered, or nothing selected | Note it and continue to Step 1. If the `informatica:` section or exported `INFORMATICA_*` variables already supply credentials, the probe passes and there is nothing to register; if it fails, Step 1 is where you register. |

**Do not register a connection from this step.** A project whose credentials already resolve from
exported environment variables needs none, and registering would copy the password out of the
environment into a cleartext file on disk for no gain.

### Where the values end up coming from

At run time the runner resolves the connection by name (`resolve_informatica_connection` in
`testing-infrastructure/test-runner/src/test_runner/common/config.py`) and merges it over the
`informatica:` section of `.scai/settings/test_config.yaml` **per field, connection wins**. So the
connection supplies whatever it carries — credentials plus `service` / `domain` — and anything it
does not carry still falls back to that section. Registering never invalidates an existing one.

### When `--service` / `--domain` rule a connection out

One case cannot use a connection at all: `add-informatica-pmcmd` **requires** `--service` and
`--domain`, while the runner treats them as optional (it omits the matching `pmcmd -sv` / `-d` flag
and lets pmcmd apply its own `domains.infa` defaults). A project that deliberately relies on those
defaults should fill the `informatica:` section instead — and if you have to look at that file, note
that it holds a password: never `cat` it, print the section, or quote its values back to the user.

## Fixing a failing `pmcmd_credentials`

`pmcmd_credentials` resolves the username and password through the same resolver the real run uses —
a registered connection first, then the `informatica:` section, with `${VAR}` references expanded
from the environment — so it passes on an exported `INFORMATICA_PASSWORD` and fails on an unexported
one, naming which route supplied each value. The password is never echoed, in the message or the
details, so the output is safe to read back to the user.

There are **two** fixes. **Recommend the connection**: it is the supported route (the seeded block
says `# PREFERRED`), it survives a new shell, and it keeps the credential out of the project
entirely. Keep the other available rather than deciding for the user:

- **Register a connection once** — the recommended fix. Note the trade honestly: a connection keeps
  the password in **cleartext** under `~/.snowflake/snowct/`, protected only by file permissions, so
  it buys scope rather than encryption.
- **Export the variables.** `INFORMATICA_USERNAME` / `INFORMATICA_PASSWORD` resolve the check just as
  well and keep the password nowhere on disk. Offer this when the user does not want it on disk, when
  they already have the variables in their shell, or when `--service` / `--domain` rule a connection
  out (above).

Neither fix is "edit `test_config.yaml`". **A credential value must never be written into that file**
— its `username:` / `password:` are env-var *references* in a committed file, and this check cannot
catch a literal: it fails only on an *unresolved* `${VAR}`, so an inlined password passes and reports
`password from test_config.yaml`. If the user offers the value, route it to an exported variable or
to the connection's own hidden prompt.

To register, follow
[`../../../../connection/informatica-pmcmd-connection/SKILL.md`](../../../../connection/informatica-pmcmd-connection/SKILL.md)
from its **Step 1** rather than copying its commands here — a second copy is what drifts when the
sub-skill changes. It runs `scai connection add-informatica-pmcmd` with no options, and the **CLI**
prompts for all seven values (pmcmd path, repository user, password, Integration Service, domain,
optional `domains.infa`, connection name).

**STOPPING POINT** — those prompts are the user's to answer. Do not collect any of the values in
chat, do not put the password on a command line, and do not echo it back. Then re-run the probe.

Registering also clears a `pmcmd_accessibility` failure, because a connection carries `pmcmd_path`
as well.
