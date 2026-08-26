#!/usr/bin/env sh
set -eu

script_dir="$(cd "$(dirname "$0")" && pwd)"
hook="$script_dir/../session-context.sh"
dev_reminder="$script_dir/../dev-build-reminder.txt"
test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

run_hook() {
  build_channel="$1"
  session_id="$2"
  manifest_layout="${3:-multiline}"
  plugin_root="$test_root/plugin-$build_channel"
  marker_root="$test_root/markers-$session_id"
  mkdir -p "$plugin_root/.cortex-plugin" "$plugin_root/hooks"
  if [ "$build_channel" = none ]; then
    printf '{\n  "name": "snowflake-migration"\n}\n' > "$plugin_root/.cortex-plugin/plugin.json"
  elif [ "$manifest_layout" = compact ]; then
    printf '{"name":"snowflake-migration","buildChannel":"%s","version":"1.0.0"}\n' "$build_channel" > "$plugin_root/.cortex-plugin/plugin.json"
  else
    printf '{\n  "buildChannel": "%s"\n}\n' "$build_channel" > "$plugin_root/.cortex-plugin/plugin.json"
  fi
  cp "$dev_reminder" "$plugin_root/hooks/dev-build-reminder.txt"
  mkdir -p "$marker_root"
  TMPDIR="$marker_root" CLAUDE_PLUGIN_ROOT="$plugin_root" sh "$hook" <<EOF
{"session_id":"$session_id","cwd":"$test_root"}
EOF
}

dev_output="$(run_hook dev dev-session)"
printf '%s' "$dev_output" | grep -Fq 'Do not work around plugin bugs.' \
  || fail "dev manifest did not inject the bug guardrail"

compact_dev_output="$(run_hook dev compact-dev-session compact)"
printf '%s' "$compact_dev_output" | grep -Fq 'Do not work around plugin bugs.' \
  || fail "compact dev manifest did not inject the bug guardrail"

preview_output="$(run_hook preview preview-session)"
if printf '%s' "$preview_output" | grep -Fq 'Do not work around plugin bugs.'; then
  fail "preview manifest injected the bug guardrail"
fi

no_channel_output="$(run_hook none no-channel-session)"
if printf '%s' "$no_channel_output" | grep -Fq 'Do not work around plugin bugs.'; then
  fail "manifest without buildChannel injected the bug guardrail"
fi

echo "session-context.sh tests passed"
