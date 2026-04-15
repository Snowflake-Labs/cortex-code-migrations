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

# SessionStart hook -- downloads the MCP server binary and installs system dependencies.
# Windows (PowerShell).

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

$arch = if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -eq [System.Runtime.InteropServices.Architecture]::Arm64) { "arm64" } else { "x64" }
$platform = "win-$arch"
$BlobBase = "https://sctoolsartifacts.z5.web.core.windows.net/linux/beta/plugins/bin"

if (-not $env:SCAI_CHANNEL) { $env:SCAI_CHANNEL = "preview" }

Log "SessionStart hook running (v$Version, $platform, plugin root: $PluginRoot)"
$cortexCh = if ($env:CORTEX_CHANNEL) { $env:CORTEX_CHANNEL } else { "(not set)" }
Log "SCAI_CHANNEL=$($env:SCAI_CHANNEL), CORTEX_CHANNEL=$cortexCh"

# -- MCP server binary ------------------------------------------------
$BinDir = Join-Path $PluginRoot "mcp-server\bin"
$ExePath = Join-Path $BinDir "migration-mcp-server.exe"
$CmdShim = Join-Path $BinDir "migration-mcp-server.cmd"
$VersionMarker = Join-Path $BinDir ".version"
$BinaryUrl = "${BlobBase}/migration-mcp-server-v${Version}-${platform}"

$NeedsDownload = $true
if ((Test-Path $ExePath) -and (Test-Path $VersionMarker)) {
    $InstalledVersion = (Get-Content $VersionMarker -Raw).Trim()
    if ($InstalledVersion -eq $Version) {
        $NeedsDownload = $false
        Log "MCP server binary up to date (v$Version)"
    } else {
        Log "MCP server binary outdated (v$InstalledVersion -> v$Version)"
    }
}

if ($NeedsDownload) {
    New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
    $start = Get-Date
    Log "Downloading MCP server binary ($platform, v$Version)..."
    try {
        Invoke-WebRequest -Uri $BinaryUrl -OutFile $ExePath -UseBasicParsing
        '@"%~dp0migration-mcp-server.exe" %*' | Out-File -FilePath $CmdShim -Encoding ascii -NoNewline
        $Version | Out-File -FilePath $VersionMarker -NoNewline
        $size = [math]::Round((Get-Item $ExePath).Length / 1MB, 1)
        Log "MCP server binary installed ($([math]::Round(((Get-Date) - $start).TotalSeconds))s, ${size}MB)"
    } catch {
        Log "Binary download failed - MCP server will be unavailable: $_"
    }
}

# -- Python dependencies (snowpark) -----------------------------------
$pyproject = Join-Path $PluginRoot "mcp-server\pyproject.toml"
$venvDir = Join-Path $PluginRoot "mcp-server\.venv"
if ((Test-Path $pyproject) -and !(Test-Path $venvDir) -and (Get-Command "uv" -ErrorAction SilentlyContinue)) {
    $start = Get-Date
    Log "Installing Python dependencies (snowpark)..."
    try {
        Push-Location (Join-Path $PluginRoot "mcp-server")
        uv sync --quiet 2>&1
        Pop-Location
        Log "Python dependencies installed ($([math]::Round(((Get-Date) - $start).TotalSeconds))s)"
    } catch {
        Pop-Location
        Log "uv sync failed (snowpark will be unavailable): $_"
    }
}

# -- System dependencies -----------------------------------------------

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

# scai CLI
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
