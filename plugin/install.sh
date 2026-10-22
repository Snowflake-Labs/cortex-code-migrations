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

# First install when `git clone` / `cortex plugin install` fails with
# "RPC failed; HTTP 403 curl 22". The GitHub archive GET still works.
# Same archive URL as install_plugin_from_archive in hooks/install-dependencies.sh.
#
#   curl -fsSL https://raw.githubusercontent.com/Snowflake-Labs/cortex-code-migrations/main/plugin/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/Snowflake-Labs/cortex-code-migrations/main/plugin/install.sh | bash -s -- preview

set -euo pipefail

PLUGIN_REPO="Snowflake-Labs/cortex-code-migrations"
PLUGIN_NAME="snowflake-migration"
ref="${1:-main}"
case "$ref" in
  *[!A-Za-z0-9._/-]*) echo "ERROR: bad plugin ref '$ref'" >&2; exit 1 ;;
esac
case "$ref" in
  v[0-9]*) url="https://github.com/$PLUGIN_REPO/archive/refs/tags/${ref}.zip" ;;
  *) url="https://github.com/$PLUGIN_REPO/archive/refs/heads/${ref}.zip" ;;
esac

dest="$HOME/.snowflake/cortex/plugins/$PLUGIN_NAME"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "Downloading $PLUGIN_NAME ($ref) from $url"
curl -fsSL --max-time 60 "$url" > "$tmp/plugin.zip"
unzip -q "$tmp/plugin.zip" -d "$tmp/extract"

src_dir=""
for version_file in "$tmp/extract"/*/plugin/VERSION; do
  if [ -f "$version_file" ]; then src_dir="$(dirname "$version_file")"; break; fi
done
if [ -z "$src_dir" ]; then
  echo "ERROR: archive has no plugin/VERSION" >&2
  exit 1
fi

rm -rf "$dest"
mkdir -p "$dest"
cp -R "$src_dir"/. "$dest"/

registry="$HOME/.snowflake/cortex/plugins/registry.json"
source="github:${PLUGIN_REPO}/plugin#${ref}"
mkdir -p "$(dirname "$registry")"
if [ ! -f "$registry" ]; then
  printf '%s\n' "{\"plugins\":{\"${PLUGIN_NAME}\":{\"source\":\"${source}\"}}}" > "$registry"
elif command -v python3 >/dev/null 2>&1; then
  python3 - "$registry" "$PLUGIN_NAME" "$source" <<'PY'
import json, sys
path, name, source = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
if not isinstance(data, dict):
    data = {}
plugins = data.setdefault("plugins", {})
if not isinstance(plugins, dict):
    plugins = {}
    data["plugins"] = plugins
entry = plugins.setdefault(name, {})
if not isinstance(entry, dict):
    entry = {}
    plugins[name] = entry
entry["source"] = source
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
else
  echo "WARNING: $registry exists and python3 is missing; plugin files installed, registry left unchanged" >&2
fi

echo "Installed $PLUGIN_NAME $(tr -d '[:space:]' < "$dest/VERSION") at $dest"
echo "Start Cortex Code. The session-start hook installs scai."
