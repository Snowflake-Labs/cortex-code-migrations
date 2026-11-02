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

# Runs informatica_assessment_analyzer. The package has no third-party dependencies.
# A locked-down Windows VDI often has only the Microsoft Store python stub, and the
# uv installer cannot put uv on PATH. This script skips that stub, forces UTF-8
# (Windows defaults to cp1252), and uses a real Python 3.11+.

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AnalyzerArgs
)

$ErrorActionPreference = "Stop"
if (-not $AnalyzerArgs) { $AnalyzerArgs = @() }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillRoot = Split-Path -Parent $ScriptDir
$HomeDir = if ($env:USERPROFILE) { $env:USERPROFILE } else { $env:HOME }

function Test-WindowsStorePythonStub {
    param([string]$Path)
    return [bool]($Path -and ($Path -match '[\\/]WindowsApps[\\/]'))
}

function Test-Python311 {
    param([string]$Exe, [string[]]$Prefix)
    $prefix = @()
    if ($Prefix) { $prefix = @($Prefix) }
    & $Exe @prefix -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
    return $LASTEXITCODE -eq 0
}

function Invoke-Analyzer {
    param([string]$Exe, [string[]]$Prefix)
    $prefix = @()
    if ($Prefix) { $prefix = @($Prefix) }
    & $Exe @prefix -X utf8 -m informatica_assessment_analyzer @AnalyzerArgs
    exit $LASTEXITCODE
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$ScriptDir$([IO.Path]::PathSeparator)$($env:PYTHONPATH)"
} else {
    $env:PYTHONPATH = $ScriptDir
}

foreach ($name in @("py", "python", "python3")) {
    $cmds = @(Get-Command $name -All -ErrorAction SilentlyContinue)
    foreach ($cmd in $cmds) {
        if (Test-WindowsStorePythonStub $cmd.Source) { continue }
        $prefix = @()
        if ($cmd.Name -match '^(?i)py(\.exe)?$') { $prefix = @("-3") }
        if (Test-Python311 $cmd.Source $prefix) { Invoke-Analyzer $cmd.Source $prefix }
    }
}

$venvCandidates = @(
    (Join-Path $HomeDir ".snowflake\scai\python\venv\Scripts\python.exe"),
    (Join-Path $HomeDir ".snowflake\scai\python\venv\bin\python")
)
if ($env:SNOWFLAKE_HOME) {
    $venvCandidates += (Join-Path $env:SNOWFLAKE_HOME "scai\python\venv\Scripts\python.exe")
    $venvCandidates += (Join-Path $env:SNOWFLAKE_HOME "scai\python\venv\bin\python")
}
foreach ($candidate in $venvCandidates) {
    if ((Test-Path -LiteralPath $candidate) -and (Test-Python311 $candidate @())) {
        Invoke-Analyzer $candidate @()
    }
}

$searchRoots = @((Join-Path $HomeDir ".snowflake\cortex"))
if ($env:LOCALAPPDATA) {
    $searchRoots = @(
        (Join-Path $env:LOCALAPPDATA "snowflake-cortex"),
        (Join-Path $env:LOCALAPPDATA "cortex")
    ) + $searchRoots
}
foreach ($root in $searchRoots) {
    if (-not (Test-Path -LiteralPath $root)) { continue }
    $hits = @(Get-ChildItem -LiteralPath $root -Recurse -Depth 6 -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @("python.exe", "python") -and $_.FullName -match 'reladiff-runtime' })
    foreach ($hit in $hits) {
        if (Test-Python311 $hit.FullName @()) { Invoke-Analyzer $hit.FullName @() }
    }
}

$uv = $null
$uvCmd = Get-Command uv -ErrorAction SilentlyContinue
if ($uvCmd -and (Test-Path -LiteralPath $uvCmd.Source)) { $uv = $uvCmd.Source }
if (-not $uv) {
    foreach ($rel in @(".local\bin\uv.exe", ".local\bin\uv", ".cargo\bin\uv.exe", ".cargo\bin\uv")) {
        $path = Join-Path $HomeDir $rel
        if (Test-Path -LiteralPath $path) { $uv = $path; break }
    }
}
if ($uv) {
    & $uv run --project $SkillRoot python -X utf8 -m informatica_assessment_analyzer @AnalyzerArgs
    exit $LASTEXITCODE
}

[Console]::Error.WriteLine(@"
Informatica analyzer cannot start. No Python 3.11+ is available. The Windows Store python stub does not count, and uv is not installed.
Do not write a substitute HTML report and do not open the assessment JSON with another program.
"@)
exit 1
