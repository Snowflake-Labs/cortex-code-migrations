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
# Also installs git, and updates the plugin last.
# Wrapped in { ...; exit; } so bash reads the entire script into memory before
# executing, making it safe to overwrite this file during updates.

{
set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
mkdir -p "$PLUGIN_ROOT/logs"
LOG="$PLUGIN_ROOT/logs/install-dependencies.log"
CA_SCRIPT="$SCRIPT_DIR/lib/trust-windows-ca.sh"

HOOK_START=$SECONDS

# PATH inherited from the parent process (the Cortex Code app). Capture it before
# this hook modifies PATH, so we can tell whether the app can resolve `scai`.
# The app's environment is fixed at its launch, so a newly installed `scai` stays
# invisible to the MCP server until the user restarts the application.
INHERITED_PATH="$PATH"
log() {
  local elapsed=$(( SECONDS - HOOK_START ))
  # || true: a plugin update can replace logs/ mid-run.
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [${elapsed}s] $*" 2>/dev/null | tee -a "$LOG" >&2 || true
}

# Behind TLS inspection (e.g. ZScaler), WSL and the Windows bash shells ignore
# the Windows certificate store, so curl fails: exit 60 (untrusted) or 77 (a CA
# variable names an unreadable file). Prints that code, else 0.
curl_tls_rc() {
  local rc=0
  curl -sS -o /dev/null --max-time 15 https://astral.sh >/dev/null 2>&1 || rc=$?
  case "$rc" in 60|77) printf '%s\n' "$rc" ;; *) printf '0\n' ;; esac
}
tls_error() {
  if [ "$1" = 77 ]; then
    log "ERROR: curl cannot read the CA file named by SSL_CERT_FILE or CURL_CA_BUNDLE; fix or unset it."
  else
    log "ERROR: curl still cannot verify TLS. Run in a terminal: bash $CA_SCRIPT"
  fi
}

# If a POSIX shell on Windows (Git Bash/MSYS/Cygwin) reaches this script, the
# Unix install path is wrong -- delegate to the PowerShell hook instead so
# Windows always gets the correct (Windows) scai build. It runs as a child, so
# this shell's own CA store (which the Windows tools do not use) is fixed after.
case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*|Windows_NT)
    # MSYS2 and Cygwin can start without the Windows PATH.
    ps_exe="$(command -v powershell.exe || true)"
    if [ -z "$ps_exe" ] && command -v cygpath &>/dev/null; then
      ps_exe="$(cygpath -u "${SYSTEMROOT:-C:\\Windows}")/System32/WindowsPowerShell/v1.0/powershell.exe"
    fi
    ps1_rc=0
    (cd "$SCRIPT_DIR" && "${ps_exe:-powershell.exe}" -NoProfile -ExecutionPolicy Bypass -File install-dependencies.ps1) || ps1_rc=$?
    if [ "$ps1_rc" -ne 0 ]; then log "WARNING: install-dependencies.ps1 exited with code $ps1_rc (${ps_exe:-powershell.exe})"; fi
    # bash has no PATHEXT, so it cannot run the Cortex Code CLI's cortex.cmd as
    # `cortex`. This wrapper sits next to it (a dir the CLI installer puts on
    # the Windows PATH) and reads the cortex.exe path from the shim at run time,
    # since Cortex Code updates rewrite it.
    if command -v cygpath &>/dev/null; then
      cortex_bin="$(cygpath -u "${LOCALAPPDATA:-$USERPROFILE\\AppData\\Local}")/cortex/bin"
      if [ -f "$cortex_bin/cortex.cmd" ]; then
        cat > "$cortex_bin/cortex" <<'EOF' && chmod +x "$cortex_bin/cortex" || log "WARNING: could not write $cortex_bin/cortex"
#!/bin/sh
# Written by install-dependencies.sh: runs the cortex.exe named by cortex.cmd.
shim="$(dirname "$0")/cortex.cmd"
exe=$(tr -d '\r' < "$shim" | sed -n 's/^@\{0,1\}"\([^"]*\.exe\)".*/\1/p' | head -1)
[ -n "$exe" ] || { echo "cortex: no cortex.exe path in $shim" >&2; exit 127; }
exec "$(cygpath -u "$exe")" "$@"
EOF
      fi
    fi
    # New Git Bash terminals get the Windows user PATH the .ps1 wrote only when
    # started from a fresh environment; one started inside the app inherits its
    # PATH. So add the tool dirs to the bash rc files too (not for a dir already
    # on the inherited PATH).
    if command -v cygpath &>/dev/null; then
      win_lad="$(cygpath -u "${LOCALAPPDATA:-$USERPROFILE\\AppData\\Local}")"
      rc_added=false
      for dir in "$win_lad/snowconvertai/bin" "$win_lad/cortex/bin" "$(cygpath -u "${USERPROFILE:-$HOME}")/.local/bin"; do
        [ -d "$dir" ] || continue
        case ":$INHERITED_PATH:" in *":$dir:"*) continue ;; esac
        if ! tr -d '\r' < "$HOME/.bashrc" 2>/dev/null | grep -qxF "# >>> snowconvertai PATH $dir >>>"; then rc_added=true; fi
        # Subshell: sourcing defines the CA script's helpers; only
        # persist_env_block is used, with its messages sent to the log.
        ( # shellcheck source=lib/trust-windows-ca.sh
          . "$CA_SCRIPT"
          info() { log "$*"; }; warn() { log "WARNING: $*"; }
          persist_env_block "PATH $dir" "case \":\$PATH:\" in *\":$dir:\"*) ;; *) export PATH=\"$dir:\$PATH\" ;; esac" ) ||
          log "WARNING: could not add $dir to the bash rc files"
      done
      if $rc_added; then
        log "New bash terminals get the updated PATH. To use it in an open one, run: source ~/.bashrc"
      fi
    fi
    # Without elevation the fix leaves git a CA bundle copy; the rc files point
    # new shells at it, but this non-interactive shell reads no rc file.
    ca_copy="$HOME/.config/trust-windows-ca/git-ca-bundle.crt"
    if [ -z "${CURL_CA_BUNDLE:-}" ] && [ -f "$ca_copy" ]; then export CURL_CA_BUNDLE="$ca_copy"; fi
    tls_rc="$(curl_tls_rc)"
    if [ "$tls_rc" != 0 ]; then
      log "curl in this shell cannot verify TLS (exit $tls_rc). Fixing its CA store (in Cygwin, this can take minutes)..."
      if [ "${CURL_CA_BUNDLE:-}" = "$ca_copy" ]; then unset CURL_CA_BUNDLE; fi
      bash "$CA_SCRIPT" --quiet </dev/null 2>&1 | tee -a "$LOG" >&2 || true
      if [ -z "${CURL_CA_BUNDLE:-}" ] && [ -f "$ca_copy" ]; then export CURL_CA_BUNDLE="$ca_copy"; fi
      tls_rc="$(curl_tls_rc)"
      if [ "$tls_rc" != 0 ]; then tls_error "$tls_rc"; fi
    fi
    exit "$ps1_rc"
    ;;
esac

VERSION=$(cat "$PLUGIN_ROOT/VERSION" 2>/dev/null | tr -d '[:space:]')
if [ -z "$VERSION" ]; then
  log "ERROR: plugin/VERSION not found or empty"
  exit 1
fi

# Disable scai auto-update for this session only (we manage updates below).
# Not persisted, so the user's global scai config is untouched; set only if unset.
export SCAI_AUTO_UPDATE="${SCAI_AUTO_UPDATE:-false}"

log "SessionStart hook running (v$VERSION, plugin root: $PLUGIN_ROOT)"

PLUGIN_NAME=snowflake-migration
PLUGIN_REPO=Snowflake-Labs/cortex-code-migrations
CORTEX_HOME="$HOME/.snowflake/cortex"
PLUGIN_REGISTRY="$CORTEX_HOME/plugins/registry.json"

# plugin_ref FILE: the git ref of the plugin's registry source, either form:
# github:<repo>/plugin#<ref> or https://github.com/<repo>/tree/<ref>/plugin.
# Empty when the source names no ref.
plugin_ref() {
  local src
  src="$(grep -oE "github:$PLUGIN_REPO/plugin#[A-Za-z0-9._/-]+|github\.com/$PLUGIN_REPO/tree/[A-Za-z0-9._/-]+/plugin" "$1" 2>/dev/null | head -1 || true)"
  case "$src" in
    *"/plugin#"*) printf '%s\n' "${src##*#}" ;;
    *) src="${src#*/tree/}"; printf '%s\n' "${src%/plugin}" ;;
  esac
}
# ref_channel REF: the plugin channel of a channel branch or a version tag;
# empty for an alpha branch. A source with no ref follows main.
ref_channel() {
  case "$1" in
    ""|main) echo stable ;;
    preview|v[0-9]*.[0-9]*.[0-9]*-Pr.*) echo preview ;;
    v[0-9]*) if printf '%s\n' "$1" | grep -qxE 'v[0-9]+\.[0-9]+\.[0-9]+'; then echo stable; fi ;;
  esac
}
# channel_branch CHANNEL: the plugin branch of a channel. The plugin has no dev
# channel: with dev, scai uses dev and the plugin uses preview.
channel_branch() { case "$1" in preview|dev) echo preview ;; *) echo main ;; esac; }

# Optional runtime override (opt-in): pin a specific scai or plugin version via the shared
# config file. Absent config = default behavior (update to the channel's latest).
# The channel is the one `scai settings set channel=` writes, at scai's path ($SNOWFLAKE_HOME when
# that directory exists). Intentional simplification: scai's OS-specific fallbacks apply only
# without ~/.snowflake, which Cortex needs.
MIGRATION_CONFIG="$HOME/.snowflake/migration-plugin/config.json"
if [ -n "${SNOWFLAKE_HOME:-}" ] && [ -d "$SNOWFLAKE_HOME" ]; then
  SCAI_SETTINGS="$SNOWFLAKE_HOME/scai/settings.json"
else
  SCAI_SETTINGS="$HOME/.snowflake/scai/settings.json"
fi
SCAI_VERSION_PIN=""
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
# The plugin pin ({"plugin": {"version": "X"}}) and the scai `channel` (a top-level
# string in the flat file scai writes) are read without python3. Only a version counts.
PLUGIN_VERSION_PIN="$(tr -d '\r\n' 2>/dev/null < "$MIGRATION_CONFIG" | sed -n 's/.*"plugin"[[:space:]]*:[[:space:]]*{[^}]*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' || true)"
if ! printf '%s\n' "$PLUGIN_VERSION_PIN" | grep -qxE '[0-9]+(\.[0-9]+)*(-Pr\.[0-9]+)?'; then PLUGIN_VERSION_PIN=""; fi
[ -n "$PLUGIN_VERSION_PIN" ] && log "Config pins plugin.version=$PLUGIN_VERSION_PIN"
SETTINGS_CHANNEL="$(tr -d '\r\n' 2>/dev/null < "$SCAI_SETTINGS" | sed -n 's/.*"channel"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' || true)"

# One channel for scai and the plugin: SCAI_CHANNEL, then the scai settings
# file, then the channel of the installed plugin source, then stable.
PLUGIN_REF="$(plugin_ref "$PLUGIN_REGISTRY")"
# A plugin installed from a fork or a local path is left alone.
PLUGIN_FROM_REPO=false
if grep -q "\"$PLUGIN_NAME\"" "$PLUGIN_REGISTRY" 2>/dev/null && grep -q "$PLUGIN_REPO" "$PLUGIN_REGISTRY"; then PLUGIN_FROM_REPO=true; fi
plugin_channel=""
if $PLUGIN_FROM_REPO; then plugin_channel="$(ref_channel "$PLUGIN_REF")"; fi
SCAI_CHANNEL="$(printf '%s' "${SCAI_CHANNEL:-${SETTINGS_CHANNEL:-${plugin_channel:-stable}}}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
case "$SCAI_CHANNEL" in
  stable|preview|dev) ;;
  *) log "WARNING: unknown channel '$SCAI_CHANNEL' (expected stable, preview, or dev); using stable"; SCAI_CHANNEL=stable ;;
esac
export SCAI_CHANNEL

log "SCAI_CHANNEL=$SCAI_CHANNEL, CORTEX_CHANNEL=${CORTEX_CHANNEL:-(not set)}"

# System dependencies

# WSL: add the Windows certificates to the distro store when curl cannot verify
# TLS. Once fixed, rerun every session to pick up rotated certificates.
if grep -qi microsoft /proc/version 2>/dev/null; then
  tls_rc="$(curl_tls_rc)"
  if [ "$tls_rc" != 0 ]; then
    log "curl cannot verify TLS (exit $tls_rc: corporate TLS inspection, for example ZScaler, or an unreadable CA file). Checking the CA store of this shell..."
  fi
  if [ "$tls_rc" != 0 ] || [ -f "$HOME/.config/trust-windows-ca/windows-ca.pem" ]; then
    bash "$CA_SCRIPT" --quiet </dev/null 2>&1 | tee -a "$LOG" >&2 || true
  fi
  # The probe checks astral.sh only, and TLS inspection often exempts other
  # hosts (snowconvert.snowflake.com, GitHub), so log one error and go on: each
  # later step logs its own failure, and an installed scai is still checked.
  if [ "$tls_rc" != 0 ]; then
    tls_rc="$(curl_tls_rc)"
    if [ "$tls_rc" != 0 ]; then tls_error "$tls_rc"; fi
  fi
fi

# uv's bundled certs fail behind TLS-intercepting proxies (e.g. ZScaler); use the
# OS trust store instead. Set only if unset.
export UV_SYSTEM_CERTS="${UV_SYSTEM_CERTS:-true}"

# uv -- tools invoke bare `uv`, so ensure a callable `uv` lands on PATH.
# Install with astral's standalone installer, from astral.sh, else the same
# installer from the GitHub release (the plugin already needs GitHub), else
# pipx (for a site that blocks both but mirrors PyPI).
add_user_path() {
  local dir="$1"
  [ -n "$dir" ] && [ -d "$dir" ] || return 0
  case ":$PATH:" in
    *":$dir:"*) ;;
    *) export PATH="$dir:$PATH" ;;
  esac
}

UV_LOCAL_BIN="$HOME/.local/bin"
# A hook started from a GUI app may lack ~/.local/bin on PATH; reuse that uv.
if ! command -v uv &>/dev/null && [ -x "$UV_LOCAL_BIN/uv" ]; then
  add_user_path "$UV_LOCAL_BIN"
fi
if command -v uv &>/dev/null; then
  log "uv already installed"
else
  start=$SECONDS
  uv_ready=false

  # Standalone installer (installs to ~/.local/bin and writes the receipt
  # `uv self update` needs). Corporate proxies (e.g. ZScaler) can block
  # astral.sh but allow GitHub, so the GitHub release copy is the second URL.
  for uv_installer in https://astral.sh/uv/install.sh \
                      https://github.com/astral-sh/uv/releases/latest/download/uv-installer.sh; do
    uv_host="${uv_installer#https://}"; uv_host="${uv_host%%/*}"
    log "Installing uv (standalone installer from $uv_host)..."
    if curl -LsSf "$uv_installer" | bash; then
      add_user_path "$UV_LOCAL_BIN"
      if command -v uv &>/dev/null; then uv_ready=true; log "Installed uv (standalone from $uv_host)"; break; fi
    else
      log "Standalone uv installer from $uv_host failed"
    fi
  done

  # pipx (isolated, astral-recommended); bootstrap pipx via pip --user if absent.
  if ! $uv_ready && command -v python3 &>/dev/null; then
    if ! command -v pipx &>/dev/null; then
      # Behind TLS-intercepting corporate proxies (e.g. ZScaler) pip cannot verify
      # PyPI certs yet, so use --trusted-host to fetch pip-system-certs, which then
      # makes pip trust the OS cert store for later installs.
      pip_trusted="--trusted-host pypi.org --trusted-host pypi.python.org --trusted-host files.pythonhosted.org"
      log "Installing pip-system-certs (trusted-host bootstrap)..."
      # shellcheck disable=SC2086 # word-splitting of $pip_trusted flags is intended
      python3 -m pip install --user pip -U $pip_trusted --quiet </dev/null >>"$LOG" 2>&1 || log "pip upgrade failed"
      # shellcheck disable=SC2086
      python3 -m pip install --user pip_system_certs -U $pip_trusted --quiet </dev/null >>"$LOG" 2>&1 || log "pip-system-certs install failed"
      log "Bootstrapping pipx (pip install --user pipx)..."
      python3 -m pip install --user pipx --quiet </dev/null >>"$LOG" 2>&1 || log "pipx bootstrap failed"
    fi
    if python3 -m pipx ensurepath </dev/null >>"$LOG" 2>&1 && python3 -m pipx install uv </dev/null >>"$LOG" 2>&1; then
      add_user_path "$UV_LOCAL_BIN"
      if command -v uv &>/dev/null; then uv_ready=true; log "Installed uv (pipx)"; fi
    else
      log "pipx install uv failed"
    fi
  fi

  $uv_ready && log "uv ready ($(( SECONDS - start ))s)" || log "WARNING: could not make uv callable on PATH after $(( SECONDS - start ))s"
fi

# git -- the plugin update and the migration workflow need it.
# macOS: /usr/bin/git is a stub (it opens an install dialog) until the Command
# Line Tools are installed, so it does not count.
git_works() {
  local g
  g="$(command -v git || true)"
  [ -n "$g" ] || return 1
  if [ "$(uname -s)" = Darwin ] && [ "$g" = /usr/bin/git ] && ! xcode-select -p >/dev/null 2>&1; then
    return 1
  fi
  git --version >/dev/null 2>&1
}
# The hook has no terminal, so root must need no password: root, sudo -n, or in
# WSL wsl.exe -u root. Prints the prefix words, one per line.
root_prefix() {
  if [ "$(id -u)" -eq 0 ]; then return 0; fi
  if command -v sudo &>/dev/null && sudo -n true 2>/dev/null; then printf '%s\n' sudo -n; return 0; fi
  if [ -n "${WSL_DISTRO_NAME:-}" ] && command -v wsl.exe &>/dev/null &&
     wsl.exe -d "$WSL_DISTRO_NAME" -u root --exec true </dev/null >/dev/null 2>&1; then
    printf '%s\n' wsl.exe -d "$WSL_DISTRO_NAME" -u root --exec; return 0
  fi
  return 1
}
install_git_linux() {
  local cmd="" prefix=() line
  if command -v apt-get &>/dev/null; then cmd="apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y git"
  elif command -v dnf &>/dev/null; then cmd="dnf install -y git"
  elif command -v yum &>/dev/null; then cmd="yum install -y git"
  elif command -v zypper &>/dev/null; then cmd="zypper -n install git"
  elif command -v pacman &>/dev/null; then cmd="pacman -S --noconfirm git"
  elif command -v apk &>/dev/null; then cmd="apk add git"
  else log "No supported package manager found to install git"; return 1
  fi
  if ! root_prefix >/dev/null; then
    log "Installing git needs root without a password prompt; run in a terminal: sudo sh -c '$cmd'"
    return 1
  fi
  while IFS= read -r line; do prefix+=("$line"); done < <(root_prefix)
  log "Installing git ($cmd)..."
  "${prefix[@]+"${prefix[@]}"}" sh -c "$cmd" </dev/null >>"$LOG" 2>&1
}
if git_works; then
  log "git already installed"
else
  start=$SECONDS
  if [ "$(uname -s)" = Darwin ]; then
    if command -v brew &>/dev/null; then
      log "Installing git (brew)..."
      brew install git </dev/null >>"$LOG" 2>&1 || log "brew install git failed"
    else
      log "Opening the Xcode Command Line Tools installer (includes git); finish it, then start a new session"
      xcode-select --install >>"$LOG" 2>&1 || true
    fi
  else
    install_git_linux || log "git install failed"
  fi
  if git_works; then
    log "Installed git ($(( SECONDS - start ))s)"
  else
    log "WARNING: git is not installed after $(( SECONDS - start ))s"
  fi
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
scai_link_target() {
  [ -L "$SCAI_LINK" ] || return 1
  # Declared before assignment: `local x=$(...)` would mask the exit status.
  local target resolved
  target="$(readlink "$SCAI_LINK" 2>/dev/null)" || return 1
  case "$target" in
    /*) printf '%s\n' "$target" ;;
    *)
      resolved="$(cd "$(dirname "$SCAI_LINK")" && cd "$(dirname "$target")" && pwd)/$(basename "$target")" || return 1
      printf '%s\n' "$resolved"
      ;;
  esac
}
# A symlink outside SCAI_ROOT is a `make build` checkout (or similar). Relinking
# it to the release hides local MCP changes. Require -x so a wiped checkout is
# still repaired.
scai_is_user_managed() {
  local target
  target="$(scai_link_target)" || return 1
  [ -x "$target" ] || return 1
  case "$target" in
    "$SCAI_ROOT"/*) return 1 ;;
    *) return 0 ;;
  esac
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
# Skipped for a user-managed scai: we are not going to act on the answer.
scai_latest=""
if ! scai_is_user_managed; then
  meta_json="$(curl -fsSL --max-time 30 "$SCAI_BASE/$(scai_metadata_file)" 2>/dev/null || true)"
  if [ -n "$meta_json" ]; then
    scai_latest=$(printf '%s' "$meta_json" | grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/' || true)
  fi
fi

# Active version = the version dir the ~/.local/bin/scai symlink points at.
scai_active="$(scai_read_active)"

# Target version: an explicit config pin wins over the channel's latest.
scai_target="${SCAI_VERSION_PIN:-$scai_latest}"

if scai_is_user_managed; then
  add_user_path "$SCAI_BIN_DIR"
  log "scai is user-managed (-> $(scai_link_target)) - left untouched ($(( SECONDS - start ))s)"
elif [ -n "$scai_target" ] && [ "$scai_active" = "$scai_target" ]; then
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

# snowflake-migration plugin: `cortex plugin install <URL> --force` from the
# branch of the resolved channel (see SCAI_CHANNEL above), or from the tag of a
# pinned version. Skipped with a .no-auto-update file
# in the plugin root (the source tree and dev checkouts have one), without a
# Cortex Code CLI, or when the plugin is not in the Cortex registry from the
# public repo (loaded with --plugin-dir, or from a fork). Last, since the install may replace this plugin directory.
# version_gt A B: true if dotted version A is newer than B (numeric parts).
version_gt() {
  awk -v a="$1" -v b="$2" 'BEGIN {
    n = split(a, x, /[^0-9]+/); m = split(b, y, /[^0-9]+/)
    for (i = 1; i <= (n > m ? n : m); i++) {
      if (x[i] + 0 > y[i] + 0) exit 0
      if (x[i] + 0 < y[i] + 0) exit 1
    }
    exit 1 }'
}
start=$SECONDS
# Cortex Code CLI -- the plugin update runs it. When none is found, run the
# official installer (to ~/.local/bin); the hook has no terminal, so skip its
# PATH prompt.
cortex_cli="$(command -v cortex || true)"
if [ -z "$cortex_cli" ] && [ -x "$HOME/.local/bin/cortex" ]; then cortex_cli="$HOME/.local/bin/cortex"; fi
if [ -n "$cortex_cli" ]; then
  log "Cortex Code CLI found ($cortex_cli)"
else
  log "Installing the Cortex Code CLI (official installer)..."
  # stdin is the installer script, so no </dev/null here.
  if curl -qfsSL --max-time 60 https://ai.snowflake.com/static/cc-scripts/install.sh |
     SKIP_PATH_PROMPT=1 NON_INTERACTIVE=1 sh >>"$LOG" 2>&1; then
    add_user_path "$HOME/.local/bin"
  else
    log "Cortex Code CLI installer failed"
  fi
  if [ -x "$HOME/.local/bin/cortex" ]; then
    cortex_cli="$HOME/.local/bin/cortex"
    log "Installed the Cortex Code CLI ($(( SECONDS - start ))s)"
  else
    log "WARNING: the Cortex Code CLI is not installed after $(( SECONDS - start ))s"
  fi
fi
start=$SECONDS
if [ -f "$PLUGIN_ROOT/.no-auto-update" ]; then
  log "$PLUGIN_NAME plugin: .no-auto-update found in $PLUGIN_ROOT, not updating"
elif [ -z "$cortex_cli" ]; then
  log "No Cortex Code CLI found; skipping the $PLUGIN_NAME plugin update"
elif ! $PLUGIN_FROM_REPO; then
  log "$PLUGIN_NAME plugin is not in the Cortex plugin registry from $PLUGIN_REPO (running from $PLUGIN_ROOT); nothing to update"
else
  installed="$(tr -d '[:space:]' < "$CORTEX_HOME/plugins/$PLUGIN_NAME/VERSION" 2>/dev/null || true)"
  installed="${installed:-$VERSION}"
  # An alpha branch (no channel) follows its own head. A pin installs its version tag.
  plugin_branch="$PLUGIN_REF"; pin=""
  if [ -n "$plugin_channel" ]; then plugin_branch="$(channel_branch "$SCAI_CHANNEL")"; pin="$PLUGIN_VERSION_PIN"; fi
  why=""
  if [ -n "$pin" ]; then
    published="$pin"; install_ref="v$pin"; why="pinned"
  else
    published="$(curl -fsSL --max-time 15 "https://raw.githubusercontent.com/$PLUGIN_REPO/$plugin_branch/plugin/VERSION" 2>/dev/null | tr -d '[:space:]' || true)"
    # A proxy or captive portal can answer with a page of its own; only a
    # version (X.Y.Z or X.Y.Z-Pr.N) counts.
    if ! printf '%s\n' "$published" | grep -qxE '[0-9]+(\.[0-9]+)*(-Pr\.[0-9]+)?'; then published=""; fi
    install_ref="$plugin_branch"
    # A channel switch installs the new channel's latest, also a lower version (as scai).
    # Compare plugin branches: dev and preview share the preview branch.
    if [ -n "$plugin_channel" ] && [ "$(channel_branch "$plugin_channel")" != "$plugin_branch" ]; then why="channel $plugin_channel -> $SCAI_CHANNEL"; fi
  fi
  if [ -z "$published" ]; then
    log "Could not fetch the published $PLUGIN_NAME VERSION (branch $plugin_branch)"
  elif [ "$published" = "$installed" ] || { [ -z "$why" ] && ! version_gt "$published" "$installed"; }; then
    log "$PLUGIN_NAME plugin up to date (v$installed, branch $plugin_branch) ($(( SECONDS - start ))s)"
  else
    install_url="https://github.com/$PLUGIN_REPO/tree/$install_ref/plugin"
    log "Updating the $PLUGIN_NAME plugin (v$installed -> v$published${why:+, $why}) from $install_url..."
    if "$cortex_cli" plugin install "$install_url" --force </dev/null >>"$LOG" 2>&1; then
      log "Updated the $PLUGIN_NAME plugin to v$published. It takes effect in the next session or after /plugin reload."
    else
      log "WARNING: cortex plugin install $install_url --force failed"
    fi
  fi
fi

log "SessionStart hook complete (total: $(( SECONDS - HOOK_START ))s)"
exit
}
