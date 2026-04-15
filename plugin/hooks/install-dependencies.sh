#!/bin/bash
# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# SessionStart hook — downloads the MCP server binary and installs system dependencies.
# Wrapped in { ...; exit; } so bash reads the entire script into memory before
# executing, making it safe to overwrite this file during updates.

{
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
mkdir -p "$PLUGIN_ROOT/logs"
LOG="$PLUGIN_ROOT/logs/install-dependencies.log"

HOOK_START=$SECONDS
log() {
  local elapsed=$(( SECONDS - HOOK_START ))
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [${elapsed}s] $*" 2>/dev/null | tee -a "$LOG" >&2
}

VERSION=$(cat "$PLUGIN_ROOT/VERSION" 2>/dev/null | tr -d '[:space:]')
if [ -z "$VERSION" ]; then
  log "ERROR: plugin/VERSION not found or empty"
  exit 1
fi

PLAT_OS=$(uname -s | tr '[:upper:]' '[:lower:]')
PLAT_ARCH=$(uname -m)
case "$PLAT_OS" in darwin) PLAT_OS=osx ;; *) PLAT_OS=linux ;; esac
case "$PLAT_ARCH" in x86_64) PLAT_ARCH=x64 ;; arm64|aarch64) PLAT_ARCH=arm64 ;; esac
PLATFORM="${PLAT_OS}-${PLAT_ARCH}"

BLOB_BASE="https://sctoolsartifacts.z5.web.core.windows.net/linux/beta/plugins/bin"

log "SessionStart hook running (v$VERSION, $PLATFORM, plugin root: $PLUGIN_ROOT)"

# ── MCP server binary ───────────────────────────────────────────
BIN_DIR="$PLUGIN_ROOT/mcp-server/bin"
BIN="$BIN_DIR/migration-mcp-server"
BINARY_URL="${BLOB_BASE}/migration-mcp-server-v${VERSION}-${PLATFORM}"

NEEDS_DOWNLOAD=true
if [ -f "$BIN" ] && [ -f "$BIN_DIR/.version" ]; then
  INSTALLED_VERSION=$(cat "$BIN_DIR/.version" 2>/dev/null | tr -d '[:space:]')
  if [ "$INSTALLED_VERSION" = "$VERSION" ]; then
    NEEDS_DOWNLOAD=false
    log "MCP server binary up to date (v$VERSION)"
  else
    log "MCP server binary outdated (v$INSTALLED_VERSION → v$VERSION)"
  fi
fi

if [ "$NEEDS_DOWNLOAD" = "true" ]; then
  start=$SECONDS
  mkdir -p "$BIN_DIR"
  log "Downloading MCP server binary ($PLATFORM, v$VERSION)..."
  if curl -fsSL "$BINARY_URL" -o "$BIN"; then
    chmod +x "$BIN"
    xattr -dr com.apple.quarantine "$BIN" 2>/dev/null || true
    echo "$VERSION" > "$BIN_DIR/.version"
    log "MCP server binary installed ($(( SECONDS - start ))s, $(du -h "$BIN" | cut -f1))"
  else
    log "Binary download failed — MCP server will be unavailable"
  fi
fi

# ── Python dependencies (snowpark) ──────────────────────────────
if [ -f "$PLUGIN_ROOT/mcp-server/pyproject.toml" ] && command -v uv &>/dev/null; then
  if [ ! -d "$PLUGIN_ROOT/mcp-server/.venv" ]; then
    start=$SECONDS
    log "Installing Python dependencies (snowpark)..."
    (cd "$PLUGIN_ROOT/mcp-server" && uv sync --quiet 2>&1) || log "uv sync failed (snowpark will be unavailable)"
    log "Python dependencies installed ($(( SECONDS - start ))s)"
  fi
fi

# ── System dependencies ─────────────────────────────────────────
FORMULAE=(uv)
CASKS=("snowconvert-ai-${PLUGIN_CHANNEL:-pr}")

start=$SECONDS
INSTALLED_FORMULAE=$(brew list --formula 2>/dev/null | tr '\n' ' ')
INSTALLED_CASKS=$(brew list --cask 2>/dev/null | tr '\n' ' ')
TAPPED=$(brew tap 2>/dev/null | tr '\n' ' ')
log "Fetched brew state ($(( SECONDS - start ))s)"

needs_tap() { [[ " $TAPPED " != *" $1 "* ]]; }
is_installed_formula() { [[ " $INSTALLED_FORMULAE " == *" $1 "* ]]; }
is_installed_cask() { [[ " $INSTALLED_CASKS " == *" $1 "* ]]; }

if needs_tap "snowflakedb/snowconvert-ai"; then
  log "Tapping snowflakedb/snowconvert-ai..."
  brew tap snowflakedb/snowconvert-ai
else
  log "snowflakedb/snowconvert-ai already tapped"
fi

log "Syncing brew tap definitions..."
brew update --quiet 2>/dev/null || log "brew update failed, continuing with cached definitions"

for cask in "${CASKS[@]}"; do
  start=$SECONDS
  if is_installed_cask "$cask"; then
    log "Upgrading $cask (cask)..."
    brew upgrade --cask "$cask" 2>/dev/null || log "$cask already at latest version"
    log "$cask up to date ($(( SECONDS - start ))s)"
  else
    log "Installing $cask (cask)..."
    brew install --cask "$cask"
    log "Installed $cask ($(( SECONDS - start ))s)"
  fi
done

for formula in "${FORMULAE[@]}"; do
  start=$SECONDS
  if is_installed_formula "$formula"; then
    log "$formula already installed ($(( SECONDS - start ))s)"
  else
    log "Installing $formula..."
    brew install "$formula"
    log "Installed $formula ($(( SECONDS - start ))s)"
  fi
done

log "SessionStart hook complete (total: $(( SECONDS - HOOK_START ))s)"
exit
}
