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

# PATH inherited from the parent process (the Cortex Code app). Capture it before
# this hook modifies $env:PATH, so we can tell whether the app can resolve `scai`.
# The app's environment block is fixed at its launch: a registry PATH write does
# not reach it, so a newly installed `scai` stays invisible to the MCP server
# until the user restarts the application. See the restart warning below.
$InheritedPath = $env:PATH

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

if (-not $env:SCAI_CHANNEL) { $env:SCAI_CHANNEL = "stable" }

# Disable scai auto-update for this session only (we manage updates below).
# Not persisted, so the user's global scai config is untouched; set only if unset.
if (-not $env:SCAI_AUTO_UPDATE) { $env:SCAI_AUTO_UPDATE = "false" }

Log "SessionStart hook running (v$Version, plugin root: $PluginRoot)"
$cortexCh = if ($env:CORTEX_CHANNEL) { $env:CORTEX_CHANNEL } else { "(not set)" }
Log "SCAI_CHANNEL=$($env:SCAI_CHANNEL), CORTEX_CHANNEL=$cortexCh"

# Optional runtime override (opt-in): pin a specific scai version via the shared
# config file. Absent config = default behavior (update to the channel's latest).
$ScaiVersionPin = ""
$MigrationConfig = Join-Path $env:USERPROFILE ".snowflake\migration-plugin\config.json"
if (Test-Path $MigrationConfig) {
    try {
        $cfg = Get-Content $MigrationConfig -Raw | ConvertFrom-Json
        $v = $cfg.scai.version
        if ($v -is [string] -and $v) {
            $ScaiVersionPin = $v
            Log "Config pins scai.version=$ScaiVersionPin"
        }
    } catch {
        Log "WARNING: could not parse $MigrationConfig - ignoring, using default scai version"
    }
}

# System dependencies

# uv's bundled certs fail behind TLS-intercepting proxies (e.g. ZScaler); use the
# OS trust store instead. Persisted for future sessions; set only if unset.
if (-not $env:UV_SYSTEM_CERTS) {
    $env:UV_SYSTEM_CERTS = "true"
    [Environment]::SetEnvironmentVariable("UV_SYSTEM_CERTS", "true", "User")
}

# uv -- tools invoke bare `uv`, so ensure a callable `uv` lands on PATH.
# Install in isolation (astral standalone, else pipx).
function Add-UserPath {
    param([string]$Dir)
    if (-not $Dir -or -not (Test-Path $Dir)) { return }
    $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    if (($userPath -split ';') -inotcontains $Dir) {
        [Environment]::SetEnvironmentVariable("PATH", "$Dir;$userPath", "User")
    }
    if (($env:PATH -split ';') -inotcontains $Dir) { $env:PATH = "$Dir;$env:PATH" }
}

$uvLocalBin = Join-Path $env:USERPROFILE ".local\bin"

# 1. Standalone installer (astral default; installs to %USERPROFILE%\.local\bin).
# Astral's install.ps1 uses `exit 1` on failure. iex would kill this hook and
# skip the pipx fallback, so run it as a child. UseBasicParsing + TimeoutSec
# avoid the PS 5.1 IE-engine hang on the script fetch. Success means a callable
# `uv`: the installer can exit 1 after uv.exe is already in place (a failed
# receipt or registry write), and that uv is usable.
function Install-UvStandalone {
    Log "Installing uv (standalone installer)..."
    $uvInstallerPs1 = Join-Path ([IO.Path]::GetTempPath()) "uv-official-install-$PID.ps1"
    try {
        Invoke-WebRequest -Uri "https://astral.sh/uv/install.ps1" -OutFile $uvInstallerPs1 -TimeoutSec 60 -UseBasicParsing -ErrorAction Stop
        $hostExe = (Get-Process -Id $PID).Path
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $uvExit = $null
        try {
            & $hostExe -NoProfile -ExecutionPolicy Bypass -File $uvInstallerPs1 *>> $LogFile
            $uvExit = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $prevEAP
        }
        Add-UserPath $uvLocalBin
        if (Get-Command "uv" -ErrorAction SilentlyContinue) {
            Log "Installed uv (standalone, installer exit $uvExit)"
            return $true
        }
        Log "Standalone uv installer did not make uv callable (exit $uvExit)"
    } catch {
        Log "Standalone uv installer failed: $_"
    } finally {
        Remove-Item $uvInstallerPs1 -Force -ErrorAction SilentlyContinue
    }
    return $false
}

if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    Log "uv already installed"
} else {
    $start = Get-Date
    $uvReady = Install-UvStandalone

    # 2. pipx (isolated, astral-recommended). Bootstrap pipx via pip --user if absent.
    if (-not $uvReady -and (Get-Command python -ErrorAction SilentlyContinue)) {
        # pip/pipx output goes to the log FILE (*>>), not the console, to keep
        # SessionStart quiet. 'Continue' stops pip stderr from becoming a
        # terminating error while $ErrorActionPreference is 'Stop'.
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            if (-not (Get-Command pipx -ErrorAction SilentlyContinue)) {
                # Behind TLS-intercepting corporate proxies (e.g. ZScaler) pip cannot
                # verify PyPI certs yet, so use --trusted-host to fetch pip-system-certs,
                # which then makes pip trust the OS cert store for later installs.
                $pipTrusted = @(
                    "--trusted-host", "pypi.org",
                    "--trusted-host", "pypi.python.org",
                    "--trusted-host", "files.pythonhosted.org"
                )
                Log "Installing pip-system-certs (trusted-host bootstrap)..."
                python -m pip install --user pip -U @pipTrusted --quiet *>> $LogFile
                python -m pip install --user pip_system_certs -U @pipTrusted --quiet *>> $LogFile
                Log "Bootstrapping pipx (pip install --user pipx)..."
                python -m pip install --user pipx --quiet *>> $LogFile
            }
            python -m pipx ensurepath *>> $LogFile
            python -m pipx install uv *>> $LogFile
            Add-UserPath $uvLocalBin
            if (Get-Command "uv" -ErrorAction SilentlyContinue) { $uvReady = $true; Log "Installed uv (pipx)" }
        } catch {
            Log "pipx install uv failed: $_"
        } finally {
            $ErrorActionPreference = $prevEAP
        }
    }

    $elapsed = [math]::Round(((Get-Date) - $start).TotalSeconds)
    if ($uvReady) {
        Log "uv ready (${elapsed}s)"
    } else {
        Log "WARNING: could not make uv callable on PATH after ${elapsed}s"
    }
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

# scai CLI (bundles the migration MCP server binary).
# Centralized storage URL map -- single source of truth for host, OS segment,
# and channel-to-segment mapping (stable=prod, preview=beta, dev=dev).
$ScaiStorageBase     = "https://snowconvert.snowflake.com/storage"
$ScaiChannelSegments = @{ stable = "prod"; preview = "beta"; dev = "dev" }

function Get-ScaiOsSegment {
    # Match install.ps1: OS arch, not process arch (WoW64 / x64-on-ARM).
    $arch = ""
    if ($env:PROCESSOR_IDENTIFIER -match 'ARM|AArch64') { $arch = "ARM64" }
    if (-not $arch) { $arch = $env:PROCESSOR_ARCHITEW6432 }
    if (-not $arch) { $arch = $env:PROCESSOR_ARCHITECTURE }
    if ($arch -match 'ARM64') { return "windows_arm64" }
    return "windows"
}

# Archives + latest-archive.json are per-arch. install.ps1 is published only
# under windows/ (it self-detects and then fetches the arch-specific archive).
$ScaiOsSegment          = Get-ScaiOsSegment
$ScaiInstallerOsSegment = "windows"

function Get-ScaiCliBaseUrl {
    param(
        [string]$Channel,
        [string]$OsSegment = $ScaiOsSegment
    )
    $seg = $ScaiChannelSegments[$Channel]
    if (-not $seg) { $seg = "prod" }
    "$ScaiStorageBase/$OsSegment/$seg/cli"
}

# Official user-local layout (matches install.ps1): versioned dirs + a bin shim.
$scaiRoot   = Join-Path $env:LOCALAPPDATA "snowconvertai"
$scaiBinDir = Join-Path $scaiRoot "bin"
$scaiShim   = Join-Path $scaiBinDir "scai.cmd"

function Get-ScaiActiveVersion {
    # Active version = the version dir the bin shim currently points at, if any.
    if (-not (Test-Path $scaiShim)) { return $null }
    $shimText = Get-Content $scaiShim -Raw -ErrorAction SilentlyContinue
    if ($shimText -match '\\snowconvertai\\([^\\]+)\\orchestrator\\scai\.exe') {
        return $Matches[1]
    }
    return $null
}

function Test-ScaiVersionInstalled {
    param([string]$Version)
    if (-not $Version) { return $false }
    Test-Path (Join-Path (Join-Path $scaiRoot $Version) "orchestrator\scai.exe")
}

function Set-ScaiShim {
    # (Re)point the bin shim at a specific installed version and ensure PATH.
    param([string]$Version)
    $exe = Join-Path (Join-Path $scaiRoot $Version) "orchestrator\scai.exe"
    New-Item -ItemType Directory -Path $scaiBinDir -Force | Out-Null
    "@echo off`r`n`"$exe`" %*" | Set-Content -Path $scaiShim -Encoding ASCII
    Add-UserPath $scaiBinDir
}

function Test-ScaiReachedTarget {
    # True only when the shim points at $Target. An older leftover install
    # must not count as success.
    param([string]$Target)
    if (-not $Target) { return $false }
    return (Get-ScaiActiveVersion) -eq $Target
}

$start         = Get-Date
$base          = Get-ScaiCliBaseUrl $env:SCAI_CHANNEL
$installerBase = Get-ScaiCliBaseUrl $env:SCAI_CHANNEL $ScaiInstallerOsSegment

# Resolve the channel's latest version from the small metadata file, so we can
# install or update WITHOUT relying on `scai update` (whose update URL is broken
# on some platforms in the shipped build). The official install.ps1 is itself a
# full updater, so we drive it behind this active-pointer check.
$latest = $null
$meta   = $null
try {
    $meta   = Invoke-RestMethod -Uri "$base/latest-archive.json" -TimeoutSec 30 -UseBasicParsing -ErrorAction Stop
    $latest = $meta.version
} catch {
    Log "Could not fetch scai version metadata from ${base}: $_"
}

$activeVersion = Get-ScaiActiveVersion

# Target version: an explicit config pin wins over the channel's latest.
$scaiTarget = if ($ScaiVersionPin) { $ScaiVersionPin } else { $latest }

if ($scaiTarget -and ($activeVersion -eq $scaiTarget)) {
    # Already on the target version -- ensure PATH only, no download.
    Add-UserPath $scaiBinDir
    Log "scai up to date (channel=$($env:SCAI_CHANNEL), v$scaiTarget) ($([math]::Round(((Get-Date) - $start).TotalSeconds))s)"
} elseif ($scaiTarget -and (Test-ScaiVersionInstalled $scaiTarget)) {
    # Target already on disk but launcher stale/missing -- re-point only, no download.
    Set-ScaiShim $scaiTarget
    Log "scai relinked to v$scaiTarget (channel=$($env:SCAI_CHANNEL)) ($([math]::Round(((Get-Date) - $start).TotalSeconds))s)"
} else {
    # Install/update needed: official channel-aware installer first, then manual fallback.
    if ($ScaiVersionPin) {
        Log "Installing scai CLI (pinned v$ScaiVersionPin, channel=$($env:SCAI_CHANNEL))..."
        # install.ps1 honors SCAI_VERSION to install a specific version.
        $env:SCAI_VERSION = $ScaiVersionPin
    } elseif ($latest) {
        Log "Installing scai CLI v$latest (channel=$($env:SCAI_CHANNEL))..."
    } else {
        Log "Installing scai CLI (channel=$($env:SCAI_CHANNEL))..."
    }

    $scaiInstalled = $false
    $installerPs1  = Join-Path ([IO.Path]::GetTempPath()) "scai-official-install-$PID.ps1"
    try {
        # install.ps1 uses `exit 1` on failure. iex would kill this hook and
        # skip the zip fallback, so run it as a child and inspect $LASTEXITCODE.
        Invoke-WebRequest -Uri "$installerBase/install.ps1" -OutFile $installerPs1 -TimeoutSec 60 -UseBasicParsing -ErrorAction Stop
        $hostExe = (Get-Process -Id $PID).Path
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $installerOutput = & $hostExe -NoProfile -ExecutionPolicy Bypass -File $installerPs1 2>&1
            $exitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $prevEAP
        }
        foreach ($line in @($installerOutput)) {
            if ($line) { Log "$line" }
        }
        Add-UserPath $scaiBinDir
        if ($null -eq $exitCode) { $exitCode = 1 }
        if ($exitCode -eq 0 -and (Test-ScaiReachedTarget $scaiTarget)) {
            $scaiInstalled = $true
        } elseif ($exitCode -eq 0 -and -not $scaiTarget -and (Get-ScaiActiveVersion)) {
            $scaiInstalled = $true
        } else {
            Log "Official installer did not reach target (exit $exitCode, active=$(Get-ScaiActiveVersion), target=$scaiTarget) - trying manual download..."
        }
    } catch {
        Log "Official installer failed: $_ - trying manual download..."
    } finally {
        Remove-Item $installerPs1 -Force -ErrorAction SilentlyContinue
    }

    # Fallback: manual download + checksum verify + versioned extraction.
    # The metadata only describes the channel's latest archive, so this cannot
    # serve a pinned version -- a pin relies on the official installer.
    if (-not $scaiInstalled -and $ScaiVersionPin -and ($ScaiVersionPin -ne $latest)) {
        Log "WARNING: no manual fallback for pinned v$ScaiVersionPin (metadata covers only v$latest)"
    } elseif (-not $scaiInstalled) {
        try {
            if (-not $meta) {
                $meta   = Invoke-RestMethod -Uri "$base/latest-archive.json" -TimeoutSec 30 -UseBasicParsing -ErrorAction Stop
                $latest = $meta.version
            }
            if (-not $scaiTarget -and $latest) { $scaiTarget = $latest }
            $zipUrl     = "$base/$($meta.archive)"
            $tempZip    = Join-Path ([IO.Path]::GetTempPath()) "scai-cli-$latest.zip"
            $versionDir = Join-Path $scaiRoot $latest

            Log "Downloading scai CLI from $zipUrl..."
            # Suppress progress only on Windows PowerShell 5.1, where progress
            # rendering can throttle large downloads. PowerShell 7+ keeps progress.
            $previousProgressPreference = $ProgressPreference
            if ($PSVersionTable.PSEdition -eq 'Desktop' -or $PSVersionTable.PSVersion.Major -lt 6) {
                $ProgressPreference = 'SilentlyContinue'
            }
            try {
                Invoke-WebRequest -Uri $zipUrl -OutFile $tempZip -TimeoutSec 300 -UseBasicParsing -ErrorAction Stop
            } finally {
                $ProgressPreference = $previousProgressPreference
            }

            # Verify the SHA256 from the metadata before extracting.
            if ($meta.sha256) {
                $actualHash = (Get-FileHash -Path $tempZip -Algorithm SHA256).Hash.ToLower()
                if ($actualHash -ne $meta.sha256.ToLower()) {
                    throw "Checksum mismatch for scai archive (expected $($meta.sha256), got $actualHash)"
                }
            }

            Log "Extracting scai CLI v$latest (this may take a few minutes)..."
            # Replace only this version's dir (matches install.ps1 / develop retention);
            # never remove sibling versions or the whole install root.
            if (Test-Path $versionDir) { Remove-Item -Path $versionDir -Recurse -Force -ErrorAction SilentlyContinue }
            New-Item -ItemType Directory -Path $versionDir -Force | Out-Null
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            [System.IO.Compression.ZipFile]::ExtractToDirectory($tempZip, $versionDir)
            Remove-Item $tempZip -Force -ErrorAction SilentlyContinue

            if (Test-ScaiVersionInstalled $latest) {
                Set-ScaiShim $latest
                $scaiInstalled = Test-ScaiReachedTarget $scaiTarget
                if (-not $scaiInstalled -and $latest -and ((Get-ScaiActiveVersion) -eq $latest)) {
                    $scaiInstalled = $true
                }
            }
        } catch {
            Log "WARNING: Manual scai CLI installation also failed: $_"
        }
    }

    $elapsed = [math]::Round(((Get-Date) - $start).TotalSeconds)
    if ($scaiInstalled) {
        Log "Installed scai CLI (${elapsed}s)"
    } else {
        Log "WARNING: scai CLI installation failed after ${elapsed}s"
    }
}

# Auto-update disabled via the session-scoped SCAI_AUTO_UPDATE env var set above.

# The MCP server is launched by the app as bare `scai`, which resolves against the
# PATH the app inherited at launch. If the scai bin dir is missing there, the MCP
# server cannot start, however healthy this install is. Only a full application
# restart reloads that PATH, so say so plainly.
if ((Get-ScaiActiveVersion) -and (($InheritedPath -split ';') -inotcontains $scaiBinDir)) {
    Log "ACTION REQUIRED: scai is installed at $scaiBinDir but that path was not"
    Log "ACTION REQUIRED: on this application's PATH when it started, so the"
    Log "ACTION REQUIRED: snowflake-migration MCP server cannot launch scai."
    Log "ACTION REQUIRED: Fully quit and relaunch Cortex Code (a new chat or"
    Log "ACTION REQUIRED: session is not enough) to pick up the updated PATH."
}

Log "SessionStart hook complete (total: $([math]::Round(((Get-Date) - $HookStart).TotalSeconds))s)"
