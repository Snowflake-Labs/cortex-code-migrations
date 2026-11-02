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

# Runs informatica_assessment_analyzer without requiring `uv` on PATH.
# Forces UTF-8. Skips the Windows Store python stub.

set -euo pipefail

# cd and pwd are shell builtins, so this still works when PATH has no dirname.
SCRIPT_DIR="$(cd "${BASH_SOURCE[0]%/*}" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOME_DIR="${USERPROFILE:-$HOME}"

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
if [ -n "${PYTHONPATH:-}" ]; then
  export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"
else
  export PYTHONPATH="${SCRIPT_DIR}"
fi

fail() {
  echo "Informatica analyzer cannot start. No Python 3.11+ is available. The Windows Store python stub does not count, and uv is not installed." >&2
  echo "Do not write a substitute HTML report and do not open the assessment JSON with another program." >&2
  exit 1
}

is_store_stub() {
  case "$1" in
    *[\\/]WindowsApps[\\/]*) return 0 ;;
    *) return 1 ;;
  esac
}

python_is_311() {
  local exe="$1"
  shift
  if is_store_stub "$exe"; then
    return 1
  fi
  "$exe" "$@" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
}

run_python() {
  local exe="$1"
  shift
  exec "$exe" "$@" -X utf8 -m informatica_assessment_analyzer "${ANALYZER_ARGS[@]}"
}

ANALYZER_ARGS=("$@")

shopt -s nullglob
for name in py python python3; do
  IFS=':' read -r -a path_dirs <<< "${PATH:-}"
  for dir in "${path_dirs[@]}"; do
    [ -n "$dir" ] || continue
    for candidate in "$dir/$name" "$dir/$name.exe"; do
      [ -x "$candidate" ] || continue
      if is_store_stub "$candidate"; then
        continue
      fi
      prefix=()
      case "$name" in
        py) prefix=(-3) ;;
      esac
      if python_is_311 "$candidate" "${prefix[@]}"; then
        run_python "$candidate" "${prefix[@]}"
      fi
    done
  done
done

for candidate in \
  "$HOME_DIR/.snowflake/scai/python/venv/bin/python" \
  "$HOME_DIR/.snowflake/scai/python/venv/Scripts/python.exe" \
  "${SNOWFLAKE_HOME:-}/scai/python/venv/bin/python"
do
  [ -n "$candidate" ] && [ -x "$candidate" ] || continue
  if python_is_311 "$candidate"; then
    run_python "$candidate"
  fi
done

search_roots=()
[ -n "${LOCALAPPDATA:-}" ] && search_roots+=("$LOCALAPPDATA/snowflake-cortex" "$LOCALAPPDATA/cortex")
search_roots+=("$HOME_DIR/.snowflake/cortex")
for root in "${search_roots[@]}"; do
  [ -d "$root" ] || continue
  found="$(find "$root" -maxdepth 6 \( -path '*reladiff-runtime*' -name 'python' -o -path '*reladiff-runtime*' -name 'python.exe' \) -print -quit 2>/dev/null || true)"
  if [ -n "$found" ] && [ -x "$found" ] && python_is_311 "$found"; then
    run_python "$found"
  fi
done

uv=""
if command -v uv >/dev/null 2>&1; then
  uv="$(command -v uv)"
fi
if [ -z "$uv" ]; then
  for rel in .local/bin/uv .local/bin/uv.exe .cargo/bin/uv .cargo/bin/uv.exe; do
    if [ -x "$HOME_DIR/$rel" ]; then
      uv="$HOME_DIR/$rel"
      break
    fi
  done
fi
if [ -n "$uv" ]; then
  exec "$uv" run --project "$SKILL_ROOT" python -X utf8 -m informatica_assessment_analyzer "${ANALYZER_ARGS[@]}"
fi

fail
