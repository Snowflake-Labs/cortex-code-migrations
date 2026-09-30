---
name: confirm-project-dir-app
description: Confirm the project directory in the desktop app — Yes proceeds here; a different location goes through the app's own control
license: Proprietary. See License-Skills for complete terms
---

# Confirm Project Directory (desktop app)

Ask the user:

> "Set up the migration project in `<project_dir>`?"
>
> 1. **Yes, use it** — Proceed with the current directory.
> 2. **Use a different location** — Open **+ New project…** in the app header.

**If option 1:**

```
configure(project_dir_confirmed=true)
```

**If option 2:** Tell the user to open the project menu in the app header and choose **+ New project…** — it picks an empty folder and switches the app to it. Do not ask for a path and do not call `configure(project_dir=…)`. Then stop. Carry on with the current project until they switch.
