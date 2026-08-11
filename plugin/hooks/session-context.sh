#!/bin/sh
# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
#
# UserPromptSubmit hook — ONCE per session, injects a single fact (does a
# migration project exist in this directory?) plus which way to route, so the
# agent orients on the user's first message. Tool-level instructions
# (configure, migration_status) belong to the migration skill, not here.
#
# Why UserPromptSubmit, not SessionStart: coco only logs/displays SessionStart
# additionalContext (agentService.executeSessionStartHooks logs it; the CLI
# renders a "[Hook] Session context" line) and never sends it to the model.
# UserPromptSubmit additionalContext IS injected into the outgoing message, so
# it actually reaches the agent.
#
# Fire exactly once per session: UserPromptSubmit runs on every message, so a
# per-session sentinel (keyed on session_id, under the temp dir) guards against
# re-injecting the same guidance and wasting tokens on every turn.

input="$(cat 2>/dev/null)"

sid="$(printf '%s' "$input" | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
marker=""
if [ -n "$sid" ]; then
  marker="${TMPDIR:-/tmp}/scai-migration-ctx/$sid"
  [ -f "$marker" ] && exit 0
elif printf '%s' "$input" | grep -q '"response_metadata"'; then
  # No session_id to key on — fall back to coco's turn-1 signal (response_metadata
  # is absent until a prior assistant turn) so we still inject only on the first message.
  exit 0
fi

dir="$(printf '%s' "$input" | sed -n 's/.*"cwd"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
[ -n "$dir" ] || dir="$PWD"

if [ -f "$dir/.scai/config/project.yml" ]; then
  cat <<'EOF'
<system-reminder>
[snowflake-migration] A migration project exists in this directory (.scai/config/project.yml).
- If the user's message names a specific migration task, or says "continue"/"resume"/"next": act on it by reading the built-in snowflake-migration:migration skill.
- If the message is vague (e.g. "help", "hi", "can you help me migrate"): ask "What would you like to do today? Say 'continue' to pick up your migration where we left off, or tell me something specific."
- Otherwise, match the request to the relevant migration skill.
</system-reminder>
EOF
else
  cat <<'EOF'
<system-reminder>
[snowflake-migration] No migration project exists in this directory yet (no .scai/config/project.yml).
- To start or continue a migration here: read the built-in snowflake-migration:migration skill and follow its setup flow.
- Otherwise, match the request to the relevant skill.
</system-reminder>
EOF
fi

# Record that this session has received the context so later turns stay silent.
if [ -n "$marker" ]; then
  mkdir -p "$(dirname "$marker")" 2>/dev/null && : > "$marker" 2>/dev/null
fi

exit 0
