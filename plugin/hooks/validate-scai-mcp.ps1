# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0

$PluginRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $PluginRoot "logs"
$LogFile = Join-Path $LogDir "mcp-server-validation.log"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

# The Microsoft Store python stub exits 9009, which would fail SessionStart, so it counts as no Python.
. (Join-Path $PSScriptRoot "lib/resolve-real-python.ps1")
$python = Get-UvBootstrapPython
if (-not $python) {
    $message = "SCAI_MCP_UNVERIFIED: Python is unavailable; skipped bounded MCP initialize probe"
    Add-Content -Path $LogFile -Value $message
    [Console]::Error.WriteLine($message)
    exit 0
}

$pythonPrefix = @()
if ($python.Prefix) { $pythonPrefix = @($python.Prefix) }
& $python.Exe @pythonPrefix (Join-Path $PSScriptRoot "validate-scai-mcp.py")
# Propagate INCOMPATIBLE (exit 1). Do not rewrite it as UNVERIFIED - SessionStart
# must fail when the PATH-selected scai cannot serve as the plugin MCP server.
exit $LASTEXITCODE
