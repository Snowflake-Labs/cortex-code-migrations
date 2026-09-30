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

# SessionStart hook - installs system dependencies (uv, scai CLI). The migration
# MCP server binary ships inside the scai CLI and is launched via `scai mcp`.
# Wrapped in { ...; exit; } so bash reads the entire script into memory before
# executing, making it safe to overwrite this file during updates.

{
set -e
set -o pipefail

# If a POSIX shell on Windows (Git Bash/MSYS/Cygwin) reaches this script, the
# Unix install path is wrong -- delegate to the PowerShell hook instead so
# Windows always gets the correct (Windows) scai build.
case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*|Windows_NT)
    cd "$(dirname "$0")" || exit 1
    exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File install-dependencies.ps1
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
mkdir -p "$PLUGIN_ROOT/logs"
LOG="$PLUGIN_ROOT/logs/install-dependencies.log"

HOOK_START=$SECONDS

# PATH inherited from the parent process (the Cortex Code app). Capture it before
# this hook modifies PATH, so we can tell whether the app can resolve `scai`.
# The app's environment is fixed at its launch, so a newly installed `scai` stays
# invisible to the MCP server until the user restarts the application.
INHERITED_PATH="$PATH"
log() {
  local elapsed=$(( SECONDS - HOOK_START ))
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [${elapsed}s] $*" 2>/dev/null | tee -a "$LOG" >&2
}

VERSION=$(cat "$PLUGIN_ROOT/VERSION" 2>/dev/null | tr -d '[:space:]')
if [ -z "$VERSION" ]; then
  log "ERROR: plugin/VERSION not found or empty"
  exit 1
fi

export SCAI_CHANNEL="${SCAI_CHANNEL:-stable}"

# Disable scai auto-update for this session only (we manage updates below).
# Not persisted, so the user's global scai config is untouched; set only if unset.
export SCAI_AUTO_UPDATE="${SCAI_AUTO_UPDATE:-false}"

log "SessionStart hook running (v$VERSION, plugin root: $PLUGIN_ROOT)"
log "SCAI_CHANNEL=$SCAI_CHANNEL, CORTEX_CHANNEL=${CORTEX_CHANNEL:-(not set)}"

# Optional runtime override (opt-in): pin a specific scai version via the shared
# config file. Absent config = default behavior (update to the channel's latest).
SCAI_VERSION_PIN=""
MIGRATION_CONFIG="$HOME/.snowflake/migration-plugin/config.json"
if [ -f "$MIGRATION_CONFIG" ]; then
  if command -v python3 &>/dev/null; then
    # `if VAR=$(...)` keeps `set -e` from aborting when the JSON is unparseable.
    if SCAI_VERSION_PIN=$(python3 - "$MIGRATION_CONFIG" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    cfg = json.load(f)
v = (cfg.get("scai") or {}).get("version")
print(v if isinstance(v, str) else "")
PY
    ); then
      [ -n "$SCAI_VERSION_PIN" ] && log "Config pins scai.version=$SCAI_VERSION_PIN"
    else
      SCAI_VERSION_PIN=""
      log "WARNING: could not parse $MIGRATION_CONFIG - ignoring, using default scai version"
    fi
  else
    log "WARNING: python3 not found - ignoring $MIGRATION_CONFIG, using default scai version"
  fi
fi

# System dependencies

# uv's bundled certs fail behind TLS-intercepting proxies (e.g. ZScaler); use the
# OS trust store instead. Set only if unset.
export UV_SYSTEM_CERTS="${UV_SYSTEM_CERTS:-true}"

# uv -- tools invoke bare `uv`, so ensure a callable `uv` lands on PATH.
# Install in isolation (astral standalone, else pipx).
add_user_path() {
  local dir="$1"
  [ -n "$dir" ] && [ -d "$dir" ] || return 0
  case ":$PATH:" in
    *":$dir:"*) ;;
    *) export PATH="$dir:$PATH" ;;
  esac
}

UV_LOCAL_BIN="$HOME/.local/bin"
if command -v uv &>/dev/null; then
  log "uv already installed"
else
  start=$SECONDS
  uv_ready=false

  # 1. standalone installer (astral default; installs to ~/.local/bin)
  log "Installing uv (standalone installer)..."
  if curl -LsSf https://astral.sh/uv/install.sh | bash; then
    add_user_path "$UV_LOCAL_BIN"
    if command -v uv &>/dev/null; then uv_ready=true; log "Installed uv (standalone)"; fi
  else
    log "Standalone uv installer failed"
  fi

  # 2. pipx (isolated, astral-recommended); bootstrap pipx via pip --user if absent
  if ! $uv_ready && command -v python3 &>/dev/null; then
    if ! command -v pipx &>/dev/null; then
      # Behind TLS-intercepting corporate proxies (e.g. ZScaler) pip cannot verify
      # PyPI certs yet, so use --trusted-host to fetch pip-system-certs, which then
      # makes pip trust the OS cert store for later installs.
      pip_trusted="--trusted-host pypi.org --trusted-host pypi.python.org --trusted-host files.pythonhosted.org"
      log "Installing pip-system-certs (trusted-host bootstrap)..."
      # shellcheck disable=SC2086 # word-splitting of $pip_trusted flags is intended
      python3 -m pip install --user pip -U $pip_trusted --quiet >>"$LOG" 2>&1 || log "pip upgrade failed"
      python3 -m pip install --user pip_system_certs -U $pip_trusted --quiet >>"$LOG" 2>&1 || log "pip-system-certs install failed"
      log "Bootstrapping pipx (pip install --user pipx)..."
      python3 -m pip install --user pipx --quiet >>"$LOG" 2>&1 || log "pipx bootstrap failed"
    fi
    if python3 -m pipx ensurepath >>"$LOG" 2>&1 && python3 -m pipx install uv >>"$LOG" 2>&1; then
      add_user_path "$UV_LOCAL_BIN"
      if command -v uv &>/dev/null; then uv_ready=true; log "Installed uv (pipx)"; fi
    else
      log "pipx install uv failed"
    fi
  fi

  $uv_ready && log "uv ready ($(( SECONDS - start ))s)" || log "WARNING: could not make uv callable on PATH after $(( SECONDS - start ))s"
fi

# Remove legacy brew-based snowconvert-ai casks (replaced by scai CLI)
if command -v brew &>/dev/null; then
  LEGACY_CASKS=(snowconvert-ai snowconvert-ai-pr snowconvert-ai-dev)
  INSTALLED_CASKS=$(brew list --cask 2>/dev/null | tr '\n' ' ')
  for cask in "${LEGACY_CASKS[@]}"; do
    if [[ " $INSTALLED_CASKS " == *" $cask "* ]]; then
      start=$SECONDS
      log "Uninstalling legacy cask $cask..."
      brew uninstall --cask "$cask" 2>&1 | tee -a "$LOG" >&2 || log "Failed to uninstall $cask"
      log "Uninstalled $cask ($(( SECONDS - start ))s)"
    fi
  done
fi

# scai CLI (bundles the migration MCP server binary).
# Centralized storage URL map -- single source of truth. Portable to bash 3.2
# (macOS) so no associative arrays. Channel-to-segment: stable=prod, preview=beta,
# dev=dev; OS segment matches the published storage layout.
SCAI_STORAGE_BASE="https://snowconvert.snowflake.com/storage"
scai_channel_segment() { case "$1" in preview) echo beta ;; dev) echo dev ;; *) echo prod ;; esac; }
scai_os_segment() {
  case "$(uname -s)/$(uname -m)" in
    Darwin/arm64)        echo darwin_arm64 ;;
    Darwin/x86_64)       echo darwin_x64 ;;
    Linux/*)             echo linux ;;
    MINGW*|MSYS*|CYGWIN*) echo windows ;;
    *)                   echo linux ;;
  esac
}
scai_cli_base() { echo "$SCAI_STORAGE_BASE/$(scai_os_segment)/$(scai_channel_segment "$1")/cli"; }
# install.sh is published ONLY under the linux segment (it self-detects the OS);
# see user-local-install.md. The channel is still honored via SCAI_CHANNEL.
scai_installer_url() { echo "$SCAI_STORAGE_BASE/linux/$(scai_channel_segment "$1")/cli/install.sh"; }
# Linux publishes arch-suffixed metadata (latest-archive-x64.json / -arm64.json)
# under the shared linux/ prefix; macOS uses an unsuffixed file per darwin_* prefix.
scai_metadata_file() {
  case "$(uname -s)/$(uname -m)" in
    Linux/x86_64)  echo "latest-archive-x64.json" ;;
    Linux/aarch64) echo "latest-archive-arm64.json" ;;
    *)             echo "latest-archive.json" ;;
  esac
}
scai_read_active() {
  if [ -L "$SCAI_LINK" ]; then
    readlink "$SCAI_LINK" 2>/dev/null | sed -n 's#.*/snowconvertai/\([^/]*\)/orchestrator/.*#\1#p' || true
  fi
}

# Install/update WITHOUT `scai update` (its update URL is broken on some platforms
# in the shipped build). The official install.sh is itself a full updater; we
# drive it behind an active-pointer (symlink) check so we only download when the
# channel's latest is not already the active version.
start=$SECONDS
SCAI_ROOT="$HOME/.local/share/snowconvertai"
SCAI_BIN_DIR="$HOME/.local/bin"
SCAI_LINK="$SCAI_BIN_DIR/scai"
SCAI_BASE="$(scai_cli_base "$SCAI_CHANNEL")"

# Resolve the channel's latest version from the small metadata file (no jq dep).
scai_latest=""
meta_json="$(curl -fsSL --max-time 30 "$SCAI_BASE/$(scai_metadata_file)" 2>/dev/null || true)"
if [ -n "$meta_json" ]; then
  scai_latest=$(printf '%s' "$meta_json" | grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/' || true)
fi

# Active version = the version dir the ~/.local/bin/scai symlink points at.
scai_active="$(scai_read_active)"

# Target version: an explicit config pin wins over the channel's latest.
scai_target="${SCAI_VERSION_PIN:-$scai_latest}"

if [ -n "$scai_target" ] && [ "$scai_active" = "$scai_target" ]; then
  add_user_path "$SCAI_BIN_DIR"
  log "scai up to date (channel=$SCAI_CHANNEL, v$scai_target) ($(( SECONDS - start ))s)"
elif [ -n "$scai_target" ] && [ -x "$SCAI_ROOT/$scai_target/orchestrator/scai" ]; then
  # Target already on disk but symlink stale/missing -- relink only, no download.
  mkdir -p "$SCAI_BIN_DIR"
  ln -sf "$SCAI_ROOT/$scai_target/orchestrator/scai" "$SCAI_LINK"
  add_user_path "$SCAI_BIN_DIR"
  log "scai relinked to v$scai_target (channel=$SCAI_CHANNEL) ($(( SECONDS - start ))s)"
else
  if [ -n "$SCAI_VERSION_PIN" ]; then
    log "Installing scai CLI (pinned v$SCAI_VERSION_PIN, channel=$SCAI_CHANNEL)..."
  elif [ -n "$scai_latest" ]; then
    log "Installing scai CLI v$scai_latest (channel=$SCAI_CHANNEL)..."
  else
    log "Installing scai CLI (channel=$SCAI_CHANNEL)..."
  fi
  # SCAI_VERSION empty = install the channel's latest; set = pin. install.sh honors it.
  # pipefail (set above) makes this pipeline fail if curl or the installer fails,
  # not just if tee fails. install.sh runs in a child bash, so its `exit` is safe.
  if curl -fsSL "$(scai_installer_url "$SCAI_CHANNEL")" | SCAI_VERSION="$SCAI_VERSION_PIN" bash 2>&1 | tee -a "$LOG" >&2; then
    install_ok=true
  else
    log "scai install failed"
    install_ok=false
  fi
  add_user_path "$SCAI_BIN_DIR"
  scai_active="$(scai_read_active)"
  # Only claim success when the installer succeeded AND the symlink points at
  # the target (or, with no target, at some newly-linked version). A leftover
  # scai on PATH must not count.
  if $install_ok && [ -n "$scai_target" ] && [ "$scai_active" = "$scai_target" ]; then
    log "Installed scai CLI ($(( SECONDS - start ))s)"
  elif $install_ok && [ -z "$scai_target" ] && [ -n "$scai_active" ]; then
    log "Installed scai CLI ($(( SECONDS - start ))s)"
  else
    log "WARNING: scai CLI installation failed after $(( SECONDS - start ))s"
  fi
fi

# Auto-update disabled via the session-scoped SCAI_AUTO_UPDATE env var set above.

# The MCP server is launched by the app as bare `scai`, which resolves against the
# PATH the app inherited at launch. If the scai bin dir is missing there, the MCP
# server cannot start, however healthy this install is. Only a full application
# restart reloads that PATH, so say so plainly.
case ":$INHERITED_PATH:" in
  *":$SCAI_BIN_DIR:"*) ;;
  *)
    if [ -x "$SCAI_LINK" ]; then
      log "ACTION REQUIRED: scai is installed at $SCAI_BIN_DIR but that path was not"
      log "ACTION REQUIRED: on this application's PATH when it started, so the"
      log "ACTION REQUIRED: snowflake-migration MCP server cannot launch scai."
      log "ACTION REQUIRED: Fully quit and relaunch Cortex Code (a new chat or"
      log "ACTION REQUIRED: session is not enough) to pick up the updated PATH."
    fi
    ;;
esac

log "SessionStart hook complete (total: $(( SECONDS - HOOK_START ))s)"
exit
}
