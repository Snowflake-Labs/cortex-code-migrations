# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0

$PluginRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $PluginRoot "logs"
$LogFile = Join-Path $LogDir "mcp-server-validation.log"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

$python = Get-Command "python3" -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $python) {
    $python = Get-Command "python" -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
}
if (-not $python) {
    $message = "SCAI_MCP_UNVERIFIED: Python is unavailable; skipped bounded MCP initialize probe"
    Add-Content -Path $LogFile -Value $message
    [Console]::Error.WriteLine($message)
    exit 0
}

& $python.Source (Join-Path $PSScriptRoot "validate-scai-mcp.py")
# Propagate INCOMPATIBLE (exit 1). Do not rewrite it as UNVERIFIED - SessionStart
# must fail when the PATH-selected scai cannot serve as the plugin MCP server.
exit $LASTEXITCODE
