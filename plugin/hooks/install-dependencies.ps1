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

Log "SessionStart hook running (v$Version, $platform, plugin root: $PluginRoot)"

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

# scai CLI (MSI -- runs /passive so users see progress but no wizard dialogs)
$start = Get-Date
$MsiUrl = "https://snowconvert.snowflake.com/storage/windows/beta/cli/snowflake-scai-cli-windows-x64-beta.msi"
$MsiPath = Join-Path ([System.IO.Path]::GetTempPath()) "snowflake-scai-cli.msi"
$action = if (Get-Command "scai" -ErrorAction SilentlyContinue) { "Upgrading" } else { "Installing" }
Log "$action scai CLI..."
Invoke-WebRequest -Uri $MsiUrl -OutFile $MsiPath -UseBasicParsing
Log "Running scai CLI installer (passive mode)..."
$proc = Start-Process msiexec -ArgumentList "/i `"$MsiPath`" /passive /norestart" -Wait -PassThru
Remove-Item -Path $MsiPath -Force -ErrorAction SilentlyContinue
if ($proc.ExitCode -eq 0) {
    $elapsed = [math]::Round(((Get-Date) - $start).TotalSeconds)
    Log "$action scai CLI complete (${elapsed}s)"
} else {
    Log "WARNING: scai CLI installer exited with code $($proc.ExitCode) - you may need to install manually"
}

Log "SessionStart hook complete (total: $([math]::Round(((Get-Date) - $HookStart).TotalSeconds))s)"
