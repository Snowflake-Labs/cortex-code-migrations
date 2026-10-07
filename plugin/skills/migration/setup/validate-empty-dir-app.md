---
name: validate-empty-dir-app
description: Handle a non-empty project directory in the desktop app — the user picks the new one, so point them at the app's own control
license: Proprietary. See License-Skills for complete terms
---

# Validate Empty Directory (desktop app)

The current directory is not empty and cannot be used to initialize a new migration project.

The project directory is the user's to choose here, and the app denies any attempt to switch it. Do not offer to put the project somewhere else and do not create a directory — one you create is not in their project list, so sending them there dead-ends them.

Ask the user directly — do not describe or explain what is in the directory:

> "This folder already has files in it, so a migration project can't be initialized here. Open the project menu in the app header and choose **+ New project…** — it picks an empty folder and switches the app to it."

Then stop. Carry on with the current project until they switch.
