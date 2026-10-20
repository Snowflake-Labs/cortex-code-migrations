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

# First install when git clone / cortex plugin install fails with
# "RPC failed; HTTP 403 curl 22". The GitHub archive GET still works.
# Same archive URL as Install-PluginFromArchive in hooks/install-dependencies.ps1.
#
#   irm https://raw.githubusercontent.com/Snowflake-Labs/cortex-code-migrations/main/plugin/install.ps1 | iex
#   $env:PLUGIN_REF = "preview"; irm .../install.ps1 | iex

$ErrorActionPreference = "Stop"
$PluginRepo = "Snowflake-Labs/cortex-code-migrations"
$PluginName = "snowflake-migration"
$ref = if ($env:PLUGIN_REF) { $env:PLUGIN_REF } elseif ($args.Count -gt 0) { $args[0] } else { "main" }
if ($ref -notmatch '^[A-Za-z0-9._/-]+$') { throw "bad plugin ref '$ref'" }
if ($ref -match '^v[0-9]') {
    $url = "https://github.com/$PluginRepo/archive/refs/tags/$ref.zip"
} else {
    $url = "https://github.com/$PluginRepo/archive/refs/heads/$ref.zip"
}

$dest = Join-Path $env:USERPROFILE ".snowflake\cortex\plugins\$PluginName"
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("aim-plugin-" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    Write-Host "Downloading $PluginName ($ref) from $url"
    $zip = Join-Path $tmp "plugin.zip"
    Invoke-WebRequest -Uri $url -OutFile $zip -TimeoutSec 60 -UseBasicParsing
    $extract = Join-Path $tmp "extract"
    Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force
    $versionFile = Get-ChildItem -Path $extract -Filter VERSION -Recurse |
        Where-Object { $_.Directory.Name -eq "plugin" } |
        Select-Object -First 1
    if (-not $versionFile) { throw "archive has no plugin/VERSION" }
    if (Test-Path -LiteralPath $dest) { Remove-Item -LiteralPath $dest -Recurse -Force }
    New-Item -ItemType Directory -Path $dest | Out-Null
    Copy-Item -Path (Join-Path $versionFile.Directory.FullName "*") -Destination $dest -Recurse -Force

    $registry = Join-Path $env:USERPROFILE ".snowflake\cortex\plugins\registry.json"
    $source = "github:${PluginRepo}/plugin#$ref"
    $registryDir = Split-Path -Parent $registry
    if (-not (Test-Path -LiteralPath $registryDir)) { New-Item -ItemType Directory -Path $registryDir | Out-Null }
    if (-not (Test-Path -LiteralPath $registry)) {
        "{`"plugins`":{`"$PluginName`":{`"source`":`"$source`"}}}" | Set-Content -LiteralPath $registry -Encoding utf8
    } else {
        $data = Get-Content -LiteralPath $registry -Raw | ConvertFrom-Json
        if (-not $data.plugins) { $data | Add-Member -NotePropertyName plugins -NotePropertyValue ([pscustomobject]@{}) }
        $entry = $data.plugins.$PluginName
        if (-not $entry) {
            $data.plugins | Add-Member -NotePropertyName $PluginName -NotePropertyValue ([pscustomobject]@{ source = $source })
        } else {
            $entry.source = $source
        }
        $data | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $registry -Encoding utf8
    }
    $version = (Get-Content -LiteralPath (Join-Path $dest "VERSION") -Raw).Trim()
    Write-Host "Installed $PluginName $version at $dest"
    Write-Host "Start Cortex Code. The session-start hook installs scai."
} finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
