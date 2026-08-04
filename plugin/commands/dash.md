---
description: Open the migration dashboard in the browser
allowed-tools: Bash(open:*)
---

The migration dashboard is a **read-only web view** of this project — object
inventory, wave/deployment progress, and data-migration status — served
locally on `127.0.0.1`. Point the user at it so they can watch progress while
the agent works.

## 1. Find the dashboard URL

The dashboard is opt-in and only runs when a `dashboard_port` has been set.
Resolve the actual port (do **not** guess — there is no fixed default unless
`-1` was chosen):

- The `configure()` response returns the **bound URL** whenever the dashboard
  is running — use it verbatim.
- Otherwise read the persisted `dashboard_port` from `.scai/config/plugin.yml`
  (it's saved there so the dashboard auto-starts on later sessions). Map it to
  a URL: `-1` → `http://127.0.0.1:7878/`; a positive integer → that port. A
  value of `-2` (auto-scan) has no fixed port — get the real one from the
  `configure()` response, not the file.

## 2. Open it and tell the user what it's for

Open the resolved URL in the default browser:

!`open <resolved-url>`

Then tell the user it's now open and that it shows live migration progress
(objects, waves, and data migration/validation status), refreshing as work
proceeds.

## If no dashboard is running

If no `dashboard_port` is set, enable it by calling
`configure(dashboard_port=<value>)`:

- `-2` — auto-scan for a free port starting at `7878` (recommended)
- `-1` — fixed port `7878`
- any positive integer — bind that exact port

The choice is persisted to `.scai/config/plugin.yml` and reused next session.
The `configure()` response returns the bound URL — open it as in step 2. For
the full setup flow, see `setup/SKILL.md`.
