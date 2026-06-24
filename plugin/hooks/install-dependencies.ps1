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

# SessionStart hook -- installs system dependencies (uv, scai CLI) on Windows.
# The migration MCP server binary ships inside the scai CLI (launched via 'scai mcp').

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PluginRoot = Split-Path -Parent $ScriptDir
$LogDir = Join-Path $PluginRoot "logs"
$LogFile = Join-Path $LogDir "install-dependencies.log"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

$HookStart = Get-Date

function Log {
    param([string]$Message)
    $elapsed = [math]::Round(((Get-Date) - $HookStart).TotalSeconds)
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [${elapsed}s] $Message"
    $line | Tee-Object -FilePath $LogFile -Append | Write-Host
}

$VersionFile = Join-Path $PluginRoot "VERSION"
if (!(Test-Path $VersionFile)) {
    Log "ERROR: plugin/VERSION not found"
    exit 1
}
$Version = (Get-Content $VersionFile -Raw).Trim()

if (-not $env:SCAI_CHANNEL) { $env:SCAI_CHANNEL = "preview" }

Log "SessionStart hook running (v$Version, plugin root: $PluginRoot)"
$cortexCh = if ($env:CORTEX_CHANNEL) { $env:CORTEX_CHANNEL } else { "(not set)" }
Log "SCAI_CHANNEL=$($env:SCAI_CHANNEL), CORTEX_CHANNEL=$cortexCh"

# System dependencies

# uv
if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    Log "uv already installed"
} else {
    $start = Get-Date
    Log "Installing uv..."
    irm https://astral.sh/uv/install.ps1 | iex
    $elapsed = [math]::Round(((Get-Date) - $start).TotalSeconds)
    Log "Installed uv (${elapsed}s)"
}

# Remove legacy brew-based snowconvert-ai casks (replaced by scai CLI)
if (Get-Command "brew" -ErrorAction SilentlyContinue) {
    $legacyCasks = @("snowconvert-ai", "snowconvert-ai-pr", "snowconvert-ai-dev")
    $installedCasks = (brew list --cask 2>$null) -split "`n"
    foreach ($cask in $legacyCasks) {
        if ($installedCasks -contains $cask) {
            $start = Get-Date
            Log "Uninstalling legacy cask $cask..."
            try {
                brew uninstall --cask $cask 2>&1 | ForEach-Object { Log $_ }
            } catch {
                Log "Failed to uninstall ${cask}: $_"
            }
            $elapsed = [math]::Round(((Get-Date) - $start).TotalSeconds)
            Log "Uninstalled $cask (${elapsed}s)"
        }
    }
}

# scai CLI (bundles the migration MCP server binary)
$start = Get-Date
if (Get-Command "scai" -ErrorAction SilentlyContinue) {
    Log "scai already installed, running explicit update..."
    try {
        scai update 2>&1 | ForEach-Object { Log $_ }
    } catch {
        Log "scai update failed: $_"
    }
    $elapsed = [math]::Round(((Get-Date) - $start).TotalSeconds)
    Log "scai up to date (${elapsed}s)"
} else {
    Log "Installing scai CLI..."
    try {
        irm https://snowconvert.snowflake.com/storage/windows/prod/cli/install.ps1 | iex
        $elapsed = [math]::Round(((Get-Date) - $start).TotalSeconds)
        Log "Installed scai CLI (${elapsed}s)"
    } catch {
        Log "WARNING: scai CLI installation failed: $_"
    }
}

# Disable scai auto-update (we manage updates explicitly above)
$scaiSettings = Join-Path $env:USERPROFILE ".snowflake\scai\settings.json"
$scaiSettingsDir = Split-Path -Parent $scaiSettings
if (!(Test-Path $scaiSettingsDir)) {
    New-Item -ItemType Directory -Path $scaiSettingsDir -Force | Out-Null
}
if (!(Test-Path $scaiSettings)) {
    '{}' | Set-Content $scaiSettings
}
$content = Get-Content $scaiSettings -Raw
if ($content -match '"autoUpdate"') {
    $content = $content -replace '"autoUpdate"\s*:\s*true', '"autoUpdate": false'
} else {
    $content = $content -replace '^\{', '{"autoUpdate": false,'
}
$content | Set-Content $scaiSettings

Log "SessionStart hook complete (total: $([math]::Round(((Get-Date) - $HookStart).TotalSeconds))s)"
