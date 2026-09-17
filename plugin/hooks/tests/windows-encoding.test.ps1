# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Windows PowerShell 5.1 decodes a BOM-less .ps1 with the machine ANSI codepage.
# A UTF-8 em dash (bytes E2 80 94) becomes U+201D on cp1252, which PowerShell
# treats as a string delimiter, so SessionStart aborts with ParserErrors.
# This script must itself stay ASCII and must be invoked with powershell.exe.

$ErrorActionPreference = "Stop"

$hooksRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath $hooksRoot)) {
    throw "FAIL: hooks dir missing: $hooksRoot"
}

$exts = @(".ps1", ".psm1", ".cmd")
$scripts = @(
    Get-ChildItem -LiteralPath $hooksRoot -Recurse -File |
        Where-Object { $exts -contains $_.Extension.ToLowerInvariant() }
)

if ($scripts.Count -lt 1) {
    throw "FAIL: no .ps1/.psm1/.cmd under ai/plugin/hooks"
}

$offenders = New-Object System.Collections.Generic.List[string]
foreach ($f in $scripts) {
    $bytes = [System.IO.File]::ReadAllBytes($f.FullName)
    for ($i = 0; $i -lt $bytes.Length; $i++) {
        if ($bytes[$i] -gt 127) {
            $rel = $f.FullName.Substring($hooksRoot.Length + 1)
            $offenders.Add(("{0}: offset {1} byte 0x{2:X2}" -f $rel, $i, $bytes[$i]))
        }
    }
}

if ($offenders.Count -gt 0) {
    $offenders | ForEach-Object { Write-Host "ERROR: $_" }
    throw ("FAIL: {0} non-ASCII byte(s) in plugin Windows hooks" -f $offenders.Count)
}

$parseFailed = $false
$psFiles = @($scripts | Where-Object { $_.Extension -match "^\.psm?1$" })
foreach ($f in $psFiles) {
    $tokens = $null
    $parseErrors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile(
        $f.FullName,
        [ref]$tokens,
        [ref]$parseErrors
    )
    if ($parseErrors -and $parseErrors.Count -gt 0) {
        $parseFailed = $true
        foreach ($e in $parseErrors) {
            Write-Host ("ERROR: {0}:{1}: {2}" -f $f.Name, $e.Extent.StartLineNumber, $e.Message)
        }
    }
}

if ($parseFailed) {
    throw "FAIL: Windows PowerShell 5.1 parse errors in plugin hooks"
}

Write-Host ("PASS: {0} Windows scripts ASCII; {1} parsed with PowerShell {2}" -f `
    $scripts.Count, $psFiles.Count, $PSVersionTable.PSVersion)
