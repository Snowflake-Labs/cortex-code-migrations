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
# Also installs Git for Windows, and updates the plugin last.

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

# Disable scai auto-update for this session only (we manage updates below).
# Not persisted, so the user's global scai config is untouched; set only if unset.
if (-not $env:SCAI_AUTO_UPDATE) { $env:SCAI_AUTO_UPDATE = "false" }

Log "SessionStart hook running (v$Version, plugin root: $PluginRoot)"

$PluginName = "snowflake-migration"
$PluginRepo = "Snowflake-Labs/cortex-code-migrations"
$cortexHome = Join-Path $env:USERPROFILE ".snowflake\cortex"

# The git ref of the plugin's registry source, either form:
# github:<repo>/plugin#<ref> or https://github.com/<repo>/tree/<ref>/plugin.
# Empty when the source names no ref.
function Get-PluginRef {
    param([string]$RegistryText)
    $repo = [regex]::Escape($PluginRepo)
    if ($RegistryText -match "github:$repo/plugin#([A-Za-z0-9._/-]+)") { return $Matches[1] }
    if ($RegistryText -match "github\.com/$repo/tree/([A-Za-z0-9._/-]+)/plugin") { return $Matches[1] }
    return ""
}

# The plugin channel of a channel branch or a version tag; empty for an alpha
# branch. A source with no ref follows main.
function Get-RefChannel {
    param([string]$Ref)
    if (-not $Ref -or $Ref -eq 'main') { return 'stable' }
    if ($Ref -eq 'preview' -or $Ref -match '^v\d+\.\d+\.\d+-Pr\.') { return 'preview' }
    if ($Ref -match '^v\d+\.\d+\.\d+$') { return 'stable' }
    return ""
}

# The plugin branch of a channel. The plugin has no dev channel: with dev, scai
# uses dev and the plugin uses preview.
function Get-ChannelBranch {
    param([string]$Channel)
    switch ($Channel) { 'preview' { return 'preview' } 'dev' { return 'preview' } default { return 'main' } }
}

# One channel for scai and the plugin: the first set of SCAI_CHANNEL, the scai
# settings file, and the installed plugin source, else stable.
function Resolve-Channel {
    param([string]$EnvChannel, [string]$SettingsChannel, [string]$PluginChannel)
    $c = @($EnvChannel, $SettingsChannel, $PluginChannel, 'stable') | Where-Object { "$_".Trim() } | Select-Object -First 1
    $c = "$c".Trim().ToLowerInvariant()
    if ($c -in @('stable', 'preview', 'dev')) { return $c }
    Log "WARNING: unknown channel '$c' (expected stable, preview, or dev); using stable"
    return 'stable'
}

# A JSON file as an object, or $null when it is absent or cannot be parsed.
function Read-JsonFile {
    param([string]$Path, [string]$What)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try {
        return (Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json)
    } catch {
        Log "WARNING: could not parse $Path - ignoring it, using the default $What"
        return $null
    }
}

# Optional runtime override (opt-in): pin a specific scai or plugin version via the shared
# config file. Absent config = default behavior (update to the channel's latest).
# The channel is the one `scai settings set channel=` writes, at scai's path ($env:SNOWFLAKE_HOME
# when that directory exists). Intentional simplification: scai's other fallbacks apply only
# without ~/.snowflake, which Cortex needs.
$MigrationConfig = Join-Path $env:USERPROFILE ".snowflake\migration-plugin\config.json"
$snowflakeDir = Join-Path $env:USERPROFILE ".snowflake"
if ($env:SNOWFLAKE_HOME -and (Test-Path -LiteralPath $env:SNOWFLAKE_HOME -PathType Container)) { $snowflakeDir = $env:SNOWFLAKE_HOME }
$ScaiSettings = Join-Path $snowflakeDir "scai\settings.json"
$ScaiVersionPin = ""
$PluginVersionPin = ""
$cfg = Read-JsonFile $MigrationConfig "versions"
if ($cfg) {
    if ($cfg.scai.version -is [string] -and $cfg.scai.version) {
        $ScaiVersionPin = $cfg.scai.version
        Log "Config pins scai.version=$ScaiVersionPin"
    }
    # Only a plugin version counts (X.Y.Z or X.Y.Z-Pr.N), as in the bash hook:
    # anything else would build a tag URL that cannot exist and retry it every session.
    if ($cfg.plugin.version -is [string] -and $cfg.plugin.version -match '^\d+(\.\d+)*(-Pr\.\d+)?$') {
        $PluginVersionPin = $cfg.plugin.version
        Log "Config pins plugin.version=$PluginVersionPin"
    }
}
$scaiSettingsObj = Read-JsonFile $ScaiSettings "channel"
$SettingsChannel = if ($scaiSettingsObj -and $scaiSettingsObj.channel -is [string]) { $scaiSettingsObj.channel } else { "" }

$registryFile = Join-Path $cortexHome "plugins\registry.json"
$registryText = $null
if (Test-Path $registryFile) {
    try {
        $registryText = Get-Content $registryFile -Raw
        $null = $registryText | ConvertFrom-Json
    } catch {
        $registryText = $null
    }
}
# A plugin installed from a fork or a local path is left alone.
$pluginFromRepo = [bool]($registryText -and $registryText -match "`"$PluginName`"" -and $registryText -match [regex]::Escape($PluginRepo))
$PluginRef = Get-PluginRef $registryText
$pluginChannel = if ($pluginFromRepo) { Get-RefChannel $PluginRef } else { "" }
$env:SCAI_CHANNEL = Resolve-Channel $env:SCAI_CHANNEL $SettingsChannel $pluginChannel

$cortexCh = if ($env:CORTEX_CHANNEL) { $env:CORTEX_CHANNEL } else { "(not set)" }
Log "SCAI_CHANNEL=$($env:SCAI_CHANNEL), CORTEX_CHANNEL=$cortexCh"

# System dependencies

# uv's bundled certs fail behind TLS-intercepting proxies (e.g. ZScaler); use the
# OS trust store instead. Persisted for future sessions; set only if unset.
if (-not $env:UV_SYSTEM_CERTS) {
    $env:UV_SYSTEM_CERTS = "true"
    [Environment]::SetEnvironmentVariable("UV_SYSTEM_CERTS", "true", "User")
}

# uv -- tools invoke bare `uv`, so ensure a callable `uv` lands on PATH.
# Install with astral's standalone installer, from astral.sh, else the same
# installer from the GitHub release (the plugin already needs GitHub), else
# pipx (for a site that blocks both but mirrors PyPI).
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
# A hook started from a GUI app may lack .local\bin on PATH; reuse that uv.
if (-not (Get-Command "uv" -ErrorAction SilentlyContinue) -and (Test-Path (Join-Path $uvLocalBin "uv.exe"))) {
    Add-UserPath $uvLocalBin
}

# Standalone installer (installs to %USERPROFILE%\.local\bin and writes the
# receipt `uv self update` needs). Corporate proxies (e.g. ZScaler) can block
# astral.sh but allow GitHub, so the GitHub release copy is the second URL.
# Astral's installer uses `exit 1` on failure. iex would kill this hook and
# skip the next URL, so run it as a child. UseBasicParsing + TimeoutSec
# avoid the PS 5.1 IE-engine hang on the script fetch. Success means a callable
# `uv`: the installer can exit 1 after uv.exe is already in place (a failed
# receipt or registry write), and that uv is usable.
$UvInstallerUrls = @(
    "https://astral.sh/uv/install.ps1",
    "https://github.com/astral-sh/uv/releases/latest/download/uv-installer.ps1"
)
function Install-UvStandalone {
    param([string]$Url)
    $uvHost = ([uri]$Url).Host
    Log "Installing uv (standalone installer from $uvHost)..."
    $uvInstallerPs1 = Join-Path ([IO.Path]::GetTempPath()) "uv-official-install-$PID.ps1"
    try {
        Invoke-WebRequest -Uri $Url -OutFile $uvInstallerPs1 -TimeoutSec 60 -UseBasicParsing -ErrorAction Stop
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
            Log "Installed uv (standalone from $uvHost, installer exit $uvExit)"
            return $true
        }
        Log "Standalone uv installer from $uvHost did not make uv callable (exit $uvExit)"
    } catch {
        Log "Standalone uv installer from $uvHost failed: $_"
    } finally {
        Remove-Item $uvInstallerPs1 -Force -ErrorAction SilentlyContinue
    }
    return $false
}

# pipx (isolated, astral-recommended). Bootstrap pipx via pip --user if absent.
function Install-UvPipx {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) { return $false }
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
        if (Get-Command "uv" -ErrorAction SilentlyContinue) { Log "Installed uv (pipx)"; return $true }
        Log "pipx install uv did not make uv callable"
    } catch {
        Log "pipx install uv failed: $_"
    } finally {
        $ErrorActionPreference = $prevEAP
    }
    return $false
}

if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    Log "uv already installed"
} else {
    $start = Get-Date
    $uvReady = $false
    foreach ($uvInstallerUrl in $UvInstallerUrls) {
        if (Install-UvStandalone $uvInstallerUrl) { $uvReady = $true; break }
    }
    if (-not $uvReady) { $uvReady = Install-UvPipx }

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

# Stop-ProcessTree PROCESS: kill a process and its children (an installer's own
# setup process, which Kill() alone leaves running).
function Stop-ProcessTree {
    param($Process)
    try {
        $Process.Kill($true)  # .NET Core 3+ (PowerShell 7)
        return
    } catch { }
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & taskkill.exe /T /F /PID $Process.Id *> $null } catch { } finally { $ErrorActionPreference = $prevEAP }  # Windows PowerShell 5.1
    try { $Process.Kill() } catch { }
}

# Invoke-Child FILE ARGS TIMEOUTSEC [INPUT]: run FILE as a child process with
# INPUT as its stdin and its output appended to the log, and return its exit
# code. A child (an installer calling `exit 1`) cannot end the hook. Past the
# timeout the child and its children are killed, and this throws.
function Invoke-Child {
    param([string]$FilePath, [string[]]$ArgumentList, [int]$TimeoutSec, [string]$InputText = "")
    $tag = Join-Path ([IO.Path]::GetTempPath()) "install-dependencies-$PID-$([guid]::NewGuid().ToString('N'))"
    $in = "$tag.in"; $out = "$tag.out"; $err = "$tag.err"
    try {
        Set-Content -LiteralPath $in -Value $InputText -Encoding ASCII
        $startArgs = @{
            FilePath = $FilePath; PassThru = $true; NoNewWindow = $true
            RedirectStandardInput = $in; RedirectStandardOutput = $out; RedirectStandardError = $err
        }
        if ($ArgumentList) { $startArgs.ArgumentList = $ArgumentList }
        $proc = Start-Process @startArgs
        # Read the handle now, or PowerShell 5.1 reports no ExitCode.
        $null = $proc.Handle
        if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
            Stop-ProcessTree $proc
            throw "$(Split-Path -Leaf $FilePath) did not finish in $TimeoutSec s"
        }
        return $proc.ExitCode
    } finally {
        foreach ($f in @($out, $err)) {
            if (Test-Path -LiteralPath $f) { Get-Content -LiteralPath $f -ErrorAction SilentlyContinue | Add-Content -LiteralPath $LogFile -ErrorAction SilentlyContinue }
        }
        Remove-Item -LiteralPath $in, $out, $err -Force -ErrorAction SilentlyContinue
    }
}

# git -- the plugin update and the migration workflow need it. Only Git for
# Windows counts: cortex.exe cannot use a Cygwin or MSYS2 git, which may come
# first on PATH, so its install dirs are checked first.
$gitUserDir = Join-Path $env:LOCALAPPDATA "Programs\Git"
function Get-GitForWindowsCmdDir {
    $programFiles = if ($env:ProgramFiles) { $env:ProgramFiles } else { "C:\Program Files" }
    foreach ($base in @($gitUserDir, (Join-Path $programFiles "Git"))) {
        $cmdDir = Join-Path $base "cmd"
        if (Test-Path (Join-Path $cmdDir "git.exe")) { return $cmdDir }
    }
    $git = Get-Command "git.exe" -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($git) {
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try { $gitVersion = "$(& $git.Path --version 2>$null)" } finally { $ErrorActionPreference = $prevEAP }
        if ($gitVersion -like "*.windows.*") { return (Split-Path -Parent $git.Path) }
    }
    return $null
}

$gitCmdDir = Get-GitForWindowsCmdDir
if ($gitCmdDir) {
    Log "git already installed ($gitCmdDir)"
} else {
    $start = Get-Date
    Log "Git for Windows not found. Installing it per-user in $gitUserDir. This can take several minutes..."
    $gitArch = if ($ScaiOsSegment -eq "windows_arm64") { "arm64" } else { "64-bit" }
    $gitInstaller = Join-Path ([IO.Path]::GetTempPath()) "git-for-windows-$PID.exe"
    try {
        # GitHub's API rejects requests without a User-Agent.
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/git-for-windows/git/releases/latest" -Headers @{ "User-Agent" = "snowconvertai-installer" } -TimeoutSec 30 -UseBasicParsing -ErrorAction Stop
        $asset = @($release.assets) | Where-Object { $_.name -match "^Git-[0-9.]+-$([regex]::Escape($gitArch))\.exe$" } | Select-Object -First 1
        if (-not $asset) { throw "no Git-<version>-$gitArch.exe in the latest Git for Windows release" }
        $previousProgressPreference = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'
        try {
            Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $gitInstaller -TimeoutSec 900 -UseBasicParsing -ErrorAction Stop
        } finally {
            $ProgressPreference = $previousProgressPreference
        }
        # The user installer is per-user already (it rejects /CURRENTUSER).
        # CURLOption=WinSSL: git uses the Windows certificate store, so TLS
        # inspection (e.g. ZScaler) works as in the browser.
        $gitArgs = @("/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES", "/o:CURLOption=WinSSL", "/DIR=`"$gitUserDir`"")
        $gitExit = Invoke-Child $gitInstaller $gitArgs 900
        if ($gitExit -ne 0) { Log "Git installer exit code $gitExit" }
    } catch {
        Log "WARNING: Git for Windows installation failed: $_"
    } finally {
        Remove-Item $gitInstaller -Force -ErrorAction SilentlyContinue
    }
    $elapsed = [math]::Round(((Get-Date) - $start).TotalSeconds)
    $gitCmdDir = Join-Path $gitUserDir "cmd"
    if (Test-Path (Join-Path $gitCmdDir "git.exe")) {
        Add-UserPath $gitCmdDir
        Log "Installed Git for Windows (${elapsed}s)"
    } else {
        $gitCmdDir = $null
        Log "WARNING: git is not installed after ${elapsed}s"
    }
}

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

# Cortex Code CLI -- the plugin update runs it, and the Windows bash shells get
# a `cortex` wrapper for it. When none is found, run the official installer as
# a child (it calls `exit 1` on failure). Empty stdin answers its PATH prompt
# with the default (yes), which adds %LOCALAPPDATA%\cortex\bin to the user PATH.
$cortexShim = Join-Path $env:LOCALAPPDATA "cortex\bin\cortex.cmd"
function Find-CortexCli {
    $cmd = Get-Command "cortex" -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { return $cmd.Path }
    if (Test-Path $cortexShim) { return $cortexShim }
    return $null
}
$cortexCli = Find-CortexCli
if ($cortexCli) {
    Log "Cortex Code CLI found ($cortexCli)"
} else {
    $start = Get-Date
    Log "Installing the Cortex Code CLI (official installer)..."
    $cortexInstallerPs1 = Join-Path ([IO.Path]::GetTempPath()) "cortex-official-install-$PID.ps1"
    try {
        Invoke-WebRequest -Uri "https://ai.snowflake.com/static/cc-scripts/install.ps1" -OutFile $cortexInstallerPs1 -TimeoutSec 60 -UseBasicParsing -ErrorAction Stop
        $hostExe = (Get-Process -Id $PID).Path
        $cortexExit = $null
        # The installer runs a bare `tar`; from Git Bash, Git's GNU tar (which
        # cannot read C:\ paths) comes first on PATH, so put System32 first.
        $prevPath = $env:PATH
        $env:PATH = "$(Join-Path $env:SystemRoot 'System32');$env:PATH"
        try {
            $cortexExit = Invoke-Child $hostExe @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$cortexInstallerPs1`"") 600 ""
        } finally {
            $env:PATH = $prevPath
        }
        Add-UserPath (Split-Path -Parent $cortexShim)
        $cortexCli = Find-CortexCli
        $elapsed = [math]::Round(((Get-Date) - $start).TotalSeconds)
        if ($cortexCli) {
            Log "Installed the Cortex Code CLI (installer exit $cortexExit, ${elapsed}s)"
        } else {
            Log "WARNING: the Cortex Code CLI installer did not install cortex (exit $cortexExit, ${elapsed}s)"
        }
    } catch {
        Log "WARNING: Cortex Code CLI installation failed: $_"
    } finally {
        Remove-Item $cortexInstallerPs1 -Force -ErrorAction SilentlyContinue
    }
}

# snowflake-migration plugin: `cortex plugin install <URL> --force` from the
# branch of the resolved channel (see SCAI_CHANNEL above), or from the tag of a
# pinned version. Skipped with a .no-auto-update file
# in the plugin root (the source tree and dev checkouts have one), without a
# Cortex Code CLI, or when the plugin is not in the Cortex registry from the
# public repo (loaded with --plugin-dir, or from a fork). Last, since the install may replace this plugin directory.

function Test-VersionNewer {
    # True if dotted version $Published is newer than $Installed (numeric parts).
    param([string]$Published, [string]$Installed)
    $a = @($Published -split '[^0-9]+' | Where-Object { $_ } | ForEach-Object { [long]$_ })
    $b = @($Installed -split '[^0-9]+' | Where-Object { $_ } | ForEach-Object { [long]$_ })
    for ($i = 0; $i -lt [math]::Max($a.Count, $b.Count); $i++) {
        $x = if ($i -lt $a.Count) { $a[$i] } else { 0 }
        $y = if ($i -lt $b.Count) { $b[$i] } else { 0 }
        if ($x -gt $y) { return $true }
        if ($x -lt $y) { return $false }
    }
    return $false
}

# A VERSION file's text, trimmed, when it is a plugin version, else "": X.Y.Z
# (stable) or X.Y.Z-Pr.N (preview), as scai. A proxy or
# captive portal can answer the published VERSION URL with a page of its own,
# and an installed VERSION file can be empty.
function ConvertTo-PluginVersion {
    param([string]$Text)
    $t = "$Text".Trim()
    if ($t -match '^\d+(\.\d+)*(-Pr\.\d+)?$') { return $t }
    return ""
}

$start = Get-Date
if (Test-Path (Join-Path $PluginRoot ".no-auto-update")) {
    Log "$PluginName plugin: .no-auto-update found in $PluginRoot, not updating"
} elseif (-not $cortexCli) {
    Log "No Cortex Code CLI found; skipping the $PluginName plugin update"
} elseif (-not $pluginFromRepo) {
    Log "$PluginName plugin is not in the Cortex plugin registry from $PluginRepo (running from $PluginRoot); nothing to update"
} else {
    $installedFile = Join-Path $cortexHome "plugins\$PluginName\VERSION"
    $installed = if (Test-Path $installedFile) { ConvertTo-PluginVersion (Get-Content $installedFile -Raw) } else { "" }
    if (-not $installed) { $installed = $Version }
    # An alpha branch (no channel) follows its own head. A pin installs its version tag.
    $pluginBranch = $PluginRef
    $pin = ""
    if ($pluginChannel) {
        $pluginBranch = Get-ChannelBranch $env:SCAI_CHANNEL
        $pin = $PluginVersionPin
    }
    $why = ""
    if ($pin) {
        $published = $pin
        $installRef = "v$pin"
        $why = "pinned"
    } else {
        try {
            $published = ConvertTo-PluginVersion "$(Invoke-RestMethod -Uri "https://raw.githubusercontent.com/$PluginRepo/$pluginBranch/plugin/VERSION" -TimeoutSec 15 -UseBasicParsing -ErrorAction Stop)"
        } catch {
            $published = ""
        }
        $installRef = $pluginBranch
        # A channel switch installs the new channel's latest, also a lower version (as scai).
        # Compare plugin branches: dev and preview share the preview branch.
        if ($pluginChannel -and (Get-ChannelBranch $pluginChannel) -ne $pluginBranch) { $why = "channel $pluginChannel -> $($env:SCAI_CHANNEL)" }
    }
    if (-not $published) {
        Log "Could not fetch the published $PluginName VERSION (branch $pluginBranch)"
    } elseif ($published -eq $installed -or (-not $why -and -not (Test-VersionNewer $published $installed))) {
        Log "$PluginName plugin up to date (v$installed, branch $pluginBranch) ($([math]::Round(((Get-Date) - $start).TotalSeconds))s)"
    } else {
        $installUrl = "https://github.com/$PluginRepo/tree/$installRef/plugin"
        $whyNote = if ($why) { ", $why" } else { "" }
        Log "Updating the $PluginName plugin (v$installed -> v$published$whyNote) from $installUrl..."
        # Git for Windows first: cortex.exe cannot use a Cygwin or MSYS2 git.
        $prevPath = $env:PATH
        if ($gitCmdDir) { $env:PATH = "$gitCmdDir;$env:PATH" }
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $updateExit = $null
        try {
            & $cortexCli plugin install $installUrl --force *>> $LogFile
            $updateExit = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $prevEAP
            $env:PATH = $prevPath
        }
        if ($updateExit -eq 0) {
            Log "Updated the $PluginName plugin to v$published. It takes effect in the next session or after /plugin reload."
        } else {
            Log "WARNING: cortex plugin install $installUrl --force failed (exit $updateExit)"
        }
    }
}

Log "SessionStart hook complete (total: $([math]::Round(((Get-Date) - $HookStart).TotalSeconds))s)"
