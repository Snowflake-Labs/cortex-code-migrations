#!/bin/sh
# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0

set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PLUGIN_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
LOG="$PLUGIN_ROOT/logs/mcp-server-validation.log"

if command -v python3 >/dev/null 2>&1; then
  exec python3 "$SCRIPT_DIR/validate-scai-mcp.py"
fi
if command -v python >/dev/null 2>&1; then
  exec python "$SCRIPT_DIR/validate-scai-mcp.py"
fi

mkdir -p "$PLUGIN_ROOT/logs"
message="SCAI_MCP_UNVERIFIED: Python is unavailable; skipped bounded MCP initialize probe"
printf '%s\n' "$message" | tee -a "$LOG" >&2
exit 0
