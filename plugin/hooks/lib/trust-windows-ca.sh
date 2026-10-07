#!/usr/bin/env bash
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

# Fix "unable to get local issuer certificate" errors behind a TLS-inspecting
# proxy (for example ZScaler or Netskope) in WSL, Git Bash, MSYS2, and Cygwin.
#
# These environments use their own CA bundle, not the Windows store where the
# company CAs live. Steps:
#   1. Check TLS to the installer hosts with the environment bundle and each
#      bundle named by SSL_CERT_FILE and similar variables. Stop if all pass.
#   2. Get the Windows trust store (export-windows-ca.ps1; with WSL interop off,
#      --cert-file or the ZScaler Client Connector export) and confirm it fixes
#      the failing hosts.
#   3. Add it to the environment CA store and set the CA variables (curl, git,
#      Python, Node.js, uv) in the rc files.
#   4. Re-check the failing hosts.
#
# Usage: bash trust-windows-ca.sh [--check] [--quiet] [--cert-file PATH]...
#   --check      Do steps 1 and 2 only. Change nothing.
#   --quiet      Show only warnings and errors.
#   --cert-file  Trust this PEM or DER certificate instead of reading Windows.
#                Repeatable.
#
# Exit status: 0 if the environment store trusts all hosts (unreachable hosts
# and bad CA variables only warn). 1 if needed certificates cannot be found.
#
# SessionStart hooks run this with --quiet when curl exits 60 or 77, and in WSL
# on every session after the first fix. Sourcing only defines functions.

PROG="$(basename "${BASH_SOURCE[0]}")"
SELF="${BASH_SOURCE[0]}"
EXPORT_PS1="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/export-windows-ca.ps1"
HOSTS=(pypi.org files.pythonhosted.org astral.sh github.com snowconvert.snowflake.com)
CA_ENV_VARS=(SSL_CERT_FILE CURL_CA_BUNDLE REQUESTS_CA_BUNDLE PIP_CERT GIT_SSL_CAINFO AWS_CA_BUNDLE)
MARKER="# Added by $PROG from the Windows certificate store"

ENV_KIND=""
STORE_BUNDLE=""
ANCHOR_DIR=""
UPDATE_CMD=""
PROXY_ARGS=()
WORK=""
QUIET=false
CERT_FILES=()
SEEN_FPS=""
OUT_DIR="$HOME/.config/trust-windows-ca"

info() { if ! $QUIET; then printf '%s\n' "$*"; fi; }
info_row() { if ! $QUIET; then printf '  %-28s %s\n' "$1" "$2"; fi; }
# Not silenced by --quiet; use before a slow step.
notice() { printf '%s\n' "$*" >&2; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

detect_env() {
  case "$(uname -s)" in
    CYGWIN*) ENV_KIND=cygwin ;;
    MINGW*|MSYS*)
      if [ -x /usr/bin/pacman ]; then ENV_KIND=msys2; else ENV_KIND=gitbash; fi ;;
    Linux)
      if [ -n "${WSL_DISTRO_NAME:-}" ] || grep -qi microsoft /proc/version 2>/dev/null; then ENV_KIND=wsl
      else die "Not running under Windows (WSL, Git Bash, MSYS2, or Cygwin)."; fi ;;
    *) die "Unsupported environment: $(uname -s)" ;;
  esac
}

first_file() {
  local f
  for f in "$@"; do if [ -s "$f" ]; then printf '%s\n' "$f"; return 0; fi; done
  return 1
}

# The CA bundle used by this environment's OpenSSL-based tools.
detect_store_bundle() {
  case "$ENV_KIND" in
    gitbash) STORE_BUNDLE="$(first_file /clangarm64/etc/ssl/certs/ca-bundle.crt /ucrt64/etc/ssl/certs/ca-bundle.crt /mingw64/etc/ssl/certs/ca-bundle.crt /mingw32/etc/ssl/certs/ca-bundle.crt /usr/ssl/certs/ca-bundle.crt)" ;;
    msys2|cygwin) STORE_BUNDLE="$(first_file /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem /usr/ssl/certs/ca-bundle.crt /etc/pki/tls/certs/ca-bundle.crt)" ;;
    *) STORE_BUNDLE="$(first_file /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt /var/lib/ca-certificates/ca-bundle.pem /etc/ssl/cert.pem)" ;;
  esac || die "No CA bundle found; install the ca-certificates package."
}

# Windows <-> POSIX paths (wslpath in WSL, cygpath elsewhere). Cygwin does not
# convert path arguments for Windows programs, so pass them to_windows paths.
to_posix() {
  if [[ ! "$1" =~ ^[A-Za-z]:[\\/] ]]; then printf '%s\n' "$1"
  elif command -v cygpath >/dev/null 2>&1; then cygpath -u "$1"
  else wslpath -u "$1"; fi
}
to_windows() {
  if command -v wslpath >/dev/null 2>&1; then wslpath -w "$1"; else cygpath -w "$1"; fi
}

# openssl s_client ignores https_proxy, so pass it explicitly.
detect_proxy() {
  local p="${https_proxy:-${HTTPS_PROXY:-}}"
  p="${p#*://}"; p="${p##*@}"; p="${p%%/*}"
  if [ -n "$p" ]; then PROXY_ARGS=(-proxy "$p"); fi
}

# The Windows system drive as a POSIX path. The globs cover Windows on another
# drive or mount root.
find_windows_root() {
  local d
  for d in "$(to_posix 'C:\')" /mnt/*/ /cygdrive/*/ /*/; do
    d="${d%/}"
    if [ -n "$d" ] && [ -d "$d/Windows/System32" ]; then printf '%s\n' "$d"; return 0; fi
  done
  return 1
}

find_powershell() {
  local c root
  c="$(command -v powershell.exe 2>/dev/null || true)"
  if [ -n "$c" ]; then printf '%s\n' "$c"; return 0; fi
  root="$(find_windows_root)" || return 1
  c="$root/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
  [ -f "$c" ] && printf '%s\n' "$c"
}

# ---------------------------------------------------------------------------
# Step 1: check
# ---------------------------------------------------------------------------

# verify HOST BUNDLE -> ok | untrusted | unreachable  (BUNDLE alone, no CA dir)
verify() {
  local out
  out="$(timeout 20 openssl s_client -connect "$1:443" -servername "$1" -CAfile "$2" -no-CApath \
         "${PROXY_ARGS[@]+"${PROXY_ARGS[@]}"}" </dev/null 2>&1 || true)"
  case "$out" in
    *"Verify return code: 0 "*) echo ok ;;
    *"Verify return code:"*)    echo untrusted ;;
    *)                          echo unreachable ;;
  esac
}

# On Windows each openssl s_client call takes about 1 second even on a fast
# network, so handshakes run in parallel in the background.
# start_verify DIR BUNDLE HOST...: results go to DIR/<n>. Call wait before
# read_verify.
start_verify() {
  local dir="$1" bundle="$2" host i=0
  shift 2
  mkdir -p "$dir"
  for host in "$@"; do i=$(( i + 1 )); verify "$host" "$bundle" > "$dir/$i" & done
}

# read_verify DIR HOST...: "<host>\t<status>" for each host, in order.
read_verify() {
  local dir="$1" host status i=0
  shift
  for host in "$@"; do
    i=$(( i + 1 )); IFS= read -r status < "$dir/$i" || status=unreachable
    printf '%s\t%s\n' "$host" "$status"
  done
}

verify_hosts() {
  local bundle="$1" dir
  shift
  dir="$(mktemp -d "$WORK/verify.XXXXXX")"
  start_verify "$dir" "$bundle" "$@"
  wait
  read_verify "$dir" "$@"
}

# "<label>\t<path>" per bundle to check, environment store first.
bundles_to_test() {
  local v path
  printf '%s\t%s\n' "$ENV_KIND CA store" "$STORE_BUNDLE"
  for v in "${CA_ENV_VARS[@]}"; do
    if [ -z "${!v:-}" ]; then continue; fi
    path="$(to_posix "${!v}")"
    if [ "$path" != "$STORE_BUNDLE" ]; then printf '%s\t%s\n' "\$$v" "$path"; fi
  done
}

# Hosts failing with the environment store go to $WORK/failing (fixed in step
# 3); missing or failing variable bundles go to $WORK/bad-env (advice only).
# Returns 1 if any check failed.
check_trust() {
  local label path host status any=false n=0
  : > "$WORK/failing"; : > "$WORK/bad-env"
  bundles_to_test > "$WORK/bundles"
  while IFS=$'\t' read -r label path; do
    n=$(( n + 1 ))
    if [ -f "$path" ]; then start_verify "$WORK/check.$n" "$path" "${HOSTS[@]}"; fi
  done < "$WORK/bundles"
  wait
  n=0
  while IFS=$'\t' read -r label path; do
    n=$(( n + 1 ))
    info "$label: $path"
    if [ ! -f "$path" ]; then
      info "  file does not exist"
      printf '%s\t%s\tmissing\n' "$label" "$path" >> "$WORK/bad-env"; any=true
      continue
    fi
    while IFS=$'\t' read -r host status; do
      info_row "$host" "$status"
      if [ "$status" != untrusted ]; then continue; fi
      any=true
      if [ "$path" = "$STORE_BUNDLE" ]; then printf '%s\n' "$host" >> "$WORK/failing"
      else printf '%s\t%s\tuntrusted\n' "$label" "$path" >> "$WORK/bad-env"; fi
    done < <(read_verify "$WORK/check.$n" "${HOSTS[@]}")
  done < "$WORK/bundles"
  sort -u -o "$WORK/bad-env" "$WORK/bad-env"
  ! $any
}

advise_env_overrides() {
  local label path why
  while IFS=$'\t' read -r label path why; do
    if [ "$why" = missing ]; then
      warn "$label points at a file that does not exist ($path). Unset it or point it at $STORE_BUNDLE."
    else
      warn "$label uses its own bundle ($path), which lacks the company CA. Point it at $STORE_BUNDLE, or unset it."
    fi
  done < "$WORK/bad-env"
}

# ---------------------------------------------------------------------------
# Step 2: collect the Windows trust store
# ---------------------------------------------------------------------------

# append_pem FILE SOURCE: add one PEM or DER CA certificate to $WORK/windows.pem
# after a "# <subject>" line (used by not_in and main). Skips non-CA, expired,
# and duplicate certificates. Always returns 0.
append_pem() {
  local in="$1" src="$2" pem="$WORK/one.pem" subj fp
  if ! openssl x509 -in "$in" -out "$pem" 2>/dev/null &&
     ! openssl x509 -inform DER -in "$in" -out "$pem" 2>/dev/null; then
    warn "Not a certificate, skipped: $src"
    return 0
  fi
  subj="$(openssl x509 -in "$pem" -noout -subject -nameopt RFC2253 | sed 's/^subject= *//')"
  if ! openssl x509 -in "$pem" -noout -checkend 0 >/dev/null 2>&1; then
    warn "Expired, skipped: $subj ($src)"
    return 0
  fi
  if [[ "$(openssl x509 -in "$pem" -noout -text)" != *"CA:TRUE"* ]]; then
    warn "Not a CA certificate, skipped: $subj ($src)"
    return 0
  fi
  # The ZScaler directory often has the same root as .crt and as .cer.
  fp="$(openssl x509 -in "$pem" -noout -fingerprint -sha256 | sed 's/.*=//; s/://g')"
  case " $SEEN_FPS " in *" $fp "*) return 0 ;; esac
  SEEN_FPS="$SEEN_FPS $fp"
  { printf '# %s\n' "$subj"; cat "$pem"; } >> "$WORK/windows.pem"
}

# append_bundle FILE SOURCE: FILE is a PEM bundle or one DER certificate.
# Returns 1 if nothing was added.
append_bundle() {
  local f="$1" src="$2" dir part before after
  before="$(count_certs "$WORK/windows.pem")"
  if ! grep -q -- '-----BEGIN CERTIFICATE-----' "$f" 2>/dev/null; then
    append_pem "$f" "$src"
  else
    dir="$(mktemp -d "$WORK/split.XXXXXX")"
    awk -v d="$dir" '
      /-----BEGIN CERTIFICATE-----/ { n++; f = sprintf("%s/%03d.pem", d, n); on = 1 }
      on { print > f }
      /-----END CERTIFICATE-----/ { if (on) close(f); on = 0 }' "$f"
    for part in "$dir"/*.pem; do
      if [ -f "$part" ]; then append_pem "$part" "$src"; fi
    done
  fi
  after="$(count_certs "$WORK/windows.pem")"
  [ "$after" -gt "$before" ]
}

# ZScaler Client Connector exports its root CA here; WSL can read it through the
# drive mount even with interop off.
zscaler_client_certs() {
  local root dir f
  root="$(find_windows_root)" || return 0
  dir="$root/ProgramData/Zscaler"
  [ -d "$dir" ] || return 0
  for f in "$dir"/*.crt "$dir"/*.cer "$dir"/*.pem; do
    if [ -f "$f" ] && [ -r "$f" ]; then printf '%s\n' "$f"; fi
  done
}

# Runs the .ps1 as a scriptblock, not with -File, because the execution policy
# (often AllSigned by Group Policy, or RemoteSigned for \\wsl.localhost paths)
# can block -File.
windows_store_pem() {
  local ps ps1
  ps="$(find_powershell)" || return 1
  [ -f "$EXPORT_PS1" ] || die "$EXPORT_PS1 is missing; keep it next to $PROG."
  ps1="$(to_windows "$EXPORT_PS1")"
  ( cd / && "$ps" -NoLogo -NoProfile -NonInteractive \
      -Command "& ([scriptblock]::Create([IO.File]::ReadAllText('${ps1//\'/\'\'}')))" 2>"$WORK/ps.err" ) |
    tr -d '\r'
}

# Writes $WORK/windows.pem from the first source with certificates: --cert-file,
# the Windows store via PowerShell, then the ZScaler export (WSL with interop off).
collect_windows_ca() {
  local f
  : > "$WORK/windows.pem"
  SEEN_FPS=""

  if [ ${#CERT_FILES[@]} -gt 0 ]; then
    for f in "${CERT_FILES[@]}"; do
      [ -r "$f" ] || die "Cannot read --cert-file $f"
      append_bundle "$f" "$f" || die "No certificate found in $f"
    done
    info "Using $(count_certs "$WORK/windows.pem") certificate(s) from --cert-file."
    return 0
  fi

  if windows_store_pem > "$WORK/store.pem" && grep -q 'BEGIN CERTIFICATE' "$WORK/store.pem"; then
    cat "$WORK/store.pem" > "$WORK/windows.pem"
    return 0
  fi
  warn "Could not read the Windows certificate store (is WSL interop disabled?): $(tr -d '\r' < "$WORK/ps.err" 2>/dev/null | head -c 200)"

  while IFS= read -r f; do
    append_bundle "$f" "$f" || true
  done < <(zscaler_client_certs)
  if grep -q 'BEGIN CERTIFICATE' "$WORK/windows.pem" 2>/dev/null; then
    info "Using $(count_certs "$WORK/windows.pem") certificate(s) from the ZScaler Client Connector export."
    return 0
  fi

  die "No certificates found. Export the CA on Windows and pass it with --cert-file (see the header)."
}

# not_in BUNDLE PEM: certificates (with comment lines) in PEM missing from
# BUNDLE. Compares base64 bodies, so line width and comments do not matter.
not_in() {
  awk -v have_file="$1" '
    { sub(/\r$/, "") }
    /-----BEGIN CERTIFICATE-----/ { inblock = 1; body = ""; block = $0 "\n"; next }
    inblock && /-----END CERTIFICATE-----/ {
      inblock = 0; block = block $0 "\n"
      if (FILENAME == have_file) have[body] = 1
      else if (!(body in have)) { printf "%s%s\n", comments, block; have[body] = 1 }
      comments = ""; next
    }
    inblock { body = body $0; block = block $0 "\n"; next }
    FILENAME != have_file && /^#/ { comments = comments $0 "\n"; next }
    { comments = "" }' "$1" "$2"
}

count_certs() { grep -c 'BEGIN CERTIFICATE' "$1" || true; }

# ---------------------------------------------------------------------------
# Step 3: add to the store of this environment
# ---------------------------------------------------------------------------

# sudo only in WSL: in MSYS2 and Cygwin, `sudo` is the Windows sudo.exe (a UAC
# prompt); those need an elevated shell instead.
needs_sudo() { [ "$ENV_KIND" = wsl ] && [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; }
ROOT_CMD=()
as_root() { "${ROOT_CMD[@]+"${ROOT_CMD[@]}"}" "$@"; }

# The SessionStart hook has stdin on /dev/null, so never wait for a password;
# without passwordless sudo, use wsl.exe -u root, which needs none. Only reached
# when certificates change (check_trust exits earlier otherwise).
ensure_sudo() {
  needs_sudo || return 0
  if [ -t 0 ]; then
    info "Updating the distro trust store (sudo may prompt for your password)..."
    sudo -v || die "sudo failed."
    ROOT_CMD=(sudo)
  elif sudo -n true 2>/dev/null; then
    ROOT_CMD=(sudo)
  elif [ -n "${WSL_DISTRO_NAME:-}" ] && command -v wsl.exe >/dev/null 2>&1 &&
       wsl.exe -d "$WSL_DISTRO_NAME" -u root --exec true </dev/null >/dev/null 2>&1; then
    ROOT_CMD=(wsl.exe -d "$WSL_DISTRO_NAME" -u root --exec)
  else
    die "Updating the trust store needs your sudo password. Run in a terminal: bash $SELF"
  fi
}

# Test the anchor directory, not the tool: Arch has update-ca-trust but uses a
# different directory.
detect_anchor_dir() {
  ANCHOR_DIR=""
  UPDATE_CMD=""
  if [ "$ENV_KIND" != wsl ]; then
    ANCHOR_DIR=/etc/pki/ca-trust/source/anchors; UPDATE_CMD="$(command -v update-ca-trust || true)"   # MSYS2 / Cygwin
  elif [ -d /usr/local/share/ca-certificates ]; then
    ANCHOR_DIR=/usr/local/share/ca-certificates; UPDATE_CMD="$(command -v update-ca-certificates || echo /usr/sbin/update-ca-certificates)"
  elif [ -d /etc/pki/ca-trust/source/anchors ]; then
    ANCHOR_DIR=/etc/pki/ca-trust/source/anchors; UPDATE_CMD="$(command -v update-ca-trust || echo /usr/bin/update-ca-trust)"
  elif [ -d /etc/pki/trust/anchors ]; then
    ANCHOR_DIR=/etc/pki/trust/anchors; UPDATE_CMD="$(command -v update-ca-certificates || echo /usr/sbin/update-ca-certificates)"
  elif [ -d /etc/ca-certificates/trust-source/anchors ]; then
    ANCHOR_DIR=/etc/ca-certificates/trust-source/anchors; UPDATE_CMD="$(command -v update-ca-trust || echo /usr/bin/update-ca-trust)"
  fi
}

# Replace this script's anchor files (one certificate each) with the current
# Windows trust store, then rebuild the distro bundle.
add_anchors() {
  detect_anchor_dir
  if [ -z "$ANCHOR_DIR" ] || [ -z "$UPDATE_CMD" ] || [ ! -x "$UPDATE_CMD" ]; then
    die "No update-ca-certificates / update-ca-trust found; install the ca-certificates package."
  fi
  # Start empty so certificates removed from the store do not linger.
  rm -rf "$WORK/anchors"
  mkdir -p "$WORK/anchors"
  awk -v d="$WORK/anchors" '
    /^#/ && !inblock { comments = comments $0 "\n"; next }
    /-----BEGIN CERTIFICATE-----/ { n++; f = sprintf("%s/windows-ca-%03d.crt", d, n); printf "%s", comments > f; inblock = 1 }
    inblock { print > f }
    /-----END CERTIFICATE-----/ { close(f); inblock = 0; comments = "" }' "$WORK/windows.pem"
  ensure_sudo
  as_root mkdir -p "$ANCHOR_DIR"
  as_root rm -f "$ANCHOR_DIR"/windows-ca-*.crt
  as_root install -m 0644 "$WORK"/anchors/*.crt "$ANCHOR_DIR/" ||
    die "Cannot write $ANCHOR_DIR (from MSYS2 / Cygwin, start the shell as Administrator)."
  notice "Rebuilding the $ENV_KIND CA store ($UPDATE_CMD). This can take several minutes..."
  if [[ "$UPDATE_CMD" == *update-ca-trust ]]; then as_root "$UPDATE_CMD" extract; else as_root "$UPDATE_CMD" >/dev/null; fi
  detect_store_bundle
}

# Returns 1 if BUNDLE is not writable.
append_missing() {
  { : >> "$1"; } 2>/dev/null || return 1
  not_in "$1" "$WORK/windows.pem" > "$WORK/append.pem"
  if [ -s "$WORK/append.pem" ]; then { printf '\n%s\n' "$MARKER"; cat "$WORK/append.pem"; } >> "$1"; fi
}

# Git's bundle is in Program Files, writable only from an elevated shell;
# otherwise give git a copy in the user profile, unless the user already chose
# a CA file or the Windows store (schannel) for git.
add_gitbash() {
  local copy="$OUT_DIR/git-ca-bundle.crt" extra current backend
  if append_missing "$STORE_BUNDLE"; then
    info "Updated $STORE_BUNDLE (a Git for Windows upgrade replaces it; re-run afterwards)."
    for extra in /usr/ssl/certs/ca-bundle.crt /usr/ssl/cert.pem; do
      if [ -f "$extra" ] && [ "$extra" != "$STORE_BUNDLE" ]; then append_missing "$extra" || true; fi
    done
    return 0
  fi
  mkdir -p "$(dirname "$copy")"
  rm -f "$copy"
  cat "$STORE_BUNDLE" > "$copy"   # not cp: a copy of a read-only bundle stays read-only
  append_missing "$copy" || die "Cannot write $copy."
  current="$(git config --global --get http.sslCAInfo 2>/dev/null || true)"
  backend="$(git config --global --get http.sslBackend 2>/dev/null || true)"
  if [ "$backend" = schannel ]; then
    info "git uses the Windows store (http.sslBackend schannel); http.sslCAInfo not set."
  elif [ -n "$current" ] && [ "$(to_posix "$current")" != "$copy" ]; then
    warn "git config --global http.sslCAInfo is already $current; not changed. For git behind TLS inspection, point it at $copy."
  else
    git config --global http.sslCAInfo "$(cygpath -m "$copy")"
    info "$STORE_BUNDLE is read-only (not an elevated shell), so git now uses a copy:"
    info "  $copy  (git config --global http.sslCAInfo)"
    info "Alternatively let git use the Windows store directly: git config --global http.sslBackend schannel"
  fi
  STORE_BUNDLE="$copy"
}

# persist_env_block LABEL LINE...: write LINEs in a block marked by LABEL in the
# bash rc files (and ~/.zshrc for zsh users). Replaces an outdated block; never
# adds a second one. Markers match also in a CRLF file (Windows editors).
persist_env_block() {
  local label="$1" begin end body rc rcs=() new_profile=""
  shift
  begin="# >>> snowconvertai $label >>>"
  end="# <<< snowconvertai $label <<<"
  body="$(printf '%s\n' "$@")"

  # A login shell reads only the first of these files that exists.
  for rc in "$HOME/.bash_profile" "$HOME/.bash_login" "$HOME/.profile"; do
    if [ -f "$rc" ]; then rcs+=("$rc"); break; fi
  done
  if [ ${#rcs[@]} -eq 0 ]; then new_profile="$HOME/.bash_profile"; rcs+=("$new_profile"); fi
  rcs+=("$HOME/.bashrc")
  # A zsh user gets ~/.zshrc also when it does not exist yet.
  if [ -f "$HOME/.zshrc" ] || [[ "${SHELL:-}" == */zsh ]]; then rcs+=("$HOME/.zshrc"); fi

  # A new ~/.bash_profile hides ~/.bashrc from login shells (Git Bash starts
  # one), so it reads ~/.bashrc first, as Git Bash's own generated one does.
  if [ -n "$new_profile" ]; then
    printf '%s\n' '# Added by snowconvertai: a login shell reads only this file, so read ~/.bashrc too.' \
      'if [ -f ~/.bashrc ]; then . ~/.bashrc; fi' >> "$new_profile" || true
  fi

  for rc in "${rcs[@]}"; do
    if [ -f "$rc" ] && rc_has_line "$rc" "$begin"; then
      if [ "$(awk -v b="$begin" -v e="$end" '{ sub(/\r$/, "") } $0 == b { f = 1; next } $0 == e { f = 0; next } f' "$rc")" = "$body" ]; then
        continue
      fi
      # Without the end marker, removal would delete the rest of the file.
      if ! rc_has_line "$rc" "$end"; then
        warn "$rc has '$begin' but no '$end'. Fix the file; it was not changed."
        continue
      fi
      # Write in place with cat to keep the file's owner and permissions.
      awk -v b="$begin" -v e="$end" '{ l = $0; sub(/\r$/, "", l) } l == b { skip = 1; next } l == e { skip = 0; next } !skip' \
        "$rc" > "$rc.snowconvertai.tmp" && cat "$rc.snowconvertai.tmp" > "$rc"
      rm -f "$rc.snowconvertai.tmp"
    fi
    printf '\n%s\n%s\n%s\n' "$begin" "$body" "$end" >> "$rc" || continue
    info "Updated the '$label' block in $rc"
  done
}

# rc_has_line FILE LINE: FILE has LINE, with or without a trailing CR.
rc_has_line() {
  awk -v l="$2" '{ sub(/\r$/, "") } $0 == l { found = 1; exit } END { exit !found }' "$1"
}

# Point curl, git, and tools with their own CA list (Python requests, pip,
# botocore, Node.js, uv) at the fixed store, keeping user-set values. Outside WSL
# use C:/... paths so Windows programs can read them; Cygwin does not convert
# POSIX paths in variables for them.
persist_ca_env() {
  local v store node lines=()
  [ -f "$OUT_DIR/windows-ca.pem" ] || return 0
  store="$STORE_BUNDLE"; node="$OUT_DIR/windows-ca.pem"
  if [ "$ENV_KIND" != wsl ]; then store="$(cygpath -m "$store")"; node="$(cygpath -m "$node")"; fi
  for v in "${CA_ENV_VARS[@]}"; do
    lines+=("[ -n \"\${$v:-}\" ] || export $v=\"$store\"")
  done
  lines+=("[ -n \"\${NODE_EXTRA_CA_CERTS:-}\" ] || export NODE_EXTRA_CA_CERTS=\"$node\"")
  lines+=('[ -n "${UV_SYSTEM_CERTS:-}" ] || export UV_SYSTEM_CERTS=true')
  persist_env_block ca "${lines[@]}"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
  local check_only=false host status fixed=0 still=false failing=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --check)     check_only=true; shift ;;
      --quiet)     QUIET=true; shift ;;
      --cert-file) CERT_FILES+=("${2:?--cert-file needs a path}"); shift 2 ;;
      *) die "Usage: $PROG [--check] [--quiet] [--cert-file PATH]..." ;;
    esac
  done
  command -v openssl >/dev/null 2>&1 || die "openssl is required."
  command -v timeout >/dev/null 2>&1 || timeout() { shift; "$@"; }

  OUT_DIR="$HOME/.config/trust-windows-ca"
  detect_env
  detect_store_bundle
  detect_proxy
  WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT

  info "== 1. Checking TLS trust ($ENV_KIND)"
  if check_trust; then
    $check_only || persist_ca_env
    info ""; info "No certificate problems found."
    return 0
  fi
  # Only a CA variable is wrong; no new CA is needed, so warn and do not fail.
  if [ ! -s "$WORK/failing" ]; then
    $check_only || persist_ca_env
    info ""; advise_env_overrides
    return 0
  fi
  mapfile -t failing < "$WORK/failing"

  info ""; info "== 2. Collecting the Windows trust store"
  collect_windows_ca
  cat "$STORE_BUNDLE" "$WORK/windows.pem" > "$WORK/combined.pem"
  while IFS=$'\t' read -r host status; do
    info_row "$host" "$status with the Windows trust store"
    if [ "$status" = ok ]; then fixed=$(( fixed + 1 )); fi
  done < <(verify_hosts "$WORK/combined.pem" "${failing[@]}")
  if [ "$fixed" -eq 0 ]; then
    warn "Windows does not trust these hosts either; ask IT for the TLS-inspection root CA."
    return 1
  fi
  not_in "$STORE_BUNDLE" "$WORK/windows.pem" > "$WORK/new.pem"
  info "Windows trusts $(count_certs "$WORK/windows.pem") CA certificates; $(count_certs "$WORK/new.pem") are missing here, including:"
  if ! $QUIET; then grep -m 15 '^# [A-Z]*=' "$WORK/new.pem" | sed 's/^# /  - /' || true; fi
  if $check_only; then info ""; info "Run without --check to add them."; advise_env_overrides; return 1; fi

  info ""; info "== 3. Adding the Windows trust store to the $ENV_KIND CA store"
  if [ "$ENV_KIND" = gitbash ]; then add_gitbash; else add_anchors; fi
  mkdir -p "$OUT_DIR"
  cp "$WORK/windows.pem" "$OUT_DIR/windows-ca.pem"
  persist_ca_env

  info ""; info "== 4. Verifying against $STORE_BUNDLE"
  while IFS=$'\t' read -r host status; do
    info_row "$host" "$status"
    if [ "$status" != ok ]; then still=true; fi
  done < <(verify_hosts "$STORE_BUNDLE" "${failing[@]}")
  info ""
  info "Open a new terminal to load the CA variables."
  advise_env_overrides
  if $still; then warn "Some hosts still fail verification."; return 1; fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  set -euo pipefail
  main "$@"
fi
